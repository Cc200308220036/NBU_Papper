"""Prepare GP5 formal 8-job order package, pending 4+6 kernel receipt materials, and frozen plan.

Strictly read-only with respect to historical artifacts, production source, and execution:
never runs episodes, orders, monitor assessments, LP solver, or model calls.
"""
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path

from scipy.optimize._highspy import _core

from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_kernel_completion import required_coverage
from semantic_pallet_planner.jev_select.geometry_native_protocol import policy_digest
from semantic_pallet_planner.jev_select.geometry_order_execution import validate_monitor_snapshot
from semantic_pallet_planner.jev_select.geometry_order_meter import CallBudget
from semantic_pallet_planner.jev_select.ledger import write
from semantic_pallet_planner.jev_select.packaging_versions import (
    DEFAULT_GEOMETRY_BACKEND,
    GEOMETRY_BACKENDS,
    GEOMETRY_NATIVE_VERSION,
)
from semantic_pallet_planner.jev_select.stability.monitor import exact_freeze

OUT = Path("semantic_pallet_planner/outputs")
DATA_ROOT = OUT / "DATA_JEV_PACKAGING_LOAD_20261102_02"
P2_RUNTIME = OUT / "GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01"
P2_LAUNCH_QA = OUT / "GEOM_CANDIDATES_GP5_P2_APPROVED_LAUNCH_QA_20261120_01"
P2_RUN = OUT / "GEOM_CANDIDATES_GP5_P2_FIXED_ACCEPTANCE_20261120_01"
PREP_ROOT = OUT / "GEOM_CANDIDATES_GP5_FORMAL_ORDER_PREP_20261120_01"
EXPECTED_HEAD = "24f75b978cedd0a15efafe991a918d90de09c92b"


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ref(path):
    return {"path": str(path), "sha256": sha(path)}


