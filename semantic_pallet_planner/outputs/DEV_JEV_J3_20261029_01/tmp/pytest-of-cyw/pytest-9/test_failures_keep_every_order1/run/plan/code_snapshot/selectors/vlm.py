"""阶段1C文本/视觉选择器，负责将显示编号转换为内部候选ID。"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from ..logging.artifacts import dump
from ..protocol import resolve_response
from ..visualization.renderer import prepare_visual_request
from ..vlm.cache import ResponseCache, cache_key
from ..vlm.candidate_mapping import build_candidate_mapping
from ..vlm.client import ModelRequest, VLMClient
from ..vlm.leakage import scan_model_input
from ..vlm.prompt_builder import OUTPUT_SCHEMA, build_prompt
from ..vlm.response_parser import VLMResponseError, parse_choice


class VLMSelector:
    privileged_input = False
    future_visible = False
    requires_images = False  # 图像需要在私有候选ID完成映射后生成。

    def __init__(self, *, mode: str, client: VLMClient, model: str, seed: int,
                 artifact_root: str | Path, cache: ResponseCache,
                 provider: str = "glm", temperature: float = 0.0,
                 max_output_tokens: int = 512, timeout_s: float = 60.0,
                 max_format_repairs: int = 1):
        if mode not in ("text", "visual"):
            raise ValueError("mode must be text or visual")
        if max_format_repairs not in (0, 1):
            raise ValueError("stage1C permits zero or one format repair")
        self.mode = mode
        self.name = f"vlm_{mode}"
        self.client = client
        self.model = model
        self.seed = seed
        self.artifact_root = Path(artifact_root)
        self.cache = cache
        self.provider = provider
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_s = timeout_s
        self.max_format_repairs = max_format_repairs
        self.last_trace: dict[str, Any] = {}

    def _call(self, request: ModelRequest, prompt_version: str):
        key = cache_key(self.provider, request, prompt_version)
        result = self.cache.complete(key, lambda: self.client.complete(request))
        return key, result

    def select(self, request, *, rng, memories=None):
        if memories is not None:
            raise ValueError("stage1C requires memories=None")
        mapping = build_candidate_mapping(request, self.seed)
        directory = self.artifact_root / self.name / request["request_id"]
        directory.mkdir(parents=True, exist_ok=True)
        visible_request = copy.deepcopy(mapping.model_request)
        image_paths: tuple[str, ...] = ()
        if self.mode == "visual":
            visible_request = prepare_visual_request(visible_request, directory)
            image_paths = (visible_request["visual_inputs"]["workspace_image"],
                           visible_request["visual_inputs"]["candidate_montage"])
            visible_request["visual_inputs"] = {
                "workspace_image": "attached_image_1",
                "candidate_montage": "attached_image_2",
            }
        prompt = build_prompt(visible_request, self.mode, image_paths)
        real_ids = list(mapping.display_to_candidate.values())
        leakage = scan_model_input(visible_request, prompt.user_text, real_ids)
        dump(directory / "public_request.json", visible_request)
        dump(directory / "mapping.audit.json", mapping.audit_dict())
        dump(directory / "prompt.json", prompt.as_dict())
        dump(directory / "leakage_report.json", leakage)
        self.last_trace = {
            "provider": self.provider, "model": self.model, "mode": self.mode,
            "prompt_version": prompt.prompt_version, "prompt_sha256": prompt.prompt_sha256,
            "mapping_sha256": mapping.mapping_sha256, "leakage_hit_count":
                len(leakage["forbidden_key_hits"]) + len(leakage["forbidden_value_hits"]) + len(leakage["real_candidate_id_hits"]),
            "attempt_count": 0, "repair_count": 0, "vlm_response_valid": False,
            "cache_hit": False, "input_tokens": None, "output_tokens": None,
            "api_latency_s": 0.0, "estimated_cost": None, "error_category": None,
            "selected_display_position": None,
        }
        if not leakage["passed"]:
            self.last_trace["error_category"] = "leakage_detected"
            raise ValueError("model input leakage detected")
        model_request = ModelRequest(
            model=self.model, system_prompt=prompt.system_prompt, user_text=prompt.user_text,
            image_paths=image_paths, temperature=self.temperature,
            max_output_tokens=self.max_output_tokens, timeout_s=self.timeout_s,
            response_schema=OUTPUT_SCHEMA,
        )
        results = []
        try:
            key, result = self._call(model_request, prompt.prompt_version)
            results.append(result)
            self.last_trace["attempt_count"] = 1
            try:
                response, parsed = parse_choice(result.raw_text, request, mapping.display_to_candidate)
            except VLMResponseError as first_error:
                if self.max_format_repairs != 1 or first_error.category not in ("invalid_json", "schema_error"):
                    raise
                repair_text = (
                    prompt.user_text + "\n\n你上一次的输出不符合协议。请重新完成原选择任务。"
                    "不要复述DECISION_REQUEST，不要使用Markdown代码围栏，只返回一个顶层JSON对象。"
                    "合法display_candidate_id为：" + ",".join(mapping.display_to_candidate) +
                    "。上一次错误输出的开头为：" + result.raw_text[:500]
                )
                repair_request = ModelRequest(
                    model=self.model, system_prompt=prompt.system_prompt,
                    user_text=repair_text, image_paths=image_paths, temperature=self.temperature,
                    max_output_tokens=self.max_output_tokens, timeout_s=self.timeout_s,
                    response_schema=OUTPUT_SCHEMA,
                )
                _, repaired = self._call(repair_request, prompt.prompt_version + "_repair")
                results.append(repaired)
                self.last_trace.update(attempt_count=2, repair_count=1)
                response, parsed = parse_choice(repaired.raw_text, request, mapping.display_to_candidate)
            resolve_response(request, response)
            self.last_trace.update(vlm_response_valid=True,
                                   selected_display_position=parsed["display_candidate_id"])
            dump(directory / "response.json", {
                "attempts": [r.as_dict() for r in results], "parsed": parsed,
                "core_response": response,
            })
            return response
        except Exception as exc:
            self.last_trace["error_category"] = getattr(exc, "category", type(exc).__name__)
            dump(directory / "response.json", {
                "attempts": [r.as_dict() for r in results],
                "error_category": self.last_trace["error_category"], "error": str(exc),
            })
            raise
        finally:
            if results:
                self.last_trace["cache_hit"] = all(r.cache_hit for r in results)
                values = [r.input_tokens for r in results if r.input_tokens is not None]
                self.last_trace["input_tokens"] = sum(values) if values else None
                values = [r.output_tokens for r in results if r.output_tokens is not None]
                self.last_trace["output_tokens"] = sum(values) if values else None
                self.last_trace["api_latency_s"] = sum(r.latency_s for r in results)
                values = [r.estimated_cost for r in results if r.estimated_cost is not None]
                self.last_trace["estimated_cost"] = sum(values) if values else None
