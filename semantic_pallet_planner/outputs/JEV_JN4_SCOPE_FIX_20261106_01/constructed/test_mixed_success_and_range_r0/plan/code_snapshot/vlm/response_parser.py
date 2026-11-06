"""严格校验VLM显示编号响应，并在本地恢复内部候选ID。"""
from __future__ import annotations

from typing import Any
import json
import jsonschema

from .prompt_builder import OUTPUT_SCHEMA


class VLMResponseError(ValueError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def _strip_single_json_fence(raw_text: str) -> str:
    """只剥离完整的外层Markdown代码围栏，之后仍执行严格JSON校验。"""
    text = raw_text.strip()
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].strip().lower() in ("```json", "```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def parse_choice(raw_text: str, request: dict[str, Any],
                 display_to_candidate: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        value = json.loads(_strip_single_json_fence(raw_text))
    except (json.JSONDecodeError, TypeError) as exc:
        raise VLMResponseError("invalid_json", str(exc)) from exc
    try:
        jsonschema.validate(value, OUTPUT_SCHEMA)
    except jsonschema.ValidationError as exc:
        extras = set(value) - set(OUTPUT_SCHEMA["properties"]) if isinstance(value, dict) else set()
        category = "coordinate_injection" if extras.intersection({"x", "y", "z", "yaw", "pose", "x_mm", "y_mm", "z_base_mm", "yaw_deg"}) else "schema_error"
        raise VLMResponseError(category, exc.message) from exc
    if value["request_id"] != request["request_id"]:
        raise VLMResponseError("request_id_mismatch", "request_id mismatch")
    if value["state_hash"] != request["state_hash"]:
        raise VLMResponseError("state_hash_mismatch", "state_hash mismatch")
    display_id = value["display_candidate_id"]
    if display_id not in display_to_candidate:
        raise VLMResponseError("unknown_display_candidate", "unknown display candidate")
    response = {
        "schema_version": "pallet_selector_response_v1",
        "request_id": request["request_id"],
        "state_hash": request["state_hash"],
        "candidate_id": display_to_candidate[display_id],
        "confidence": value.get("confidence"),
        "reason": value.get("reason", "vlm"),
    }
    return response, value


def repair_prompt(raw_text: str, request: dict[str, Any], labels: list[str]) -> str:
    return json.dumps({
        "instruction": "将原始输出修复为严格JSON。不要改变选择；只能使用合法候选编号。",
        "request_id": request["request_id"],
        "state_hash": request["state_hash"],
        "legal_display_candidate_ids": labels,
        "required_example": {
            "schema_version": "pallet_vlm_choice_v1",
            "request_id": request["request_id"],
            "state_hash": request["state_hash"],
            "display_candidate_id": labels[0],
            "confidence": None,
            "reason": "简短理由",
        },
        "raw_output": raw_text,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
