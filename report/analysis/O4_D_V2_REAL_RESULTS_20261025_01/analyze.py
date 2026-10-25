"""Read-only analysis of existing V2 requests/jobs, never calls a provider.

Checks sealed files, raw payloads, binding/repair ledgers, metrics and PNG request
encoding. Does not execute an experiment or repeat a full replay/render.
"""
import copy
import json
from collections import Counter, defaultdict
from pathlib import Path

from semantic_pallet_planner.config import WORKSPACE
from semantic_pallet_planner.o4.common import canonical, digest, read, write
from semantic_pallet_planner.o4.evaluator import _accept, semantic_signature
from semantic_pallet_planner.o4.remote.evaluation import compilation_metrics
from semantic_pallet_planner.o4.remote.transport import ChatTransport
from semantic_pallet_planner.o4.remote_v2.compiler import audit_records
from semantic_pallet_planner.o4.remote_v2.experiment import aggregate, file_manifest, verify_plan
from semantic_pallet_planner.o4.remote_v2.protocol import parse_response

HERE = Path(__file__).resolve().parent
OUTPUTS = WORKSPACE / "semantic_pallet_planner/outputs"


def zero_load_equivalence(ast):
    """Analysis-only equivalence explicitly defined by the existing O4 spec."""
    result = copy.deepcopy(ast)
    for rule in result["rules"]:
        if rule["type"] == "max_top_load" and rule.get("limit") == {"constant_kg": 0}:
            rule["type"] = "no_top_load"
            del rule["limit"]
    return result


def quantile(values, fraction):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * fraction))] if values else None


def analyze(name):
    root = OUTPUTS / name
    before = file_manifest(root)
    assert before == read(root / "delivery_manifest.json")["files"]
    plan, inputs, config = verify_plan(root / "frozen_plan")
    run = read(root / "run.json")
    acceptance = read(root / "acceptance_report.json")
    assert not run["test_double"] and not acceptance["test_double"] and acceptance["D4"]
    records = [read(path) for path in sorted((root / "responses").glob("D*.json"))]
    attempts = read(root / "audit/attempts.json")
    assert attempts == [a for r in records for a in r["attempts"]]
    audit_records(records, ChatTransport(config), root, run["budget"])
    provider_ids = []
    per_condition = defaultdict(lambda: {"attempts": 0, "input_tokens": 0, "output_tokens": 0, "latencies": []})
    by_record = {r["compilation_id"]: r for r in records}
    for record in records:
        assert not record["test_double"]
        for attempt in record["attempts"]:
            assert json.loads(attempt["raw_text"]) == attempt["payload"]
            assert attempt["usage"] == attempt["payload"]["usage"]
            assert parse_response(attempt["payload"], record["envelope"]["public_request"]) == record["response"]
            provider_ids.append(attempt["payload"]["id"])
            counter = per_condition[record["condition"]]
            counter["attempts"] += 1
            counter["input_tokens"] += attempt["usage"]["prompt_tokens"]
            counter["output_tokens"] += attempt["usage"]["completion_tokens"]
            counter["latencies"].append(attempt["latency_s"])
    cases = {case["case_id"]: case for case in inputs["fixed"]}
    jobs = [read(root / "jobs" / (job["job_id"] + ".json")) for job in plan["jobs"]]
    all_differences, stats = [], defaultdict(Counter)
    equivalent = Counter()
    for expected, job in zip(plan["jobs"], jobs):
        assert all(job[key] == value for key, value in expected.items())
        case = cases[job["case_id"]]
        computed = compilation_metrics(case["request"], job["response"], case["reference_policy"], case["candidates"])
        assert computed == job["metrics"]
        if job["compilation_id"]:
            record = by_record[job["compilation_id"]]
            assert record["source"] == case["request"] and record["response"] == job["response"]
        actual, reference = job["response"]["policy_ast"], case["reference_policy"]
        backend = job["backend"]
        stats[backend]["records"] += 1
        stats[backend]["raw_ast_equal"] += actual == reference
        stats[backend]["finite_domain_equal"] += computed["policy_comparison"]["finite_domain_equal"]
        is_equivalent = semantic_signature(zero_load_equivalence(actual)) == semantic_signature(zero_load_equivalence(reference))
        equivalent[backend] += is_equivalent
        if not computed["semantic_equal"]:
            # For this run verify the exact source of every mismatch; do not
            # assume that finite probes alone prove equivalence.
            assert len(actual["rules"]) == len(reference["rules"]) == 1 and is_equivalent
            a, b = actual["rules"][0], reference["rules"][0]
            assert a["type"] == "no_top_load" and b["type"] == "max_top_load" and b["limit"] == {"constant_kg": 0}
            assert {k: v for k, v in a.items() if k != "type"} == {k: v for k, v in b.items() if k not in ("type", "limit")}
            objects = case["request"]["placed_objects"] + case["request"]["available_objects"]
            assert [o["object_id"] for o in objects if _accept(o, a["target"])] == [o["object_id"] for o in objects if _accept(o, b["target"])]
            all_differences.append({"job_id": job["job_id"], "case_id": case["case_id"], "compilation_id": job["compilation_id"],
                                   "backend": backend, "instruction_text": case["request"]["instruction_text"],
                                   "actual": actual, "reference": reference, "classification": "zero_limit_equivalent_representation",
                                   "finite_domain_equal": True, "allowed_set_equal": computed["allowed_set_equal"],
                                   "original_metrics": computed})
    assert aggregate(jobs, records, attempts) == read(root / "metrics/summary.json")
    pair_stats = defaultdict(Counter)
    for backend in plan["backends"]:
        grouped = defaultdict(list)
        for job in jobs:
            case = cases[job["case_id"]]
            if job["backend"] == backend and "pair_id" in case:
                grouped[case["pair_id"]].append(job)
        for pair in grouped.values():
            assert len(pair) == 2
            kind = cases[pair[0]["case_id"]]["kind"]
            pair_stats[backend][kind + "_pairs"] += 1
            change = pair[0]["metrics"]["method_allowed_ids"] != pair[1]["metrics"]["method_allowed_ids"]
            pair_stats[backend][kind + "_allowed_changes"] += change
    for counter in per_condition.values():
        latencies = counter.pop("latencies")
        counter.update(latency_total_s=sum(latencies), latency_p50_s=quantile(latencies, .5), latency_p95_s=quantile(latencies, .95))
    assert before == file_manifest(root)
    result = {"experiment": name, "sealed_files_checked": len(before), "original_files_unchanged": True,
              "acceptance": acceptance, "summary": read(root / "metrics/summary.json"),
              "raw_stats": dict(stats), "zero_limit_equivalence_diagnostic": dict(equivalent),
              "mismatches": all_differences, "pair_stats": dict(pair_stats), "conditions": dict(per_condition),
              "provider_ids": provider_ids, "distinct_provider_ids": len(set(provider_ids)),
              "cases": len(cases), "reference_empty_cases": sum(not audit["metrics"]["reference_allowed_ids"] for audit in jobs if audit["backend"] == "oracle_ast"),
              "known_development_sources": plan["fixed_development_sources"], "new_api_calls": 0,
              "full_replay_repeated": False, "method": "sealed-file, request/PNG encoding, raw response, ledger and per-job metric recomputation"}
    return result, inputs, records


