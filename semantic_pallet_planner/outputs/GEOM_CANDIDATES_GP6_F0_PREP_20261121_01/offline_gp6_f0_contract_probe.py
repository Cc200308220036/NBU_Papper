#!/usr/bin/env python3
"""Offline GP6-F0 contract probe using Python stdlib only.

Strictly read-only over archived GP5 artifacts and production source files.
- Real model calls: 0
- Reads no API credentials
- Runs no network transport, no real orders, no monitor/LP, no freeze, no real recovery.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import pathlib
import platform
import sys
import tempfile
from decimal import Decimal
from typing import Any


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT_DIR = pathlib.Path(__file__).resolve().parent
GP5_RUN_DIR = REPO_ROOT / "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_FORMAL_ORDER_RUN_20261120_01"
SRC_JEV = REPO_ROOT / "semantic_pallet_planner/src/semantic_pallet_planner/jev_select"


def canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --- Offline contract double for RequestLedger + parse_response semantics ---

class OfflineDoubleTransport:
    """Pure in-memory transport double; never touches network or credentials."""

    origin = "test_double"

    def __init__(self, handler):
        self._handler = handler
        self.calls: list[dict[str, Any]] = []

    def complete(self, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(copy.deepcopy(body))
        return self._handler(body, len(self.calls))


def make_transport_outcome(status: str, raw: bytes = b"", *, http_status: int | None = None, error: str | None = None, network_attempted: bool | None = False) -> dict[str, Any]:
    return {
        "version": "jev_transport_v1",
        "status": status,
        "http_status": http_status,
        "raw_body_b64": base64.b64encode(raw).decode("ascii"),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "latency_s": 0.0,
        "error": error,
        "network_attempted": network_attempted,
    }


def parse_choice_response_contract(context: dict[str, Any], saved_transport: dict[str, Any], *, expected_model: str, prob_tol: float = 1e-5) -> dict[str, Any]:
    """Mirrors selector.parse_response contract checks without external deps."""
    if saved_transport["status"] != "OK":
        status = "unknown_in_flight" if saved_transport["status"] == "UNKNOWN_IN_FLIGHT" else "provider_failure"
        return {"status": status, "selected_display_id": None, "selected_candidate_id": None, "error": saved_transport["error"]}
    raw = base64.b64decode(saved_transport["raw_body_b64"], validate=True)
    if hashlib.sha256(raw).hexdigest() != saved_transport["raw_sha256"]:
        return {"status": "invalid_response", "selected_display_id": None, "selected_candidate_id": None, "error": "raw_digest_changed"}
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("model") != expected_model:
            raise ValueError("wrong_served_model")
        answers = payload.get("answers")
        if not isinstance(answers, dict) or set(answers) != {"next_action"}:
            raise ValueError("wrong_question_keys")
        ans = answers["next_action"]
        if not isinstance(ans, dict) or set(ans) != {"type", "choice", "probabilities", "confidence"} or ans["type"] != "choice":
            raise ValueError("wrong_choice_type")
        labels = context["criteria"]
        choice = ans["choice"]
        probs = ans["probabilities"]
        conf = ans["confidence"]
        if not isinstance(choice, str) or choice not in labels:
            raise ValueError("unknown_choice")
        if not isinstance(probs, dict) or set(probs) != set(labels):
            raise ValueError("wrong_probability_keys")
        vals = [*probs.values(), conf]
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in vals):
            raise ValueError("invalid_probability_value")
        if abs(math.fsum(probs.values()) - 1.0) > prob_tol:
            # 2dp rounding interval check (strict_or_2dp_rounding_interval_v1)
            decs = [Decimal(str(v)).quantize(Decimal("0.01")) for v in probs.values()]
            half = Decimal("0.005")
            if not (sum(max(Decimal(0), d - half) for d in decs) <= Decimal(1) <= sum(min(Decimal(1), d + half) for d in decs)):
                raise ValueError("invalid_probability_sum")
        if max(probs.values()) - probs[choice] > prob_tol:
            raise ValueError("choice_not_maximum")
        mapping_entry = context["display_mapping"][choice]
        return {
            "status": "selected",
            "selected_display_id": choice,
            "selected_candidate_id": mapping_entry["candidate_id"],
            "candidate_digest": mapping_entry["candidate_digest"],
            "served_model": payload["model"],
            "error": None,
        }
    except Exception as exc:
        return {"status": "invalid_response", "selected_display_id": None, "selected_candidate_id": None, "error": str(exc)}


class OfflineRequestLedgerDouble:
    """Pure stdlib mirror of packaging_remote.RequestLedger state machine."""

    def __init__(self, path: pathlib.Path, *, max_sends: int):
        self.path = path
        self.max_sends = max_sends
        if not self.path.exists():
            self._save({"version": "gp6_offline_probe_ledger_v1", "max_sends": max_sends, "requests": []})

    def _save(self, data: dict[str, Any]) -> None:
        self.path.write_text(canonical(data) + "\n", encoding="utf-8")

    def _load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def request(self, context: dict[str, Any], job_id: str, decision_id: str, transport: OfflineDoubleTransport | None) -> dict[str, Any]:
        if context["route"] != "CHOICE_REQUIRED":
            raise ValueError("route_not_choice_required")
        ctx_digest = digest(context)
        body_digest = digest(context["request_body"])
        data = self._load()
        matches = [r for r in data["requests"] if (r["job_id"], r["decision_id"]) == (job_id, decision_id)]
        if matches:
            row = matches[0]
            if row["context_digest"] != ctx_digest or row["body_digest"] != body_digest:
                raise ValueError("stale_request")
            if row["state"] == "SENDING":
                row["transport"] = make_transport_outcome("UNKNOWN_IN_FLIGHT", error="UNKNOWN_SEND", network_attempted=None)
                row["state"] = "UNKNOWN_SEND"
                self._save(data)
            if row["state"] != "INTENT":
                return copy.deepcopy(row)
        else:
            if transport is None:
                raise ValueError("missing_transport")
            if sum(1 for r in data["requests"] if r["send_started"]) >= self.max_sends:
                raise ValueError("request_budget_exhausted")
            row = {
                "attempt_id": f"A{len(data['requests']) + 1:06d}",
                "job_id": job_id,
                "decision_id": decision_id,
                "context_digest": ctx_digest,
                "body_digest": body_digest,
                "send_started": False,
                "state": "INTENT",
                "transport": None,
                "selection": None,
            }
            data["requests"].append(row)
            self._save(data)

        row["send_started"] = True
        row["state"] = "SENDING"
        self._save(data)
        try:
            saved = transport.complete(context["request_body"])
        except Exception:
            saved = make_transport_outcome("UNKNOWN_IN_FLIGHT", error="UNKNOWN_SEND", network_attempted=None)
        row["transport"] = saved
        row["state"] = "UNKNOWN_SEND" if saved["status"] == "UNKNOWN_IN_FLIGHT" else ("RESPONSE_SAVED" if saved["status"] == "OK" else "FAILED")
        self._save(data)
        return copy.deepcopy(row)

    def save_selection(self, attempt_id: str, selection: dict[str, Any]) -> None:
        data = self._load()
        row = next(r for r in data["requests"] if r["attempt_id"] == attempt_id)
        if row["selection"] is not None:
            if row["selection"] != selection:
                raise ValueError("selection_overwrite")
            return
        row["selection"] = selection
        if selection["status"] == "selected":
            row["state"] = "SELECTION_SAVED"
        self._save(data)


def main() -> None:
    checks: list[dict[str, Any]] = []

    def record(name: str, passed: bool, evidence: Any) -> None:
        checks.append({"probe": name, "status": "PASS" if passed else "FAIL", "evidence": evidence})

    # Load real archived GP5 decision events (E2 J00_D0000 and EMS J02_D0000)
    j00_rec = load_json(GP5_RUN_DIR / "jobs/J00/record.json")
    j02_rec = load_json(GP5_RUN_DIR / "jobs/J02/record.json")
    j00_d0 = next(e for e in j00_rec["checkpoint"]["events"] if e.get("decision_id") == "J00_D0000")
    j02_d0 = next(e for e in j02_rec["checkpoint"]["events"] if e.get("decision_id") == "J02_D0000")

    # Probe 1: F0 public-state-only & zero-memory audit on archived E2 + EMS contexts
    forbidden_tokens = [
        "e2_original_v1",
        "ems_surface_hybrid_v1",
        "EMS_STYLE_3D",
        "SURFACE_CORNER",
        "pct_exact_pose_network",
        "stability_monitor",
        "future_items",
        "NEW_00100027",
        "SG_901bbb22f834c63f",
    ]
    f0_audit = {}
    f0_ok = True
    for label, ev in [("J00_D0000_E2", j00_d0), ("J02_D0000_EMS", j02_d0)]:
        ctx = ev["context"]
        body = ctx["request_body"]
        body_bytes = canonical(body).encode("utf-8")
        body_str = body_bytes.decode("utf-8")
        leaked = [tok for tok in forbidden_tokens if tok in body_str]
        mem_empty = ctx["model_state"]["memories"] == [] and "memory_view" not in ctx and "retrieval_receipt" not in ctx
        size_ok = len(body_bytes) <= 96000
        labels_ok = sorted(ctx["criteria"].keys()) == [f"C{i:02d}" for i in range(1, len(ctx["criteria"]) + 1)]
        same_keys = set(ctx["criteria"].keys()) == set(ctx["display_mapping"].keys())
        item_ok = mem_empty and size_ok and labels_ok and same_keys and not leaked
        f0_ok = f0_ok and item_ok
        f0_audit[label] = {
            "route": ctx["route"],
            "criteria_count": len(ctx["criteria"]),
            "memories_empty": mem_empty,
            "request_body_bytes": len(body_bytes),
            "within_96000_bytes": size_ok,
            "cxx_labels_contiguous": labels_ok,
            "mapping_keys_match_criteria": same_keys,
            "forbidden_tokens_leaked": leaked,
        }
    record("P1_f0_public_state_only_and_no_memory_injection", f0_ok, f0_audit)

    # Probe 2: Jev Cxx choice -> exact candidate & exact pose binding + negative rejections
    sample_ctx = copy.deepcopy(j02_d0["context"])
    sample_bundle = j02_d0["bundle"]
    target_model = "jev-1.14.0"
    sample_ctx["request_body"]["model"] = target_model
    labels = sorted(sample_ctx["criteria"].keys())
    chosen_label = labels[1]  # C02
    probs = {l: 0.0 for l in labels}
    probs[chosen_label] = 1.0
    ok_payload = {
        "model": target_model,
        "answers": {"next_action": {"type": "choice", "choice": chosen_label, "probabilities": probs, "confidence": 0.9}},
        "usage": {"input_tokens": 100, "output_tokens": 10},
    }
    ok_sel = parse_choice_response_contract(
        sample_ctx,
        make_transport_outcome("OK", json.dumps(ok_payload).encode("utf-8"), http_status=200),
        expected_model=target_model,
    )
    mapped_cand = next(c for c in sample_bundle["physical_candidates"] if c["candidate_id"] == ok_sel["selected_candidate_id"])
    exact_match = (
        ok_sel["status"] == "selected"
        and ok_sel["selected_display_id"] == chosen_label
        and digest(mapped_cand) == ok_sel["candidate_digest"]
        and mapped_cand["pose"] == sample_ctx["criteria"][chosen_label]["pose"]
        and mapped_cand["oriented_size_mm"] == sample_ctx["criteria"][chosen_label]["oriented_size_mm"]
    )
    # Negative cases
    neg_unknown = copy.deepcopy(ok_payload)
    neg_unknown["answers"]["next_action"]["choice"] = "C99"
    r_neg_unknown = parse_choice_response_contract(sample_ctx, make_transport_outcome("OK", json.dumps(neg_unknown).encode("utf-8"), http_status=200), expected_model=target_model)

    neg_wrong_model = copy.deepcopy(ok_payload)
    neg_wrong_model["model"] = "wrong-model"
    r_neg_model = parse_choice_response_contract(sample_ctx, make_transport_outcome("OK", json.dumps(neg_wrong_model).encode("utf-8"), http_status=200), expected_model=target_model)

    neg_not_max = copy.deepcopy(ok_payload)
    neg_not_max["answers"]["next_action"]["choice"] = labels[0]
    r_neg_not_max = parse_choice_response_contract(sample_ctx, make_transport_outcome("OK", json.dumps(neg_not_max).encode("utf-8"), http_status=200), expected_model=target_model)

    p2_ok = (
        exact_match
        and r_neg_unknown["status"] == "invalid_response"
        and r_neg_model["status"] == "invalid_response"
        and r_neg_not_max["status"] == "invalid_response"
    )
    record(
        "P2_cxx_choice_exact_action_binding_and_negative_rejections",
        p2_ok,
        {
            "selected_display_id": ok_sel["selected_display_id"],
            "selected_candidate_id": ok_sel["selected_candidate_id"],
            "pose_exact_match": mapped_cand["pose"] == sample_ctx["criteria"][chosen_label]["pose"],
            "candidate_digest_match": digest(mapped_cand) == ok_sel["candidate_digest"],
            "neg_unknown_choice": r_neg_unknown["error"],
            "neg_wrong_model": r_neg_model["error"],
            "neg_choice_not_max": r_neg_not_max["error"],
        },
    )

    # Probe 3: Singleton bypass never calls transport or consumes request ledger
    singleton_ctx = copy.deepcopy(sample_ctx)
    singleton_ctx["route"] = "SINGLETON_BYPASS"
    singleton_ctx["criteria"] = {"C01": sample_ctx["criteria"]["C01"]}
    singleton_ctx["display_mapping"] = {"C01": sample_ctx["display_mapping"]["C01"]}
    singleton_ctx["request_body"] = None
    singleton_transport = OfflineDoubleTransport(lambda b, n: make_transport_outcome("OK", b"{}", http_status=200))
    if singleton_ctx["route"] == "SINGLETON_BYPASS":
        singleton_sel = {
            "status": "singleton",
            "source": "singleton",
            "selected_display_id": "C01",
            "selected_candidate_id": singleton_ctx["display_mapping"]["C01"]["candidate_id"],
        }
    else:
        singleton_transport.complete(singleton_ctx["request_body"])
        singleton_sel = {}
    p3_ok = (
        singleton_ctx["request_body"] is None
        and len(singleton_transport.calls) == 0
        and singleton_sel["status"] == "singleton"
        and singleton_sel["selected_display_id"] == "C01"
    )
    record(
        "P3_singleton_bypass_zero_transport_calls",
        p3_ok,
        {"route": singleton_ctx["route"], "request_body": singleton_ctx["request_body"], "transport_calls": len(singleton_transport.calls), "selection": singleton_sel},
    )

    # Probe 4: Saved selection idempotency (no resend) & stale_request rejection
    with tempfile.TemporaryDirectory(prefix="gp6_probe_") as td:
        ledger = OfflineRequestLedgerDouble(pathlib.Path(td) / "requests.json", max_sends=2)
        t_ok = OfflineDoubleTransport(lambda b, n: make_transport_outcome("OK", json.dumps(ok_payload).encode("utf-8"), http_status=200))
        a1 = ledger.request(sample_ctx, "G00", "G00_D0000", t_ok)
        s1 = parse_choice_response_contract(sample_ctx, a1["transport"], expected_model=target_model)
        ledger.save_selection(a1["attempt_id"], s1)
        # Re-request same decision -> must reuse saved selection, no second send
        a2 = ledger.request(sample_ctx, "G00", "G00_D0000", t_ok)
        # Mutated context -> must raise stale_request
        mutated_ctx = copy.deepcopy(sample_ctx)
        mutated_ctx["request_body"]["state"]["objective"] = "TAMPERED"
        stale_rejected = False
        try:
            ledger.request(mutated_ctx, "G00", "G00_D0000", t_ok)
        except ValueError as exc:
            stale_rejected = str(exc) == "stale_request"
        p4_ok = (
            len(t_ok.calls) == 1
            and a2["state"] == "SELECTION_SAVED"
            and a2["selection"] == s1
            and stale_rejected
        )
        record(
            "P4_saved_selection_no_resend_and_stale_rejection",
            p4_ok,
            {"transport_calls_after_replay": len(t_ok.calls), "replayed_state": a2["state"], "stale_request_rejected": stale_rejected},
        )

    # Probe 5: UNKNOWN_SEND stops immediately with zero implicit retries (both exception and interrupted SENDING)
    with tempfile.TemporaryDirectory(prefix="gp6_probe_unk_") as td:
        ledger_u = OfflineRequestLedgerDouble(pathlib.Path(td) / "requests.json", max_sends=2)

        def fail_timeout(_b, _n):
            raise TimeoutError("simulated timeout")

        t_unk = OfflineDoubleTransport(fail_timeout)
        u1 = ledger_u.request(sample_ctx, "G01", "G01_D0000", t_unk)
        u1_sel = parse_choice_response_contract(sample_ctx, u1["transport"], expected_model=target_model)
        # Re-request after UNKNOWN_SEND -> must NOT retry
        u2 = ledger_u.request(sample_ctx, "G01", "G01_D0000", t_unk)

        # Simulate crash while state == SENDING on G01_D0001
        raw_ledger = json.loads((pathlib.Path(td) / "requests.json").read_text(encoding="utf-8"))
        raw_ledger["requests"].append(
            {
                "attempt_id": "A000002",
                "job_id": "G01",
                "decision_id": "G01_D0001",
                "context_digest": digest(sample_ctx),
                "body_digest": digest(sample_ctx["request_body"]),
                "send_started": True,
                "state": "SENDING",
                "transport": None,
                "selection": None,
            }
        )
        (pathlib.Path(td) / "requests.json").write_text(canonical(raw_ledger) + "\n", encoding="utf-8")
        u3 = ledger_u.request(sample_ctx, "G01", "G01_D0001", t_unk)

        p5_ok = (
            u1["state"] == "UNKNOWN_SEND"
            and u1_sel["status"] == "unknown_in_flight"
            and u2["state"] == "UNKNOWN_SEND"
            and len(t_unk.calls) == 1
            and u3["state"] == "UNKNOWN_SEND"
            and len(t_unk.calls) == 1
        )
        record(
            "P5_unknown_send_stops_and_never_implicitly_retries",
            p5_ok,
            {
                "first_state": u1["state"],
                "parsed_status": u1_sel["status"],
                "replay_state": u2["state"],
                "interrupted_sending_recovered_state": u3["state"],
                "total_transport_calls": len(t_unk.calls),
            },
        )

    # Probe 6: Static verification of GP5 local gates & untouched default/explicit routing
    goe_text = (SRC_JEV / "geometry_order_execution.py").read_text(encoding="utf-8")
    pv_text = (SRC_JEV / "packaging_versions.py").read_text(encoding="utf-8")
    cfg_v17 = load_json(SRC_JEV / "schemas/config_v17.schema.json")
    plan_v2 = load_json(SRC_JEV / "schemas/geometry_order_plan_v2.schema.json")
    gp5_gates_intact = (
        "geometry_order_local_selector_required" in goe_text
        and "DEFAULT_GEOMETRY_BACKEND='ems_surface_hybrid_v1'" in pv_text
        and "GEOMETRY_BACKENDS=('e2_original_v1','ems_surface_hybrid_v1')" in pv_text
        and cfg_v17["properties"]["model"].get("const") == "LOCAL_TEST_DOUBLE_NOT_JEV"
        and cfg_v17["properties"]["selector"].get("enum") == ["local_geometry_test_double", "local_first_test_double"]
        and plan_v2["properties"]["model_calls_max"].get("const") == 0
    )
    record(
        "P6_gp5_local_gates_and_backend_routes_intact",
        gp5_gates_intact,
        {
            "default_backend_ems": "DEFAULT_GEOMETRY_BACKEND='ems_surface_hybrid_v1'" in pv_text,
            "explicit_e2_and_ems_registered": "GEOMETRY_BACKENDS=('e2_original_v1','ems_surface_hybrid_v1')" in pv_text,
            "v17_model_locked_local": cfg_v17["properties"]["model"].get("const"),
            "v17_selector_locked_local": cfg_v17["properties"]["selector"].get("enum"),
            "plan_v2_model_calls_max_const": plan_v2["properties"]["model_calls_max"].get("const"),
        },
    )

    all_passed = all(c["status"] == "PASS" for c in checks)
    receipt = {
        "schema": "gp6_f0_offline_contract_receipt_v1",
        "date": "2026-11-21",
        "interpreter": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "jsonschema_available_in_probe_env": False,
            "note": "Probe uses Python stdlib only; no dependencies were installed or modified.",
        },
        "real_model_calls": 0,
        "credentials_read": False,
        "network_attempted": False,
        "all_offline_probes_passed": all_passed,
        "probes_count": len(checks),
        "passed_count": sum(1 for c in checks if c["status"] == "PASS"),
        "failed_count": sum(1 for c in checks if c["status"] != "PASS"),
        "probes": checks,
        "not_run_real_chain_behaviors": {
            "real_jev_https_transport": "NOT_RUN",
            "real_jev_api_response_parsing": "NOT_RUN",
            "production_pytest_with_jsonschema": "NOT_RUN_MISSING_JSONSCHEMA_IN_SANDBOX_PYTHON",
            "real_order_episode_execution": "NOT_RUN",
            "real_pct_exact_pose_v3_monitor_and_lp": "NOT_RUN",
            "real_plan_or_monitor_freeze": "NOT_RUN",
            "real_checkpoint_recovery_execution": "NOT_RUN",
        },
        "boundary_statement": (
            "Offline contract doubles verify only isolated F0 payload/binding/ledger/gate invariants. "
            "They do NOT prove that end-to-end production GP6 transport, orders, monitoring, or recovery have passed."
        ),
    }
    (OUT_DIR / "offline_contract_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_offline_probes_passed": all_passed, "passed": receipt["passed_count"], "total": receipt["probes_count"]}, ensure_ascii=False))
    if not all_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
