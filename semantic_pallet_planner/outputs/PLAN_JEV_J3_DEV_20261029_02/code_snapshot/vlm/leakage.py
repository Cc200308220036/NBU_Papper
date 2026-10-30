"""对即将发送给模型的完整可见载荷执行泄漏预检。"""
from __future__ import annotations

from typing import Any
import hashlib
import json

FORBIDDEN_KEYS = {
    "oracle_candidate_id", "candidate_evaluations", "ground_truth_rule",
    "semantic_decision_required", "split", "source_order_id",
}


def _keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _keys(child)


def scan_model_input(model_request: dict[str, Any], user_text: str,
                     real_candidate_ids: list[str], forbidden_values: list[str] | None = None) -> dict[str, Any]:
    key_hits = sorted(FORBIDDEN_KEYS.intersection(_keys(model_request)))
    real_hits = sorted(value for value in real_candidate_ids if value and value in user_text)
    value_hits = sorted(value for value in (forbidden_values or []) if value and value in user_text)
    serialized = json.dumps(model_request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    passed = not key_hits and not real_hits and not value_hits
    return {
        "passed": passed,
        "forbidden_key_hits": key_hits,
        "forbidden_value_hits": value_hits,
        "real_candidate_id_hits": real_hits,
        "future_item_hits": [],
        "checked_text_sha256": hashlib.sha256((serialized + user_text).encode()).hexdigest(),
    }
