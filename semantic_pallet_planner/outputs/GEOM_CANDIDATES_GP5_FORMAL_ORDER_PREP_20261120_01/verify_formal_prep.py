"""Repeatable read-only verification for GP5 formal 8-job preparation package.

Strictly read-only: never calls run_order_job, run_episode, exact_freeze,
monitor assessments, LP solver, or any model.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_kernel_completion import required_coverage
from semantic_pallet_planner.jev_select.geometry_native_protocol import policy_digest
from semantic_pallet_planner.jev_select.geometry_order_execution import (
    load_order_config,
    validate_monitor_snapshot,
)
from semantic_pallet_planner.jev_select.packaging_versions import GEOMETRY_BACKENDS, GEOMETRY_NATIVE_VERSION
from semantic_pallet_planner.jev_select.packaging_runtime import METHODS

OUT = Path("semantic_pallet_planner/outputs")
DATA_ROOT = OUT / "DATA_JEV_PACKAGING_LOAD_20261102_02"
P2_RUNTIME = OUT / "GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01"
P2_LAUNCH_QA = OUT / "GEOM_CANDIDATES_GP5_P2_APPROVED_LAUNCH_QA_20261120_01"
P2_RUN = OUT / "GEOM_CANDIDATES_GP5_P2_FIXED_ACCEPTANCE_20261120_01"
PREP_ROOT = OUT / "GEOM_CANDIDATES_GP5_FORMAL_ORDER_PREP_20261120_01"


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_ref(ref):
    path = Path(ref["path"])
    assert path.is_file(), f"Missing referenced file: {path}"
    actual = sha(path)
    assert actual == ref["sha256"], f"SHA-256 drift for {path}: expected {ref['sha256']}, got {actual}"
    return read(path)


def main():
    parser = argparse.ArgumentParser(description="Read-only verification of GP5 formal 8-job preparation.")
    parser.add_argument("--kernel-receipt", type=Path, default=None, help="Signed geometry_real_kernel_receipt_v3 JSON path")
    parser.add_argument("--admission", type=Path, default=None, help="Signed geometry_order_admission_v2 JSON path")
    parser.add_argument("--write-receipt", type=Path, default=None, help="Optional path to write verification receipt JSON")
    args = parser.parse_args()

    # 1. Git & source identity checks
    branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty_protected = subprocess.check_output(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "semantic_pallet_planner/src",
            str(P2_RUNTIME),
            str(P2_LAUNCH_QA),
            str(P2_RUN),
            str(DATA_ROOT),
        ],
        text=True,
    ).strip()
    assert not dirty_protected, f"Protected paths modified:\n{dirty_protected}"

    files = source_manifest()
    src_id = digest(files)
    pol_id = policy_digest()
    src_doc = read(PREP_ROOT / "source_manifest.json")
    assert src_doc["source_identity"] == src_id and src_doc["publication_policy_digest"] == pol_id

    # 2. Monitor snapshot check (read-only validation, no exact_freeze call)
    snap = read(PREP_ROOT / "monitor_snapshot.json")
    validate_monitor_snapshot(snap)
    p2_snap = read(P2_RUNTIME / "monitor_snapshot.json")
    assert digest(snap) == digest(p2_snap)

    # 3. 4+6 pending kernel receipt & review material checks
    p2_plan = check_ref({"path": str(P2_RUNTIME / "acceptance_plan_FROZEN.json"), "sha256": sha(P2_RUNTIME / "acceptance_plan_FROZEN.json")})
    pending_review = read(PREP_ROOT / "kernel_completion_review_PENDING.json")
    pending_receipt = read(PREP_ROOT / "real_kernel_receipt_PENDING.json")

    assert pending_review["acceptance_plan_digest"] == digest(p2_plan)
    assert pending_review["records_digest"] == digest(pending_receipt["records"])
    assert pending_review["recovery_digest"] == digest(pending_receipt["recovery"])
    assert pending_review["coverage_digest"] == digest(required_coverage(p2_plan))
    assert pending_review["runtime_version"] == GEOMETRY_NATIVE_VERSION
    assert pending_review["publication_policy_digest"] == pol_id

    for rec_ref in pending_receipt["records"]:
        check_ref(rec_ref)
    for row in pending_receipt["recovery"]:
        check_ref(row["before"])
        check_ref(row["after"])
        check_ref(row["accounting"])
    for sup_row in pending_receipt["supplementary_evidence"]["recovery_phase_credentials_and_parents"]:
        check_ref(sup_row["phase_credential"])
        check_ref(sup_row["parent_record_ref"])
        check_ref(sup_row["parent_accounting_ref"])
    check_ref(pending_receipt["launch"])
    check_ref(pending_receipt["acceptance_plan"])
    final_ledger = check_ref(pending_receipt["counter_log"])
    assert final_ledger["counts"] == {"assessment_entries": 8, "solver_calls": 68, "test_double_assessments": 0}
    assert len(final_ledger["calls"]) == 76 and all(c["state"] == "DONE" for c in final_ledger["calls"])

    # 4. Data & frozen 8-job plan checks
    data_manifest = read(DATA_ROOT / "manifest.json")
    draft_plan = read(PREP_ROOT / "order_plan_DRAFT.json")
    frozen_plan = read(PREP_ROOT / "order_plan_FROZEN.json")
    assert draft_plan["status"] == "DRAFT" and frozen_plan["status"] == "FROZEN"
    p.validate_order_plan(draft_plan)
    p.validate_order_plan(frozen_plan)
    assert frozen_plan["data_identity"] == data_manifest["data_identity"]
    assert frozen_plan["source_identity"] == src_id
    assert frozen_plan["publication_policy_digest"] == pol_id
    assert frozen_plan["event_limit"] is None and frozen_plan["extra_seeds"] is False
    assert frozen_plan["model_calls_max"] == 0
    assert 0 < frozen_plan["assessment_limit"] <= 152
    assert 0 < frozen_plan["solver_limit"] <= 8192
    assert len(frozen_plan["jobs"]) == 8

    for task_entry in frozen_plan["tasks"]:
        raw_path = DATA_ROOT / "tasks" / f"{task_entry['task_id']}.json"
        adapted = p.adapt_task(raw_path.read_bytes(), origin="EXPOSED_TRAIN", expected_sha256=task_entry["raw_sha256"])
        assert adapted["identity"] == task_entry

    # 5. Zero ledger & NOT_RUN denominator checks
    ledger_path = Path(frozen_plan["call_ledger_path"])
    assert ledger_path.resolve() == (PREP_ROOT / "shared_call_ledger.json").resolve()
    ledger_before = read(ledger_path)
    assert ledger_before["plan_digest"] == digest(frozen_plan)
    assert ledger_before["evidence"] == "REAL_KERNEL"
    assert ledger_before["limits"] == {"assessment_entries": 152, "solver_calls": 8192}
    assert ledger_before["calls"] == []
    assert ledger_before["counts"] == {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0}

    run_denom = read(PREP_ROOT / "run_denominator_NOT_RUN.json")
    assert run_denom["plan_digest"] == digest(frozen_plan)
    assert [r["job_id"] for r in run_denom["rows"]] == [f"J0{i}" for i in range(8)]
    assert all(r["status"] == "NOT_RUN" and r["metrics"] is None for r in run_denom["rows"])

    # 6. Conditional signed-material checks (real kernel receipt, admission, 8-job load_order_config)
    signed_checks = {
        "validate_real_kernel_receipt": "NOT_VERIFIED_PENDING_QA_SIGN_OFF",
        "validate_admission": "NOT_VERIFIED_PENDING_AUTH_AND_QA",
        "load_order_config_jobs": {f"J0{i}": "NOT_RUN_PENDING_ADMISSION" for i in range(8)},
        "ledger_after_preflight": ledger_before["counts"],
    }

    if (args.kernel_receipt is None) != (args.admission is None):
        raise SystemExit("Provide both --kernel-receipt and --admission, or neither.")

    if args.kernel_receipt is not None and args.admission is not None:
        receipt = read(args.kernel_receipt)
        admission = read(args.admission)
        p.validate_real_kernel_receipt(receipt, frozen_plan, snap)
        signed_checks["validate_real_kernel_receipt"] = "PASS"
        p.validate_admission(frozen_plan, snap, admission, receipt)
        signed_checks["validate_admission"] = "PASS"

        job_results = {}
        for job in frozen_plan["jobs"]:
            cfg = load_order_config(
                frozen_plan,
                job["job_id"],
                monitor_snapshot=snap,
                admission=admission,
                kernel_receipt=receipt,
            )
            assert cfg["monitor_evidence"] == "REAL_KERNEL"
            assert cfg["candidate_backend"] == job["backend"]
            assert cfg["selector"] == job["method"]
            assert cfg["order_task_identity"]["task_id"] == job["task_id"]
            job_results[job["job_id"]] = {
                "status": "PASS",
                "task_id": job["task_id"],
                "backend": job["backend"],
                "method": job["method"],
                "config_digest": digest(cfg),
            }
        signed_checks["load_order_config_jobs"] = job_results
        ledger_after = read(ledger_path)
        assert ledger_after["calls"] == [] and ledger_after["counts"] == {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0}
        signed_checks["ledger_after_preflight"] = ledger_after["counts"]

    out = {
        "schema": "gp5_formal_order_prep_verification_v1",
        "git": {"branch": branch, "head": head},
        "python": sys.version.split()[0],
        "plan_digest": digest(frozen_plan),
        "monitor_digest": digest(snap),
        "source_identity": src_id,
        "publication_policy_digest": pol_id,
        "unsigned_prep_checks": {
            "source_and_monitor_identity": "PASS",
            "4_plus_6_pending_materials_and_references": "PASS",
            "data_and_frozen_8_job_plan": "PASS",
            "zero_ledger_and_not_run_denominator": "PASS",
        },
        "signed_gate_checks": signed_checks,
        "post_signoff_command_template": (
            "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src python3 -B "
            f"{PREP_ROOT / 'verify_formal_prep.py'} "
            "--kernel-receipt <SIGNED_KERNEL_RECEIPT_V3_JSON> "
            "--admission <SIGNED_ORDER_ADMISSION_V2_JSON>"
        ),
    }
    if args.write_receipt is not None:
        args.write_receipt.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
