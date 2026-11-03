"""与实验方法无关的确定性候选显示编号映射。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import copy
import hashlib
import json
import random

MAPPING_VERSION = "stage1c_v1"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class CandidateMapping:
    model_request: dict[str, Any]
    display_to_candidate: dict[str, str]
    mapping_sha256: str
    mapping_version: str = MAPPING_VERSION

    def audit_dict(self) -> dict[str, Any]:
        return {
            "mapping_version": self.mapping_version,
            "mapping_sha256": self.mapping_sha256,
            "display_to_candidate": dict(self.display_to_candidate),
        }


def build_candidate_mapping(request: dict[str, Any], seed: int,
                            mapping_version: str = MAPPING_VERSION) -> CandidateMapping:
    candidates = copy.deepcopy(request["candidates"])
    local_seed = int(_digest([seed, request["request_id"], mapping_version])[:16], 16)
    random.Random(local_seed).shuffle(candidates)
    mapping: dict[str, str] = {}
    visible = []
    for index, candidate in enumerate(candidates, 1):
        label = f"C{index:02d}"
        real_id = candidate.pop("candidate_id")
        candidate["display_label"] = label
        mapping[label] = real_id
        visible.append(candidate)
    model_request = copy.deepcopy(request)
    model_request["candidates"] = visible
    model_request["visual_inputs"] = {"workspace_image": "", "candidate_montage": ""}
    mapping_hash = _digest({"version": mapping_version, "request_id": request["request_id"],
                            "mapping": mapping})
    return CandidateMapping(model_request, mapping, mapping_hash, mapping_version)