def main():
    branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()
    assert branch == "dev/jev-select", f"Unexpected branch: {branch}"
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    assert head == EXPECTED_HEAD, f"Expected HEAD {EXPECTED_HEAD}, got {head}"
    assert not (PREP_ROOT / "order_plan_FROZEN.json").exists(), f"NO_OVERWRITE_PREP_ROOT: {PREP_ROOT}"

    PREP_ROOT.mkdir(parents=True, exist_ok=True)

    # 1. Source & environment identity
    files = source_manifest()
    src_id = digest(files)
    pol_id = policy_digest()
    p2_plan = read(P2_RUNTIME / "acceptance_plan_FROZEN.json")
    assert src_id == p2_plan["source_identity"], "Source identity drifted from P2 frozen plan"
    assert pol_id == p2_plan["publication_policy_digest"], "Policy digest drifted from P2 frozen plan"

    snap = exact_freeze()
    validate_monitor_snapshot(snap)
    p2_snap = read(P2_RUNTIME / "monitor_snapshot.json")
    assert digest(snap) == digest(p2_snap), "Monitor snapshot drifted from P2 frozen snapshot"

    host_env = {
        "platform": platform.platform(),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "numpy": importlib.metadata.version("numpy"),
        "scipy": importlib.metadata.version("scipy"),
        "jsonschema": importlib.metadata.version("jsonschema"),
        "highs_version": ".".join(str(getattr(_core, "HIGHS_VERSION_" + k)) for k in ("MAJOR", "MINOR", "PATCH")),
    }

    write(
        PREP_ROOT / "source_manifest.json",
        {
            "source_files": len(files),
            "source_identity": src_id,
            "publication_policy_digest": pol_id,
            "runtime_version": GEOMETRY_NATIVE_VERSION,
            "default_geometry_backend": DEFAULT_GEOMETRY_BACKEND,
            "geometry_backends": list(GEOMETRY_BACKENDS),
            "files": files,
        },
    )
    write(PREP_ROOT / "monitor_snapshot.json", snap)

    # 2. Part I: Pending 4+6 kernel completion review & real kernel receipt materials
    acc_plan_path = P2_RUNTIME / "acceptance_plan_FROZEN.json"
    launch_path = P2_LAUNCH_QA / "launch.json"
    ledger_final_path = P2_RUN / "shared_call_ledger_FINAL.json"
    ledger_final = read(ledger_final_path)
    assert ledger_final["counts"] == {"assessment_entries": 8, "solver_calls": 68, "test_double_assessments": 0}

    records = [ref(P2_RUN / f"primary/jobs/J0{i}/record.json") for i in range(4)]
    recovery = []
    recovery_with_credentials = []
    for job in ("J00", "J01"):
        for phase in ("SELECTED", "MONITORED", "COMMITTED"):
            before_path = P2_RUN / f"saved/{job}/{phase}/saved_checkpoint.json"
            after_path = P2_RUN / f"recovery/{job}/{phase}/jobs/{job}/record.json"
            acct_path = P2_RUN / f"recovery/{job}/{phase}/jobs/{job}/accounting.json"
            cred_path = P2_RUN / f"recovery/{job}/{phase}/jobs/{job}/phase_snapshot_credential.json"
            parent_rec_path = P2_RUN / f"primary/jobs/{job}/record.json"
            parent_acct_path = P2_RUN / f"primary/jobs/{job}/accounting.json"
            entry = {
                "job_id": job,
                "phase": phase,
                "before": ref(before_path),
                "after": ref(after_path),
                "accounting": ref(acct_path),
            }
            recovery.append(entry)
            recovery_with_credentials.append({
                **entry,
                "phase_credential": ref(cred_path),
                "parent_record_ref": ref(parent_rec_path),
                "parent_accounting_ref": ref(parent_acct_path),
            })

    cov = required_coverage(p2_plan)
    review_fields = {
        "version": "geometry_kernel_completion_review_v2",
        "scope": "KERNEL_ACCEPTANCE_SYNTHETIC_ONLY",
        "status": "PENDING_INDEPENDENT_QA_SIGN_OFF",
        "target_approved_status": "APPROVED",
        "acceptance_plan_digest": digest(p2_plan),
        "records_digest": digest(records),
        "recovery_digest": digest(recovery),
        "counter_log": ref(ledger_final_path),
        "coverage_digest": digest(cov),
        "runtime_version": GEOMETRY_NATIVE_VERSION,
        "publication_policy_digest": pol_id,
    }
    write(PREP_ROOT / "kernel_completion_review_PENDING.json", review_fields)

    receipt_pending = {
        "version": "geometry_real_kernel_receipt_v3",
        "scope": "KERNEL_ACCEPTANCE_SYNTHETIC_ONLY",
        "status": "PENDING_INDEPENDENT_QA_SIGN_OFF",
        "target_accepted_status": "ACCEPTED",
        "source_identity": p2_plan["source_identity"],
        "environment_digest": p2_plan["environment_digest"],
        "monitor_digest": digest(snap),
        "launch": ref(launch_path),
        "acceptance_plan": ref(acc_plan_path),
        "records": records,
        "counts": {"assessment_entries": 8, "solver_calls": 68, "test_double_assessments": 0},
        "counter_log": ref(ledger_final_path),
        "review": {
            "path": "<PENDING_INDEPENDENT_QA_KERNEL_COMPLETION_REVIEW_V2_PATH>",
            "sha256": "<PENDING_INDEPENDENT_QA_KERNEL_COMPLETION_REVIEW_V2_SHA256>",
        },
        "recovery": recovery,
        "runtime_version": GEOMETRY_NATIVE_VERSION,
        "publication_policy_digest": pol_id,
        "supplementary_evidence": {
            "model_calls": 0,
            "original_empty_ledger": ref(P2_RUNTIME / "shared_call_ledger.json"),
            "driver_receipt": ref(P2_RUN / "driver_receipt.json"),
            "qa_fixed_acceptance_review": ref(OUT / "GEOM_CANDIDATES_GP5_P2_FIXED_ACCEPTANCE_QA_20261120_01/quality_review.json"),
            "recovery_phase_credentials_and_parents": recovery_with_credentials,
        },
    }
    write(PREP_ROOT / "real_kernel_receipt_PENDING.json", receipt_pending)

    # 3. Part II: Data verification and formal 8-job plan (DRAFT -> FROZEN)
    data_manifest = read(DATA_ROOT / "manifest.json")
    data_source_manifest = read(DATA_ROOT / "source_manifest.json")
    data_split_manifest = read(DATA_ROOT / "split_manifest.json")
    data_identity = data_manifest["data_identity"]

    adapted_tasks = []
    task_records = []
    for task_id in p.TASK_IDS:
        raw_path = DATA_ROOT / "tasks" / f"{task_id}.json"
        raw_bytes = raw_path.read_bytes()
        raw_hash = sha(raw_path)
        adapted = p.adapt_task(raw_bytes, origin="EXPOSED_TRAIN", expected_sha256=raw_hash)
        adapted_tasks.append(adapted)
        task_records.append({
            "task_id": task_id,
            "raw_path": str(raw_path),
            "identity": adapted["identity"],
            "item_count": len(adapted["frozen"]["items"]),
            "arrival_order_matches_items": adapted["frozen"]["arrival_order"] == [o["item_id"] for o in adapted["frozen"]["items"]],
            "partition": adapted["frozen"]["partition"],
            "source_group_id": adapted["frozen"]["source_group_id"],
            "source_order_id": adapted["frozen"].get("source_order_id"),
            "mode": adapted["frozen"]["mode"],
            "feasibility_status": adapted["frozen"]["feasibility_status"],
        })

    draft_plan = p.prepare_order_plan(adapted_tasks, data_identity=data_identity, scope=p.ORDER, native=True)
    assert draft_plan["status"] == "DRAFT"
    write(PREP_ROOT / "order_plan_DRAFT.json", draft_plan)

    frozen_plan = dict(draft_plan)
    frozen_plan.update(
        status="FROZEN",
        assessment_limit=152,
        solver_limit=8192,
        call_ledger_path=str(PREP_ROOT / "shared_call_ledger.json"),
    )
    p.validate_order_plan(frozen_plan)
    write(PREP_ROOT / "order_plan_FROZEN.json", frozen_plan)

    budget = CallBudget(PREP_ROOT / "shared_call_ledger.json", frozen_plan, evidence="REAL_KERNEL", job_id="PRESTART_NO_CALL")
    assert budget.value["calls"] == []
    assert budget.value["counts"] == {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0}

    run_denom = p.draft_run(frozen_plan)
    assert len(run_denom["rows"]) == 8 and all(r["status"] == "NOT_RUN" for r in run_denom["rows"])
    write(PREP_ROOT / "run_denominator_NOT_RUN.json", run_denom)

    # 4. Data & matrix audit summary + termination/metrics contract
    write(
        PREP_ROOT / "data_and_matrix_summary.json",
        {
            "dataset_root": str(DATA_ROOT),
            "data_identity": data_identity,
            "manifest_ref": ref(DATA_ROOT / "manifest.json"),
            "source_manifest_ref": ref(DATA_ROOT / "source_manifest.json"),
            "split_manifest_ref": ref(DATA_ROOT / "split_manifest.json"),
            "handoff_ref": ref(DATA_ROOT / "handoff.json"),
            "exposed_training_only": data_source_manifest["exposed_training_only"],
            "independent_new_sources": data_source_manifest["independent_new_sources"],
            "selected_source_group": "SG_901bbb22f834c63f",
            "selected_source_note": "Both tasks are capacity variants of the same exposed training source (00100027 / SG_901bbb22f834c63f); not two independent sources and not unseen test.",
            "tasks": task_records,
            "plan_digest_draft": digest(draft_plan),
            "plan_digest_frozen": digest(frozen_plan),
            "plan_frozen_sha256": sha(PREP_ROOT / "order_plan_FROZEN.json"),
            "jobs": frozen_plan["jobs"],
        },
    )

    # 5. Part III: Scope authorization, scope review, admission pending templates & checklist
    plan_digest = digest(frozen_plan)
    write(
        PREP_ROOT / "scope_authorization_PENDING.json",
        {
            "target_schema": "geometry_scope_authorization_v2",
            "status": "PENDING_USER_AUTHORIZATION",
            "required_fields": {
                "version": "geometry_scope_authorization_v2",
                "scope": "EXPOSED_TRAIN_LOCAL_ORDER_ONLY",
                "plan_digest": plan_digest,
                "status": "APPROVED",
                "runtime_version": GEOMETRY_NATIVE_VERSION,
                "publication_policy_digest": pol_id,
            },
            "note": "Must be issued by user after reviewing the exact 8-job plan digest and budget. Old 4+6 authorization cannot be reused.",
        },
    )
    write(
        PREP_ROOT / "scope_review_PENDING.json",
        {
            "target_schema": "geometry_scope_review_v2",
            "status": "PENDING_INDEPENDENT_QA_REVIEW",
            "required_fields": {
                "version": "geometry_scope_review_v2",
                "scope": "EXPOSED_TRAIN_LOCAL_ORDER_ONLY",
                "plan_digest": plan_digest,
                "status": "APPROVED",
                "runtime_version": GEOMETRY_NATIVE_VERSION,
                "publication_policy_digest": pol_id,
            },
            "note": "Must be issued by independent QA for this exact plan_digest.",
        },
    )
    write(
        PREP_ROOT / "order_admission_PENDING.json",
        {
            "target_schema": "geometry_order_admission_v2",
            "status": "PENDING_USER_AUTH_AND_QA_REVIEW",
            "required_fields": {
                "version": "geometry_order_admission_v2",
                "scope": "EXPOSED_TRAIN_LOCAL_ORDER_ONLY",
                "plan_digest": plan_digest,
                "source_identity": src_id,
                "environment_digest": frozen_plan["environment_digest"],
                "monitor_digest": digest(snap),
                "status": "APPROVED",
                "authorization": {
                    "path": "<USER_AUTHORIZED_GEOMETRY_SCOPE_AUTHORIZATION_V2_PATH>",
                    "sha256": "<USER_AUTHORIZED_GEOMETRY_SCOPE_AUTHORIZATION_V2_SHA256>",
                },
                "review": {
                    "path": "<QA_APPROVED_GEOMETRY_SCOPE_REVIEW_V2_PATH>",
                    "sha256": "<QA_APPROVED_GEOMETRY_SCOPE_REVIEW_V2_SHA256>",
                },
                "runtime_version": GEOMETRY_NATIVE_VERSION,
                "publication_policy_digest": pol_id,
            },
        },
    )
    write(
        PREP_ROOT / "execution_scope_checklist.json",
        {
            "schema": "gp5_formal_order_execution_scope_checklist_v1",
            "date": "2026-11-20",
            "timezone": "Asia/Shanghai",
            "host_environment": host_env,
            "git": {"branch": branch, "upstream": "origin/dev/jev-select", "head": head},
            "plan_digest": plan_digest,
            "plan_ref": ref(PREP_ROOT / "order_plan_FROZEN.json"),
            "runtime_version": GEOMETRY_NATIVE_VERSION,
            "publication_policy_digest": pol_id,
            "source_identity": src_id,
            "environment_digest": frozen_plan["environment_digest"],
            "monitor_digest": digest(snap),
            "data_identity": data_identity,
            "feature_profile": frozen_plan["feature_profile"],
            "jobs": frozen_plan["jobs"],
            "shared_budget_upper_limits_not_permit": {
                "assessment_entries_max": 152,
                "solver_calls_max": 8192,
                "model_calls_max": 0,
                "event_limit": None,
                "extra_seeds": False,
            },
            "stop_conditions": [
                "ALL_ITEMS_PLACED",
                "STOP_NO_PHYSICAL_CANDIDATE",
                "PREDICTED_STATIC_INSTABILITY (stop immediately, no second choice)",
                "STABILITY_UNASSESSABLE / STABILITY_MONITOR_ERROR (stop immediately, no commit)",
                "Budget exhaustion / technical / input / identity / storage error (STOP_NO_RETRY)",
            ],
            "explicit_exclusions": [
                "No GP6, no Jev/LLM/VLM, no T/E experience",
                "No extra seeds or repeats",
                "No unseen-source or generalization claims (both tasks share SG_901bbb22f834c63f)",
                "No re-run of 4+6 synthetic acceptance",
                "No modification of frozen tolerances, physical checks, or source code",
            ],
            "prerequisites_before_dispatch": [
                "Independent QA signs geometry_kernel_completion_review_v2 and issues/verifies geometry_real_kernel_receipt_v3",
                "User authorizes exact 8-job plan (geometry_scope_authorization_v2)",
                "Independent QA reviews scope (geometry_scope_review_v2) and issues geometry_order_admission_v2",
                "Read-only preflight (verify_formal_prep.py with all external receipts) passes 8/8 load_order_config with shared ledger still 0/0/0",
            ],
        },
    )
    print("PREPARATION_COMPLETE", plan_digest)


if __name__ == "__main__":
    main()
