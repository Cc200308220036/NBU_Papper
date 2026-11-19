"""Offline tests for EMS default routing and ordinary v16/v17 completion compatibility."""
import copy
import json
import socket
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import test_geometry_external_review_identity_r1 as review_fixtures
import test_geometry_runtime_n1 as n1_fixtures

from semantic_pallet_planner.jev_select import episode
from semantic_pallet_planner.jev_select import geometry_kernel_completion as completion
from semantic_pallet_planner.jev_select import geometry_order_accounting as accounting
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.candidate_backends import (
    GeometryConstructionError,
    load_geometry_config,
)
from semantic_pallet_planner.jev_select.candidates import CandidateProvider
from semantic_pallet_planner.jev_select.config import (
    generator_config,
    generator_config_for,
    load_config,
    load_v2_config,
    load_v3_config,
)
from semantic_pallet_planner.jev_select.contracts import JevSelectError, canonical, digest
from semantic_pallet_planner.jev_select.geometry_execution import GeometryStore, load_run_config
from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields, wire
from semantic_pallet_planner.jev_select.packaging_runtime import (
    LocalPackagingDouble,
    load_runtime_config,
)
from semantic_pallet_planner.jev_select.packaging_versions import (
    DEFAULT_GEOMETRY_BACKEND,
    GEOMETRY_BACKENDS,
)
from semantic_pallet_planner.jev_select.stability import monitor
from semantic_pallet_planner.jev_select.stability.exact_adapter import algorithm_identity
from semantic_pallet_planner.jev_select.stability.exact_contracts import ExactConfig, ExactResult


def _manual_fixture(singleton=False):
    t = {
        "version": "jev_geometry_fixture_task_v1",
        "fixture_only": True,
        "task_id": "CONSTRUCTED_NOT_SOURCE_ORDER",
        "mode": "controlled_packaging",
        "layer": "CONSTRUCTED_MECHANISM",
        "feasibility_status": "UNKNOWN",
        "container": {
            "container_id": "fixture",
            "coordinate_frame": "container_bottom_center",
            "length_mm": 1000,
            "width_mm": 1000,
            "max_height_mm": 1000,
            "max_payload_kg": 1000,
        },
        "items": [
            {
                "item_id": "manual_box",
                "dimensions_mm": {"length": 100, "width": 100, "height": 100},
                "mass_kg": 1,
                "stackable": True,
                "fragile": False,
                "weight_class": "medium",
                "top_load_limit_kg_synthetic": 100,
                "product_category": "general",
            }
        ],
        "attributes": {
            "manual_box": {
                "object_id": "manual_box",
                "physical_top_load_limit_kg": 100,
                "cargo_category": "general",
                "packaging": {"reinforced": False},
                "labels": {"no_top_load": False, "max_top_load_kg": 100},
            }
        },
        "instruction_text": n1_fixtures.INSTRUCTION,
        "regions": [],
        "reference_policy": {"version": "jev_packaging_load_dataset_v1", "rules": []},
    }
    if singleton:
        t["items"][0]["dimensions_mm"]["width"] = 80
        t["container"].update(length_mm=100, width_mm=80, max_height_mm=100)
    return t


@contextmanager
def _kernel_double(status="STABLE", calls=None):
    original = monitor.kernel_interface

    def interface(algorithm):
        assert algorithm == "pct_exact_pose_network_v3"

        def assess(state, box, cfg):
            if calls is not None:
                calls.append({"selected_box": asdict(box), "state": asdict(state), "TEST_DOUBLE": True})
            return ExactResult(
                status=status,
                reason_code="TEST_DOUBLE_" + status,
                state_digest=digest(asdict(state)),
                candidate_digest=digest(asdict(box)),
                candidate_id=box.item_id,
                config_digest=digest(asdict(cfg)),
                algorithm_identity=algorithm_identity(),
                baseline_status="NOT_ASSESSED",
                first_bad_prefix=None,
                failed_item_id=None,
                height_delta_mm=None,
                evaluated_pose=None,
                kernel_calls=0,
                diagnostics={"TEST_DOUBLE": True, "actual_PCT_LP_calls": 0},
            )

        _, loader, result, schema = original(algorithm)
        return assess, loader, result, schema

    with patch.object(monitor, "kernel_interface", side_effect=interface):
        yield


