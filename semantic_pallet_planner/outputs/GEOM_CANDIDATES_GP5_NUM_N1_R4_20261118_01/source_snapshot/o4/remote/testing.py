"""Labelled service double for exercising the actual HTTP encoding offline.

This module is never used by --remote. It parses only the serialized public
request; it has no reference answers. Its accuracy is not a model measurement.
"""
from __future__ import annotations

import base64
import copy
import io
import json

from ..common import canonical
from ..compiler import parse_instruction, response_for


class ProtocolServiceDouble:
    """An opener replacement with deterministic protocol fault injection."""

    def __init__(self, faults=()):
        self.faults = list(faults)
        self.requests: list[dict] = []
        self.image_bytes: list[bytes] = []

    def __call__(self, request, timeout):
        body = json.loads(request.data)
        self.requests.append(copy.deepcopy(body))
        fault = self.faults.pop(0) if self.faults else "valid"
        if fault == "timeout":
            raise TimeoutError()
        content = body["messages"][1]["content"]
        for block in content[1:]:
            prefix, encoded = block["image_url"]["url"].split(",", 1)
            assert prefix == "data:image/png;base64"
            image = base64.b64decode(encoded, validate=True)
            assert image.startswith(b"\x89PNG\r\n\x1a\n")
            self.image_bytes.append(image)
        public = json.loads(content[0]["text"])["public_input"]["public_request"]
        obs = public.get("observation", public)
        response = response_for(obs, parse_instruction(obs["instruction_text"]))
        if "observation" in public:
            response.update(schema_version="o4_buffer_response_v1",
                            buffer_state_hash=public["buffer_state_hash"], event_index=public["event_index"])
        if fault == "stale":
            response["observation_digest"] = "0" * 64
        if fault == "drop_rules":
            response["policy_ast"]["rules"] = []
        text = "malformed JSON" if fault == "malformed" else canonical(response)
        payload = {"id": f"offline-{len(self.requests)}", "model": "TEST_DOUBLE",
                   "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        if fault == "missing_usage":
            payload.pop("usage")
        return io.BytesIO(canonical(payload).encode())
