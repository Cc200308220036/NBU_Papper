"""Labelled public-input-only local service; never used by remote execution."""
import copy
import io
import json
import base64

from ..common import canonical
from ..compiler import response_for
from .parser import parse_normalized


class StudyServiceDouble:
    def __init__(self, faults=()):
        self.faults = list(faults)
        self.requests = []

    def __call__(self, request, timeout):
        body = json.loads(request.data)
        self.requests.append(copy.deepcopy(body))
        fault = self.faults.pop(0) if self.faults else "valid"
        if fault == "timeout":
            raise TimeoutError()
        content = body["messages"][1]["content"]
        public = json.loads(content[0]["text"])["public_input"]["public_request"]
        for image in content[1:]:
            assert base64.b64decode(image["image_url"]["url"].split(",", 1)[1], validate=True).startswith(b"\x89PNG")
        obs = public.get("observation", public)
        response = response_for(obs, parse_normalized(obs["instruction_text"]))
        if "observation" in public:
            response.update(schema_version="o4_buffer_response_v1", buffer_state_hash=public["buffer_state_hash"], event_index=public["event_index"])
        if fault == "drop_rules":
            response["policy_ast"]["rules"] = []
        if fault == "stale":
            response["state_hash"] = "0" * 64
        text = "invalid JSON" if fault == "malformed" else canonical(response)
        payload = {"id": f"study-double-{len(self.requests)}", "model": "TEST_DOUBLE",
                   "choices": [{"finish_reason": "stop", "message": {"content": text}}],
                   "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        if fault == "missing_usage":
            payload.pop("usage")
        return io.BytesIO(canonical(payload).encode())
