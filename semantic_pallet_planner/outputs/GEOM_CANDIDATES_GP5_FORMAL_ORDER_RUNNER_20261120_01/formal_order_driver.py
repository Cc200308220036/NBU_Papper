"""Thin batch runner for the frozen GP5 formal 8-job matrix (J00-J07).

Default mode runs preflight only (no dispatches). Real execution requires
explicit --execute, signed kernel receipt v3, signed order admission v2,
and a fresh --run-root (intended for an isolated Linux worktree).
Reuses existing load_order_config, run_order_job, CallBudget, and run.json
without modifying production source or historical artifacts.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from semantic_pallet_planner.jev_select import geometry_order_execution as order
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_native_protocol import policy_digest
from semantic_pallet_planner.jev_select.ledger import write

OUT = Path("semantic_pallet_planner/outputs")
DATA_ROOT = OUT / "DATA_JEV_PACKAGING_LOAD_20261102_02"
PREP_ROOT = OUT / "GEOM_CANDIDATES_GP5_FORMAL_ORDER_PREP_20261120_01"
FROZEN_PLAN_DIGEST = "493e547d85a3df0909b6741ed53cd7c93047af49cef695a9380d695be48006aa"
EXPECTED_LIMITS = {"assessment_entries": 152, "solver_calls": 8192}
ZERO_COUNTS = {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0}


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_initial_zero_ledger(plan):
    ledger_path = Path(plan["call_ledger_path"])
    assert ledger_path.is_file(), f"MISSING_SHARED_LEDGER: {ledger_path}"
    ledger = read(ledger_path)
    assert set(ledger) == {"version", "plan_digest", "evidence", "limits", "calls", "counts"}, "LEDGER_SCHEMA_MISMATCH"
    assert ledger["version"] == "geometry_call_ledger_v1", "LEDGER_VERSION_MISMATCH"
    assert ledger["evidence"] == "REAL_KERNEL", "LEDGER_EVIDENCE_MISMATCH"
    assert ledger["plan_digest"] == digest(plan), "LEDGER_PLAN_DIGEST_MISMATCH"
    assert ledger["limits"] == EXPECTED_LIMITS, "LEDGER_LIMITS_MISMATCH"
    assert ledger["calls"] == [], "NONEMPTY_INITIAL_LEDGER_CALLS"
    assert ledger["counts"] == ZERO_COUNTS, "NONZERO_INITIAL_LEDGER_COUNTS"
    return ledger


def load_adapted_tasks(plan):
    adapted_by_task = {}
    for task_entry in plan["tasks"]:
        task_id = task_entry["task_id"]
        raw_path = DATA_ROOT / "tasks" / f"{task_id}.json"
        assert raw_path.is_file(), f"MISSING_TASK_FILE: {raw_path}"
        adapted = p.adapt_task(
            raw_path.read_bytes(),
            origin="EXPOSED_TRAIN",
            expected_sha256=task_entry["raw_sha256"],
        )
        assert adapted["identity"] == task_entry, f"TASK_IDENTITY_DRIFT: {task_id}"
        adapted_by_task[task_id] = adapted
    return adapted_by_task


def run_preflight(plan_path, snap_path, receipt_path, admission_path):
    plan = read(plan_path)
    p.validate_order_plan(plan)
    assert plan["status"] == "FROZEN", "PLAN_NOT_FROZEN"
    assert plan["scope"] == p.ORDER, "PLAN_SCOPE_MISMATCH"
    actual_plan_digest = digest(plan)
    assert actual_plan_digest == FROZEN_PLAN_DIGEST, (
        f"PLAN_DIGEST_MISMATCH: expected {FROZEN_PLAN_DIGEST}, got {actual_plan_digest}"
    )
    assert [j["job_id"] for j in plan["jobs"]] == [f"J0{i}" for i in range(8)], "PLAN_JOBS_MISMATCH"
    assert plan["source_identity"] == digest(source_manifest()), "SOURCE_IDENTITY_DRIFT"
    assert plan["publication_policy_digest"] == policy_digest(), "POLICY_DIGEST_DRIFT"

    snap = read(snap_path)
    order.validate_monitor_snapshot(snap)

    adapted_by_task = load_adapted_tasks(plan)
    ledger_before = check_initial_zero_ledger(plan)

    assert receipt_path is not None and Path(receipt_path).is_file(), "MISSING_SIGNED_KERNEL_RECEIPT"
    assert admission_path is not None and Path(admission_path).is_file(), "MISSING_SIGNED_ORDER_ADMISSION"
    receipt = read(receipt_path)
    admission = read(admission_path)

    p.validate_real_kernel_receipt(receipt, plan, snap)
    p.validate_admission(plan, snap, admission, receipt)

    preflight_configs = {}
    for job in plan["jobs"]:
        cfg = order.load_order_config(
            plan,
            job["job_id"],
            monitor_snapshot=snap,
            admission=admission,
            kernel_receipt=receipt,
        )
        assert cfg["monitor_evidence"] == "REAL_KERNEL", f"MONITOR_EVIDENCE_MISMATCH: {job['job_id']}"
        assert cfg["candidate_backend"] == job["backend"], f"BACKEND_MISMATCH: {job['job_id']}"
        assert cfg["selector"] == job["method"], f"SELECTOR_MISMATCH: {job['job_id']}"
        assert cfg["order_task_identity"]["task_id"] == job["task_id"], f"TASK_MISMATCH: {job['job_id']}"
        preflight_configs[job["job_id"]] = {
            "status": "PASS",
            "task_id": job["task_id"],
            "backend": job["backend"],
            "method": job["method"],
            "config_digest": digest(cfg),
        }

    ledger_after = check_initial_zero_ledger(plan)
    return {
        "plan": plan,
        "plan_digest": actual_plan_digest,
        "snap": snap,
        "receipt": receipt,
        "admission": admission,
        "adapted_by_task": adapted_by_task,
        "preflight_configs": preflight_configs,
        "ledger_before": ledger_before["counts"],
        "ledger_after_preflight": ledger_after["counts"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="GP5 formal 8-job runner (preflight-only by default).")
    parser.add_argument("--plan", type=Path, default=PREP_ROOT / "order_plan_FROZEN.json")
    parser.add_argument("--monitor-snapshot", type=Path, default=PREP_ROOT / "monitor_snapshot.json")
    parser.add_argument("--kernel-receipt", type=Path, default=None, help="Signed geometry_real_kernel_receipt_v3 JSON")
    parser.add_argument("--admission", type=Path, default=None, help="Signed geometry_order_admission_v2 JSON")
    parser.add_argument("--run-root", type=Path, default=None, help="Fresh output directory for --execute")
    parser.add_argument("--execute", action="store_true", help="Actually dispatch J00-J07 after 8/8 preflight")
    args = parser.parse_args(argv)

    ctx = run_preflight(args.plan, args.monitor_snapshot, args.kernel_receipt, args.admission)

    if not args.execute:
        summary = {
            "mode": "PREFLIGHT_ONLY",
            "plan_digest": ctx["plan_digest"],
            "preflight": "8/8 PASS",
            "preflight_configs": ctx["preflight_configs"],
            "ledger_before": ctx["ledger_before"],
            "ledger_after_preflight": ctx["ledger_after_preflight"],
            "dispatched_jobs": 0,
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    assert args.run_root is not None, "RUN_ROOT_REQUIRED_FOR_EXECUTE"
    run_root = Path(args.run_root)
    run_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_root.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise AssertionError(f"NO_OVERWRITE_EXISTING_RUN_ROOT: {run_root}") from exc

    plan = ctx["plan"]
    job_rows = []
    first_error = None
    for job in plan["jobs"]:
        job_id = job["job_id"]
        adapted = ctx["adapted_by_task"][job["task_id"]]
        try:
            res = order.run_order_job(
                plan,
                job_id,
                adapted,
                monitor_snapshot=ctx["snap"],
                admission=ctx["admission"],
                root=run_root,
                kernel_receipt=ctx["receipt"],
            )
            summary = res.get("summary") if isinstance(res, dict) else None
            if not isinstance(summary, dict) or not summary:
                first_error = {
                    "job_id": job_id,
                    "type": "EMPTY_SUMMARY_TECHNICAL_FAILURE",
                    "detail": "run_order_job returned missing or empty summary",
                }
                job_rows.append({
                    "job_id": job_id,
                    "task_id": job["task_id"],
                    "backend": job["backend"],
                    "method": job["method"],
                    "status": "TECHNICAL_FAILURE",
                    "error": first_error,
                })
                break

            term_class = summary.get("termination_class")
            term_reason = summary.get("termination_reason")
            if term_class == "CANCELLED" or term_reason == "CANCELLED":
                first_error = {
                    "job_id": job_id,
                    "type": "CANCELLED",
                    "detail": term_reason or "CANCELLED",
                }
                job_rows.append({
                    "job_id": job_id,
                    "task_id": job["task_id"],
                    "backend": job["backend"],
                    "method": job["method"],
                    "status": "CANCELLED",
                    "termination_reason": term_reason,
                    "termination_class": term_class,
                    "placed_items": summary.get("placed_items"),
                    "planned_items": summary.get("planned_items"),
                    "error": first_error,
                })
                break

            if term_class == "TECHNICAL_FAILURE":
                first_error = {
                    "job_id": job_id,
                    "type": "TECHNICAL_FAILURE",
                    "detail": term_reason or "TECHNICAL_FAILURE",
                }
                job_rows.append({
                    "job_id": job_id,
                    "task_id": job["task_id"],
                    "backend": job["backend"],
                    "method": job["method"],
                    "status": "TECHNICAL_FAILURE",
                    "termination_reason": term_reason,
                    "termination_class": term_class,
                    "placed_items": summary.get("placed_items"),
                    "planned_items": summary.get("planned_items"),
                    "error": first_error,
                })
                break

            job_rows.append({
                "job_id": job_id,
                "task_id": job["task_id"],
                "backend": job["backend"],
                "method": job["method"],
                "status": "COMPLETE" if summary.get("completed") else "STOPPED",
                "termination_reason": term_reason,
                "termination_class": term_class,
                "placed_items": summary.get("placed_items"),
                "planned_items": summary.get("planned_items"),
            })
        except BaseException as exc:
            first_error = {"job_id": job_id, "type": type(exc).__name__, "detail": str(exc)[:240]}
            job_rows.append({
                "job_id": job_id,
                "task_id": job["task_id"],
                "backend": job["backend"],
                "method": job["method"],
                "status": "CANCELLED" if isinstance(exc, KeyboardInterrupt) else "TECHNICAL_FAILURE",
                "error": first_error,
            })
            break

    dispatched_ids = {r["job_id"] for r in job_rows}
    for job in plan["jobs"]:
        if job["job_id"] not in dispatched_ids:
            job_rows.append({
                "job_id": job["job_id"],
                "task_id": job["task_id"],
                "backend": job["backend"],
                "method": job["method"],
                "status": "NOT_RUN",
            })

    ledger_final = read(plan["call_ledger_path"])
    driver_receipt = {
        "schema": "gp5_formal_order_driver_receipt_v1",
        "mode": "EXECUTE",
        "plan_digest": ctx["plan_digest"],
        "run_root": str(run_root),
        "preflight": "8/8 PASS",
        "preflight_configs": ctx["preflight_configs"],
        "dispatched_jobs": len(dispatched_ids),
        "first_error": first_error,
        "rows": job_rows,
        "final_ledger_counts": ledger_final["counts"],
        "status": "STOPPED_ON_ERROR" if first_error else "COMPLETE_8_OF_8_DISPATCHED",
    }
    write(run_root / "driver_receipt.json", driver_receipt)
    print(json.dumps(driver_receipt, indent=2, ensure_ascii=False))
    return 1 if first_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
