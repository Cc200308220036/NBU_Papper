"""Public-only compilation with a write-ahead attempt ledger and one repair.

The compiler has no reference policy, candidates, future stream or evaluator.
Failures return no AST. In particular semantic errors never trigger repairs.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
import time

from ..common import O4Error, digest, write
from ..visual.bundle import AssetStore
from ..visual.facts import unpack
from .protocol import CONTRACT_VERSION, PROMPT_VERSION, parse_response, repair_context, system_prompt, validate_envelope
from ..remote.transport import ChatTransport


class AttemptLedger:
    """Budget counts issued HTTP attempts, including repairs and failures."""

    def __init__(self, root: Path, budget: int):
        if type(budget) is not int or budget < 0:
            raise ValueError("API attempt budget must be a nonnegative integer")
        self.root = Path(root)
        self.budget = budget
        self.rows: list[dict] = []

    def start(self, compilation_id: str, body_digest: str, repair: bool) -> int:
        if len(self.rows) >= self.budget:
            raise O4Error("budget_exhausted")
        row = {"attempt_id": len(self.rows) + 1, "compilation_id": compilation_id,
               "body_digest": body_digest, "repair": repair, "status": "in_flight",
               "usage": None, "cost": None, "latency_s": None}
        self.rows.append(row)
        # Persist before contacting a provider. A killed process leaves a visible
        # in-flight attempt; it cannot silently become a successful response.
        write(self.root / "audit/attempts.json", self.rows)
        with (self.root / "audit/attempts.json").open("rb") as stream:
            os.fsync(stream.fileno())
        return row["attempt_id"]

    def finish(self, attempt_id: int, **values) -> dict:
        self.rows[attempt_id - 1].update(values)
        write(self.root / "audit/attempts.json", self.rows)
        return copy.deepcopy(self.rows[attempt_id - 1])


class RemoteCompiler:
    """The same model and prompt are used for text and image conditions."""

    def __init__(self, root, transport: ChatTransport, budget: int):
        self.root = Path(root)
        self.transport = transport
        self.assets = AssetStore(self.root)
        self.ledger = AttemptLedger(self.root, budget)
        self.records: list[dict] = []

    def compile(self, source: dict, condition: str) -> dict:
        if condition not in ("text", "image"):
            raise ValueError("unknown input condition")
        identifier = f"D{len(self.records) + 1:07d}"
        bundle = self.assets.build(source)
        envelope = bundle[condition + "_input"]
        validate_envelope(envelope, source)
        attached_source = envelope["public_request"]
        _, buffered = unpack(attached_source)
        prompt = system_prompt(buffered is not None)
        prompt_path = self.root / "prompts" / ("buffer.txt" if buffered else "single.txt")
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        record = {"compilation_id": identifier, "condition": condition,
                  "contract_version": CONTRACT_VERSION,
                  "source": copy.deepcopy(source), "envelope": envelope,
                  "prompt_version": PROMPT_VERSION, "prompt_digest": digest(prompt),
                  "test_double": self.transport.test_double, "attempts": [],
                  "response": None, "status": "in_flight", "first_valid": False,
                  "repaired_valid": False}
        path = self.root / "responses" / f"{identifier}.json"
        write(path, record)
        repair_error = None
        for repair_index in range(2):
            try:
                body = self.transport.body(envelope, self.root, prompt, repair_error)
                attempt_id = self.ledger.start(identifier, digest(body), bool(repair_index))
            except O4Error as exc:
                record["status"] = exc.code
                break
            started = time.perf_counter()
            payload = None
            raw_text = None
            response = None
            error_detail = None
            diagnostic = None
            try:
                result = self.transport.complete(body)
                payload = result["payload"]
                raw_text = result.get("raw_text")
                response = parse_response(payload, attached_source)
                status = "valid"
            except O4Error as exc:
                status = exc.code
                error_detail = str(exc)
                if status in ("invalid_ast", "invalid_binding"):
                    diagnostic = repair_context(exc, payload)
            attempt = self.ledger.finish(
                attempt_id, status=status, payload=payload, raw_text=raw_text, error_detail=error_detail,
                repair_diagnostic=diagnostic,
                usage=payload.get("usage") if isinstance(payload, dict) else None,
                latency_s=time.perf_counter() - started,
            )
            record["attempts"].append(attempt)
            record["status"] = status
            write(path, record)
            if response is not None:
                record.update(response=response, first_valid=repair_index == 0,
                              repaired_valid=repair_index == 1)
                break
            if status not in ("invalid_ast", "invalid_binding"):
                break
            repair_error = diagnostic
        write(path, record)
        self.records.append(copy.deepcopy(record))
        write(self.root / "public/assets.json", self.assets.assets)
        return record


class RecordedCompiler:
    """Consume saved responses once, revalidate them and never open a socket."""

    def __init__(self, records: list[dict]):
        self.records = copy.deepcopy(records)
        self.cursor = 0

    def compile(self, source: dict, condition: str) -> dict:
        if self.cursor >= len(self.records):
            raise O4Error("replay_mismatch", "missing compilation")
        record = self.records[self.cursor]
        self.cursor += 1
        if record.get("contract_version") != CONTRACT_VERSION:
            raise O4Error("replay_mismatch", "compilation contract version")
        if record["source"] != source or record["condition"] != condition:
            raise O4Error("replay_mismatch", "changed compilation state")
        validate_envelope(record["envelope"], source)
        parsed = None
        for index, attempt in enumerate(record["attempts"]):
            if parsed is not None:
                raise O4Error("replay_mismatch", "attempt after valid response")
            diagnostic = None
            try:
                if attempt["payload"] is not None:
                    parsed = parse_response(attempt["payload"], record["envelope"]["public_request"])
                    status = "valid"
                else:
                    status = "provider_error"
            except O4Error as exc:
                status = exc.code
                if status in ("invalid_ast", "invalid_binding"):
                    diagnostic = repair_context(exc, attempt["payload"])
            if status != attempt["status"]:
                raise O4Error("replay_mismatch", "changed raw response or status")
            if attempt.get("repair_diagnostic") != diagnostic:
                raise O4Error("replay_mismatch", "changed repair diagnostic")
        if parsed != record["response"]:
            raise O4Error("replay_mismatch", "changed parsed response")
        successful_index = len(record["attempts"]) - 1 if parsed is not None else None
        if (record["first_valid"] != (successful_index == 0)
                or record["repaired_valid"] != (successful_index == 1)):
            raise O4Error("replay_mismatch", "first/repair metrics")
        if record["attempts"] and record["status"] != record["attempts"][-1]["status"]:
            if record["status"] not in ("budget_exhausted", "image_limit", "request_limit"):
                raise O4Error("replay_mismatch", "terminal compilation status")
        return copy.deepcopy(record)


def audit_records(records: list[dict], encoder: ChatTransport, root, budget: int) -> None:
    """Reconstruct the entire attempt/repair/budget state machine offline."""
    issued = 0
    for record in records:
        validate_envelope(record["envelope"], record["source"])
        attached = record["envelope"]["public_request"]
        prompt = system_prompt("observation" in attached)
        prompt_path = Path(root) / "prompts" / ("buffer.txt" if "observation" in attached else "single.txt")
        if prompt_path.read_text() != prompt:
            raise O4Error("replay_mismatch", "saved prompt")
        if (record.get("contract_version") != CONTRACT_VERSION
                or record["prompt_version"] != PROMPT_VERSION or record["prompt_digest"] != digest(prompt)):
            raise O4Error("replay_mismatch", "prompt version")
        consumed = 0
        parsed = None
        repair_error = None
        for repair_index in range(2):
            try:
                body = encoder.body(record["envelope"], root, prompt, repair_error)
                if issued >= budget:
                    raise O4Error("budget_exhausted")
            except O4Error as exc:
                status = exc.code
                break
            if consumed >= len(record["attempts"]):
                raise O4Error("replay_mismatch", "missing issued attempt")
            attempt = record["attempts"][consumed]
            consumed += 1
            issued += 1
            if (attempt["attempt_id"] != issued or attempt["body_digest"] != digest(body)
                    or attempt["repair"] != bool(repair_index)
                    or attempt["compilation_id"] != record["compilation_id"]):
                raise O4Error("replay_mismatch", "attempt binding")
            try:
                parsed = parse_response(attempt["payload"], attached)
                status = "valid"
                diagnostic = None
            except O4Error as exc:
                status = exc.code
                diagnostic = repair_context(exc, attempt["payload"]) if status in ("invalid_ast", "invalid_binding") else None
            if status != attempt["status"]:
                raise O4Error("replay_mismatch", "attempt status")
            if attempt.get("repair_diagnostic") != diagnostic:
                raise O4Error("replay_mismatch", "repair diagnostic")
            if parsed is not None or status not in ("invalid_ast", "invalid_binding"):
                break
            repair_error = diagnostic
        if consumed != len(record["attempts"]) or status != record["status"] or parsed != record["response"]:
            raise O4Error("replay_mismatch", "terminal compilation")
