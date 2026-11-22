"""Two-job top-load-switch batch launcher derived from the archived GP6 driver for GP6-F0 (G00-G01), kept outside src/ to preserve source_identity.

Contract:
- Default mode is --preflight-only (0 dispatches, 0 model calls, 0 monitor/LP calls,
  0 credential reads, 0 ledger byte mutations, no --run-root created).
- Real execution requires explicit --execute, FROZEN plan, signed APPROVED kernel bridge,
  signed APPROVED admission, separated pre-initialized empty/zero ledgers (outside --run-root),
  and a fresh non-existent --run-root.
- Supports reusing an existing manifest-matching historical_package_root on the target host,
  or temporarily exporting it from a pinned Git commit (default 2c97f59444f07e40b98da529e5256efc441207d4)
  for the duration of preflight and execution, while keeping validate_kernel_bridge's full checks intact.
- Dispatches strictly G00 -> G01 via run_jev_job with persistent checkpoint callback;
  halts batch immediately on UNKNOWN_SEND, PROVIDER_FAILURE, INVALID_RESPONSE, BUDGET_EXHAUSTED,
  TECHNICAL_FAILURE, CANCELLED, or uncaught exception, leaving remaining jobs NOT_RUN (no implicit retry).
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "semantic_pallet_planner" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from semantic_pallet_planner.jev_select import geometry_jev_execution as jev_exec
from semantic_pallet_planner.jev_select import geometry_jev_kernel_bridge as bridge_mod
from semantic_pallet_planner.jev_select import geometry_jev_protocol as jev_proto
from semantic_pallet_planner.jev_select import geometry_order_execution as order_exec
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as pkg_proto
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_native_protocol import policy_digest
from semantic_pallet_planner.jev_select.ledger import write
from semantic_pallet_planner.jev_select.transport import JevTransport

OUT_ROOT = REPO_ROOT / "semantic_pallet_planner" / "outputs"
DATA_ROOT = OUT_ROOT / "DATA_JEV_PACKAGING_LOAD_20261102_02"
GP5_MONITOR_DEFAULT = (
    OUT_ROOT / "GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01" / "monitor_snapshot.json"
)
DEFAULT_HISTORICAL_GIT_COMMIT = "2c97f59444f07e40b98da529e5256efc441207d4"
EXPECTED_JOB_IDS = ["G00", "G01"]
EXPECTED_PER_JOB_MAX_SENDS = 19
EXPECTED_SHARED_MAX_SENDS = 38
EXPECTED_CALL_LIMITS = {"assessment_entries": 76, "solver_calls": 4096}
ZERO_CALL_COUNTS = {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0}
CONTINUE_TERMINATION_CLASSES = {
    "COMPLETE",
    "NO_CANDIDATE",
    "PREDICTED_STATIC_INSTABILITY",
    "UNASSESSABLE",
}
HALT_TERMINATION_CLASSES = {
    "UNKNOWN_SEND",
    "PROVIDER_FAILURE",
    "INVALID_RESPONSE",
    "BUDGET_EXHAUSTED",
    "TECHNICAL_FAILURE",
    "CANCELLED",
}


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_bytes().decode("utf-8"))


def sha_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_initial_request_ledger_readonly(plan: dict) -> tuple[dict, str]:
    """Pure read-only check of initial empty request ledger (no lock files, no byte writes)."""
    req_path_str = plan.get("request_ledger_path")
    assert isinstance(req_path_str, str) and req_path_str, "MISSING_REQUEST_LEDGER_PATH"
    req_path = Path(req_path_str)
    if not req_path.is_absolute():
        req_path = REPO_ROOT / req_path
    assert req_path.is_file(), f"MISSING_REQUEST_LEDGER_FILE: {req_path}"
    raw = req_path.read_bytes()
    raw_sha = hashlib.sha256(raw).hexdigest()
    doc = json.loads(raw.decode("utf-8"))
    expected_keys = {"version", "plan_digest", "per_job_max_sends", "max_sends", "requests", "record_digest"}
    assert set(doc.keys()) == expected_keys, "REQUEST_LEDGER_SCHEMA_MISMATCH"
    assert doc["version"] == "geometry_jev_requests_v2", "REQUEST_LEDGER_VERSION_MISMATCH"
    assert doc["plan_digest"] == digest(plan), "REQUEST_LEDGER_PLAN_DIGEST_MISMATCH"
    assert doc["per_job_max_sends"] == plan["per_job_max_sends"] == EXPECTED_PER_JOB_MAX_SENDS, (
        "REQUEST_LEDGER_PER_JOB_LIMIT_MISMATCH"
    )
    assert doc["max_sends"] == plan["shared_max_sends"] == plan["model_calls_max"] == EXPECTED_SHARED_MAX_SENDS, (
        "REQUEST_LEDGER_SHARED_LIMIT_MISMATCH"
    )
    assert doc["requests"] == [], "NONEMPTY_INITIAL_REQUEST_LEDGER"
    body_without_digest = {k: v for k, v in doc.items() if k != "record_digest"}
    assert doc["record_digest"] == digest(body_without_digest), "REQUEST_LEDGER_DIGEST_MISMATCH"
    return doc, raw_sha


def check_initial_call_ledger_readonly(plan: dict) -> tuple[dict, str]:
    """Pure read-only check of initial zero call/LP ledger (no lock files, no byte writes)."""
    call_path_str = plan.get("call_ledger_path")
    assert isinstance(call_path_str, str) and call_path_str, "MISSING_CALL_LEDGER_PATH"
    call_path = Path(call_path_str)
    if not call_path.is_absolute():
        call_path = REPO_ROOT / call_path
    assert call_path.is_file(), f"MISSING_CALL_LEDGER_FILE: {call_path}"
    raw = call_path.read_bytes()
    raw_sha = hashlib.sha256(raw).hexdigest()
    doc = json.loads(raw.decode("utf-8"))
    expected_keys = {"version", "plan_digest", "evidence", "limits", "calls", "counts"}
    assert set(doc.keys()) == expected_keys, "CALL_LEDGER_SCHEMA_MISMATCH"
    assert doc["version"] == "geometry_call_ledger_v1", "CALL_LEDGER_VERSION_MISMATCH"
    assert doc["evidence"] == "REAL_KERNEL", "CALL_LEDGER_EVIDENCE_MISMATCH"
    assert doc["plan_digest"] == digest(plan), "CALL_LEDGER_PLAN_DIGEST_MISMATCH"
    assert doc["limits"] == EXPECTED_CALL_LIMITS, "CALL_LEDGER_LIMITS_MISMATCH"
    assert doc["calls"] == [], "NONEMPTY_INITIAL_CALL_LEDGER"
    assert doc["counts"] == ZERO_CALL_COUNTS, "NONZERO_INITIAL_CALL_LEDGER_COUNTS"
    return doc, raw_sha


def check_ledger_run_root_separation(plan: dict, run_root: Path | None) -> None:
    """Ensure pre-initialized ledgers live outside --run-root so fresh run_root never conflicts."""
    if run_root is None:
        return
    run_resolved = Path(run_root).resolve()
    for field in ("request_ledger_path", "call_ledger_path"):
        p = Path(plan[field])
        if not p.is_absolute():
            p = REPO_ROOT / p
        resolved = p.resolve()
        assert not resolved.is_relative_to(run_resolved), f"LEDGER_INSIDE_RUN_ROOT_CONFLICT: {field}"


def load_adapted_tasks(plan: dict, data_root: Path = DATA_ROOT) -> dict:
    adapted_by_task = {}
    for task_entry in plan["tasks"]:
        task_id = task_entry["task_id"]
        raw_path = Path(data_root) / "tasks" / f"{task_id}.json"
        assert raw_path.is_file(), f"MISSING_TASK_FILE: {raw_path}"
        adapted = pkg_proto.adapt_task(
            raw_path.read_bytes(),
            origin="EXPOSED_TRAIN",
            expected_sha256=task_entry["raw_sha256"],
        )
        assert adapted["identity"] == task_entry, f"TASK_IDENTITY_DRIFT: {task_id}"
        adapted_by_task[task_id] = adapted
    return adapted_by_task


@contextmanager
def historical_source_context(
    bridge: dict,
    *,
    historical_git_commit: str | None = DEFAULT_HISTORICAL_GIT_COMMIT,
    repo_root: Path = REPO_ROOT,
    run_root: Path | None = None,
):
    """Ensure bridge['historical_package_root'] is readable during preflight and execution.

    - If the path already exists on the target host, reuse it read-only (never delete on exit).
    - If it does not exist and historical_git_commit is provided, temporarily export
      semantic_pallet_planner/src/semantic_pallet_planner from that pinned Git commit
      into bridge['historical_package_root'], keep it readable throughout the context,
      and remove the temporary directory on exit.
    - Never bypasses validate_kernel_bridge's byte/path/symlink/manifest checks.
    """
    hist_str = bridge.get("historical_package_root") if isinstance(bridge, dict) else None
    if not isinstance(hist_str, str) or not hist_str:
        yield {"mode": "UNSET", "path": hist_str, "temporary": False}
        return

    target = Path(hist_str)
    if not target.is_absolute():
        target = (Path(repo_root) / target).resolve()
    else:
        target = target.resolve()

    if target.exists():
        yield {"mode": "EXISTING_HOST_DIR", "path": str(target), "temporary": False}
        return

    if not historical_git_commit:
        yield {"mode": "MISSING_NO_GIT_EXPORT", "path": str(target), "temporary": False}
        return

    current_pkg = (SRC_ROOT / "semantic_pallet_planner").resolve()
    assert target != current_pkg and not target.is_relative_to(SRC_ROOT.resolve()), (
        "HISTORICAL_EXPORT_TARGET_INSIDE_SRC_FORBIDDEN"
    )
    if run_root is not None:
        assert not target.is_relative_to(Path(run_root).resolve()), (
            "HISTORICAL_EXPORT_TARGET_INSIDE_RUN_ROOT_FORBIDDEN"
        )

    proc = subprocess.run(
        [
            "git",
            "archive",
            historical_git_commit,
            "semantic_pallet_planner/src/semantic_pallet_planner",
        ],
        cwd=str(repo_root),
        capture_output=True,
    )
    assert proc.returncode == 0, f"HISTORICAL_GIT_ARCHIVE_FAILED: {proc.stderr.decode('utf-8', 'replace')[:240]}"

    created_root = target
    target.mkdir(parents=True, exist_ok=False)
    try:
        prefix = "semantic_pallet_planner/src/semantic_pallet_planner/"
        with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as tf:
            for member in tf.getmembers():
                if not member.name.startswith(prefix):
                    continue
                rel = member.name[len(prefix):]
                if not rel or member.isdir():
                    continue
                assert member.isfile() and not member.issym() and not member.islnk(), (
                    f"HISTORICAL_ARCHIVE_UNSAFE_MEMBER: {member.name}"
                )
                dest = (target / rel).resolve()
                assert dest.is_relative_to(target), f"HISTORICAL_ARCHIVE_PATH_ESCAPE: {rel}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                extracted = tf.extractfile(member)
                assert extracted is not None
                dest.write_bytes(extracted.read())
        yield {
            "mode": "TEMPORARY_GIT_ARCHIVE_EXPORT",
            "git_commit": historical_git_commit,
            "path": str(target),
            "temporary": True,
        }
    finally:
        if created_root.exists():
            shutil.rmtree(created_root)


def run_preflight(
    plan_path: Path,
    snap_path: Path,
    bridge_path: Path | None,
    admission_path: Path | None,
    *,
    run_root: Path | None = None,
    data_root: Path = DATA_ROOT,
) -> dict:
    """Run all GP6-F0 preflight gates in pure read-only mode (0 dispatches, 0 ledger writes)."""
    assert plan_path is not None and Path(plan_path).is_file(), "MISSING_PLAN_FILE"
    assert snap_path is not None and Path(snap_path).is_file(), "MISSING_MONITOR_SNAPSHOT_FILE"

    plan = read_json(plan_path)
    jev_proto.validate_jev_plan(plan)
    assert plan["version"] == "geometry_jev_plan_v2" and plan["packaging_top_load_limit_enabled"] is False, "SWITCH_PLAN_REQUIRED"
    assert plan["status"] == "FROZEN", "PLAN_NOT_FROZEN"
    assert plan["scope"] == jev_proto.GP6_ORDER, "PLAN_SCOPE_MISMATCH"
    assert [j["job_id"] for j in plan["jobs"]] == EXPECTED_JOB_IDS, "PLAN_JOBS_MISMATCH"
    assert plan["per_job_max_sends"] == EXPECTED_PER_JOB_MAX_SENDS, "PLAN_PER_JOB_BUDGET_MISMATCH"
    assert plan["shared_max_sends"] == plan["model_calls_max"] == EXPECTED_SHARED_MAX_SENDS, (
        "PLAN_SHARED_BUDGET_MISMATCH"
    )
    assert plan["assessment_limit"] == EXPECTED_CALL_LIMITS["assessment_entries"], "PLAN_ASSESSMENT_LIMIT_MISMATCH"
    assert plan["solver_limit"] == EXPECTED_CALL_LIMITS["solver_calls"], "PLAN_SOLVER_LIMIT_MISMATCH"
    assert plan["source_identity"] == digest(source_manifest()), "SOURCE_IDENTITY_DRIFT"
    assert plan["publication_policy_digest"] == policy_digest(), "POLICY_DIGEST_DRIFT"
    plan_digest = digest(plan)

    check_ledger_run_root_separation(plan, run_root)

    snap = read_json(snap_path)
    order_exec.validate_monitor_snapshot(snap)

    adapted_by_task = load_adapted_tasks(plan, data_root=data_root)
    req_ledger_before, req_sha_before = check_initial_request_ledger_readonly(plan)
    call_ledger_before, call_sha_before = check_initial_call_ledger_readonly(plan)

    assert bridge_path is not None and Path(bridge_path).is_file(), "MISSING_SIGNED_KERNEL_BRIDGE"
    assert admission_path is not None and Path(admission_path).is_file(), "MISSING_SIGNED_ADMISSION"
    bridge = read_json(bridge_path)
    admission = read_json(admission_path)

    real_authorized = jev_proto.validate_jev_admission(plan, snap, admission, bridge)
    assert real_authorized is True, "REAL_TRANSPORT_NOT_AUTHORIZED"

    preflight_configs = {}
    for job in plan["jobs"]:
        cfg = jev_exec.load_jev_config(
            plan,
            job["job_id"],
            monitor_snapshot=snap,
            admission=admission,
            kernel_receipt=bridge,
        )
        assert cfg["monitor_evidence"] == "REAL_KERNEL", f"MONITOR_EVIDENCE_MISMATCH: {job['job_id']}"
        assert cfg["transport_evidence"] == "REAL_JEV", f"TRANSPORT_EVIDENCE_MISMATCH: {job['job_id']}"
        assert cfg["candidate_backend"] == job["backend"], f"BACKEND_MISMATCH: {job['job_id']}"
        assert cfg["selector"] == job["method"] == jev_proto.GP6_METHOD, f"SELECTOR_MISMATCH: {job['job_id']}"
        assert cfg["order_task_identity"]["task_id"] == job["task_id"], f"TASK_MISMATCH: {job['job_id']}"
        preflight_configs[job["job_id"]] = {
            "status": "PASS",
            "task_id": job["task_id"],
            "backend": job["backend"],
            "method": job["method"],
            "config_digest": digest(cfg),
            "config": cfg,
        }

    # Verify both ledgers remained byte-for-byte untouched by preflight
    _, req_sha_after = check_initial_request_ledger_readonly(plan)
    _, call_sha_after = check_initial_call_ledger_readonly(plan)
    assert req_sha_after == req_sha_before, "PREFLIGHT_MUTATED_REQUEST_LEDGER"
    assert call_sha_after == call_sha_before, "PREFLIGHT_MUTATED_CALL_LEDGER"

    return {
        "plan": plan,
        "plan_digest": plan_digest,
        "snap": snap,
        "bridge": bridge,
        "admission": admission,
        "adapted_by_task": adapted_by_task,
        "preflight_configs": preflight_configs,
        "request_ledger_sha256": req_sha_before,
        "call_ledger_sha256": call_sha_before,
        "call_ledger_counts_before": call_ledger_before["counts"],
        "request_ledger_count_before": len(req_ledger_before["requests"]),
    }


def _resolve_repo_path(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else (REPO_ROOT / p)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="GP6-F0 formal 2-job launcher (G00-G01). Default mode is --preflight-only (0 dispatches)."
    )
    parser.add_argument("--plan", type=Path, required=True, help="FROZEN geometry_jev_plan_v2 JSON")
    parser.add_argument("--monitor-snapshot", type=Path, default=GP5_MONITOR_DEFAULT, help="GP5 monitor_snapshot.json")
    parser.add_argument("--kernel-bridge", type=Path, default=None, help="Signed APPROVED geometry_jev_kernel_bridge_v1 JSON")
    parser.add_argument("--admission", type=Path, default=None, help="Signed APPROVED geometry_jev_admission_v1 JSON")
    parser.add_argument("--api-key-file", type=Path, default=None, help="Optional API key file (used only under --execute)")
    parser.add_argument("--historical-git-commit", type=str, default=DEFAULT_HISTORICAL_GIT_COMMIT,
                        help="Pinned Git commit for temporary historical source export if host dir does not exist")
    parser.add_argument("--no-git-historical-export", action="store_true",
                        help="Disable temporary Git export; require bridge['historical_package_root'] to already exist")
    parser.add_argument("--run-root", type=Path, default=None, help="Fresh non-existent output directory (required for --execute)")
    parser.add_argument("--execute", action="store_true", help="Dispatch G00-G01 sequentially after 2/2 preflight PASS")
    args = parser.parse_args(argv)

    bridge_preview = read_json(args.kernel_bridge) if (args.kernel_bridge and args.kernel_bridge.is_file()) else {}
    git_commit = None if args.no_git_historical_export else args.historical_git_commit

    with historical_source_context(
        bridge_preview,
        historical_git_commit=git_commit,
        repo_root=REPO_ROOT,
        run_root=args.run_root,
    ) as hist_info:
        ctx = run_preflight(
            args.plan,
            args.monitor_snapshot,
            args.kernel_bridge,
            args.admission,
            run_root=args.run_root,
        )

        if not args.execute:
            summary = {
                "mode": "PREFLIGHT_ONLY",
                "driver_sha256": sha_file(Path(__file__)),
                "plan_digest": ctx["plan_digest"],
                "preflight": "2/2 PASS",
                "historical_source": hist_info,
                "preflight_configs": {
                    jid: {k: v for k, v in info.items() if k != "config"}
                    for jid, info in ctx["preflight_configs"].items()
                },
                "request_ledger_sha256_unchanged": ctx["request_ledger_sha256"],
                "call_ledger_sha256_unchanged": ctx["call_ledger_sha256"],
                "request_ledger_count": ctx["request_ledger_count_before"],
                "call_ledger_counts": ctx["call_ledger_counts_before"],
                "dispatched_jobs": 0,
            }
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return 0

        assert args.run_root is not None, "RUN_ROOT_REQUIRED_FOR_EXECUTE"
        run_root = Path(args.run_root)
        check_ledger_run_root_separation(ctx["plan"], run_root)
        run_root.parent.mkdir(parents=True, exist_ok=True)
        try:
            run_root.mkdir(parents=False, exist_ok=False)
        except FileExistsError as exc:
            raise AssertionError(f"NO_OVERWRITE_EXISTING_RUN_ROOT: {run_root}") from exc

        plan = ctx["plan"]
        req_ledger_file = _resolve_repo_path(plan["request_ledger_path"])
        ledger = jev_exec.GeometryJevRequestLedger(
            req_ledger_file.parent,
            plan_digest=ctx["plan_digest"],
            per_job_max_sends=plan["per_job_max_sends"],
            shared_max_sends=plan["shared_max_sends"],
            allow_real_transport=True,
            runtime_version=plan["runtime_version"],
        )

        # Bind-check all 2 job configs against the live request ledger before any dispatch
        transports = {}
        for job in plan["jobs"]:
            jid = job["job_id"]
            cfg = ctx["preflight_configs"][jid]["config"]
            transport = JevTransport(cfg, api_key_file=args.api_key_file)
            jev_exec.validate_jev_request_ledger_binding(
                plan, cfg, ledger, transport, real_authorized=True
            )
            transports[jid] = transport

        job_rows = []
        first_error = None
        for job in plan["jobs"]:
            job_id = job["job_id"]
            adapted = ctx["adapted_by_task"][job["task_id"]]
            ckpt_path = run_root / "jobs" / job_id / "checkpoint.json"

            def _make_checkpoint_cb(target_path: Path):
                def _on_checkpoint(cp):
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    write(target_path, cp)
                return _on_checkpoint

            try:
                ep = jev_exec.run_jev_job(
                    plan,
                    job_id,
                    adapted,
                    monitor_snapshot=ctx["snap"],
                    admission=ctx["admission"],
                    root=run_root,
                    transport=transports[job_id],
                    ledger=ledger,
                    kernel_receipt=ctx["bridge"],
                    on_checkpoint=_make_checkpoint_cb(ckpt_path),
                )
                summary = ep.get("summary") if isinstance(ep, dict) else None
                if not isinstance(summary, dict) or not summary:
                    first_error = {
                        "job_id": job_id,
                        "type": "EMPTY_SUMMARY_TECHNICAL_FAILURE",
                        "detail": "run_jev_job returned missing or empty summary",
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
                if term_class in HALT_TERMINATION_CLASSES or term_class not in CONTINUE_TERMINATION_CLASSES:
                    row_status = (
                        "CANCELLED"
                        if term_class == "CANCELLED"
                        else ("TECHNICAL_FAILURE" if term_class == "TECHNICAL_FAILURE" else "STOPPED")
                    )
                    first_error = {
                        "job_id": job_id,
                        "type": term_class or "UNKNOWN_TERMINATION_CLASS",
                        "detail": term_reason or str(term_class),
                    }
                    job_rows.append({
                        "job_id": job_id,
                        "task_id": job["task_id"],
                        "backend": job["backend"],
                        "method": job["method"],
                        "status": row_status,
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
                row_status = "CANCELLED" if isinstance(exc, KeyboardInterrupt) else "TECHNICAL_FAILURE"
                first_error = {
                    "job_id": job_id,
                    "type": type(exc).__name__,
                    "detail": str(exc)[:240],
                }
                job_rows.append({
                    "job_id": job_id,
                    "task_id": job["task_id"],
                    "backend": job["backend"],
                    "method": job["method"],
                    "status": row_status,
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

        receipt = {
            "version": "gp6_f0_driver_receipt_v1",
            "driver_sha256": sha_file(Path(__file__)),
            "plan_digest": ctx["plan_digest"],
            "historical_source": hist_info,
            "dispatched_jobs": len(dispatched_ids),
            "planned_jobs": len(plan["jobs"]),
            "status": (
                "COMPLETE_2_OF_2_DISPATCHED"
                if (first_error is None and len(dispatched_ids) == 2)
                else "HALTED_ON_ERROR"
            ),
            "no_implicit_retry": True,
            "first_error": first_error,
            "rows": job_rows,
        }
        write(run_root / "driver_receipt.json", receipt)
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
        return 0 if first_error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
