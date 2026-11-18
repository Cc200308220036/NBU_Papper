"""与模型供应商无关的客户端数据结构及确定性离线模拟客户端。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
import json
import time


@dataclass(frozen=True)
class ModelRequest:
    model: str
    system_prompt: str
    user_text: str
    image_paths: tuple[str, ...] = ()
    temperature: float = 0.0
    max_output_tokens: int = 512
    timeout_s: float = 60.0
    response_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class ModelResult:
    raw_text: str
    finish_reason: str = "stop"
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_s: float = 0.0
    provider_request_id: str | None = None
    estimated_cost: float | None = None
    cache_hit: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "finish_reason": self.finish_reason,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_s": self.latency_s,
            "provider_request_id": self.provider_request_id,
            "estimated_cost": self.estimated_cost,
            "cache_hit": self.cache_hit,
        }


class VLMClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResult: ...


class FakeClient:
    """用于测试的确定性客户端，始终选择配置指定的显示编号。"""
    def __init__(self, choice: str = "C01", responses: list[str] | None = None):
        self.choice = choice
        self.responses = list(responses or [])
        self.calls = 0

    def complete(self, request: ModelRequest) -> ModelResult:
        started = time.perf_counter()
        self.calls += 1
        if self.responses:
            raw = self.responses.pop(0)
        else:
            request_id = request.user_text.split("request_id=", 1)[1].splitlines()[0]
            state_hash = request.user_text.split("state_hash=", 1)[1].splitlines()[0]
            raw = json.dumps({
                "schema_version": "pallet_vlm_choice_v1",
                "request_id": request_id,
                "state_hash": state_hash,
                "display_candidate_id": self.choice,
                "confidence": 0.8,
                "reason": "fake_client",
            }, ensure_ascii=False, separators=(",", ":"))
        return ModelResult(raw_text=raw, input_tokens=len(request.user_text) // 4,
                           output_tokens=len(raw) // 4,
                           latency_s=time.perf_counter() - started,
                           provider_request_id=f"fake-{self.calls}")
