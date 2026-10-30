"""Read-only reconstruction from saved native answers; never calls a live model."""
from __future__ import annotations

from pathlib import Path

from .contracts import JevSelectError, digest
from .episode import run_episode
from .evaluation import aggregate
from .experiment import file_manifest, load_plan
from .ledger import Ledger, read
from .selector import JevSelector, LocalSelector


def replay_experiment(experiment_root, *, network_allowed=False, require_seal=True):
    if network_allowed is not False:
        raise JevSelectError("replay_network_forbidden")
    root = Path(experiment_root)
    if require_seal and file_manifest(root) != read(root / "delivery_manifest.json"):
        raise JevSelectError("experiment_changed")
    plan, config, tasks = load_plan(root / "plan")
    identity = {"version": "jev_experiment_v1", "mode": plan["mode"], "plan_digest": digest(file_manifest(root / "plan"))}
    if read(root / "manifest.json") != identity:
        raise JevSelectError("experiment_identity_changed")
    ledger = Ledger(root, plan["budget"], readonly=True, origin="jev" if plan["mode"] == "remote" else "test_double")
    # Offline fixtures can be independently regenerated; these are not real model answers.
    if plan["mode"] == "offline":
        from .testing import OfflineTransport
    jobs = plan["jobs"]; known = {j["job_id"] for j in jobs}
    if any(r["job_id"] not in known or r["origin"] != ("test_double" if plan["mode"] == "offline" else "jev") for r in ledger.data["attempts"]):
        raise JevSelectError("invalid_offline_attempt_origin")
    tasks_by_id = {t["task_id"]: t for t in tasks}
    rows = []; statuses = []; expected_request_files = set()
    for job in jobs:
        job_id, method = job["job_id"], job["method"]; cfg = dict(config, selector=method)
        selector = JevSelector(cfg, ledger, job_id) if method == "jev_choice" else LocalSelector(method)
        def compare_request(phase, event):
            if phase != "decision_ready": return
            did = event["decision_id"]
            req_path = root / "requests" / job_id / f"{did}.json"
            map_path = root / "mappings" / job_id / f"{did}.json"
            expected_request_files.update((req_path, map_path))
            if read(req_path) != event["context"]["request_body"] or read(map_path) != event["context"]:
                raise JevSelectError("saved_request_or_mapping_changed")
            for attempt in ledger.data["attempts"]:
                if attempt["job_id"] == job_id and attempt["decision_id"] == did:
                    saved = attempt["transport"]
                    if attempt["state"] == "RESERVED":
                        raise JevSelectError("incomplete_attempt")
                    if saved["error"] == "interrupted_after_reservation":
                        if saved["status"] != "UNKNOWN_IN_FLIGHT" or saved["raw_body_b64"] != "":
                            raise JevSelectError("invalid_interruption")
                    elif plan["mode"] == "offline" and saved != OfflineTransport(cfg, plan["offline_scenario"]).complete(event["context"]["request_body"]):
                        raise JevSelectError("offline_response_changed")
        saved = read(root / "episodes" / f"{job_id}.json")
        result = run_episode(tasks_by_id[job["task_id"]], selector, cfg, job_id=job_id, method=method,
                             hook=compare_request, expected_events=saved["events"])
        if result != saved or result["checkpoint"] != read(root / "checkpoints" / f"{job_id}.json"):
            raise JevSelectError("episode_or_checkpoint_changed")
        rows.append(result["summary"])
        statuses.append({**job, "status": "RECORDED", "termination_reason": result["summary"]["termination_reason"]})
    actual_request_files = set((root / "requests").rglob("*.json")) | set((root / "mappings").rglob("*.json"))
    if actual_request_files != expected_request_files:
        raise JevSelectError("request_registry_changed")
    if ledger.used != {r["attempt_id"] for r in ledger.data["attempts"]}:
        raise JevSelectError("orphan_attempts")
    summary = aggregate(rows, ledger.data["attempts"], mode=plan["mode"], pricing=plan["pricing"])
    if read(root / "metrics/rows.json") != rows or read(root / "metrics/summary.json") != summary or read(root / "audit/jobs.json") != statuses:
        raise JevSelectError("derived_metrics_changed")
    selected = sum(e.get("selection", {}).get("status") == "selected" and e.get("selection", {}).get("source") == "jev"
                   for job in jobs for e in read(root / "episodes" / f"{job['job_id']}.json")["events"] if e.get("selection"))
    real_status = "NOT_RUN" if summary["model_api_calls"] == 0 else "PASS" if selected else "FAIL_VALID_CHOICE"
    report = {"status": "PASS", "scope": "J1_OFFLINE_ENGINEERING" if plan["mode"] == "offline" else "J2_NATIVE_SMOKE",
              "verified_jobs": len(jobs), "source_orders": summary["source_orders"],
              "model_api_calls": summary["model_api_calls"], "unknown_send_attempts": summary["unknown_send_attempts"],
              "offline_attempts": summary["offline_attempts"], "groups": summary["groups"],
              "model_quality": summary["model_quality"], "valid_remote_choices": selected, "J2": real_status,
              "served_models": summary["served_models"], "usage_complete": summary["usage_complete"],
              "estimated_model_cost_usd": summary["estimated_model_cost_usd"]}
    if require_seal and (report != read(root / "replay_report.json") or report != read(root / "acceptance_report.json")):
        raise JevSelectError("acceptance_report_changed")
    return report
