"""为文本与视觉消融实验构造带版本的白名单提示词。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import hashlib
import json

PROMPT_VERSION = "stage1c_prompt_v1"
SYSTEM_PROMPT = """你是码垛语义候选选择器。所有候选已通过几何和物理合法性检查。
请先满足自然语言业务硬规则，再比较语义软偏好；语义效果接近时保持较好的几何质量。
你只能从给出的C01…CK中选择，不能生成坐标、修改候选或推测未来物料。
只输出一个顶层JSON对象，不要使用Markdown代码围栏，不要复述输入，不要输出分析过程。
顶层JSON只能包含schema_version、request_id、state_hash、display_candidate_id、confidence、applied_rule、reason。"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"const": "pallet_vlm_choice_v1"},
        "request_id": {"type": "string"},
        "state_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "display_candidate_id": {"type": "string", "pattern": "^C[0-9]{2,3}$"},
        "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "applied_rule": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["schema_version", "request_id", "state_hash", "display_candidate_id"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Prompt:
    prompt_version: str
    system_prompt: str
    user_text: str
    image_paths: tuple[str, ...]
    prompt_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_version": self.prompt_version,
            "system_prompt": self.system_prompt,
            "user_text": self.user_text,
            "image_paths": list(self.image_paths),
            "prompt_sha256": self.prompt_sha256,
        }


def build_prompt(model_request: dict[str, Any], mode: str,
                 image_paths: tuple[str, ...] = ()) -> Prompt:
    if mode not in ("text", "visual"):
        raise ValueError("mode must be text or visual")
    if mode == "text" and image_paths:
        raise ValueError("text mode must not contain images")
    if mode == "visual" and len(image_paths) != 2:
        raise ValueError("visual mode requires workspace and candidate montage")
    request_json = json.dumps(model_request, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False)
    user_text = (
        "请根据下面的DECISION_REQUEST作出一次选择。只返回顶层JSON对象。\n"
        "必须原样复制以下request_id和state_hash；display_candidate_id必须是候选列表中的C编号。\n"
        f"request_id={model_request['request_id']}\n"
        f"state_hash={model_request['state_hash']}\n"
        "输出示例仅说明字段，不代表答案："
        '{"schema_version":"pallet_vlm_choice_v1","request_id":"上述request_id",'
        '"state_hash":"上述state_hash","display_candidate_id":"从合法候选中选择一个C编号",'
        '"confidence":0.8,"applied_rule":"简短规则名","reason":"简短中文理由"}\n'
        "DECISION_REQUEST_BEGIN\n" + request_json + "\nDECISION_REQUEST_END"
    )
    digest = hashlib.sha256(json.dumps({
        "version": PROMPT_VERSION, "system": SYSTEM_PROMPT,
        "user": user_text, "images": list(image_paths),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return Prompt(PROMPT_VERSION, SYSTEM_PROMPT, user_text, image_paths, digest)
