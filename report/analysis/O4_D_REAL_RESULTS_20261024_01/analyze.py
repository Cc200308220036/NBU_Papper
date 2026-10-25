"""Read-only analysis of O4-D real runs. Never calls a model or rewrites runs."""
from __future__ import annotations

from collections import Counter, defaultdict
import copy
import json
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSPACE / "semantic_pallet_planner/src"))

from semantic_pallet_planner.o4.common import read, write, digest
from semantic_pallet_planner.o4.evaluator import semantic_signature
from semantic_pallet_planner.o4.remote.audit import audit_episode
from semantic_pallet_planner.o4.remote.compiler import audit_records
from semantic_pallet_planner.o4.remote.experiment import aggregate, file_manifest, file_hash
from semantic_pallet_planner.o4.remote.protocol import validate_response
from semantic_pallet_planner.o4.remote.transport import ChatTransport, ModelConfig

OUTPUT = Path(__file__).resolve().parent
RUNS = ("EXP_O4_D_COMPILE_SMOKE_REAL_20261023_01", "EXP_O4_D_ORDERS_REAL_20261023_01")
ALIASES = {"glass": "glassware", "cleaning_supplies": "household_cleaner", "清洁用品": "household_cleaner"}


def reason(attempt):
    detail = attempt.get("error_detail") or ""
    return "unknown_category" if "unknown category" in detail else attempt["status"]


def replace_category_aliases(value):
    """Diagnostic copy only; never used to score or commit the actual method."""
    if isinstance(value, dict):
        if value.get("field") == "cargo_category" and value.get("value") in ALIASES:
            value["value"] = ALIASES[value["value"]]
        for child in value.values():
            replace_category_aliases(child)
    elif isinstance(value, list):
        for child in value:
            replace_category_aliases(child)


