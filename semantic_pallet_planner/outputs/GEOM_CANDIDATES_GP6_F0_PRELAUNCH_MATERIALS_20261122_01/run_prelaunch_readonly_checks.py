"""Read-only target Linux environment check, GP6-F0 DRAFT material generation, and zero-call preflight.

Rules enforced:
- 0 real model calls, 0 real monitor assessments, 0 LP calls, 0 credential reads.
- Never modifies production source or historical GP5 artifacts.
- Never pre-fills APPROVED, VERIFIED, or FROZEN on unsigned/pending materials.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "semantic_pallet_planner" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from semantic_pallet_planner.jev_select import geometry_jev_execution as jev_exec
from semantic_pallet_planner.jev_select import geometry_jev_kernel_bridge as bridge_mod
from semantic_pallet_planner.jev_select import geometry_jev_protocol as jev_proto
from semantic_pallet_planner.jev_select import geometry_order_execution as order_exec
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as pkg_proto
from semantic_pallet_planner.jev_select import packaging_runtime as pkg_rt
from semantic_pallet_planner.jev_select.contracts import JevSelectError, digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_native_protocol import policy_digest
from semantic_pallet_planner.jev_select.geometry_runtime_contracts import environment, same_native
from semantic_pallet_planner.jev_select.stability import runtime as stab_rt

OUT = REPO / "semantic_pallet_planner" / "outputs"
PKG = OUT / "GEOM_CANDIDATES_GP6_F0_PRELAUNCH_MATERIALS_20261122_01"
DATA_ROOT = OUT / "DATA_JEV_PACKAGING_LOAD_20261102_02"
GP5_RUNTIME = OUT / "GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01"
GP5_APPROVED = OUT / "GEOM_CANDIDATES_GP5_FORMAL_ORDER_APPROVED_QA_20261120_01"
QA_BUDGET = OUT / "GEOM_CANDIDATES_GP6_F0_BUDGET_REC_FIX_QA_20261121_01"

GP5_COMMIT = "2c97f59444f07e40b98da529e5256efc441207d4"
EXPECTED_QA_SOURCE_ID = "68b879c5759b5a6df33fe8184019234bcb06e06483596f86390ca6c9974ca48e"
EXPECTED_QA_DELTA_DIGEST = "4716c4e4ba2f316c48fd29bb52ab37d7b05d8f3134ea43ab5eb3b8de24ebdbd3"


def read_json(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8"))


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def collect_live_environment_and_compare() -> dict:
    import scipy.optimize
    from scipy.optimize._highspy import _core

    gp5_plan = read_json(GP5_RUNTIME / "acceptance_plan_FROZEN.json")
    gp5_snap = read_json(GP5_RUNTIME / "monitor_snapshot.json")
    gp5_source = read_json(GP5_RUNTIME / "source_manifest.json")
    gp5_receipt = read_json(GP5_APPROVED / "real_kernel_receipt.json")

    live_env = environment()
    live_env_digest = digest(live_env)
    live_monitor_env = stab_rt.environment()
    highs_ver = ".".join(str(getattr(_core, "HIGHS_VERSION_" + k)) for k in ("MAJOR", "MINOR", "PATCH"))
    highs_sha = sha_file(Path(_core.__file__))
    scipy_py_shas = {
        name: sha_file(Path(scipy.optimize.__file__).parent / name)
        for name in sorted(gp5_snap["algorithm_identity"]["dependencies"]["scipy_python_sha256"])
    }
    live_deps = {
        "highs_core_sha256": highs_sha,
        "highs_version": highs_ver,
        "numpy": importlib.metadata.version("numpy"),
        "scipy": importlib.metadata.version("scipy"),
        "scipy_python_sha256": scipy_py_shas,
    }
    live_dep_digest = digest(live_deps)

    stab_root = SRC / "semantic_pallet_planner" / "jev_select" / "stability"
    live_stab_files = {
        rel: sha_file(stab_root / rel)
        for rel in sorted(gp5_snap["algorithm_identity"]["files_sha256"])
    }
    live_stab_source_digest = digest(live_stab_files)

    try:
        order_exec.validate_monitor_snapshot(gp5_snap)
        monitor_validation = {"status": "PASS", "error": None}
    except Exception as exc:
        monitor_validation = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}

    # Verify GP5 receipt and all 39 referenced files
    refs = []
    refs.append(("real_kernel_receipt", str(GP5_APPROVED.relative_to(REPO) / "real_kernel_receipt.json"), sha_file(GP5_APPROVED / "real_kernel_receipt.json")))
    def collect_refs(obj, prefix=""):
        if isinstance(obj, dict):
            if set(obj.keys()) == {"path", "sha256"} and isinstance(obj["path"], str):
                p = REPO / obj["path"]
                actual = sha_file(p) if p.is_file() else None
                refs.append({
                    "role": prefix.rstrip("."),
                    "path": obj["path"],
                    "expected_sha256": obj["sha256"],
                    "actual_sha256": actual,
                    "matches": actual == obj["sha256"],
                })
                return
            for k, v in obj.items():
                collect_refs(v, f"{prefix}{k}.")
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                collect_refs(item, f"{prefix}[{idx}].")

    ref_checks = []
    def add_ref(role, path_str, expected_sha):
        p = REPO / path_str
        actual = sha_file(p) if p.is_file() else None
        ref_checks.append({
            "role": role,
            "path": path_str,
            "expected_sha256": expected_sha,
            "actual_sha256": actual,
            "matches": actual == expected_sha,
        })

    # Collect nested refs from real_kernel_receipt.json and launch.json + records
    for key in ("launch", "acceptance_plan", "counter_log", "review"):
        add_ref(key, gp5_receipt[key]["path"], gp5_receipt[key]["sha256"])
    launch_doc = read_json(REPO / gp5_receipt["launch"]["path"])
    for key in ("authorization", "review"):
        add_ref(f"launch.{key}", launch_doc[key]["path"], launch_doc[key]["sha256"])
    for i, rec_ref in enumerate(gp5_receipt["records"]):
        add_ref(f"records[{i}]", rec_ref["path"], rec_ref["sha256"])
        rec_doc = read_json(REPO / rec_ref["path"])
        add_ref(f"records[{i}].raw_task", rec_doc["raw_task"]["path"], rec_doc["raw_task"]["sha256"])
    for i, rv in enumerate(gp5_receipt["recovery"]):
        for sub in ("accounting", "after", "before"):
            add_ref(f"recovery[{i}].{sub}", rv[sub]["path"], rv[sub]["sha256"])
        after_doc = read_json(REPO / rv["after"]["path"])
        add_ref(f"recovery[{i}].after.raw_task", after_doc["raw_task"]["path"], after_doc["raw_task"]["sha256"])

    # Also check receipt itself
    receipt_rel = "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_FORMAL_ORDER_APPROVED_QA_20261120_01/real_kernel_receipt.json"
    receipt_sha = sha_file(REPO / receipt_rel)
    gp5_manifest_rel = "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01/source_manifest.json"
    gp5_manifest_sha = sha_file(REPO / gp5_manifest_rel)
    gp5_monitor_rel = "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01/monitor_snapshot.json"
    gp5_monitor_sha = sha_file(REPO / gp5_monitor_rel)

    # Verify historical source tree provenance via read-only git archive into temp dir
    # and run geometry_jev_kernel_evidence_worker.py in isolated read-only mode
    worker_path = SRC / "semantic_pallet_planner" / "jev_select" / "geometry_jev_kernel_evidence_worker.py"
    hist_tree_check = {"commit": GP5_COMMIT, "status": "NOT_RUN"}
    with tempfile.TemporaryDirectory(prefix="gp6_prelaunch_hist_check_") as tmpdir:
        tmp = Path(tmpdir)
        tar_proc = subprocess.run(
            ["git", "archive", GP5_COMMIT, "semantic_pallet_planner/src/semantic_pallet_planner"],
            cwd=str(REPO),
            capture_output=True,
        )
        if tar_proc.returncode != 0:
            hist_tree_check = {"commit": GP5_COMMIT, "status": "FAIL", "error": tar_proc.stderr.decode("utf-8", "replace")[:400]}
        else:
            import io, tarfile
            with tarfile.open(fileobj=io.BytesIO(tar_proc.stdout), mode="r:") as tf:
                tf.extractall(tmp)
            hist_root = tmp / "semantic_pallet_planner" / "src" / "semantic_pallet_planner"
            expected_files = gp5_source["files"]
            actual_files = {
                p.relative_to(hist_root).as_posix(): sha_file(p)
                for p in hist_root.rglob("*")
                if p.is_file()
                and p.suffix in (".py", ".json")
                and not {"tests", "__pycache__"}.intersection(p.relative_to(hist_root).parts)
            }
            manifest_exact_match = (actual_files == expected_files)
            # Prepare isolated copy_files matching validate_kernel_bridge logic
            copy_files = dict(expected_files)
            for name, expected in gp5_snap["algorithm_identity"]["files_sha256"].items():
                key = "jev_select/stability/" + name
                copy_files[key] = expected
            imp_manifest = tmp / "import_manifest.json"
            imp_manifest.write_text(json.dumps(copy_files), encoding="utf-8")
            worker_proc = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    str(worker_path),
                    str(hist_root),
                    str(imp_manifest),
                    str(REPO / receipt_rel),
                    str(REPO / gp5_monitor_rel),
                ],
                cwd=str(REPO),
                env={"PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
                text=True,
            )
            hist_tree_check = {
                "commit": GP5_COMMIT,
                "source_tree_in_git": "semantic_pallet_planner/src/semantic_pallet_planner",
                "file_count": len(actual_files),
                "manifest_exact_match": manifest_exact_match,
                "computed_source_identity": digest(actual_files),
                "expected_gp5_source_identity": gp5_source["source_identity"],
                "isolated_worker_exit_code": worker_proc.returncode,
                "isolated_worker_stdout": worker_proc.stdout.strip(),
                "isolated_worker_stderr": worker_proc.stderr.strip()[:400],
                "status": "PASS" if (manifest_exact_match and worker_proc.returncode == 0 and worker_proc.stdout.strip() == "GP5_V17_EVIDENCE_VALID") else "FAIL",
                "note": "Read-only verification in ephemeral temp directory (cleaned up after check). Formal production bridge requires a materialized isolated historical_package_root outside current src/.",
            }

    # Verify current source_identity and delta against QA baseline
    cur_manifest = source_manifest()
    cur_source_id = digest(cur_manifest)
    delta = bridge_mod.source_delta(gp5_source["files"], cur_manifest)
    delta_digest = digest(delta)

    comparisons = {
        "python_executable_match": live_monitor_env["executable"] == gp5_snap["execution_environment"]["executable"],
        "python_version_match": live_monitor_env["python"] == gp5_snap["execution_environment"]["python"],
        "platform_match": live_monitor_env["platform"] == gp5_snap["execution_environment"]["platform"],
        "numpy_version_match": live_deps["numpy"] == gp5_snap["algorithm_identity"]["dependencies"]["numpy"],
        "numpy_core_sha256_match": live_monitor_env["numpy_core_sha256"] == gp5_snap["execution_environment"]["numpy_core_sha256"],
        "scipy_version_match": live_deps["scipy"] == gp5_snap["algorithm_identity"]["dependencies"]["scipy"],
        "highs_version_match": live_deps["highs_version"] == gp5_snap["algorithm_identity"]["dependencies"]["highs_version"],
        "highs_core_sha256_match": live_deps["highs_core_sha256"] == gp5_snap["algorithm_identity"]["dependencies"]["highs_core_sha256"],
        "scipy_python_sha256_match": live_deps["scipy_python_sha256"] == gp5_snap["algorithm_identity"]["dependencies"]["scipy_python_sha256"],
        "dependency_digest_match": live_dep_digest == gp5_snap["algorithm_identity"]["dependency_digest"],
        "stability_files_sha256_match": live_stab_files == gp5_snap["algorithm_identity"]["files_sha256"],
        "stability_source_digest_match": live_stab_source_digest == gp5_snap["algorithm_identity"]["source_digest"],
        "environment_digest_match": live_env_digest == gp5_plan["environment_digest"],
        "monitor_execution_environment_exact_match": same_native(live_monitor_env, gp5_snap["execution_environment"]),
        "validate_monitor_snapshot_pass": monitor_validation["status"] == "PASS",
        "all_historical_references_match": all(r["matches"] for r in ref_checks),
        "historical_source_tree_worker_pass": hist_tree_check["status"] == "PASS",
        "current_source_identity_matches_qa": cur_source_id == EXPECTED_QA_SOURCE_ID,
        "source_delta_digest_matches_qa": delta_digest == EXPECTED_QA_DELTA_DIGEST,
    }

    return {
        "schema": "gp6_f0_target_environment_evidence_v1",
        "date": "2026-11-22",
        "timezone": "Asia/Shanghai",
        "target_host_reached": True,
        "live_environment": live_env,
        "live_environment_digest": live_env_digest,
        "live_monitor_execution_environment": live_monitor_env,
        "live_solver_dependencies": live_deps,
        "live_dependency_digest": live_dep_digest,
        "live_stability_source_digest": live_stab_source_digest,
        "live_stability_files_count": len(live_stab_files),
        "gp5_reference_snapshot": {
            "monitor_snapshot_path": gp5_monitor_rel,
            "monitor_snapshot_sha256": gp5_monitor_sha,
            "monitor_digest": digest(gp5_snap),
            "algorithm_digest": digest(gp5_snap["algorithm_identity"]),
            "acceptance_plan_environment_digest": gp5_plan["environment_digest"],
            "source_manifest_path": gp5_manifest_rel,
            "source_manifest_sha256": gp5_manifest_sha,
            "source_identity": gp5_source["source_identity"],
            "real_kernel_receipt_path": receipt_rel,
            "real_kernel_receipt_sha256": receipt_sha,
        },
        "current_source_check": {
            "file_count": len(cur_manifest),
            "source_identity": cur_source_id,
            "expected_qa_source_identity": EXPECTED_QA_SOURCE_ID,
            "delta_count_from_gp5": len(delta),
            "delta_digest_from_gp5": delta_digest,
            "expected_qa_delta_digest": EXPECTED_QA_DELTA_DIGEST,
            "publication_policy_digest": policy_digest(),
        },
        "monitor_snapshot_validation": monitor_validation,
        "historical_reference_count": len(ref_checks),
        "historical_reference_checks": ref_checks,
        "historical_source_copy_provenance": hist_tree_check,
        "supplementary_macos_nbu_reference": {
            "path": "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_F0_BUDGET_REC_FIX_QA_20261121_01/readonly_results.json",
            "role": "SUPPLEMENTARY_OFFLINE_ONLY_NOT_TARGET_LINUX_ENV",
        },
        "comparisons": comparisons,
        "overall_status": "PASS" if all(comparisons.values()) else "FAIL",
        "real_model_calls": 0,
        "real_monitor_calls": 0,
        "real_lp_calls": 0,
        "keys_read": False,
    }


def build_draft_plan_and_checks(env_ev: dict) -> dict:
    data_manifest = read_json(DATA_ROOT / "manifest.json")
    source_man = read_json(DATA_ROOT / "source_manifest.json")
    split_man = read_json(DATA_ROOT / "split_manifest.json")
    data_identity = data_manifest["data_identity"]

    adapted_list = []
    task_audit = []
    for task_id in pkg_proto.TASK_IDS:
        raw_path = DATA_ROOT / "tasks" / f"{task_id}.json"
        raw_bytes = raw_path.read_bytes()
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        adapted = pkg_proto.adapt_task(raw_bytes, origin="EXPOSED_TRAIN", expected_sha256=raw_sha)
        adapted_list.append(adapted)
        raw_doc = json.loads(raw_bytes.decode("utf-8"))
        task_audit.append({
            "task_id": task_id,
            "raw_path": str(raw_path.relative_to(REPO)),
            "raw_bytes": len(raw_bytes),
            "raw_sha256": raw_sha,
            "item_count": len(raw_doc["items"]),
            "source_order_id": raw_doc.get("source_order_id"),
            "source_group_id": adapted["identity"]["source_group_id"],
            "origin": adapted["identity"]["origin"],
            "feasibility_status": raw_doc.get("feasibility_status", "UNKNOWN"),
            "identity": adapted["identity"],
        })

    proposed_req_ledger = "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_F0_FORMAL_RUN_PENDING/requests/requests.json"
    proposed_call_ledger = "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_F0_FORMAL_RUN_PENDING/shared_call_ledger.json"

    draft_plan = jev_proto.prepare_jev_plan(
        adapted_list,
        data_identity=data_identity,
        scope=jev_proto.GP6_ORDER,
        per_job_max_sends=19,
        shared_max_sends=76,
        request_ledger_path=proposed_req_ledger,
        call_ledger_path=proposed_call_ledger,
    )
    jev_proto.validate_jev_plan(draft_plan)
    draft_plan_digest = digest(draft_plan)
    denom = jev_proto.draft_jev_run(draft_plan)

    write_json(PKG / "gp6_f0_order_plan_DRAFT.json", draft_plan)
    write_json(PKG / "run_denominator_NOT_RUN.json", denom)

    companion = {
        "schema": "gp6_f0_plan_companion_draft_v1",
        "status": "DRAFT",
        "executable": False,
        "authorized_for_api_calls": False,
        "budget_is_not_call_permit": True,
        "date": "2026-11-22",
        "timezone": "Asia/Shanghai",
        "plan_file": "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_F0_PRELAUNCH_MATERIALS_20261122_01/gp6_f0_order_plan_DRAFT.json",
        "draft_plan_digest": draft_plan_digest,
        "denominator_file": "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_F0_PRELAUNCH_MATERIALS_20261122_01/run_denominator_NOT_RUN.json",
        "dataset_audit": {
            "dataset_root": "semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02",
            "data_identity": data_identity,
            "exposed_training_only": source_man["exposed_training_only"],
            "independent_new_sources": source_man["independent_new_sources"],
            "split_manifest": split_man,
            "exposure_statement": "Both tasks belong to exposed training source group SG_901bbb22f834c63f (source_order_id 00113144 / source_key 00100027, split=train, origin=EXPOSED_TRAIN, feasibility_status=UNKNOWN). Neither is an independent unseen test source.",
            "tasks": task_audit,
        },
        "fairness_and_prompt_bindings": {
            "runtime_version": draft_plan["runtime_version"],
            "method": jev_proto.GP6_METHOD,
            "feature_profile": draft_plan["feature_profile"],
            "memory_mode": "none (memories=[])",
            "f1_enabled": False,
            "te_memory_enabled": False,
            "training_enabled": False,
            "extra_seeds": draft_plan["extra_seeds"],
            "event_limit": draft_plan["event_limit"],
            "buffer_capacity": 3,
            "orientations_deg": [0, 90],
            "per_object_top_k": 16,
            "joint_candidates_max": 48,
            "display_order_seed": 20261102,
            "max_request_bytes": 96000,
            "model": draft_plan["model"],
            "endpoint": jev_proto.GP6_ENDPOINT,
            "api_key_env": jev_proto.GP6_API_KEY_ENV,
            "prompt_version": draft_plan["prompt_version"],
            "feature_version": draft_plan["feature_version"],
            "question_sha256": hashlib.sha256(pkg_rt.QUESTION.encode("utf-8")).hexdigest(),
            "objective_sha256": hashlib.sha256(pkg_rt.OBJECTIVE.encode("utf-8")).hexdigest(),
            "timeout_s": 30.0,
            "max_retries": 0,
            "response_max_bytes": 1000000,
            "probability_tolerance": 1e-5,
            "probability_sum_validation": "strict_or_2dp_rounding_interval_v1",
            "monitor_algorithm": "pct_exact_pose_network_v3",
            "monitor_enabled": True,
            "monitor_digest": env_ev["gp5_reference_snapshot"]["monitor_digest"],
            "only_varied_factor": "candidate_backend (e2_original_v1 vs ems_surface_hybrid_v1)",
        },
        "budget_and_ledger_contract": {
            "per_job_max_sends": 19,
            "shared_max_sends": 76,
            "model_calls_max": 76,
            "model_calls_max_equals_shared_max_sends": True,
            "assessment_limit": 76,
            "solver_limit": 4096,
            "singleton_bypass_sends": 0,
            "unknown_send_retains_reservation": True,
            "implicit_retry_allowed": False,
            "request_ledger": {
                "class": "GeometryJevRequestLedger",
                "version": "geometry_jev_requests_v1",
                "proposed_path_in_draft": proposed_req_ledger,
                "initial_state_required_before_run": "Empty requests=[] bound to final frozen plan_digest, per_job_max_sends=19, max_sends=76",
            },
            "call_ledger": {
                "class": "CallBudget / metered_jev_run",
                "version": "geometry_call_ledger_v1",
                "proposed_path_in_draft": proposed_call_ledger,
                "initial_state_required_before_run": "Zero counts {assessment_entries: 0, solver_calls: 0, test_double_assessments: 0}, calls=[], evidence='REAL_KERNEL', bound to final frozen plan_digest",
            },
        },
        "stop_rules": {
            "stop_current_job": [
                "ALL_ITEMS_PLACED (normal completion)",
                "STOP_NO_PHYSICAL_CANDIDATE (candidate pool empty)",
                "PREDICTED_STATIC_INSTABILITY (monitor returns UNSTABLE; do not place failed box)",
                "STABILITY_UNASSESSABLE / STABILITY_MONITOR_ERROR (do not merge into predicted instability)",
            ],
            "stop_job_and_halt_batch_immediately": [
                "UNKNOWN_SEND / UNKNOWN_IN_FLIGHT (retains send reservation; no implicit retry)",
                "PROVIDER_FAILURE / INVALID_RESPONSE / BUDGET_EXHAUSTED (no implicit retry)",
                "GEOMETRY_BUDGET_EXCEEDED / PHYSICAL_CHECK_DISAGREEMENT / RUNTIME_SNAPSHOT_MISMATCH / TECHNICAL_FAILURE / CANCELLED",
                "Never fall back from ems_surface_hybrid_v1 to e2_original_v1 or from Jev to local selector",
            ],
        },
        "fields_to_bind_at_formal_freeze": [
            {"field": "status", "draft_value": "DRAFT", "freeze_action": "Change to FROZEN only after QA review & user authorization"},
            {"field": "request_ledger_path", "draft_value": proposed_req_ledger, "freeze_action": "Bind to actual fresh frozen runtime directory requests/requests.json"},
            {"field": "call_ledger_path", "draft_value": proposed_call_ledger, "freeze_action": "Bind to actual fresh frozen runtime directory shared_call_ledger.json"},
            {"field": "plan_digest (derived)", "draft_value": draft_plan_digest, "freeze_action": "Recompute digest(frozen_plan) after status & ledger paths are finalized; bind into applicability_review, kernel_bridge, authorization, review, admission, and both ledgers"},
        ],
    }
    write_json(PKG / "gp6_f0_plan_companion_DRAFT.json", companion)

    # Generate unsigned pending bridge & authorization templates
    qa_delta = read_json(QA_BUDGET / "source_delta_review.json")
    gp5_snap_ref = env_ev["gp5_reference_snapshot"]
    target_pending = {
        "runtime_version": draft_plan["runtime_version"],
        "source_identity": draft_plan["source_identity"],
        "environment_digest": draft_plan["environment_digest"],
        "publication_policy_digest": draft_plan["publication_policy_digest"],
        "monitor_digest": gp5_snap_ref["monitor_digest"],
        "algorithm_digest": gp5_snap_ref["algorithm_digest"],
        "plan_digest": "<PENDING_FINAL_FROZEN_PLAN_DIGEST>",
    }

    app_review_pending = {
        "template_notice": "UNSIGNED_PENDING_TEMPLATE_NOT_APPROVED",
        "version": "geometry_jev_kernel_applicability_review_v1",
        "status": "PENDING_INDEPENDENT_QA_APPROVAL",
        "evidence_receipt": {
            "path": gp5_snap_ref["real_kernel_receipt_path"],
            "sha256": gp5_snap_ref["real_kernel_receipt_sha256"],
        },
        "historical_source_manifest": {
            "path": gp5_snap_ref["source_manifest_path"],
            "sha256": gp5_snap_ref["source_manifest_sha256"],
        },
        "historical_monitor": {
            "path": gp5_snap_ref["monitor_snapshot_path"],
            "sha256": gp5_snap_ref["monitor_snapshot_sha256"],
        },
        "target": target_pending,
        "draft_plan_digest_reference": draft_plan_digest,
        "diff_digest": qa_delta["source_delta_digest"],
        "changes": [
            {
                "path": c["path"],
                "before": c["before"],
                "after": c["after"],
                "rationale": c["rationale"],
            }
            for c in qa_delta["changes"]
        ],
        "conclusion": "<PENDING_INDEPENDENT_QA_CONCLUSION>",
        "reviewer": "<PENDING_INDEPENDENT_QA_REVIEWER_ID>",
        "limitations": "<PENDING_INDEPENDENT_QA_LIMITATIONS>",
    }
    write_json(PKG / "kernel_applicability_review_PENDING.json", app_review_pending)

    kernel_bridge_pending = {
        "template_notice": "UNSIGNED_PENDING_TEMPLATE_NOT_APPROVED",
        "version": "geometry_jev_kernel_bridge_v1",
        "status": "PENDING_INDEPENDENT_QA_APPROVAL",
        "evidence_receipt": {
            "path": gp5_snap_ref["real_kernel_receipt_path"],
            "sha256": gp5_snap_ref["real_kernel_receipt_sha256"],
        },
        "historical_source_manifest": {
            "path": gp5_snap_ref["source_manifest_path"],
            "sha256": gp5_snap_ref["source_manifest_sha256"],
        },
        "historical_package_root": "<PENDING_MATERIALIZED_ISOLATED_GP5_SOURCE_COPY_FROM_COMMIT_2c97f59444f07e40b98da529e5256efc441207d4>",
        "historical_monitor": {
            "path": gp5_snap_ref["monitor_snapshot_path"],
            "sha256": gp5_snap_ref["monitor_snapshot_sha256"],
        },
        "target": target_pending,
        "draft_plan_digest_reference": draft_plan_digest,
        "applicability_review": {
            "path": "<PENDING_SIGNED_APPLICABILITY_REVIEW_PATH>",
            "sha256": "<PENDING_SIGNED_APPLICABILITY_REVIEW_SHA256>",
        },
    }
    write_json(PKG / "kernel_bridge_PENDING.json", kernel_bridge_pending)

    scope_auth_pending = {
        "template_notice": "UNSIGNED_PENDING_TEMPLATE_NOT_APPROVED",
        "scope": jev_proto.GP6_ORDER,
        "plan_digest": "<PENDING_FINAL_FROZEN_PLAN_DIGEST>",
        "draft_plan_digest_reference": draft_plan_digest,
        "status": "PENDING_USER_AUTHORIZATION",
        "real_calls_authorized": 0,
        "requested_per_job_max_sends": 19,
        "requested_shared_max_sends": 76,
        "owner": "USER_OR_PROJECT_AUTHORITY",
    }
    write_json(PKG / "scope_authorization_PENDING.json", scope_auth_pending)

    scope_review_pending = {
        "template_notice": "UNSIGNED_PENDING_TEMPLATE_NOT_APPROVED",
        "scope": jev_proto.GP6_ORDER,
        "plan_digest": "<PENDING_FINAL_FROZEN_PLAN_DIGEST>",
        "draft_plan_digest_reference": draft_plan_digest,
        "status": "PENDING_INDEPENDENT_QA_REVIEW",
        "owner": "INDEPENDENT_QA",
    }
    write_json(PKG / "scope_review_PENDING.json", scope_review_pending)

    admission_pending = {
        "template_notice": "UNSIGNED_PENDING_TEMPLATE_NOT_APPROVED",
        "version": "geometry_jev_admission_v1",
        "runtime_version": draft_plan["runtime_version"],
        "publication_policy_digest": draft_plan["publication_policy_digest"],
        "scope": jev_proto.GP6_ORDER,
        "plan_digest": "<PENDING_FINAL_FROZEN_PLAN_DIGEST>",
        "draft_plan_digest_reference": draft_plan_digest,
        "source_identity": draft_plan["source_identity"],
        "environment_digest": draft_plan["environment_digest"],
        "monitor_digest": gp5_snap_ref["monitor_digest"],
        "status": "PENDING_INDEPENDENT_QA_APPROVAL",
        "authorization": {
            "path": "<PENDING_SIGNED_SCOPE_AUTHORIZATION_PATH>",
            "sha256": "<PENDING_SIGNED_SCOPE_AUTHORIZATION_SHA256>",
        },
        "review": {
            "path": "<PENDING_SIGNED_SCOPE_REVIEW_PATH>",
            "sha256": "<PENDING_SIGNED_SCOPE_REVIEW_SHA256>",
        },
        "api_spec_check": {
            "path": "<PENDING_QA_VERIFIED_API_SPEC_CHECK_PATH>",
            "sha256": "<PENDING_QA_VERIFIED_API_SPEC_CHECK_SHA256>",
        },
        "binding_order": [
            "Step 1 (Developer + Target Linux): Materialize isolated GP5 historical_package_root from git commit 2c97f59444f07e40b98da529e5256efc441207d4 outside src/ and implement GP6 4-job formal launcher (outside src/ to preserve source_identity).",
            "Step 2 (Developer, after QA approval of prelaunch materials): Freeze formal plan (status=FROZEN, concrete request_ledger_path & call_ledger_path in fresh runtime dir) and initialize empty request ledger + zero call ledger; obtain final frozen plan_digest.",
            "Step 3 (Independent QA): Verify API spec check -> issue VERIFIED api_spec_check; review 28-file delta & final plan_digest -> sign APPROVED kernel_applicability_review_v1, APPROVED kernel_bridge_v1, and APPROVED scope_review.",
            "Step 4 (User / Project Authority): Issue explicit APPROVED scope_authorization bound to final frozen plan_digest and 76-send / 19-per-job ceiling.",
            "Step 5 (Independent QA): Bind signed authorization, review, and api_spec_check into APPROVED geometry_jev_admission_v1.",
            "Step 6 (Developer on target Linux): Run launcher in --preflight-only mode (0 sends), verify 4/4 PASS, then execute --execute with fresh --run-root.",
        ],
    }
    write_json(PKG / "order_admission_PENDING.json", admission_pending)

    # Negative zero-call gate tests (must reject DRAFT and unsigned templates)
    gp5_snap = read_json(GP5_RUNTIME / "monitor_snapshot.json")
    neg_checks = {}

    try:
        jev_proto.validate_jev_admission(draft_plan, gp5_snap, None, None)
        neg_checks["draft_plan_rejected_by_admission"] = {"status": "FAIL", "detail": "unexpectedly accepted"}
    except JevSelectError as exc:
        neg_checks["draft_plan_rejected_by_admission"] = {
            "status": "PASS" if exc.code == "geometry_jev_draft_not_executable" else "FAIL",
            "error_code": exc.code,
        }

    try:
        jev_exec.load_jev_config(draft_plan, "G00", monitor_snapshot=gp5_snap, admission=admission_pending, kernel_receipt=kernel_bridge_pending)
        neg_checks["load_jev_config_rejects_draft"] = {"status": "FAIL", "detail": "unexpectedly accepted"}
    except JevSelectError as exc:
        neg_checks["load_jev_config_rejects_draft"] = {
            "status": "PASS" if exc.code == "geometry_jev_draft_not_executable" else "FAIL",
            "error_code": exc.code,
        }

    try:
        bridge_mod.validate_kernel_bridge(kernel_bridge_pending, draft_plan, gp5_snap)
        neg_checks["unsigned_bridge_rejected"] = {"status": "FAIL", "detail": "unexpectedly accepted"}
    except JevSelectError as exc:
        neg_checks["unsigned_bridge_rejected"] = {
            "status": "PASS",
            "error_code": exc.code,
        }

    return {
        "draft_plan_valid": True,
        "draft_plan_digest": draft_plan_digest,
        "planned_jobs": [j["job_id"] for j in draft_plan["jobs"]],
        "negative_gate_checks": neg_checks,
        "all_negative_gates_pass": all(v["status"] == "PASS" for v in neg_checks.values()),
    }


def main() -> int:
    PKG.mkdir(parents=True, exist_ok=True)
    env_ev = collect_live_environment_and_compare()
    write_json(PKG / "environment_evidence.json", env_ev)
    plan_res = build_draft_plan_and_checks(env_ev)
    summary = {
        "schema": "gp6_f0_prelaunch_readonly_results_v1",
        "date": "2026-11-22",
        "timezone": "Asia/Shanghai",
        "python_executable": sys.executable,
        "environment_overall_status": env_ev["overall_status"],
        "environment_comparisons": env_ev["comparisons"],
        "draft_plan_and_negative_gates": plan_res,
        "real_model_calls": 0,
        "real_monitor_calls": 0,
        "real_lp_calls": 0,
        "keys_read": False,
    }
    write_json(PKG / "readonly_preflight_results.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if (env_ev["overall_status"] == "PASS" and plan_res["all_negative_gates_pass"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
