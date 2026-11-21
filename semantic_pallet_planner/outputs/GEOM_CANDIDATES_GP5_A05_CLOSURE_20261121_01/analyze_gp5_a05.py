#!/usr/bin/env python3
"""Read-only GP5 / A05 formal 8-job paired analysis and closure generator.

Uses Python standard library only. Never modifies original experimental artifacts,
frozen plans, ledgers, or production source code, and never runs physics, LP, or models.
"""

from __future__ import annotations

import csv
import hashlib
import json
import pathlib
from typing import Any


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT_DIR = pathlib.Path(__file__).resolve().parent

RUN_DIR = REPO_ROOT / "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_FORMAL_ORDER_RUN_20261120_01"
PREP_DIR = REPO_ROOT / "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_FORMAL_ORDER_PREP_20261120_01"
CANCELLED_DIR = REPO_ROOT / "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_FORMAL_ORDER_CANCELLED_DUPLICATE_20261120_01"
APPROVED_QA_DIR = REPO_ROOT / "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_FORMAL_ORDER_APPROVED_QA_20261120_01"

JOB_IDS = ["J00", "J01", "J02", "J03", "J04", "J05", "J06", "J07"]
PAIRS = [
    ("P1_base_local_geometry", "J00", "J02"),
    ("P2_base_local_first", "J01", "J03"),
    ("P3_tight_local_geometry", "J04", "J06"),
    ("P4_tight_local_first", "J05", "J07"),
]


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: pathlib.Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def timings_map(timings_list: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in timings_list:
        out[str(item["segment"])] = float(item["seconds"])
    return out


def main() -> None:
    # Load core frozen & run artifacts
    prep_plan = load_json(PREP_DIR / "order_plan_FROZEN.json")
    prep_matrix = load_json(PREP_DIR / "data_and_matrix_summary.json")
    prep_ledger = load_json(PREP_DIR / "shared_call_ledger.json")
    prep_monitor = load_json(PREP_DIR / "monitor_snapshot.json")

    run_plan = load_json(RUN_DIR / "plan.json")
    driver_receipt = load_json(RUN_DIR / "driver_receipt.json")
    run_doc = load_json(RUN_DIR / "run.json")
    final_ledger = load_json(RUN_DIR / "shared_call_ledger_FINAL.json")
    transfer_manifest = load_json(RUN_DIR / "transfer_manifest.json")

    approved_handoff = load_json(APPROVED_QA_DIR / "handoff.json")
    approved_admission = load_json(APPROVED_QA_DIR / "order_admission.json")

    cancelled_receipt = load_json(CANCELLED_DIR / "execution_receipt.json")
    cancelled_denom = load_json(CANCELLED_DIR / "run_denominator.json")
    cancelled_ledger = load_json(CANCELLED_DIR / "isolated_shared_call_ledger_FINAL.json")

    # 1. Ledger breakdown by job_id
    ledger_by_job: dict[str, dict[str, int]] = {
        j: {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0, "other": 0}
        for j in JOB_IDS
    }
    ledger_non_done = 0
    for entry in final_ledger.get("calls", []):
        jid = entry["job_id"]
        kind = entry["kind"]
        if entry.get("state") != "DONE":
            ledger_non_done += 1
        if kind in ledger_by_job[jid]:
            ledger_by_job[jid][kind] += 1
        else:
            ledger_by_job[jid]["other"] += 1

    # Map run.json rows and driver_receipt rows
    run_rows_by_job = {r["job_id"]: r for r in run_doc["rows"]}
    driver_rows_by_job = {r["job_id"]: r for r in driver_receipt["rows"]}
    plan_jobs_by_id = {j["job_id"]: j for j in run_plan["jobs"]}
    task_meta_by_id = {t["task_id"]: t for t in prep_matrix["tasks"]}

    checks: list[dict[str, Any]] = []

    def add_check(name: str, passed: bool, detail: Any) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    # Plan & ledger consistency checks
    add_check(
        "prep_and_run_plan_identical",
        prep_plan == run_plan and sha256_file(PREP_DIR / "order_plan_FROZEN.json") == sha256_file(RUN_DIR / "plan.json"),
        {
            "prep_plan_sha256": sha256_file(PREP_DIR / "order_plan_FROZEN.json"),
            "run_plan_sha256": sha256_file(RUN_DIR / "plan.json"),
        },
    )
    add_check(
        "no_event_limit_in_frozen_plan",
        "event_limit" in run_plan and run_plan["event_limit"] is None and run_plan.get("extra_seeds") is False,
        {
            "plan_has_event_limit_field": "event_limit" in run_plan,
            "plan_event_limit": run_plan.get("event_limit"),
            "extra_seeds": run_plan.get("extra_seeds"),
        },
    )
    # Verify restored production source tree matches frozen source_identity
    pkg_root = REPO_ROOT / "semantic_pallet_planner/src/semantic_pallet_planner"
    prep_source_manifest = load_json(PREP_DIR / "source_manifest.json")
    cur_source_files = {
        p.relative_to(pkg_root).as_posix(): sha256_file(p)
        for p in sorted(pkg_root.rglob("*"))
        if p.is_file()
        and p.suffix in (".py", ".json")
        and not {"tests", "__pycache__"}.intersection(p.relative_to(pkg_root).parts)
    }
    cur_source_identity = hashlib.sha256(
        json.dumps(cur_source_files, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    add_check(
        "restored_source_identity_matches_frozen_plan",
        cur_source_files == prep_source_manifest["files"]
        and cur_source_identity == run_plan["source_identity"] == prep_source_manifest["source_identity"],
        {
            "source_files_count": len(cur_source_files),
            "recomputed_source_identity": cur_source_identity,
            "frozen_source_identity": run_plan["source_identity"],
            "v1_schema_sha256": cur_source_files.get("jev_select/schemas/geometry_phase_snapshot_credential_v1.schema.json"),
            "v2_schema_sha256": cur_source_files.get("jev_select/schemas/geometry_phase_snapshot_credential_v2.schema.json"),
        },
    )
    add_check(
        "prep_zero_ledger_preserved",
        prep_ledger["counts"] == {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0}
        and len(prep_ledger["calls"]) == 0
        and sha256_file(PREP_DIR / "shared_call_ledger.json") == transfer_manifest["main_ledger_sha256"],
        {
            "prep_ledger_counts": prep_ledger["counts"],
            "prep_ledger_sha256": sha256_file(PREP_DIR / "shared_call_ledger.json"),
            "transfer_manifest_main_ledger_sha256": transfer_manifest["main_ledger_sha256"],
        },
    )
    add_check(
        "final_ledger_totals_match_calls_and_receipt",
        final_ledger["counts"] == {"assessment_entries": 49, "solver_calls": 1588, "test_double_assessments": 0}
        and driver_receipt["final_ledger_counts"] == final_ledger["counts"]
        and sum(v["assessment_entries"] for v in ledger_by_job.values()) == 49
        and sum(v["solver_calls"] for v in ledger_by_job.values()) == 1588
        and sum(v["other"] for v in ledger_by_job.values()) == 0
        and ledger_non_done == 0,
        {
            "final_ledger_counts": final_ledger["counts"],
            "driver_receipt_counts": driver_receipt["final_ledger_counts"],
            "ledger_calls_len": len(final_ledger["calls"]),
            "ledger_non_done": ledger_non_done,
        },
    )
    add_check(
        "driver_receipt_8_of_8_no_first_error",
        driver_receipt["status"] == "COMPLETE_8_OF_8_DISPATCHED"
        and driver_receipt["dispatched_jobs"] == 8
        and driver_receipt["preflight"] == "8/8 PASS"
        and driver_receipt["first_error"] is None,
        {
            "status": driver_receipt["status"],
            "dispatched_jobs": driver_receipt["dispatched_jobs"],
            "preflight": driver_receipt["preflight"],
            "first_error": driver_receipt["first_error"],
        },
    )

    # 2. Extract per-job results & stop diagnostics
    job_rows: list[dict[str, Any]] = []
    stop_diagnostics: list[dict[str, Any]] = []

    sum_metrics_assessments = 0
    sum_metrics_solvers = 0
    sum_model_calls = 0

    for jid in JOB_IDS:
        jd = RUN_DIR / "jobs" / jid
        metrics = load_json(jd / "metrics.json")
        record = load_json(jd / "record.json")
        accounting = load_json(jd / "accounting.json")
        checkpoint = load_json(jd / "checkpoint.json")
        task_id_doc = load_json(jd / "task_identity.json")
        cfg = load_json(jd / "config.json")

        tmap = timings_map(metrics["timings"])
        events = record["checkpoint"]["events"]
        last_ev = events[-1]
        monitor_events = [e for e in events if e.get("monitor") is not None]
        monitor_statuses = {}
        for e in monitor_events:
            st = e["monitor"].get("status")
            monitor_statuses[st] = monitor_statuses.get(st, 0) + 1

        # Cross-check per job
        plan_entry = plan_jobs_by_id[jid]
        run_row = run_rows_by_job[jid]
        drv_row = driver_rows_by_job[jid]
        tmeta = task_meta_by_id[metrics["task_id"]]

        job_consistency = (
            plan_entry["backend"] == metrics["candidate_backend"] == drv_row["backend"]
            and plan_entry["method"] == metrics["method"] == drv_row["method"]
            and plan_entry["task_id"] == metrics["task_id"] == drv_row["task_id"] == task_id_doc["task_id"]
            and run_row["metrics"] == metrics
            and metrics["counts"]["assessment_entries"] == ledger_by_job[jid]["assessment_entries"]
            and metrics["counts"]["solver_calls"] == ledger_by_job[jid]["solver_calls"]
            and metrics["counts"]["test_double_assessments"] == 0
            and metrics["placed_items"] == drv_row["placed_items"] == accounting["cumulative"]["commit_successes"]
            and metrics["planned_items"] == drv_row["planned_items"] == 19
            and metrics["termination_reason"] == drv_row["termination_reason"] == last_ev["reason"]
            and metrics["termination_class"] == drv_row["termination_class"]
            and "event_limit" not in cfg
            and checkpoint["phase"] == "TERMINATED"
            and checkpoint["reason"] == "STOP_NO_PHYSICAL_CANDIDATE"
        )
        add_check(
            f"job_{jid}_internal_and_cross_file_consistency",
            job_consistency,
            {
                "placed_items": metrics["placed_items"],
                "ledger_assessments": ledger_by_job[jid]["assessment_entries"],
                "ledger_solvers": ledger_by_job[jid]["solver_calls"],
                "checkpoint_phase": checkpoint["phase"],
                "config_has_event_limit_field": "event_limit" in cfg,
                "monitor_statuses": monitor_statuses,
            },
        )

        sum_metrics_assessments += metrics["counts"]["assessment_entries"]
        sum_metrics_solvers += metrics["counts"]["solver_calls"]
        sum_model_calls += metrics["cost"]["model_calls"]

        pred_instab = metrics["predicted_instability_progress"]
        pred_instab_display = "NA_NO_PREDICTED_INSTABILITY" if pred_instab is None else pred_instab

        row = {
            "job_id": jid,
            "task_id": metrics["task_id"],
            "source_order_id": tmeta["source_order_id"],
            "source_group_id": tmeta["source_group_id"],
            "task_origin": task_id_doc["origin"],
            "feasibility_status": tmeta["feasibility_status"],
            "backend": metrics["candidate_backend"],
            "method": metrics["method"],
            "driver_status": drv_row["status"],
            "completed": metrics["completed"],
            "planned_items": metrics["planned_items"],
            "arrived_items": metrics["arrived_items"],
            "placed_items": metrics["placed_items"],
            "placed_item_ratio": metrics["placed_item_ratio"],
            "planned_volume_mm3": metrics["planned_volume_mm3"],
            "placed_volume_mm3": metrics["placed_volume_mm3"],
            "placed_volume_ratio": metrics["placed_volume_ratio"],
            "planned_mass_kg": metrics["planned_mass_kg"],
            "placed_mass_kg": metrics["placed_mass_kg"],
            "placed_mass_ratio": metrics["placed_mass_ratio"],
            "fixed_container_utilization": metrics["fixed_container_utilization"],
            "max_height_mm": metrics["max_height_mm"],
            "envelope_status": metrics["envelope_status"],
            "envelope_utilization": metrics["envelope_utilization"],
            "termination_class": metrics["termination_class"],
            "termination_reason": metrics["termination_reason"],
            "global_infeasibility_proven": metrics["global_infeasibility_proven"],
            "prefix_truncated": False,
            "event_limit": "PLAN_NULL_CONFIG_ABSENT",
            "monitor_evidence": metrics["monitor_evidence"],
            "monitor_statuses": monitor_statuses,
            "predicted_instability_progress": pred_instab_display,
            "assessment_entries": metrics["counts"]["assessment_entries"],
            "solver_calls": metrics["counts"]["solver_calls"],
            "test_double_assessments": metrics["counts"]["test_double_assessments"],
            "model_calls": metrics["cost"]["model_calls"],
            "service_cost": metrics["cost"]["service_cost"],
            "local_compute_cost": metrics["cost"]["local_compute_cost"],
            "selector_calls": accounting["cumulative"]["selector_calls"],
            "singleton_executions": accounting["cumulative"]["singleton_executions"],
            "monitor_reuses": accounting["cumulative"]["monitor_reuses"],
            "physical_generation_s": tmap.get("physical_generation_s"),
            "selection_s": tmap.get("selection_s"),
            "facts_context_s": tmap.get("facts_context_s"),
            "physical_commit_s": tmap.get("physical_commit_s"),
            "monitor_result_duration_s": tmap.get("monitor_result_duration_s"),
            "checkpoint_io_s": tmap.get("checkpoint_io_s"),
            "decision_wall_s": tmap.get("decision_wall_s"),
            "invocation_wall_s": tmap.get("invocation_wall_s"),
        }
        job_rows.append(row)

        # Last decision diagnostics
        bundle = last_ev["bundle"]
        geom_sha = last_ev["geometry_ref"]["sha256"]
        geom_blob_path = jd / "blobs" / geom_sha
        geom_blob = load_json(geom_blob_path)
        gen_audit = geom_blob["audit"]["generation"]

        pending_summary = [
            {
                "item_id": p["item"]["item_id"],
                "dimensions_mm": p["item"]["dimensions_mm"],
                "mass_kg": p["item"]["mass_kg"],
                "stackable": p["item"]["stackable"],
                "top_load_limit_kg_synthetic": p["item"]["top_load_limit_kg_synthetic"],
            }
            for p in last_ev["before"]["pending_items"]
        ]

        # Aggregate rejection counts across pending items
        agg_rej: dict[str, int] = {}
        total_attempts = 0
        for gc in bundle["generation_counts"]:
            total_attempts += int(gc["enumeration_attempts"])
            for rk, rv in gc["rejections"].items():
                agg_rej[rk] = agg_rej.get(rk, 0) + int(rv)

        diag_entry: dict[str, Any] = {
            "job_id": jid,
            "task_id": metrics["task_id"],
            "backend": metrics["candidate_backend"],
            "method": metrics["method"],
            "decision_id": last_ev["decision_id"],
            "event_type": last_ev["event"],
            "termination_reason": last_ev["reason"],
            "placed_items_before_stop": len(last_ev["before"]["placed_items"]),
            "arrived_items_at_stop": last_ev["before"]["arrival_count"],
            "pending_buffer_items": pending_summary,
            "physical_candidates_count": len(bundle["physical_candidates"]),
            "selectable_candidates_count": len(bundle["selectable_candidates"]),
            "total_enumeration_or_proposal_attempts": total_attempts,
            "aggregated_rejections": agg_rej,
            "per_item_generation_counts": bundle["generation_counts"],
            "geometry_blob_relpath": rel(geom_blob_path),
            "geometry_blob_sha256": geom_sha,
            "monitor_called_at_stop_step": last_ev.get("monitor") is not None,
            "error_at_stop_step": last_ev.get("error"),
        }

        if metrics["candidate_backend"] == "ems_surface_hybrid_v1":
            a = gen_audit["audit"]
            si = a["space_index"]
            diag_entry["backend_specific_audit"] = {
                "generation_status": gen_audit["status"],
                "generation_error": gen_audit["error"],
                "space_index_status": si["status"],
                "space_index_error": si["error"],
                "active_spaces_count": len(si.get("spaces", [])),
                "budget_used": si["budget_usage"]["used"],
                "budget_limits": si["budget_usage"]["limits"],
                "wall_clock_cutoff": si["budget_usage"]["wall_clock_cutoff"],
                "per_item_enumeration_complete": [
                    {
                        "item_id": it["item_id"],
                        "enumeration_complete": it["enumeration_complete"],
                        "raw_valid_count": len(it.get("raw_valid_candidates", [])),
                        "final_candidates": it["final_candidates"],
                        "rejections": it.get("rejection_counts", it.get("rejections", {})),
                    }
                    for it in a["items"]
                ],
            }
        else:
            diag_entry["backend_specific_audit"] = {
                "backend_version": gen_audit["items"][0]["version"] if gen_audit.get("items") else "UNKNOWN",
                "sampling_grid_mm": gen_audit["items"][0].get("sampling_grid_mm") if gen_audit.get("items") else "UNKNOWN",
                "any_topk_truncated": any(it.get("topk_truncated") for it in gen_audit.get("items", [])),
                "per_item_e2_counts": [
                    {
                        "public_enumeration_attempts": it["public_enumeration_attempts"],
                        "baseline_count": it["baseline_count"],
                        "public_enriched_physical_count": it["public_enriched_physical_count"],
                        "returned_count": it["returned_count"],
                        "topk_truncated": it["topk_truncated"],
                        "rejections": it.get("rejection_counts", it.get("rejections", {})),
                    }
                    for it in gen_audit.get("items", [])
                ],
            }

        stop_diagnostics.append(diag_entry)

    add_check(
        "sum_of_job_metrics_matches_ledger",
        sum_metrics_assessments == 49 and sum_metrics_solvers == 1588 and sum_model_calls == 0,
        {
            "sum_metrics_assessments": sum_metrics_assessments,
            "sum_metrics_solvers": sum_metrics_solvers,
            "sum_model_calls": sum_model_calls,
        },
    )

    # 3. Paired comparisons (EMS - E2)
    rows_by_job = {r["job_id"]: r for r in job_rows}
    paired_rows: list[dict[str, Any]] = []
    for pair_id, e2_jid, ems_jid in PAIRS:
        e2 = rows_by_job[e2_jid]
        ems = rows_by_job[ems_jid]
        assert e2["task_id"] == ems["task_id"] and e2["method"] == ems["method"]
        assert e2["backend"] == "e2_original_v1" and ems["backend"] == "ems_surface_hybrid_v1"

        paired_rows.append(
            {
                "pair_id": pair_id,
                "task_id": e2["task_id"],
                "source_group_id": e2["source_group_id"],
                "method": e2["method"],
                "e2_job_id": e2_jid,
                "ems_job_id": ems_jid,
                "e2_placed_items": e2["placed_items"],
                "ems_placed_items": ems["placed_items"],
                "delta_placed_items_ems_minus_e2": ems["placed_items"] - e2["placed_items"],
                "e2_placed_item_ratio": e2["placed_item_ratio"],
                "ems_placed_item_ratio": ems["placed_item_ratio"],
                "delta_placed_item_ratio_ems_minus_e2": ems["placed_item_ratio"] - e2["placed_item_ratio"],
                "e2_placed_volume_ratio": e2["placed_volume_ratio"],
                "ems_placed_volume_ratio": ems["placed_volume_ratio"],
                "delta_placed_volume_ratio_ems_minus_e2": ems["placed_volume_ratio"] - e2["placed_volume_ratio"],
                "e2_placed_mass_ratio": e2["placed_mass_ratio"],
                "ems_placed_mass_ratio": ems["placed_mass_ratio"],
                "delta_placed_mass_ratio_ems_minus_e2": ems["placed_mass_ratio"] - e2["placed_mass_ratio"],
                "e2_fixed_container_utilization": e2["fixed_container_utilization"],
                "ems_fixed_container_utilization": ems["fixed_container_utilization"],
                "delta_fixed_container_utilization_ems_minus_e2": ems["fixed_container_utilization"]
                - e2["fixed_container_utilization"],
                "e2_max_height_mm": e2["max_height_mm"],
                "ems_max_height_mm": ems["max_height_mm"],
                "delta_max_height_mm_ems_minus_e2": ems["max_height_mm"] - e2["max_height_mm"],
                "e2_envelope_utilization": e2["envelope_utilization"],
                "ems_envelope_utilization": ems["envelope_utilization"],
                "delta_envelope_utilization_ems_minus_e2": ems["envelope_utilization"] - e2["envelope_utilization"],
                "e2_assessment_entries": e2["assessment_entries"],
                "ems_assessment_entries": ems["assessment_entries"],
                "delta_assessment_entries_ems_minus_e2": ems["assessment_entries"] - e2["assessment_entries"],
                "e2_solver_calls": e2["solver_calls"],
                "ems_solver_calls": ems["solver_calls"],
                "delta_solver_calls_ems_minus_e2": ems["solver_calls"] - e2["solver_calls"],
                "e2_physical_generation_s": e2["physical_generation_s"],
                "ems_physical_generation_s": ems["physical_generation_s"],
                "delta_physical_generation_s_ems_minus_e2": ems["physical_generation_s"] - e2["physical_generation_s"],
                "e2_decision_wall_s": e2["decision_wall_s"],
                "ems_decision_wall_s": ems["decision_wall_s"],
                "delta_decision_wall_s_ems_minus_e2": ems["decision_wall_s"] - e2["decision_wall_s"],
                "e2_invocation_wall_s": e2["invocation_wall_s"],
                "ems_invocation_wall_s": ems["invocation_wall_s"],
                "delta_invocation_wall_s_ems_minus_e2": ems["invocation_wall_s"] - e2["invocation_wall_s"],
                "e2_termination_reason": e2["termination_reason"],
                "ems_termination_reason": ems["termination_reason"],
                "interpretation_note": (
                    "Both tasks belong to exposed training source group SG_901bbb22f834c63f "
                    "(order 00113144 capacity variants); local_geometry/local_first results do not represent Jev."
                ),
            }
        )

    # 4. Cancelled duplicate record (isolated from formal 8-job denominator)
    cancelled_record = {
        "schema": "gp5_a05_cancelled_duplicate_summary_v1",
        "excluded_from_formal_8_job_denominator": True,
        "source_dir": rel(CANCELLED_DIR),
        "status": cancelled_receipt["status"],
        "exit_code": cancelled_receipt["exit_code"],
        "head": cancelled_receipt["head"],
        "plan_digest": cancelled_receipt["plan_digest"],
        "launch_count": cancelled_receipt["launch_count"],
        "dispatched_jobs": cancelled_receipt["dispatched_jobs"],
        "counts": cancelled_receipt["counts"],
        "model_calls": cancelled_receipt["model_calls"],
        "isolated_ledger_counts": cancelled_ledger["counts"],
        "main_ledger_unchanged": cancelled_receipt["main_ledger_unchanged"],
        "main_ledger_sha256": cancelled_receipt["main_ledger_sha256"],
        "cancelled_pid": cancelled_receipt["cancelled_pid"],
        "existing_active_batch_pid": cancelled_receipt["existing_active_batch_pid"],
        "interruption_location": cancelled_receipt["interruption_location"],
        "denominator_scope": cancelled_denom["scope"],
        "denominator_jobs_all_not_run": all(r["status"] == "NOT_RUN" for r in cancelled_denom["rows"]),
        "denominator_count": len(cancelled_denom["rows"]),
    }

    # 5. Evidence manifest
    evidence_paths = [
        PREP_DIR / "order_plan_FROZEN.json",
        PREP_DIR / "data_and_matrix_summary.json",
        PREP_DIR / "shared_call_ledger.json",
        PREP_DIR / "monitor_snapshot.json",
        PREP_DIR / "source_manifest.json",
        PREP_DIR / "manifest.json",
        APPROVED_QA_DIR / "handoff.json",
        APPROVED_QA_DIR / "order_admission.json",
        APPROVED_QA_DIR / "real_kernel_receipt.json",
        APPROVED_QA_DIR / "scope_review.json",
        APPROVED_QA_DIR / "kernel_completion_review.json",
        APPROVED_QA_DIR / "authorization_provenance.json",
        RUN_DIR / "plan.json",
        RUN_DIR / "driver_receipt.json",
        RUN_DIR / "run.json",
        RUN_DIR / "shared_call_ledger_FINAL.json",
        RUN_DIR / "stdout.log",
        RUN_DIR / "stderr.log",
        RUN_DIR / "transfer_manifest.json",
        CANCELLED_DIR / "QA_HANDOFF.md",
        CANCELLED_DIR / "execution_receipt.json",
        CANCELLED_DIR / "run_denominator.json",
        CANCELLED_DIR / "isolated_shared_call_ledger_FINAL.json",
        CANCELLED_DIR / "manifest.json",
    ]
    for jid in JOB_IDS:
        jd = RUN_DIR / "jobs" / jid
        for fn in ["metrics.json", "record.json", "accounting.json", "checkpoint.json", "config.json", "task_identity.json"]:
            evidence_paths.append(jd / fn)

    evidence_manifest = {
        "schema": "gp5_a05_evidence_manifest_v1",
        "plan_digest": driver_receipt["plan_digest"],
        "data_identity": run_plan["data_identity"],
        "source_identity": run_plan["source_identity"],
        "environment_digest": run_plan["environment_digest"],
        "publication_policy_digest": run_plan["publication_policy_digest"],
        "monitor_algorithm": prep_monitor["algorithm"],
        "monitor_source_digest": prep_monitor["algorithm_identity"]["source_digest"],
        "monitor_dependency_digest": prep_monitor["algorithm_identity"]["dependency_digest"],
        "approved_qa_reviewed_head": approved_handoff["reviewed_head"],
        "admission_plan_digest": approved_admission.get("plan_digest"),
        "files": [
            {
                "path": rel(p),
                "size_bytes": p.stat().st_size,
                "sha256": sha256_file(p),
            }
            for p in evidence_paths
        ],
    }

    # Write machine-readable tables
    job_table_doc = {
        "schema": "gp5_a05_job_results_table_v1",
        "plan_digest": driver_receipt["plan_digest"],
        "runtime_version": run_plan["runtime_version"],
        "scope": run_plan["scope"],
        "formal_denominator": 8,
        "dispatched_and_terminated_count": 8,
        "completed_all_19_items_count": 0,
        "totals": {
            "assessment_entries": sum_metrics_assessments,
            "solver_calls": sum_metrics_solvers,
            "test_double_assessments": 0,
            "model_calls": sum_model_calls,
        },
        "cancelled_duplicate_excluded_note": (
            "Duplicate invocation cancelled before dispatch is recorded separately in cancelled_duplicate_record.json "
            "and excluded from this 8-job denominator."
        ),
        "rows": job_rows,
    }
    write_json(OUT_DIR / "job_results_table.json", job_table_doc)

    # CSV for job results
    job_csv_fields = [
        "job_id",
        "task_id",
        "source_order_id",
        "source_group_id",
        "task_origin",
        "feasibility_status",
        "backend",
        "method",
        "driver_status",
        "completed",
        "planned_items",
        "arrived_items",
        "placed_items",
        "placed_item_ratio",
        "placed_volume_ratio",
        "placed_mass_ratio",
        "fixed_container_utilization",
        "max_height_mm",
        "envelope_status",
        "envelope_utilization",
        "termination_class",
        "termination_reason",
        "global_infeasibility_proven",
        "prefix_truncated",
        "event_limit",
        "predicted_instability_progress",
        "assessment_entries",
        "solver_calls",
        "test_double_assessments",
        "model_calls",
        "service_cost",
        "local_compute_cost",
        "physical_generation_s",
        "selection_s",
        "facts_context_s",
        "physical_commit_s",
        "monitor_result_duration_s",
        "checkpoint_io_s",
        "decision_wall_s",
        "invocation_wall_s",
    ]
    with (OUT_DIR / "job_results_table.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=job_csv_fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in job_rows:
            w.writerow(r)

    paired_doc = {
        "schema": "gp5_a05_paired_comparison_table_v1",
        "plan_digest": driver_receipt["plan_digest"],
        "delta_definition": "ems_surface_hybrid_v1 minus e2_original_v1",
        "scope_boundary": {
            "source_group_id": "SG_901bbb22f834c63f",
            "independent_sources": 0,
            "exposed_training_only": True,
            "not_unseen_test": True,
            "local_methods_not_jev": True,
        },
        "pairs": paired_rows,
    }
    write_json(OUT_DIR / "paired_comparison_table.json", paired_doc)

    paired_csv_fields = list(paired_rows[0].keys())
    with (OUT_DIR / "paired_comparison_table.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=paired_csv_fields, lineterminator="\n")
        w.writeheader()
        for r in paired_rows:
            w.writerow(r)

    stop_diag_doc = {
        "schema": "gp5_a05_stop_diagnostics_summary_v1",
        "plan_digest": driver_receipt["plan_digest"],
        "interpretation_boundary": (
            "Saved diagnostics reflect only the candidate pool and physical/packaging rejection counts at the final "
            "observed state of each trajectory. Empty candidate pool proves only that no executable candidate was "
            "found by the respective backend under the current state; it does NOT prove global infeasibility, "
            "real collapse/instability, or a backend defect."
        ),
        "jobs": stop_diagnostics,
    }
    write_json(OUT_DIR / "stop_diagnostics_summary.json", stop_diag_doc)
    write_json(OUT_DIR / "cancelled_duplicate_record.json", cancelled_record)
    write_json(OUT_DIR / "evidence_manifest.json", evidence_manifest)

    all_passed = all(c["passed"] for c in checks)
    cross_check = {
        "schema": "gp5_a05_cross_check_receipt_v1",
        "all_checks_passed": all_passed,
        "checks_count": len(checks),
        "passed_count": sum(1 for c in checks if c["passed"]),
        "failed_count": sum(1 for c in checks if not c["passed"]),
        "checks": checks,
    }
    write_json(OUT_DIR / "cross_check_receipt.json", cross_check)

    print(json.dumps({"all_checks_passed": all_passed, "checks_count": len(checks), "failed_count": cross_check["failed_count"]}, ensure_ascii=False))
    if not all_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
