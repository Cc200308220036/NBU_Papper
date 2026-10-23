"""阶段1C的VLM适配器、提示词、候选映射、缓存与校验工具。"""

from .client import ModelRequest, ModelResult, VLMClient, FakeClient
from .candidate_mapping import CandidateMapping, build_candidate_mapping

__all__ = [
    "ModelRequest", "ModelResult", "VLMClient", "FakeClient",
    "CandidateMapping", "build_candidate_mapping",
]
