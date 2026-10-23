"""Uncached Chat Completions transport with bounded, checked PNG attachments.

Uses the standard library, without SDK retries or implicit model fallbacks.
Injected openers exercise exactly the production encoding path in offline tests.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import io
import json
import math
import os
import time
from urllib import error, parse, request

from PIL import Image

from ..common import O4Error, canonical
from ..visual.attachments import checked_bytes


@dataclass(frozen=True)
class ModelConfig:
    """Frozen provider parameters. Secrets are resolved only at request time."""

    endpoint: str
    model: str
    api_key_env: str = "O4_API_KEY"
    thinking: str = "disabled"
    temperature: float = 0.0
    max_tokens: int = 8192
    timeout_s: float = 90.0
    max_images: int = 16
    max_image_bytes: int = 10_000_000
    max_image_pixels: int = 16_000_000
    max_image_side: int = 8192
    max_request_bytes: int = 30_000_000
    max_response_bytes: int = 4_000_000

    def validate(self) -> None:
        url = parse.urlsplit(self.endpoint)
        if (url.scheme != "https" or not url.hostname or url.username
                or url.password or url.query or url.fragment):
            raise ValueError("endpoint must be an HTTPS URL without credentials or query")
        if not url.path.endswith("/chat/completions"):
            raise ValueError("endpoint must include /chat/completions")
        if not self.model.strip() or not self.api_key_env.isidentifier():
            raise ValueError("model and API key environment variable are required")
        if self.thinking not in ("disabled", "enabled"):
            raise ValueError("invalid thinking mode")
        for name in ("max_tokens", "max_images", "max_image_bytes", "max_image_pixels", "max_image_side",
                     "max_request_bytes", "max_response_bytes"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        for value in (self.temperature, self.timeout_s):
            if isinstance(value, bool) or not math.isfinite(value):
                raise ValueError("finite temperature/timeout required")
        if not 0 <= self.temperature <= 2 or self.timeout_s <= 0:
            raise ValueError("invalid temperature or timeout")

    def snapshot(self) -> dict:
        self.validate()
        return asdict(self)


class NoRedirect(request.HTTPRedirectHandler):
    """Never forward authorization to a redirected endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise O4Error("provider_error", "redirect refused")


class ChatTransport:
    """One HTTP attempt per call; its caller owns budgets and repair policy."""

    def __init__(self, config: ModelConfig, *, opener=None, test_double=False):
        config.validate()
        self.config = config
        self.test_double = test_double
        if opener is not None and not test_double:
            raise ValueError("injected opener must be labelled test_double")
        self._open = opener or request.build_opener(NoRedirect()).open

    def body(self, envelope: dict, asset_root, system_prompt: str,
             repair_error: str | None = None) -> dict:
        content = [{"type": "text", "text": canonical({
            "public_input": envelope, "repair_error": repair_error,
        })}]
        images = envelope["images"]
        if len(images) > self.config.max_images:
            raise O4Error("image_limit", "image count exceeds frozen limit")
        for asset in images:
            data = checked_bytes(asset_root, asset)
            if len(data) > self.config.max_image_bytes:
                raise O4Error("image_limit", "PNG byte limit exceeded")
            with Image.open(io.BytesIO(data)) as image:
                side_limit = min(self.config.max_image_side, 4096) if len(images) >= 15 else self.config.max_image_side
                if (image.format != "PNG" or image.width * image.height > self.config.max_image_pixels
                        or max(image.size) > side_limit):
                    raise O4Error("image_limit", "PNG format/pixel limit exceeded")
            encoded = base64.b64encode(data).decode("ascii")
            content.append({"type": "image_url", "image_url": {
                "url": "data:image/png;base64," + encoded,
                "detail": "original",
            }})
        body = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": content}],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": self.config.thinking},
            "stream": False,
        }
        if len(canonical(body).encode()) > self.config.max_request_bytes:
            raise O4Error("request_limit", "request too large; no images silently dropped")
        return body

    def complete(self, body: dict) -> dict:
        key = os.environ.get(self.config.api_key_env)
        if not key:
            raise O4Error("missing_api_key", "API key environment variable is unset")
        call = request.Request(self.config.endpoint, data=canonical(body).encode(),
                               headers={"Content-Type": "application/json",
                                        "Authorization": "Bearer " + key}, method="POST")
        started = time.perf_counter()
        try:
            with self._open(call, timeout=self.config.timeout_s) as response:
                raw = response.read(self.config.max_response_bytes + 1)
            if len(raw) > self.config.max_response_bytes:
                raise O4Error("provider_error", "response byte limit exceeded")
            # A provider echoing credentials must never put them into artifacts.
            text = raw.decode("utf-8")
            text = text.replace(key, "[REDACTED_API_KEY]")
            try:
                payload = json.loads(text)
                canonical(payload)
            except (ValueError, TypeError):
                payload = None
        except error.HTTPError as exc:
            raise O4Error("provider_error", f"HTTP {exc.code}") from None
        except (TimeoutError, error.URLError, OSError):
            raise O4Error("provider_error", "timeout or transport failure") from None
        except (UnicodeError, ValueError, TypeError):
            raise O4Error("provider_error", "non-JSON provider response") from None
        return {"payload": payload, "raw_text": text,
                "latency_s": time.perf_counter() - started}
