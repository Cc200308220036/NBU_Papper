"""基于内容寻址的VLM响应缓存。"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable
import hashlib
import json

from .client import ModelRequest, ModelResult

CACHE_SCHEMA_VERSION = "pallet_vlm_cache_v1"


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_key(provider: str, request: ModelRequest, prompt_version: str) -> str:
    payload = {
        "provider": provider,
        "model": request.model,
        "prompt_version": prompt_version,
        "system_prompt": request.system_prompt,
        "user_text": request.user_text,
        "images": [_file_hash(path) for path in request.image_paths],
        "temperature": request.temperature,
        "max_output_tokens": request.max_output_tokens,
        "response_schema": request.response_schema,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class ResponseCache:
    def __init__(self, root: str | Path, mode: str = "read_write"):
        if mode not in ("off", "read_only", "read_write"):
            raise ValueError("invalid cache mode")
        self.root = Path(root)
        self.mode = mode
        if mode == "read_write":
            self.root.mkdir(parents=True, exist_ok=True)

    def complete(self, key: str, invoke: Callable[[], ModelResult]) -> ModelResult:
        path = self.root / f"{key}.json"
        if self.mode != "off" and path.exists():
            value = json.loads(path.read_text())
            if value.get("schema_version") != CACHE_SCHEMA_VERSION or value.get("cache_key") != key:
                raise ValueError("invalid VLM cache record")
            result = value["result"]
            return ModelResult(**{**result, "cache_hit": True})
        if self.mode == "read_only":
            raise FileNotFoundError(f"VLM cache miss: {key}")
        result = invoke()
        if self.mode == "read_write":
            value = {"schema_version": CACHE_SCHEMA_VERSION, "cache_key": key,
                     "result": result.as_dict()}
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        return result
