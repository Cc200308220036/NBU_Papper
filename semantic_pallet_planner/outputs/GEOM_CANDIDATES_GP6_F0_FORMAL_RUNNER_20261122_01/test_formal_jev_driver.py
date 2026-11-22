"""Offline test-double suite for formal_jev_driver.py (GP6-F0-LAUNCH-01).

Verifies:
- Default --preflight-only: 4/4 PASS, 0 dispatches, ledgers byte-unchanged, no lock/run_root created.
- Preflight failures: DRAFT plan, missing bridge/admission, non-empty request ledger, non-zero call ledger,
  ledger inside --run-root conflict, existing --run-root overwrite, config failure on G02 -> all 0 dispatches.
- Historical source temporary Git export from 2c97f59444f07e40b98da529e5256efc441207d4: readable during
  preflight/execution, exact 594-file manifest match, cleaned up on exit.
- Sequential G00->G01->G02->G03 dispatch with persistent checkpoint callback and normal stops continuing.
- Immediate batch halt on UNKNOWN_SEND, BUDGET_EXHAUSTED, and TECHNICAL_FAILURE/exception, preserving
  remaining jobs as NOT_RUN with full 4-job denominator and 0 implicit retries.
- Strictly 0 real model calls, 0 real monitor calls, 0 LP calls, 0 credential reads.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
import formal_jev_driver as drv  # noqa: E402


def _make_initial_ledgers(ledger_dir: Path, plan: dict) -> tuple[Path, Path]:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    plan_digest = drv.digest(plan)
    req_path = ledger_dir / "requests.json"
    req_body = {
        "version": "geometry_jev_requests_v1",
        "plan_digest": plan_digest,
        "per_job_max_sends": 19,
        "max_sends": 76,
        "requests": [],
    }
    req_body["record_digest"] = drv.digest(req_body)
    req_path.write_text(json.dumps(req_body, indent=2) + "\n", encoding="utf-8")

    call_path = ledger_dir / "shared_call_ledger.json"
    call_body = {
        "version": "geometry_call_ledger_v1",
        "plan_digest": plan_digest,
        "evidence": "REAL_KERNEL",
        "limits": {"assessment_entries": 76, "solver_calls": 4096},
        "calls": [],
        "counts": {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0},
    }
    call_path.write_text(json.dumps(call_body, indent=2) + "\n", encoding="utf-8")
    return req_path, call_path


def _build_synthetic_frozen_fixture(td: Path) -> dict:
    """Build a synthetic FROZEN plan + separated initial ledgers inside temp dir for offline tests only."""
    data_manifest = drv.read_json(drv.DATA_ROOT / "manifest.json")
    adapted = []
    for tid in drv.pkg_proto.TASK_IDS:
        raw = (drv.DATA_ROOT / "tasks" / f"{tid}.json").read_bytes()
        adapted.append(
            drv.pkg_proto.adapt_task(
                raw,
                origin="EXPOSED_TRAIN",
                expected_sha256=hashlib.sha256(raw).hexdigest(),
            )
        )

    ledger_dir = td / "prep_ledgers"
    req_path = ledger_dir / "requests.json"
    call_path = ledger_dir / "shared_call_ledger.json"
    plan = drv.jev_proto.prepare_jev_plan(
        adapted,
        data_identity=data_manifest["data_identity"],
        scope=drv.jev_proto.GP6_ORDER,
        per_job_max_sends=19,
        shared_max_sends=76,
        request_ledger_path=str(req_path),
        call_ledger_path=str(call_path),
    )
    plan["status"] = "FROZEN"
    drv.jev_proto.validate_jev_plan(plan)
    _make_initial_ledgers(ledger_dir, plan)

    plan_path = td / "plan_SYNTHETIC_FROZEN.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    bridge_path = td / "bridge_SYNTHETIC.json"
    bridge_path.write_text(json.dumps({"historical_package_root": str(td / "hist_src")}), encoding="utf-8")

    admission_path = td / "admission_SYNTHETIC.json"
    admission_path.write_text(json.dumps({"dummy": True}), encoding="utf-8")

    return {
        "plan": plan,
        "plan_path": plan_path,
        "req_path": req_path,
        "call_path": call_path,
        "ledger_dir": ledger_dir,
        "bridge_path": bridge_path,
        "admission_path": admission_path,
    }


def _fake_load_jev_config(plan: dict, job_id: str, **_kwargs) -> dict:
    job = next(j for j in plan["jobs"] if j["job_id"] == job_id)
    return {
        "version": drv.jev_proto.GEOMETRY_JEV_VERSION if hasattr(drv.jev_proto, "GEOMETRY_JEV_VERSION") else "jev_packaging_geometry_jev_v18",
        "model": drv.jev_proto.GP6_MODEL,
        "endpoint": drv.jev_proto.GP6_ENDPOINT,
        "api_key_env": drv.jev_proto.GP6_API_KEY_ENV,
        "timeout_s": 30.0,
        "max_retries": 0,
        "max_request_bytes": 96000,
        "response_max_bytes": 1000000,
        "monitor_evidence": "REAL_KERNEL",
        "transport_evidence": "REAL_JEV",
        "candidate_backend": job["backend"],
        "selector": job["method"],
        "order_task_identity": {"task_id": job["task_id"]},
        "plan_digest": drv.digest(plan),
        "per_job_max_sends": plan["per_job_max_sends"],
        "shared_max_sends": plan["shared_max_sends"],
    }


class TestFormalJevDriverOffline(unittest.TestCase):
    def test_preflight_only_default_zero_dispatch_and_untouched_ledgers(self):
        spy = MagicMock()
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            fx = _build_synthetic_frozen_fixture(td)
            req_bytes_before = fx["req_path"].read_bytes()
            call_bytes_before = fx["call_path"].read_bytes()
            run_root = td / "formal_run_never_created"

            with (
                patch.object(drv.jev_proto, "validate_jev_admission", return_value=True),
                patch.object(drv.jev_exec, "load_jev_config", side_effect=_fake_load_jev_config),
                patch.object(drv.jev_exec, "run_jev_job", spy),
            ):
                rc = drv.main([
                    "--plan", str(fx["plan_path"]),
                    "--kernel-bridge", str(fx["bridge_path"]),
                    "--admission", str(fx["admission_path"]),
                    "--run-root", str(run_root),
                    "--no-git-historical-export",
                ])

            self.assertEqual(rc, 0)
            self.assertEqual(spy.call_count, 0)
            self.assertFalse(run_root.exists())
            self.assertEqual(fx["req_path"].read_bytes(), req_bytes_before)
            self.assertEqual(fx["call_path"].read_bytes(), call_bytes_before)
            self.assertFalse((fx["ledger_dir"] / ".writer.lock").exists())

    def test_draft_plan_rejected_with_zero_dispatches(self):
        spy = MagicMock()
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            fx = _build_synthetic_frozen_fixture(td)
            draft_plan = copy.deepcopy(fx["plan"])
            draft_plan["status"] = "DRAFT"
            draft_path = td / "plan_DRAFT.json"
            draft_path.write_text(json.dumps(draft_plan), encoding="utf-8")
            run_root = td / "run_draft"
            with patch.object(drv.jev_exec, "run_jev_job", spy):
                with self.assertRaisesRegex(AssertionError, "PLAN_NOT_FROZEN"):
                    drv.main([
                        "--plan", str(draft_path),
                        "--kernel-bridge", str(fx["bridge_path"]),
                        "--admission", str(fx["admission_path"]),
                        "--run-root", str(run_root),
                        "--execute",
                        "--no-git-historical-export",
                    ])
            self.assertEqual(spy.call_count, 0)
            self.assertFalse(run_root.exists())

    def test_missing_bridge_or_admission_rejected_zero_dispatches(self):
        spy = MagicMock()
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            fx = _build_synthetic_frozen_fixture(td)
            run_root = td / "run_missing"
            with patch.object(drv.jev_exec, "run_jev_job", spy):
                with self.assertRaisesRegex(AssertionError, "MISSING_SIGNED_KERNEL_BRIDGE"):
                    drv.main([
                        "--plan", str(fx["plan_path"]),
                        "--run-root", str(run_root),
                        "--execute",
                        "--no-git-historical-export",
                    ])
            self.assertEqual(spy.call_count, 0)
            self.assertFalse(run_root.exists())

    def test_nonempty_request_ledger_rejected_byte_unchanged(self):
        spy = MagicMock()
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            fx = _build_synthetic_frozen_fixture(td)
            bad = drv.read_json(fx["req_path"])
            bad["requests"] = [{"attempt_id": "A000001"}]
            del bad["record_digest"]
            bad["record_digest"] = drv.digest(bad)
            raw_before = json.dumps(bad).encode("utf-8")
            fx["req_path"].write_bytes(raw_before)
            with patch.object(drv.jev_exec, "run_jev_job", spy):
                with self.assertRaisesRegex(AssertionError, "NONEMPTY_INITIAL_REQUEST_LEDGER"):
                    drv.main([
                        "--plan", str(fx["plan_path"]),
                        "--kernel-bridge", str(fx["bridge_path"]),
                        "--admission", str(fx["admission_path"]),
                        "--no-git-historical-export",
                    ])
            self.assertEqual(fx["req_path"].read_bytes(), raw_before)
            self.assertEqual(spy.call_count, 0)

    def test_nonzero_call_ledger_rejected_byte_unchanged(self):
        spy = MagicMock()
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            fx = _build_synthetic_frozen_fixture(td)
            bad = drv.read_json(fx["call_path"])
            bad["calls"] = [{"kind": "assessment_entries", "state": "DONE", "index": 0, "job_id": "G00"}]
            bad["counts"]["assessment_entries"] = 1
            raw_before = json.dumps(bad).encode("utf-8")
            fx["call_path"].write_bytes(raw_before)
            with patch.object(drv.jev_exec, "run_jev_job", spy):
                with self.assertRaisesRegex(AssertionError, "NONEMPTY_INITIAL_CALL_LEDGER"):
                    drv.main([
                        "--plan", str(fx["plan_path"]),
                        "--kernel-bridge", str(fx["bridge_path"]),
                        "--admission", str(fx["admission_path"]),
                        "--no-git-historical-export",
                    ])
            self.assertEqual(fx["call_path"].read_bytes(), raw_before)
            self.assertEqual(spy.call_count, 0)

    def test_ledger_inside_run_root_conflict_rejected(self):
        spy = MagicMock()
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            fx = _build_synthetic_frozen_fixture(td)
            with patch.object(drv.jev_exec, "run_jev_job", spy):
                with self.assertRaisesRegex(AssertionError, "LEDGER_INSIDE_RUN_ROOT_CONFLICT"):
                    drv.main([
                        "--plan", str(fx["plan_path"]),
                        "--kernel-bridge", str(fx["bridge_path"]),
                        "--admission", str(fx["admission_path"]),
                        "--run-root", str(fx["ledger_dir"]),
                        "--no-git-historical-export",
                    ])
            self.assertEqual(spy.call_count, 0)

    def test_existing_run_root_blocks_overwrite(self):
        spy = MagicMock()
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            fx = _build_synthetic_frozen_fixture(td)
            run_root = td / "existing_run"
            run_root.mkdir()
            with (
                patch.object(drv.jev_proto, "validate_jev_admission", return_value=True),
                patch.object(drv.jev_exec, "load_jev_config", side_effect=_fake_load_jev_config),
                patch.object(drv.jev_exec, "run_jev_job", spy),
            ):
                with self.assertRaisesRegex(AssertionError, "NO_OVERWRITE_EXISTING_RUN_ROOT"):
                    drv.main([
                        "--plan", str(fx["plan_path"]),
                        "--kernel-bridge", str(fx["bridge_path"]),
                        "--admission", str(fx["admission_path"]),
                        "--run-root", str(run_root),
                        "--execute",
                        "--no-git-historical-export",
                    ])
            self.assertEqual(spy.call_count, 0)

    def test_config_failure_on_g02_blocks_with_zero_dispatches(self):
        spy = MagicMock()
        def fail_g02(plan, job_id, **kw):
            if job_id == "G02":
                raise RuntimeError("SYNTHETIC_CFG_FAIL_G02")
            return _fake_load_jev_config(plan, job_id, **kw)

        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            fx = _build_synthetic_frozen_fixture(td)
            run_root = td / "run_cfg_fail"
            with (
                patch.object(drv.jev_proto, "validate_jev_admission", return_value=True),
                patch.object(drv.jev_exec, "load_jev_config", side_effect=fail_g02),
                patch.object(drv.jev_exec, "run_jev_job", spy),
            ):
                with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_CFG_FAIL_G02"):
                    drv.main([
                        "--plan", str(fx["plan_path"]),
                        "--kernel-bridge", str(fx["bridge_path"]),
                        "--admission", str(fx["admission_path"]),
                        "--run-root", str(run_root),
                        "--execute",
                        "--no-git-historical-export",
                    ])
            self.assertEqual(spy.call_count, 0)
            self.assertFalse(run_root.exists())

    def test_temporary_git_historical_export_matches_gp5_manifest_and_cleans_up(self):
        gp5_manifest = drv.read_json(
            drv.OUT_ROOT / "GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01" / "source_manifest.json"
        )
        with tempfile.TemporaryDirectory() as td_str:
            target = Path(td_str) / "temp_gp5_hist"
            bridge = {"historical_package_root": str(target)}
            with drv.historical_source_context(bridge) as info:
                self.assertEqual(info["mode"], "TEMPORARY_GIT_ARCHIVE_EXPORT")
                self.assertTrue(info["temporary"])
                self.assertTrue(target.is_dir())
                actual_files = {
                    p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in target.rglob("*")
                    if p.is_file()
                    and p.suffix in (".py", ".json")
                    and not {"tests", "__pycache__"}.intersection(p.relative_to(target).parts)
                }
                self.assertEqual(actual_files, gp5_manifest["files"])
                self.assertEqual(drv.digest(actual_files), gp5_manifest["source_identity"])
            self.assertFalse(target.exists())

    def test_execute_4_jobs_in_order_with_checkpoints_and_normal_stops(self):
        dispatched = []
        def offline_spy(plan, job_id, adapted, *, on_checkpoint=None, **_kwargs):
            dispatched.append(job_id)
            if on_checkpoint is not None:
                on_checkpoint({"job_id": job_id, "phase": "COMMITTED", "synthetic_test": True})
            mapping = {
                "G00": {"completed": True, "termination_class": "COMPLETE", "termination_reason": "ALL_ITEMS_PLACED", "placed_items": 19, "planned_items": 19},
                "G01": {"completed": False, "termination_class": "NO_CANDIDATE", "termination_reason": "STOP_NO_PHYSICAL_CANDIDATE", "placed_items": 12, "planned_items": 19},
                "G02": {"completed": False, "termination_class": "PREDICTED_STATIC_INSTABILITY", "termination_reason": "PREDICTED_STATIC_INSTABILITY", "placed_items": 8, "planned_items": 19},
                "G03": {"completed": False, "termination_class": "UNASSESSABLE", "termination_reason": "STABILITY_UNASSESSABLE", "placed_items": 6, "planned_items": 19},
            }
            return {"summary": mapping[job_id]}

        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            fx = _build_synthetic_frozen_fixture(td)
            run_root = td / "formal_run_ok"
            with (
                patch.object(drv.jev_proto, "validate_jev_admission", return_value=True),
                patch.object(drv.jev_exec, "load_jev_config", side_effect=_fake_load_jev_config),
                patch.object(drv, "JevTransport", side_effect=lambda cfg, api_key_file=None: MagicMock(origin="jev")),
                patch.object(drv.jev_exec, "run_jev_job", side_effect=offline_spy),
            ):
                rc = drv.main([
                    "--plan", str(fx["plan_path"]),
                    "--kernel-bridge", str(fx["bridge_path"]),
                    "--admission", str(fx["admission_path"]),
                    "--run-root", str(run_root),
                    "--execute",
                    "--no-git-historical-export",
                ])
            receipt = drv.read_json(run_root / "driver_receipt.json")
            for jid in ["G00", "G01", "G02", "G03"]:
                cp_file = run_root / "jobs" / jid / "checkpoint.json"
                self.assertTrue(cp_file.is_file(), f"missing checkpoint for {jid}")
                self.assertEqual(drv.read_json(cp_file)["job_id"], jid)

        self.assertEqual(rc, 0)
        self.assertEqual(dispatched, ["G00", "G01", "G02", "G03"])
        self.assertEqual(receipt["status"], "COMPLETE_4_OF_4_DISPATCHED")
        self.assertEqual(receipt["dispatched_jobs"], 4)
        self.assertEqual([r["status"] for r in receipt["rows"]], ["COMPLETE", "STOPPED", "STOPPED", "STOPPED"])

    def test_execute_halts_on_unknown_send_and_keeps_remaining_not_run(self):
        dispatched = []
        def offline_spy(plan, job_id, adapted, **_kwargs):
            dispatched.append(job_id)
            if job_id == "G01":
                return {"summary": {"completed": False, "termination_class": "UNKNOWN_SEND", "termination_reason": "UNKNOWN_IN_FLIGHT", "placed_items": 3, "planned_items": 19}}
            return {"summary": {"completed": True, "termination_class": "COMPLETE", "termination_reason": "ALL_ITEMS_PLACED", "placed_items": 19, "planned_items": 19}}

        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            fx = _build_synthetic_frozen_fixture(td)
            run_root = td / "formal_run_unknown"
            with (
                patch.object(drv.jev_proto, "validate_jev_admission", return_value=True),
                patch.object(drv.jev_exec, "load_jev_config", side_effect=_fake_load_jev_config),
                patch.object(drv, "JevTransport", side_effect=lambda cfg, api_key_file=None: MagicMock(origin="jev")),
                patch.object(drv.jev_exec, "run_jev_job", side_effect=offline_spy),
            ):
                rc = drv.main([
                    "--plan", str(fx["plan_path"]),
                    "--kernel-bridge", str(fx["bridge_path"]),
                    "--admission", str(fx["admission_path"]),
                    "--run-root", str(run_root),
                    "--execute",
                    "--no-git-historical-export",
                ])
            receipt = drv.read_json(run_root / "driver_receipt.json")

        self.assertEqual(rc, 1)
        self.assertEqual(dispatched, ["G00", "G01"])
        self.assertEqual(receipt["status"], "HALTED_ON_ERROR")
        self.assertEqual(receipt["first_error"]["type"], "UNKNOWN_SEND")
        self.assertEqual([r["job_id"] for r in receipt["rows"]], ["G00", "G01", "G02", "G03"])
        self.assertEqual([r["status"] for r in receipt["rows"]], ["COMPLETE", "STOPPED", "NOT_RUN", "NOT_RUN"])

    def test_execute_halts_on_budget_exhausted_and_keeps_remaining_not_run(self):
        dispatched = []
        def offline_spy(plan, job_id, adapted, **_kwargs):
            dispatched.append(job_id)
            if job_id == "G02":
                return {"summary": {"completed": False, "termination_class": "BUDGET_EXHAUSTED", "termination_reason": "BUDGET_EXHAUSTED", "placed_items": 5, "planned_items": 19}}
            return {"summary": {"completed": True, "termination_class": "COMPLETE", "termination_reason": "ALL_ITEMS_PLACED", "placed_items": 19, "planned_items": 19}}

        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            fx = _build_synthetic_frozen_fixture(td)
            run_root = td / "formal_run_budget"
            with (
                patch.object(drv.jev_proto, "validate_jev_admission", return_value=True),
                patch.object(drv.jev_exec, "load_jev_config", side_effect=_fake_load_jev_config),
                patch.object(drv, "JevTransport", side_effect=lambda cfg, api_key_file=None: MagicMock(origin="jev")),
                patch.object(drv.jev_exec, "run_jev_job", side_effect=offline_spy),
            ):
                rc = drv.main([
                    "--plan", str(fx["plan_path"]),
                    "--kernel-bridge", str(fx["bridge_path"]),
                    "--admission", str(fx["admission_path"]),
                    "--run-root", str(run_root),
                    "--execute",
                    "--no-git-historical-export",
                ])
            receipt = drv.read_json(run_root / "driver_receipt.json")

        self.assertEqual(rc, 1)
        self.assertEqual(dispatched, ["G00", "G01", "G02"])
        self.assertEqual(receipt["first_error"]["type"], "BUDGET_EXHAUSTED")
        self.assertEqual([r["status"] for r in receipt["rows"]], ["COMPLETE", "COMPLETE", "STOPPED", "NOT_RUN"])

    def test_execute_halts_on_technical_exception_and_keeps_remaining_not_run(self):
        dispatched = []
        def offline_spy(plan, job_id, adapted, **_kwargs):
            dispatched.append(job_id)
            if job_id == "G01":
                raise RuntimeError("SYNTHETIC_TECH_FAIL_G01")
            return {"summary": {"completed": True, "termination_class": "COMPLETE", "termination_reason": "ALL_ITEMS_PLACED", "placed_items": 19, "planned_items": 19}}

        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            fx = _build_synthetic_frozen_fixture(td)
            run_root = td / "formal_run_exc"
            with (
                patch.object(drv.jev_proto, "validate_jev_admission", return_value=True),
                patch.object(drv.jev_exec, "load_jev_config", side_effect=_fake_load_jev_config),
                patch.object(drv, "JevTransport", side_effect=lambda cfg, api_key_file=None: MagicMock(origin="jev")),
                patch.object(drv.jev_exec, "run_jev_job", side_effect=offline_spy),
            ):
                rc = drv.main([
                    "--plan", str(fx["plan_path"]),
                    "--kernel-bridge", str(fx["bridge_path"]),
                    "--admission", str(fx["admission_path"]),
                    "--run-root", str(run_root),
                    "--execute",
                    "--no-git-historical-export",
                ])
            receipt = drv.read_json(run_root / "driver_receipt.json")

        self.assertEqual(rc, 1)
        self.assertEqual(dispatched, ["G00", "G01"])
        self.assertEqual(receipt["first_error"]["type"], "RuntimeError")
        self.assertEqual([r["status"] for r in receipt["rows"]], ["COMPLETE", "TECHNICAL_FAILURE", "NOT_RUN", "NOT_RUN"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