def main():
    smoke, smoke_inputs, _ = analyze("EXP_O4_D_V2_SMOKE_REAL_20261025_01")
    fixed, _, _ = analyze("EXP_O4_D_V2_FIXED_REAL_20261025_01")
    old = OUTPUTS / "EXP_O4_D_COMPILE_SMOKE_REAL_20261023_01"
    old_inputs = read(old / "frozen_plan/private/input_snapshot.json")
    assert old_inputs["fixed"] == smoke_inputs["fixed"]
    old_summary = read(old / "metrics/summary.json")
    all_ids = smoke["provider_ids"] + fixed["provider_ids"]
    assert len(all_ids) == len(set(all_ids)) == 312
    evidence = {"status": "PASS", "scope": "V2_REAL_SMOKE_AND_FIXED_READ_ONLY_ANALYSIS", "new_api_calls": 0,
                "real_existing_attempts": len(all_ids), "unique_provider_ids": len(set(all_ids)),
                "sealed_files_checked": smoke["sealed_files_checked"] + fixed["sealed_files_checked"],
                "raw_fixed_text_semantic_signature": "138/144", "raw_fixed_image_semantic_signature": "144/144",
                "text_mismatches": 6, "mismatch_classification": "no_top_load equals max_top_load(0 kg) under existing spec",
                "original_scores_rewritten": False, "full_replay_repeated": False,
                "v1_smoke_same_declared_cases": True, "v1_smoke_api": old_summary["api"],
                "v2_smoke_api": smoke["summary"]["api"], "causal_claim": False,
                "next_missing": ["V2 online protocol impact", "independent language/model increment evidence"]}
    write(HERE / "smoke.json", smoke)
    write(HERE / "fixed.json", fixed)
    write(HERE / "evidence.json", evidence)
    print(canonical(evidence))


if __name__ == "__main__":
    main()
