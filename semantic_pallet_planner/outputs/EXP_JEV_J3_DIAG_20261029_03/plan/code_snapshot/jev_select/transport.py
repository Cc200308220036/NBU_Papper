"""Native System One encoding and single HTTPS attempt; no automatic retries."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import time
import urllib.error
import urllib.request

from .contracts import JevSelectError, canonical
from .context import validate_context


def outcome(status, raw=b"", *, http_status=None, latency_s=0., error=None, network_attempted=False):
    return {"version": "jev_transport_v1", "status": status, "http_status": http_status,
            "raw_body_b64": base64.b64encode(raw).decode("ascii"),
            "raw_sha256": hashlib.sha256(raw).hexdigest(), "latency_s": latency_s, "error": error, "network_attempted": network_attempted}


def validate_transport(value):
    from .contracts import validate_schema
    validate_schema("transport_result", value)
    try:
        raw = base64.b64decode(value["raw_body_b64"], validate=True)
    except ValueError as exc:
        raise JevSelectError("invalid_raw_bytes") from exc
    if hashlib.sha256(raw).hexdigest() != value["raw_sha256"]:
        raise JevSelectError("raw_digest_changed")
    if value["status"] == "OK" and not (type(value["http_status"]) is int and 200 <= value["http_status"] < 300):
        raise JevSelectError("invalid_http_status")
    return raw


def strict_json(raw):
    def pairs(entries):
        result = {}
        for key, val in entries:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = val
        return result
    def nonfinite(token):
        raise ValueError("non-finite JSON number")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def credential(api_key_env, api_key_file=None):
    if api_key_file is None:
        key = os.environ.get(api_key_env, "")
    else:
        text = Path(api_key_file).read_text(encoding="utf-8")
        assignments = re.findall(r"(?:^|\n)\s*(?:export\s+)?TYPESAFE_API_KEY\s*=\s*([^\n]+)", text)
        if assignments:
            candidates = [value.strip().strip("\"'") for value in assignments]
        else:
            candidates = [line.strip().strip("`").strip() for line in text.splitlines()
                          if re.fullmatch(r"[A-Za-z0-9._-]{16,}", line.strip().strip("`").strip())]
        if len(set(candidates)) != 1:
            raise JevSelectError("ambiguous_api_key_file", "use one standalone token or TYPESAFE_API_KEY assignment")
        key = candidates[0]
    if not key or not key.strip() or "\r" in key or "\n" in key:
        raise JevSelectError("missing_or_invalid_api_key")
    return key.strip()


class JevTransport:
    origin = "jev"

    def __init__(self, config, *, api_key_file=None):
        from .contracts import validate_schema
        validate_schema("config", config)
        self.config = dict(config)
        self.api_key_file = api_key_file

    def build_body(self, context):
        value = validate_context(context, config=self.config)
        if value["route"] != "CHOICE_REQUIRED":
            raise JevSelectError("model_not_required")
        return value["request_body"]

    def encode(self, body):
        if set(body) != {"model", "state", "questions"} or body["model"] != self.config["model"]:
            raise JevSelectError("invalid_native_body")
        encoded = canonical(body).encode("utf-8")
        if len(encoded) > self.config["max_request_bytes"]:
            raise JevSelectError("request_too_large")
        return encoded

    def complete(self, body):
        encoded = self.encode(body)
        try:
            key = credential(self.config["api_key_env"], self.api_key_file)
        except (OSError, JevSelectError):
            return outcome("PROVIDER_FAILURE", error="MISSING_OR_INVALID_API_KEY")
        request = urllib.request.Request(self.config["endpoint"], data=encoded,
                    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
        start = time.perf_counter()
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=self.config["timeout_s"]) as response:
                raw = response.read(self.config["response_max_bytes"] + 1)
                code = response.status
            if len(raw) > self.config["response_max_bytes"]:
                return outcome("PROVIDER_FAILURE", raw[:self.config["response_max_bytes"]], http_status=code,
                               latency_s=time.perf_counter()-start, error="RESPONSE_TOO_LARGE", network_attempted=True)
            return outcome("OK", raw, http_status=code, latency_s=time.perf_counter()-start, network_attempted=True)
        except urllib.error.HTTPError as exc:
            # Do not persist error bodies: a provider/proxy might echo authentication.
            return outcome("PROVIDER_FAILURE", http_status=exc.code, latency_s=time.perf_counter()-start,
                           error=f"HTTP_{exc.code}", network_attempted=True)
        except (TimeoutError, socket.timeout, urllib.error.URLError, OSError):
            # No exception text or headers enter logs. Delivery may already have happened.
            return outcome("UNKNOWN_IN_FLIGHT", latency_s=time.perf_counter()-start, error="NETWORK_OUTCOME_UNKNOWN", network_attempted=True)
