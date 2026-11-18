"""Atomic experiment storage, exclusive writer and one-attempt decision ledger."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time

from .contracts import JevSelectError, canonical, digest


def exhausted(count, limit):
    return limit is not None and count >= limit


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (canonical(value) + "\n").encode("utf-8")
    fd, name = tempfile.mkstemp(prefix=".atomic-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def exclusive(root):
    with (Path(root) / ".writer.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise JevSelectError("experiment_locked") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class Ledger:
    def __init__(self, root, budget, *, readonly=False, hook=None, origin="test_double"):
        self.origin = origin
        self.path = Path(root) / "audit/attempts.json"
        self.budget = budget
        self.readonly = readonly
        self.hook = hook
        self.used = set()
        if not self.path.exists():
            if readonly:
                raise JevSelectError("missing_ledger")
            write(self.path, {"version": "jev_attempts_v1", "budget": budget, "attempts": []})
        self.data = read(self.path)
        self.validate()

    def validate(self):
        if set(self.data) != {"version", "budget", "attempts"} or self.data["version"] != "jev_attempts_v1" or self.data["budget"] != self.budget:
            raise JevSelectError("ledger_budget_changed")
        seen = set(); counts = {}
        for index, row in enumerate(self.data["attempts"], 1):
            if row["attempt_id"] != f"A{index:06d}" or (row["job_id"], row["decision_id"]) in seen:
                raise JevSelectError("duplicate_attempt")
            seen.add((row["job_id"], row["decision_id"]))
            counts[row["job_id"]] = counts.get(row["job_id"], 0) + 1
            if row["state"] not in ("RESERVED", "RESPONSE_SAVED", "UNKNOWN_IN_FLIGHT") or row["origin"] not in ("test_double", "jev"):
                raise JevSelectError("invalid_attempt")
            if row["state"] == "RESERVED":
                if row["transport"] is not None or row["finished_at"] is not None:
                    raise JevSelectError("invalid_reservation")
            else:
                from .transport import validate_transport
                validate_transport(row["transport"])
                if row["transport_digest"] != digest(row["transport"]) or row["finished_at"] < row["reserved_at"]:
                    raise JevSelectError("attempt_changed")
                if (row["state"] == "UNKNOWN_IN_FLIGHT") != (row["transport"]["status"] == "UNKNOWN_IN_FLIGHT"):
                    raise JevSelectError("attempt_state_mismatch")
        if exhausted(len(seen)-1, self.budget["global_attempts"]) or any(exhausted(n-1, self.budget["per_job_attempts"]) for n in counts.values()):
            raise JevSelectError("ledger_budget_exceeded")

    def request(self, context, job_id, decision_id, transport=None):
        from .transport import outcome
        body = context.data["request_body"]
        body_digest = digest(body)
        matches = [r for r in self.data["attempts"] if r["job_id"] == job_id and r["decision_id"] == decision_id]
        if matches:
            row = matches[0]
            if row["body_digest"] != body_digest or row["binding_digest"] != digest(context.data["local_binding"]):
                raise JevSelectError("stale_attempt")
            self.used.add(row["attempt_id"])
            if row["state"] == "RESERVED":
                if self.readonly:
                    raise JevSelectError("incomplete_attempt")
                row.update(state="UNKNOWN_IN_FLIGHT", transport=outcome("UNKNOWN_IN_FLIGHT", error="interrupted_after_reservation", network_attempted=None), finished_at=time.time())
                row["transport_digest"] = digest(row["transport"])
                write(self.path, self.data)
            return row
        if self.readonly:
            if exhausted(len(self.data["attempts"]), self.budget["global_attempts"]) or exhausted(sum(r["job_id"] == job_id for r in self.data["attempts"]), self.budget["per_job_attempts"]):
                return None
            raise JevSelectError("missing_saved_attempt")
        attempts = self.data["attempts"]
        if exhausted(len(attempts), self.budget["global_attempts"]) or exhausted(sum(r["job_id"] == job_id for r in attempts), self.budget["per_job_attempts"]):
            return None
        if transport is None:
            raise JevSelectError("missing_transport")
        row = {"attempt_id": f"A{len(attempts)+1:06d}", "job_id": job_id, "decision_id": decision_id,
               "body_digest": body_digest, "binding_digest": digest(context.data["local_binding"]),
               "origin": transport.origin, "state": "RESERVED", "reserved_at": time.time(), "finished_at": None,
               "transport": None, "transport_digest": None}
        attempts.append(row); write(self.path, self.data)
        if self.hook: self.hook("after_reserve", row)
        result = transport.complete(body)
        row.update(state="UNKNOWN_IN_FLIGHT" if result["status"] == "UNKNOWN_IN_FLIGHT" else "RESPONSE_SAVED",
                   finished_at=time.time(), transport=result, transport_digest=digest(result))
        self.validate(); write(self.path, self.data)
        self.used.add(row["attempt_id"])
        if self.hook: self.hook("after_response", row)
        return row