def analyze(name):
    root = WORKSPACE / "semantic_pallet_planner/outputs" / name
    manifest_before = file_manifest(root)
    expected_files = read(root / "delivery_manifest.json")["files"]
    assert manifest_before == expected_files, "run file collection/hash mismatch"
    inputs = read(root / "frozen_plan/private/input_snapshot.json")
    plan = read(root / "frozen_plan/plan.json")
    config = ModelConfig(**read(root / "frozen_plan/config.snapshot.json"))
    frozen = read(root / "frozen_plan/manifest.json")
    assert digest(plan) == frozen["plan_digest"]
    assert digest(inputs) == frozen["input_digest"]
    assert digest(read(root / "frozen_plan/config.snapshot.json")) == frozen["config_digest"]
    assert all(file_hash(WORKSPACE / path) == sha for path, sha in frozen["source_sha256"].items())
    records = [read(path) for path in sorted((root / "responses").glob("D*.json"))]
    attempts = read(root / "audit/attempts.json")
    run = read(root / "run.json")
    assert run["remote"] and not run["test_double"]
    assert all(not record["test_double"] for record in records)
    assert [attempt for record in records for attempt in record["attempts"]] == attempts
    # Builds and hashes request bodies and validates responses, without HTTP.
    audit_records(records, ChatTransport(config), root, run["budget"])
    for record in records:
        assert record["first_valid"] == (record["attempts"][0]["status"] == "valid")
        assert record["repaired_valid"] == (len(record["attempts"]) == 2 and record["attempts"][-1]["status"] == "valid")
        for attempt in record["attempts"]:
            assert json.loads(attempt["raw_text"]) == attempt["payload"]
            assert attempt["usage"] == attempt["payload"].get("usage")
    jobs = [read(root / "jobs" / (job["job_id"] + ".json")) for job in plan["jobs"]]
    assert len(jobs) == len(plan["jobs"])
    for planned, actual in zip(plan["jobs"], jobs):
        assert all(actual[key] == value for key, value in planned.items())
    summary = aggregate(jobs, records, attempts)
    assert summary == read(root / "metrics/summary.json")
    tasks = {task["task_id"]: task for task in inputs["tasks"]}
    cases = {case["case_id"]: case for case in inputs["fixed"]}
    reference_for_compilation = {}
    audits = []
    terminations = defaultdict(Counter)
    conditions = defaultdict(Counter)
    paired = defaultdict(dict)
    source_ratios = defaultdict(list)
    for job in jobs:
        terminations[job["backend"]][job["status"]] += 1
        if job["kind"] == "fixed":
            if job["compilation_id"]:
                reference_for_compilation[job["compilation_id"]] = cases[job["case_id"]]["reference_policy"]
            continue
        task = tasks[job["task_id"]]
        conditions[f'{job["backend"]}/{task["configuration"]}'][job["status"]] += 1
        events = [json.loads(line) for line in (root / "episodes" / (job["job_id"] + ".jsonl")).read_text().splitlines()]
        audit = audit_episode(events, inputs["scenarios"][task["scenario_id"]], task["reference_policy"])
        audits.append({"job_id": job["job_id"], **audit})
        source_ratios[(job["backend"], job["planner"], job["summary"]["source_order_key"])].append(job["summary"]["placed_item_ratio"])
        for event in events:
            compilation = event.get("compilation_id")
            if compilation:
                reference_for_compilation[compilation] = task["reference_policy"]
                paired[(task["task_id"], job["planner"], digest(event["source"]))][job["backend"]] = compilation
    assert audits == read(root / "audit/events.json")
    failures = Counter()
    failing_attempts = Counter()
    examples = []
    alias_only = 0
    for record in records:
        for attempt in record["attempts"]:
            if attempt["status"] != "valid":
                failing_attempts[reason(attempt)] += 1
        if record["response"] is not None:
            reference = reference_for_compilation[record["compilation_id"]]
            assert semantic_signature(record["response"]["policy_ast"]) == semantic_signature(reference)
            continue
        last = record["attempts"][-1]
        failures[reason(last)] += 1
        copied = json.loads(last["payload"]["choices"][0]["message"]["content"])
        replace_category_aliases(copied)
        diagnosed = False
        try:
            validate_response(copied, record["envelope"]["public_request"])
            diagnosed = semantic_signature(copied["policy_ast"]) == semantic_signature(reference_for_compilation[record["compilation_id"]])
        except ValueError:
            pass
        alias_only += diagnosed
        if len(examples) < 12:
            examples.append({"compilation_id": record["compilation_id"], "condition": record["condition"],
                             "error": last["error_detail"], "alias_only_diagnostic_equal": diagnosed})
    by_id = {record["compilation_id"]: record for record in records}
    matched = Counter()
    for pair in paired.values():
        if "remote_text" in pair and "remote_image" in pair:
            left, right = by_id[pair["remote_text"]], by_id[pair["remote_image"]]
            assert left["envelope"]["visual_facts"] == right["envelope"]["visual_facts"]
            matched["both_reached_same_public_state"] += 1
            matched[f'text_valid={left["response"] is not None},image_valid={right["response"] is not None}'] += 1
    provider_ids = [attempt["payload"]["id"] for attempt in attempts]
    assert len(set(provider_ids)) == len(provider_ids)
    assert file_manifest(root) == manifest_before, "analysis changed the experiment"
    report = {"experiment": name, "status": "PASS", "read_only": True, "new_api_calls": 0,
              "integrity_files_checked": len(manifest_before), "summary_recomputed": True,
              "request_response_ledger_audited": True, "full_planner_pixel_replay_repeated": False,
              "saved_D4": read(root / "acceptance_report.json")["D4"], "acceptance": read(root / "acceptance_report.json"),
              "summary": summary, "terminal_model_failures": dict(failures),
              "invalid_attempts_by_reason": dict(failing_attempts),
              "latency_sum_s": sum(attempt["latency_s"] for attempt in attempts),
              "terminations": {key: dict(value) for key, value in terminations.items()},
              "terminations_by_configuration": {key: dict(value) for key, value in conditions.items()},
              "event_audit_counts": {key: sum(row[key] for row in audits) for key in ("events", "physical_checks", "reference_checks", "search_evaluations")},
              "alias_only_counterfactual": {"matching_reference_after_alias_replacement": alias_only,
                  "failed_compilations": sum(failures.values()), "mapping": ALIASES,
                  "scope": "post-hoc diagnosis of copies; not model accuracy, not a new rollout, originals unchanged"},
              "matched_states": dict(matched), "failure_examples": examples,
              "prompt_contains_complete_category_dictionary": all(value in (root / "prompts/single.txt").read_text() for value in ("food", "glassware", "electronics", "household_cleaner", "general"))}
    write(OUTPUT / ("orders.json" if inputs["tasks"] else "compile_smoke.json"), report)
    print(name, "verified", len(jobs), "jobs; failures", dict(failures), "alias-only", alias_only, flush=True)
    return report


if __name__ == "__main__":
    reports = [analyze(name) for name in RUNS]
    write(OUTPUT / "evidence.json", {"status": "PASS", "new_api_calls": 0,
          "real_requests_in_existing_runs": sum(report["summary"]["api"]["attempts"] for report in reports),
          "experiments": [report["experiment"] for report in reports],
          "missing_real_fixed_matrix": not (WORKSPACE / "semantic_pallet_planner/outputs/EXP_O4_D_FIXED_REAL_20261023_01").exists(),
          "scope": "hashes, ledger/body/binding, response validation, summary, independent committed-event audit; no full planner/pixel replay"})