class V17OrdinaryCompletionAndPhaseSnapshotTests(review_fixtures.ReviewIdentity):
    def test_ordinary_v16_and_v17_with_durable_root_pass(self):
        for native in (False, True):
            with self.subTest(native=native):
                plan = self.plan(native=native)
                receipt, log, review = self.completion(plan)
                for row in receipt["recovery"]:
                    record = json.loads(Path(row["after"]["path"]).read_bytes())
                    record["durable_root"] = str(Path(row["after"]["path"]).parent)
                    row["after"] = self.ref(record)
                review["recovery_digest"] = digest(receipt["recovery"])
                receipt["review"] = self.ref(review)
                completion.validate_completion(receipt, plan, log, lambda _: None)

    def _build_phase_snapshot_completion(self, native=True):
        plan = self.plan(native=native)
        receipt, log, review = self.completion(plan)
        coverage = completion.required_coverage(plan)
        for idx, row in enumerate(coverage["primary"]):
            parent_root = self.root / f"parent_{idx}"
            parent_root.mkdir(parents=True, exist_ok=True)
            record = json.loads(Path(receipt["records"][idx]["path"]).read_bytes())
            task_id_doc = {
                "origin": "SYNTHETIC_FIXED",
                "raw_sha256": digest(f"RAW_{row['job_id']}"),
                "normalized_digest": digest(row["task_id"]),
                "runtime_digest": digest(f"RT_{row['job_id']}"),
                "adapter_digest": digest("ADAPTER"),
                "task_id": row["task_id"],
                "source_group_id": "SYNTHETIC_NOT_SOURCE",
            }
            cfg = {
                **record["config"],
                "order_task_identity": task_id_doc,
                "plan_digest": digest(plan),
                "runtime_identity": {"source_identity": plan["source_identity"]},
            }
            if native:
                cfg.update(
                    version="jev_packaging_geometry_order_v17",
                    runtime_version="jev_packaging_geometry_order_v17",
                    publication_policy_digest=plan["publication_policy_digest"],
                )
            else:
                cfg.update(version="jev_packaging_geometry_order_v16")
            cp = copy.deepcopy(record["checkpoint"])
            cp.update(
                method=cfg["selector"],
                config_digest=digest(cfg),
                task_digest=task_id_doc["runtime_digest"],
            )
            record["config"] = cfg
            record["checkpoint"] = cp
            record["durable_root"] = str(parent_root)
            raw_path = parent_root / "raw_task.json"
            raw_path.write_text("{}", encoding="utf-8")
            record["raw_task"] = {"path": str(raw_path), "sha256": task_id_doc["raw_sha256"]}
            rec_ref = self.ref(record)
            receipt["records"][idx] = rec_ref
            (parent_root / "record.json").write_text(canonical(record), encoding="utf-8")
            parent_acc = {
                **identity_fields(plan),
                "version": wire(plan, "geometry_order_accounting_v1"),
                "plan_digest": digest(plan),
                "job_id": row["job_id"],
                "config_digest": digest(cfg),
                "invocations": [
                    {
                        "index": 0,
                        "resume_phase": "FRESH",
                        "status": "RETURNED",
                        "delta": {
                            "selector_calls": 1,
                            "singleton_executions": 0,
                            "monitor_entries": 1,
                            "monitor_reuses": 0,
                            "commit_attempts": 1,
                            "commit_successes": 1,
                        },
                        "resume_checkpoint_digest": None,
                        "result_checkpoint_digest": digest(cp),
                    }
                ],
                "cumulative": {
                    "selector_calls": 1,
                    "singleton_executions": 0,
                    "monitor_entries": 1,
                    "monitor_reuses": 0,
                    "commit_attempts": 1,
                    "commit_successes": 1,
                },
            }
            (parent_root / "accounting.json").write_text(canonical(parent_acc), encoding="utf-8")

        for r_idx, row in enumerate(receipt["recovery"]):
            snap_root = self.root / f"snap_{r_idx}"
            (snap_root / "blobs").mkdir(parents=True, exist_ok=True)
            parent_idx = next(
                i
                for i, r in enumerate(coverage["primary"])
                if r["job_id"] == row["job_id"]
            )
            parent_root = self.root / f"parent_{parent_idx}"
            parent_rec = json.loads((parent_root / "record.json").read_text(encoding="utf-8"))
            cfg = parent_rec["config"]
            task_id_doc = cfg["order_task_identity"]
            raw_bytes = b"{}"
            raw_sha = task_id_doc["raw_sha256"]
            (snap_root / "blobs" / raw_sha).write_bytes(raw_bytes)
            gbytes = b'{"geom":1}'
            gsha = p.sha(gbytes)
            (snap_root / "blobs" / gsha).write_bytes(gbytes)
            # Adjust raw_sha in blob name check by writing matching bytes
            raw_sha_actual = p.sha(raw_bytes)
            (snap_root / "blobs" / raw_sha).unlink()
            (snap_root / "blobs" / raw_sha_actual).write_bytes(raw_bytes)
            # Re-bind task_id_doc raw_sha256 to actual raw_bytes sha
            cfg["order_task_identity"]["raw_sha256"] = raw_sha_actual
            parent_rec["config"] = cfg
            parent_rec["raw_task"]["sha256"] = raw_sha_actual
            parent_rec["checkpoint"]["config_digest"] = digest(cfg)
            parent_acc = json.loads((parent_root / "accounting.json").read_text(encoding="utf-8"))
            parent_acc["config_digest"] = digest(cfg)
            parent_acc["invocations"][0]["result_checkpoint_digest"] = digest(parent_rec["checkpoint"])
            (parent_root / "accounting.json").write_text(canonical(parent_acc), encoding="utf-8")
            (parent_root / "record.json").write_text(canonical(parent_rec), encoding="utf-8")
            receipt["records"][parent_idx] = {
                "path": str(parent_root / "record.json"),
                "sha256": p.sha((parent_root / "record.json").read_bytes()),
            }

            before = copy.deepcopy(parent_rec["checkpoint"])
            before["phase"] = row["phase"]
            before["pending_event"] = copy.deepcopy(before["events"][-1])
            before["pending_event"]["geometry_ref"] = {"version": "geometry_blob_ref_v1", "sha256": gsha}
            delta = {
                "selector_calls": 0,
                "singleton_executions": 0,
                "monitor_entries": int(row["phase"] == "SELECTED"),
                "monitor_reuses": int(row["phase"] == "MONITORED"),
                "commit_attempts": int(row["phase"] != "COMMITTED"),
                "commit_successes": int(row["phase"] != "COMMITTED"),
            }
            snap_acc = {
                **identity_fields(plan),
                "version": wire(plan, "geometry_order_accounting_v1"),
                "plan_digest": digest(plan),
                "job_id": row["job_id"],
                "config_digest": digest(cfg),
                "invocations": [
                    {
                        "index": 0,
                        "resume_phase": "FRESH",
                        "status": "STARTED",
                        "delta": {
                            "selector_calls": 0,
                            "singleton_executions": 0,
                            "monitor_entries": 0,
                            "monitor_reuses": 0,
                            "commit_attempts": 0,
                            "commit_successes": 0,
                        },
                        "resume_checkpoint_digest": None,
                        "result_checkpoint_digest": None,
                    }
                ],
                "cumulative": {
                    "selector_calls": 0,
                    "singleton_executions": 0,
                    "monitor_entries": 0,
                    "monitor_reuses": 0,
                    "commit_attempts": 0,
                    "commit_successes": 0,
                },
            }
            (snap_root / "checkpoint.json").write_text(canonical(before), encoding="utf-8")
            (snap_root / "config.json").write_text(canonical(cfg), encoding="utf-8")
            (snap_root / "task_identity.json").write_text(canonical(cfg["order_task_identity"]), encoding="utf-8")
            (snap_root / "accounting.json").write_text(canonical(snap_acc), encoding="utf-8")
            accounting.seal_phase_snapshot_credential(
                parent_root,
                snap_root,
                cfg,
                row["job_id"],
                row["phase"],
                before,
                parent_result={"summary": {"completed": True}, "checkpoint": parent_rec["checkpoint"]},
            )
            snap_acc["invocations"].append(
                {
                    "index": 1,
                    "resume_phase": row["phase"],
                    "status": "RETURNED",
                    "delta": delta,
                    "resume_checkpoint_digest": digest(before),
                    "result_checkpoint_digest": digest(parent_rec["checkpoint"]),
                }
            )
            snap_acc["cumulative"] = copy.deepcopy(delta)
            (snap_root / "accounting.json").write_text(canonical(snap_acc), encoding="utf-8")
            after_rec = copy.deepcopy(parent_rec)
            after_rec["durable_root"] = str(snap_root)
            row["before"] = self.ref(before)
            row["after"] = self.ref(after_rec)
            row["accounting"] = self.ref(snap_acc)
        review["records_digest"] = digest(receipt["records"])
        review["recovery_digest"] = digest(receipt["recovery"])
        receipt["review"] = self.ref(review)
        return plan, receipt, log

    def test_phase_snapshot_missing_credential_and_parent_drift_rejected(self):
        plan, receipt, log = self._build_phase_snapshot_completion(native=True)
        completion.validate_completion(receipt, plan, log, lambda _: None)

        # Missing credential file must be rejected even when phase_snapshot_credential.json is removed.
        snap0 = Path(json.loads(Path(receipt["recovery"][0]["after"]["path"]).read_text())["durable_root"])
        cred_file = snap0 / "phase_snapshot_credential.json"
        saved_cred = cred_file.read_bytes()
        cred_file.unlink()
        self.reject(
            "missing phase snapshot credential",
            lambda: completion.validate_completion(receipt, plan, log, lambda _: None),
            "geometry_completion_recovery_credential_missing",
        )
        cred_file.write_bytes(saved_cred)

        # Parent accounting drift must be rejected.
        parent0 = self.root / "parent_0"
        acc_path = parent0 / "accounting.json"
        saved_acc = acc_path.read_bytes()
        bad_acc = json.loads(saved_acc)
        bad_acc["cumulative"]["selector_calls"] += 1
        acc_path.write_text(canonical(bad_acc), encoding="utf-8")
        self.reject(
            "parent accounting drift",
            lambda: completion.validate_completion(receipt, plan, log, lambda _: None),
            "geometry_receipt_bytes_drift",
        )
        acc_path.write_bytes(saved_acc)


class EmsDefaultRouteAndNoFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gp5_ems_default_")
        self.addCleanup(self.tmp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in (
            "stability.exact_adapter.assess_candidate",
            "stability.balance_adapter.assess_candidate",
            "stability.balance_network.solve_network",
            "stability.balance_network.linprog",
            "stability.monitor.exact_freeze",
            "stability.monitor.freeze",
        ):
            self.stack.enter_context(
                patch(
                    "semantic_pallet_planner.jev_select." + name,
                    side_effect=AssertionError("REAL_KERNEL_FORBIDDEN:" + name),
                )
            )
        self.stack.enter_context(
            patch.object(socket.socket, "connect", side_effect=AssertionError("NETWORK_FORBIDDEN"))
        )

    def test_default_loaders_use_ems_and_explicit_uses_e2(self):
        self.assertEqual(DEFAULT_GEOMETRY_BACKEND, "ems_surface_hybrid_v1")
        ids = {k: digest("EMS_DEFAULT_" + k) for k in n1_fixtures.c.IDENTITY_KEYS}
        cfg_default = load_geometry_config(**ids)
        cfg_e2 = load_geometry_config(backend="e2_original_v1", **ids)
        self.assertEqual(cfg_default["candidate_backend"], "ems_surface_hybrid_v1")
        self.assertEqual(cfg_e2["candidate_backend"], "e2_original_v1")

        t = _manual_fixture()
        snap = json.loads(
            Path(
                "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_20261117_01/cases/ems_surface_hybrid_v1_stable/config.json"
            ).read_bytes()
        )["stability_monitor"]
        with patch("semantic_pallet_planner.jev_select.stability.monitor.exact_freeze", return_value=copy.deepcopy(snap)):
            run_default = load_run_config(task=t, data_identity=digest("RUN_DEFAULT"))
            run_e2 = load_run_config(backend="e2_original_v1", task=t, data_identity=digest("RUN_E2"))
        self.assertEqual(run_default["candidate_backend"], "ems_surface_hybrid_v1")
        self.assertEqual(run_e2["candidate_backend"], "e2_original_v1")

        self.assertEqual(generator_config_for(None)["generator"]["backend"], "ems_surface_hybrid_v1")
        self.assertEqual(generator_config_for(cfg_default)["generator"]["backend"], "ems_surface_hybrid_v1")
        self.assertIn("candidate_generator", generator_config_for(cfg_e2))
        self.assertIn("candidate_generator", generator_config_for(load_config()))

    def test_normal_entry_calls_ems_by_default_and_e2_when_explicit(self):
        s = n1_fixtures.current_scene()
        req = n1_fixtures.observation(s, n1_fixtures.INSTRUCTION, [])
        ids = {k: digest("EMS_NORMAL_" + k) for k in n1_fixtures.c.IDENTITY_KEYS}

        # Unspecified backend in load_geometry_config + CandidateProvider.build -> EMS (_generation_core), never E2.
        cfg_default = load_geometry_config(**ids)
        with patch(
            "semantic_pallet_planner.o4.extensions.e2.candidates.generate",
            side_effect=AssertionError("E2_MUST_NOT_BE_CALLED"),
        ):
            b_default = CandidateProvider().build(s, req, config=cfg_default)
        self.assertEqual(b_default.data["candidate_backend"], "ems_surface_hybrid_v1")
        self.assertTrue(b_default.data["physical_candidates"])

        # Explicit e2_original_v1 in load_geometry_config + CandidateProvider.build -> E2 (generate), never EMS.
        cfg_e2 = load_geometry_config(backend="e2_original_v1", **ids)
        with patch(
            "semantic_pallet_planner.planner.space_candidates.generator._generation_core",
            side_effect=AssertionError("EMS_MUST_NOT_BE_CALLED"),
        ):
            b_e2 = CandidateProvider().build(s, req, config=cfg_e2)
        self.assertEqual(b_e2.data["candidate_backend"], "e2_original_v1")
        self.assertTrue(b_e2.data["physical_candidates"])

        # Run-config entry: default EMS vs explicit E2 with monitor TEST_DOUBLE.
        t = _manual_fixture()
        snap = json.loads(
            Path(
                "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_20261117_01/cases/ems_surface_hybrid_v1_stable/config.json"
            ).read_bytes()
        )["stability_monitor"]
        for backend, forbidden_target in (
            (None, "semantic_pallet_planner.o4.extensions.e2.candidates.generate"),
            ("e2_original_v1", "semantic_pallet_planner.planner.space_candidates.generator._generation_core"),
        ):
            with self.subTest(backend=backend):
                store = GeometryStore(Path(self.tmp.name) / ("run_" + str(backend)))
                with patch("semantic_pallet_planner.jev_select.stability.monitor.exact_freeze", return_value=copy.deepcopy(snap)):
                    cfg = load_run_config(backend=backend, task=t, data_identity=digest("EMS_DEFAULT_RUN"))
                    calls = []
                    with patch(forbidden_target, side_effect=AssertionError("WRONG_BACKEND_CALLED")), _kernel_double(
                        calls=calls
                    ):
                        out = episode.run_episode(
                            t,
                            LocalPackagingDouble(cfg["selector"]),
                            cfg,
                            job_id="MANUAL_" + str(backend),
                            method=cfg["selector"],
                            on_checkpoint=lambda cp: None,
                            geometry_store=store,
                        )
                self.assertEqual(out["summary"]["placed_items"], 1)
                self.assertEqual(len(calls), 1)
                self.assertEqual(
                    cfg["candidate_backend"],
                    "ems_surface_hybrid_v1" if backend is None else "e2_original_v1",
                )

    def test_ems_empty_pool_and_error_never_fallback_to_e2(self):
        ids = {k: digest("EMS_EMPTY_ERR_" + k) for k in n1_fixtures.c.IDENTITY_KEYS}
        cfg = load_geometry_config(**ids)

        # Empty pool: nonstackable scene stops with empty physical_candidates and never calls E2.
        s_empty = n1_fixtures.current_scene(n1_fixtures.SCENES["nonstackable"])
        req_empty = n1_fixtures.observation(s_empty, n1_fixtures.INSTRUCTION, [])
        with patch(
            "semantic_pallet_planner.o4.extensions.e2.candidates.generate",
            side_effect=AssertionError("E2_FALLBACK_FORBIDDEN"),
        ):
            b_empty = CandidateProvider().build(s_empty, req_empty, config=cfg)
        self.assertEqual(b_empty.data["candidate_backend"], "ems_surface_hybrid_v1")
        self.assertEqual(b_empty.data["physical_candidates"], [])

        # EMS error: raises GeometryConstructionError without falling back to E2.
        s = n1_fixtures.current_scene()
        req = n1_fixtures.observation(s, n1_fixtures.INSTRUCTION, [])
        with patch(
            "semantic_pallet_planner.o4.extensions.e2.candidates.generate",
            side_effect=AssertionError("E2_FALLBACK_FORBIDDEN"),
        ), patch(
            "semantic_pallet_planner.planner.space_candidates.generator._generation_core",
            return_value={"status": "ERROR", "error": {"code": "EMS_SYNTHETIC_ERROR", "detail": "boom"}},
        ):
            with self.assertRaises(GeometryConstructionError) as g_err:
                CandidateProvider().build(s, req, config=cfg)
            self.assertEqual(g_err.exception.scope, "BACKEND_INTERNAL_ERROR")
            self.assertEqual(g_err.exception.code, "EMS_SYNTHETIC_ERROR")

    def test_historical_frozen_and_fixed_matrix_preserve_explicit_backends(self):
        for cfg in (
            load_config(),
            load_v2_config(),
            load_v3_config(),
            load_runtime_config(data_identity=digest("HIST_RUNTIME")),
        ):
            self.assertEqual(cfg["candidate_backend"], "e2_original_v1")

        tasks = []
        for case in ("K01", "K02"):
            raw = canonical(p.synthetic_task(case)).encode()
            tasks.append(p.adapt_task(raw, origin="SYNTHETIC_FIXED", expected_sha256=p.sha(raw)))
        plan = p.prepare_order_plan(tasks, data_identity=digest("MATRIX"), scope=p.ACCEPTANCE, native=True)
        self.assertEqual([j["backend"] for j in plan["jobs"]], list(GEOMETRY_BACKENDS) * 2)

    def test_operational_order_entry_ems_default_explicit_e2_and_no_fallback(self):
        from semantic_pallet_planner.jev_select import geometry_order_execution as o

        snap = json.loads(
            Path(
                "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_20261117_01/cases/ems_surface_hybrid_v1_stable/config.json"
            ).read_bytes()
        )["stability_monitor"]
        raw = canonical(p.synthetic_task("K01")).encode()
        adapted = p.adapt_task(raw, origin="SYNTHETIC_FIXED", expected_sha256=p.sha(raw))

        def dev_adm(plan):
            return {
                **identity_fields(plan),
                "version": wire(plan, "geometry_development_binding_v1"),
                "scope": p.DEVELOPMENT,
                "evidence": "TEST_DOUBLE",
                "plan_digest": digest(plan),
            }

        @contextmanager
        def monitor_double(calls):
            def interface(algorithm):
                assert algorithm == "pct_exact_pose_network_v3"

                def assess(state, box, cfg):
                    calls.append({"box": box.item_id})
                    return ExactResult(
                        status="STABLE",
                        reason_code="TEST_DOUBLE_STABLE",
                        state_digest=digest(asdict(state)),
                        candidate_digest=digest(asdict(box)),
                        candidate_id=box.item_id,
                        config_digest=digest(asdict(cfg)),
                        algorithm_identity=copy.deepcopy(snap["algorithm_identity"]),
                        baseline_status="NOT_ASSESSED",
                        first_bad_prefix=None,
                        failed_item_id=None,
                        height_delta_mm=None,
                        evaluated_pose=None,
                        kernel_calls=0,
                        diagnostics={"TEST_DOUBLE": True, "actual_PCT_LP_calls": 0},
                    )

                assess.geometry_test_double = True
                return assess, lambda: ExactConfig(**snap["kernel_config"]), ExactResult, "stability_result_v3.schema.json"

            with patch.object(monitor, "kernel_interface", side_effect=interface):
                yield

        with patch.object(o, "validate_monitor_snapshot", return_value=None):
            # 1. Default omitted backend -> EMS end-to-end through prepare_operational_order_plan -> load_order_config -> run_order_job -> episode.
            plan_ems = p.prepare_operational_order_plan([adapted], data_identity=digest("OP_EMS"))
            self.assertEqual(plan_ems["jobs"][0]["backend"], "ems_surface_hybrid_v1")
            adm_ems = dev_adm(plan_ems)
            cfg_ems = o.load_order_config(plan_ems, "J00", monitor_snapshot=snap, admission=adm_ems)
            self.assertEqual(cfg_ems["candidate_backend"], "ems_surface_hybrid_v1")
            calls_ems = []
            with patch(
                "semantic_pallet_planner.o4.extensions.e2.candidates.generate",
                side_effect=AssertionError("E2_MUST_NOT_BE_CALLED"),
            ), monitor_double(calls_ems):
                out_ems = o.run_order_job(
                    plan_ems,
                    "J00",
                    adapted,
                    monitor_snapshot=snap,
                    admission=adm_ems,
                    root=Path(self.tmp.name) / "op_ems",
                )
            self.assertEqual(out_ems["summary"]["candidate_backend"], "ems_surface_hybrid_v1")
            self.assertEqual(out_ems["summary"]["placed_items"], 1)
            self.assertEqual(len(calls_ems), 1)

            # 2. Explicit backend='e2_original_v1' -> original E2 end-to-end.
            plan_e2 = p.prepare_operational_order_plan([adapted], data_identity=digest("OP_E2"), backend="e2_original_v1")
            self.assertEqual(plan_e2["jobs"][0]["backend"], "e2_original_v1")
            adm_e2 = dev_adm(plan_e2)
            cfg_e2 = o.load_order_config(plan_e2, "J00", monitor_snapshot=snap, admission=adm_e2)
            self.assertEqual(cfg_e2["candidate_backend"], "e2_original_v1")
            calls_e2 = []
            with patch(
                "semantic_pallet_planner.planner.space_candidates.generator._generation_core",
                side_effect=AssertionError("EMS_MUST_NOT_BE_CALLED"),
            ), monitor_double(calls_e2):
                out_e2 = o.run_order_job(
                    plan_e2,
                    "J00",
                    adapted,
                    monitor_snapshot=snap,
                    admission=adm_e2,
                    root=Path(self.tmp.name) / "op_e2",
                )
            self.assertEqual(out_e2["summary"]["candidate_backend"], "e2_original_v1")
            self.assertEqual(out_e2["summary"]["placed_items"], 1)
            self.assertEqual(len(calls_e2), 1)

            # 3. Operational EMS empty pool -> stops with STOP_NO_PHYSICAL_CANDIDATE, no fallback to E2.
            empty_core = {
                "status": "OK_EMPTY",
                "candidates": [],
                "audit": {
                    "items": [
                        {
                            "item_id": adapted["runtime"]["items"][0]["item_id"],
                            "final_candidates": 0,
                            "raw_valid_count": 0,
                            "rejection_counts": {"no_surface": 1},
                            "raw_point_attempts": 1,
                        }
                    ]
                },
            }
            with patch(
                "semantic_pallet_planner.o4.extensions.e2.candidates.generate",
                side_effect=AssertionError("E2_FALLBACK_FORBIDDEN"),
            ), patch(
                "semantic_pallet_planner.planner.space_candidates.generator._generation_core",
                return_value=empty_core,
            ):
                out_empty = o.run_order_job(
                    plan_ems,
                    "J00",
                    adapted,
                    monitor_snapshot=snap,
                    admission=adm_ems,
                    root=Path(self.tmp.name) / "op_ems_empty",
                )
            self.assertEqual(out_empty["summary"]["candidate_backend"], "ems_surface_hybrid_v1")
            self.assertEqual(out_empty["summary"]["termination_reason"], "STOP_NO_PHYSICAL_CANDIDATE")
            self.assertEqual(out_empty["summary"]["placed_items"], 0)

            # 4. Operational EMS error -> stops on first error and records failure, no fallback to E2.
            err_root = Path(self.tmp.name) / "op_ems_err"
            with patch(
                "semantic_pallet_planner.o4.extensions.e2.candidates.generate",
                side_effect=AssertionError("E2_FALLBACK_FORBIDDEN"),
            ), patch(
                "semantic_pallet_planner.planner.space_candidates.generator._generation_core",
                return_value={"status": "ERROR", "error": {"code": "EMS_OP_ERROR", "detail": "synthetic"}},
            ):
                out_err = o.run_order_job(
                    plan_ems,
                    "J00",
                    adapted,
                    monitor_snapshot=snap,
                    admission=adm_ems,
                    root=err_root,
                )
            self.assertEqual(out_err["summary"]["candidate_backend"], "ems_surface_hybrid_v1")
            self.assertEqual(out_err["summary"]["termination_reason"], "EMS_OP_ERROR")
            self.assertEqual(out_err["summary"]["termination_class"], "TECHNICAL_FAILURE")
            self.assertEqual(out_err["summary"]["placed_items"], 0)
            run_doc = json.loads((err_root / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_doc["rows"][0]["status"], "TECHNICAL_FAILURE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
