"""供阶段1C文本与视觉实验使用的DeepSeek OpenAI兼容适配器。"""
from __future__ import annotations

from pathlib import Path
import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request

from .client import ModelRequest, ModelResult


class DeepSeekClientError(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


class DeepSeekClient:
    def __init__(self, *, api_key_env: str = "DEEPSEEK_API_KEY",
                 base_url: str = "https://api.deepseek.com/chat/completions",
                 thinking: str = "disabled", input_cost_per_million: float | None = None,
                 output_cost_per_million: float | None = None):
        self.api_key_env = api_key_env
        self.base_url = base_url
        self.thinking = thinking
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million

    def _api_key(self) -> str:
        value = os.environ.get(self.api_key_env)
        if not value:
            raise DeepSeekClientError("missing_api_key", f"missing environment variable {self.api_key_env}")
        return value

    @staticmethod
    def _image_block(path: str) -> dict:
        mime = mimetypes.guess_type(path)[0] or "image/png"
        encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}", "detail": "original"}}

    def complete(self, request: ModelRequest) -> ModelResult:
        if request.image_paths and request.model != "deepseek-flash":
            raise DeepSeekClientError("model_capability_error",
                                      f"{request.model} does not support image input; use deepseek-flash")
        content = [{"type": "text", "text": request.user_text}]
        content.extend(self._image_block(path) for path in request.image_paths)
        body = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": self.thinking},
            "stream": False,
        }
        http_request = urllib.request.Request(
            self.base_url, data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key()}"},
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(http_request, timeout=request.timeout_s) as response:
                payload = json.loads(response.read())
        except TimeoutError as exc:
            raise DeepSeekClientError("timeout", "DeepSeek request timed out") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            raise DeepSeekClientError("provider_error", f"DeepSeek HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DeepSeekClientError("transport_error", str(exc)) from exc
        latency = time.perf_counter() - started
        try:
            choice = payload["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekClientError("provider_error", "DeepSeek response shape is invalid") from exc
        usage = payload.get("usage", {})
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        cost = None
        if input_tokens is not None and output_tokens is not None and self.input_cost_per_million is not None and self.output_cost_per_million is not None:
            cost = input_tokens * self.input_cost_per_million / 1_000_000 + output_tokens * self.output_cost_per_million / 1_000_000
        return ModelResult(raw_text=text, finish_reason=choice.get("finish_reason", ""),
                           input_tokens=input_tokens, output_tokens=output_tokens,
                           latency_s=latency, provider_request_id=payload.get("id"),
                           estimated_cost=cost)
