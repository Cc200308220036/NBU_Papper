"""Offline gate and control-flow spy tests for formal_order_driver.py.

Uses explicit OFFLINE_SPY_ONLY mocks; never executes real orders, monitor
assessments, LP solver, exact_freeze, recovery, or model calls.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
import formal_order_driver as drv  # noqa: E402


class TestFormalOrderDriverOffline(unittest.TestCase):
    def setUp(self):
        self.plan_path = drv.PREP_ROOT / "order_plan_FROZEN.json"
        self.snap_path = drv.PREP_ROOT / "monitor_snapshot.json"
        self.plan = drv.read(self.plan_path)
        self.dummy_cfg = {
            "monitor_evidence": "REAL_KERNEL",
            "candidate_backend": "e2_original_v1",
            "selector": "local_geometry_test_double",
            "order_task_identity": {"task_id": "NEW_00100027_controlled_base"},
        }

    def _fake_load_order_config(self, plan, job_id, **_kwargs):
        job = next(j for j in plan["jobs"] if j["job_id"] == job_id)
        return {
            "monitor_evidence": "REAL_KERNEL",
            "candidate_backend": job["backend"],
            "selector": job["method"],
            "order_task_identity": {"task_id": job["task_id"]},
        }

    def _write_dummy_auth_files(self, td):
        r_path = Path(td) / "kernel_receipt.json"
        a_path = Path(td) / "admission.json"
        r_path.write_text('{"dummy": true}')
        a_path.write_text('{"dummy": true}')
        return r_path, a_path

    def test_missing_receipt_blocks_with_zero_dispatches(self):
        spy = MagicMock()
        with patch.object(drv.order, "run_order_job", spy):
            with self.assertRaisesRegex(AssertionError, "MISSING_SIGNED_KERNEL_RECEIPT"):
                drv.main(["--execute", "--run-root", "/tmp/unused_gp5_test"])
        self.assertEqual(spy.call_count, 0)

    def test_plan_digest_mismatch_blocks_with_zero_dispatches(self):
        spy = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            bad_plan = dict(self.plan, assessment_limit=100)
            bad_plan_path = Path(td) / "bad_plan.json"
            bad_plan_path.write_text(json.dumps(bad_plan))
            r_path, a_path = self._write_dummy_auth_files(td)
            with patch.object(drv.order, "run_order_job", spy):
                with self.assertRaisesRegex(AssertionError, "PLAN_DIGEST_MISMATCH"):
                    drv.main([
                        "--plan", str(bad_plan_path),
                        "--kernel-receipt", str(r_path),
                        "--admission", str(a_path),
                        "--execute",
                        "--run-root", str(Path(td) / "run"),
                    ])
        self.assertEqual(spy.call_count, 0)

    def test_load_order_config_failure_blocks_with_zero_dispatches(self):
        spy = MagicMock()
        def fail_on_j05(plan, job_id, **kw):
            if job_id == "J05":
                raise RuntimeError("CONFIG_LOAD_FAIL_J05")
            return self._fake_load_order_config(plan, job_id, **kw)

        with tempfile.TemporaryDirectory() as td:
            r_path, a_path = self._write_dummy_auth_files(td)
            with (
                patch.object(drv.p, "validate_real_kernel_receipt", return_value=None),
                patch.object(drv.p, "validate_admission", return_value=None),
                patch.object(drv.order, "load_order_config", side_effect=fail_on_j05),
                patch.object(drv.order, "run_order_job", spy),
            ):
                with self.assertRaisesRegex(RuntimeError, "CONFIG_LOAD_FAIL_J05"):
                    drv.main([
                        "--kernel-receipt", str(r_path),
                        "--admission", str(a_path),
                        "--execute",
                        "--run-root", str(Path(td) / "run"),
                    ])
        self.assertEqual(spy.call_count, 0)

    def test_nonzero_ledger_blocks_with_zero_dispatches(self):
        spy = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            bad_ledger_path = Path(td) / "ledger.json"
            bad_ledger = drv.read(self.plan["call_ledger_path"])
            bad_ledger["calls"] = [{"kind": "assessment_entries", "state": "DONE", "index": 0, "job_id": "J00"}]
            bad_ledger["counts"]["assessment_entries"] = 1
            bad_plan = dict(self.plan, call_ledger_path=str(bad_ledger_path))
            bad_ledger["plan_digest"] = drv.digest(bad_plan)
            raw_before = json.dumps(bad_ledger)
            bad_ledger_path.write_text(raw_before)
            # Check direct check_initial_zero_ledger (plan digest check is separate).
            with patch.object(drv.order, "run_order_job", spy):
                with self.assertRaisesRegex(AssertionError, "NONEMPTY_INITIAL_LEDGER_CALLS"):
                    drv.check_initial_zero_ledger(bad_plan)
            self.assertEqual(bad_ledger_path.read_text(), raw_before)
        self.assertEqual(spy.call_count, 0)

    def test_existing_run_root_blocks_overwrite(self):
        spy = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            r_path, a_path = self._write_dummy_auth_files(td)
            run_root = Path(td) / "existing_run"
            run_root.mkdir()
            (run_root / "run.json").write_text("{}")
            with (
                patch.object(drv.p, "validate_real_kernel_receipt", return_value=None),
                patch.object(drv.p, "validate_admission", return_value=None),
                patch.object(drv.order, "load_order_config", side_effect=self._fake_load_order_config),
                patch.object(drv.order, "run_order_job", spy),
            ):
                with self.assertRaisesRegex(AssertionError, "NO_OVERWRITE_EXISTING_RUN_ROOT"):
                    drv.main([
                        "--kernel-receipt", str(r_path),
                        "--admission", str(a_path),
                        "--execute",
                        "--run-root", str(run_root),
                    ])
        self.assertEqual(spy.call_count, 0)

    def test_preflight_only_default_mode_dispatches_zero(self):
        spy = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            r_path, a_path = self._write_dummy_auth_files(td)
            with (
                patch.object(drv.p, "validate_real_kernel_receipt", return_value=None),
                patch.object(drv.p, "validate_admission", return_value=None),
                patch.object(drv.order, "load_order_config", side_effect=self._fake_load_order_config),
                patch.object(drv.order, "run_order_job", spy),
            ):
                rc = drv.main(["--kernel-receipt", str(r_path), "--admission", str(a_path)])
        self.assertEqual(rc, 0)
        self.assertEqual(spy.call_count, 0)

    def test_execute_8_jobs_with_normal_stops_keeps_full_denominator(self):
        dispatched = []
        def offline_spy(plan, job_id, adapted, **_kwargs):
            dispatched.append(job_id)
            if job_id == "J02":
                return {"summary": {"completed": False, "termination_class": "PREDICTED_STATIC_INSTABILITY", "termination_reason": "PREDICTED_STATIC_INSTABILITY", "placed_items": 5, "planned_items": 19}}
            if job_id == "J03":
                return {"summary": {"completed": False, "termination_class": "NO_CANDIDATE", "termination_reason": "STOP_NO_PHYSICAL_CANDIDATE", "placed_items": 7, "planned_items": 19}}
            return {"summary": {"completed": True, "termination_class": "COMPLETE", "termination_reason": "ALL_ITEMS_PLACED", "placed_items": 19, "planned_items": 19}}

        with tempfile.TemporaryDirectory() as td:
            r_path, a_path = self._write_dummy_auth_files(td)
            run_root = Path(td) / "formal_run"
            with (
                patch.object(drv.p, "validate_real_kernel_receipt", return_value=None),
                patch.object(drv.p, "validate_admission", return_value=None),
                patch.object(drv.order, "load_order_config", side_effect=self._fake_load_order_config),
                patch.object(drv.order, "run_order_job", side_effect=offline_spy),
            ):
                rc = drv.main([
                    "--kernel-receipt", str(r_path),
                    "--admission", str(a_path),
                    "--execute",
                    "--run-root", str(run_root),
                ])
            receipt = drv.read(run_root / "driver_receipt.json")
        self.assertEqual(rc, 0)
        self.assertEqual(dispatched, [f"J0{i}" for i in range(8)])
        self.assertEqual(receipt["dispatched_jobs"], 8)
        self.assertEqual(receipt["status"], "COMPLETE_8_OF_8_DISPATCHED")
        self.assertEqual([r["status"] for r in receipt["rows"]], ["COMPLETE", "COMPLETE", "STOPPED", "STOPPED", "COMPLETE", "COMPLETE", "COMPLETE", "COMPLETE"])

    def test_execute_stops_on_first_technical_error_and_preserves_not_run(self):
        dispatched = []
        def offline_spy(plan, job_id, adapted, **_kwargs):
            dispatched.append(job_id)
            if job_id == "J03":
                raise RuntimeError("SYNTHETIC_TECHNICAL_ERROR_J03")
            return {"summary": {"completed": True, "termination_class": "COMPLETE", "termination_reason": "ALL_ITEMS_PLACED", "placed_items": 19, "planned_items": 19}}

        with tempfile.TemporaryDirectory() as td:
            r_path, a_path = self._write_dummy_auth_files(td)
            run_root = Path(td) / "formal_run_err"
            with (
                patch.object(drv.p, "validate_real_kernel_receipt", return_value=None),
                patch.object(drv.p, "validate_admission", return_value=None),
                patch.object(drv.order, "load_order_config", side_effect=self._fake_load_order_config),
                patch.object(drv.order, "run_order_job", side_effect=offline_spy),
            ):
                rc = drv.main([
                    "--kernel-receipt", str(r_path),
                    "--admission", str(a_path),
                    "--execute",
                    "--run-root", str(run_root),
                ])
            receipt = drv.read(run_root / "driver_receipt.json")
        self.assertEqual(rc, 1)
        self.assertEqual(dispatched, ["J00", "J01", "J02", "J03"])
        self.assertEqual(receipt["status"], "STOPPED_ON_ERROR")
        self.assertEqual(receipt["first_error"]["job_id"], "J03")
        self.assertEqual([r["status"] for r in receipt["rows"]], ["COMPLETE", "COMPLETE", "COMPLETE", "TECHNICAL_FAILURE", "NOT_RUN", "NOT_RUN", "NOT_RUN", "NOT_RUN"])

    def test_existing_run_root_with_only_jobs_subdir_blocks_with_zero_dispatches(self):
        spy = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            r_path, a_path = self._write_dummy_auth_files(td)
            run_root = Path(td) / "existing_jobs_only"
            ckpt = run_root / "jobs" / "J00" / "checkpoint.json"
            ckpt.parent.mkdir(parents=True, exist_ok=True)
            ckpt.write_text('{"phase": "SELECTED"}')
            with (
                patch.object(drv.p, "validate_real_kernel_receipt", return_value=None),
                patch.object(drv.p, "validate_admission", return_value=None),
                patch.object(drv.order, "load_order_config", side_effect=self._fake_load_order_config),
                patch.object(drv.order, "run_order_job", spy),
            ):
                with self.assertRaisesRegex(AssertionError, "NO_OVERWRITE_EXISTING_RUN_ROOT"):
                    drv.main([
                        "--kernel-receipt", str(r_path),
                        "--admission", str(a_path),
                        "--execute",
                        "--run-root", str(run_root),
                    ])
            self.assertTrue(ckpt.is_file())
            self.assertFalse((run_root / "driver_receipt.json").exists())
        self.assertEqual(spy.call_count, 0)

    def test_empty_summary_stops_batch_as_technical_failure_and_preserves_not_run(self):
        dispatched = []
        def offline_spy(plan, job_id, adapted, **_kwargs):
            dispatched.append(job_id)
            if job_id == "J02":
                return {"summary": None}
            return {"summary": {"completed": True, "termination_class": "COMPLETE", "termination_reason": "ALL_ITEMS_PLACED", "placed_items": 19, "planned_items": 19}}

        with tempfile.TemporaryDirectory() as td:
            r_path, a_path = self._write_dummy_auth_files(td)
            run_root = Path(td) / "formal_run_empty_summary"
            with (
                patch.object(drv.p, "validate_real_kernel_receipt", return_value=None),
                patch.object(drv.p, "validate_admission", return_value=None),
                patch.object(drv.order, "load_order_config", side_effect=self._fake_load_order_config),
                patch.object(drv.order, "run_order_job", side_effect=offline_spy),
            ):
                rc = drv.main([
                    "--kernel-receipt", str(r_path),
                    "--admission", str(a_path),
                    "--execute",
                    "--run-root", str(run_root),
                ])
            receipt = drv.read(run_root / "driver_receipt.json")
        self.assertEqual(rc, 1)
        self.assertEqual(dispatched, ["J00", "J01", "J02"])
        self.assertEqual(receipt["dispatched_jobs"], 3)
        self.assertEqual(receipt["status"], "STOPPED_ON_ERROR")
        self.assertEqual(receipt["first_error"]["job_id"], "J02")
        self.assertEqual(receipt["first_error"]["type"], "EMPTY_SUMMARY_TECHNICAL_FAILURE")
        self.assertEqual(len(receipt["rows"]), 8)
        self.assertEqual([r["status"] for r in receipt["rows"]], ["COMPLETE", "COMPLETE", "TECHNICAL_FAILURE", "NOT_RUN", "NOT_RUN", "NOT_RUN", "NOT_RUN", "NOT_RUN"])

    def test_returned_cancelled_stops_batch_and_preserves_not_run(self):
        dispatched = []
        def offline_spy(plan, job_id, adapted, **_kwargs):
            dispatched.append(job_id)
            if job_id == "J02":
                return {"summary": {"completed": False, "termination_class": "CANCELLED", "termination_reason": "CANCELLED", "placed_items": 3, "planned_items": 19}}
            return {"summary": {"completed": True, "termination_class": "COMPLETE", "termination_reason": "ALL_ITEMS_PLACED", "placed_items": 19, "planned_items": 19}}

        with tempfile.TemporaryDirectory() as td:
            r_path, a_path = self._write_dummy_auth_files(td)
            run_root = Path(td) / "formal_run_cancelled"
            with (
                patch.object(drv.p, "validate_real_kernel_receipt", return_value=None),
                patch.object(drv.p, "validate_admission", return_value=None),
                patch.object(drv.order, "load_order_config", side_effect=self._fake_load_order_config),
                patch.object(drv.order, "run_order_job", side_effect=offline_spy),
            ):
                rc = drv.main([
                    "--kernel-receipt", str(r_path),
                    "--admission", str(a_path),
                    "--execute",
                    "--run-root", str(run_root),
                ])
            receipt = drv.read(run_root / "driver_receipt.json")
        self.assertEqual(rc, 1)
        self.assertEqual(dispatched, ["J00", "J01", "J02"])
        self.assertEqual(receipt["dispatched_jobs"], 3)
        self.assertEqual(receipt["status"], "STOPPED_ON_ERROR")
        self.assertEqual(receipt["first_error"]["job_id"], "J02")
        self.assertEqual(receipt["first_error"]["type"], "CANCELLED")
        self.assertEqual(len(receipt["rows"]), 8)
        self.assertEqual([r["status"] for r in receipt["rows"]], ["COMPLETE", "COMPLETE", "CANCELLED", "NOT_RUN", "NOT_RUN", "NOT_RUN", "NOT_RUN", "NOT_RUN"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
