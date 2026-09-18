#!/usr/bin/env python3
"""数据集、VLM与后续ROS 2节点共用的最小候选协议。"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def state_payload(container: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    return {
        "container": container,
        "placed_items": case["placed_items"],
        "available_items": case["available_items"],
        "buffer_size": len(case["available_items"]),
    }


def state_hash(container: dict[str, Any], case: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(state_payload(container, case)).encode("utf-8")).hexdigest()


def public_candidate(candidate: dict[str, Any], index: int) -> dict[str, Any]:
    """仅保留运行时可获得的候选信息。"""
    return {
        "display_label": f"C{index:02d}",
        "candidate_id": candidate["candidate_id"],
        "pick_item_id": candidate["pick_item_id"],
        "pose": candidate["pose"],
        "oriented_size_mm": candidate["oriented_size_mm"],
        "support": candidate["support"],
        "load": candidate["load"],
        "resulting_geometry": candidate["resulting_geometry"],
        "geometry_score_components": candidate["geometry_score_components"],
    }


def build_request(
    container: dict[str, Any],
    case: dict[str, Any],
    candidate_set: dict[str, Any],
    workspace_image: str,
    candidate_montage: str,
) -> dict[str, Any]:
    calculated = state_hash(container, case)
    if calculated != candidate_set["physical_state_hash"]:
        raise ValueError(f"状态哈希不一致：{case['decision_case_id']}")
    return {
        "schema_version": "pallet_vlm_request_v1",
        "request_id": case["decision_case_id"],
        "state_hash": calculated,
        "instruction_text": case["instruction_text"],
        "container": container,
        "placed_items": case["placed_items"],
        "available_items": case["available_items"],
        "candidates": [public_candidate(c, i) for i, c in enumerate(candidate_set["candidates"], 1)],
        "visual_inputs": {
            "workspace_image": workspace_image,
            "candidate_montage": candidate_montage,
        },
    }


def resolve_response(request: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    from .validation import validate
    validate("response", response)
    allowed = {"schema_version", "request_id", "state_hash", "candidate_id", "confidence", "reason"}
    extra = set(response) - allowed
    if extra:
        raise ValueError(f"VLM响应包含禁止字段：{sorted(extra)}")
    if response.get("schema_version") != "pallet_selector_response_v1":
        raise ValueError("VLM响应协议版本错误")
    if response.get("request_id") != request["request_id"]:
        raise ValueError("VLM响应request_id过期或错配")
    if response.get("state_hash") != request["state_hash"]:
        raise ValueError("VLM响应state_hash过期或错配")
    by_id = {c["candidate_id"]: c for c in request["candidates"]}
    candidate_id = response.get("candidate_id")
    if candidate_id not in by_id:
        raise ValueError("VLM选择了未知candidate_id")
    return by_id[candidate_id]
