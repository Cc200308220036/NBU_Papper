"""Read sealed fixed experiments and write separate V2 evaluation sidecars.

No API, client, planner or replay imports. Original metrics remain embedded in
the new rows and original experiment files are never opened for writing.
"""
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path

from .common import O4Error, digest, read, write
from .evaluation_v2 import VERSION, compilation_metrics, summarize


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def files(root):
    return {str(p.relative_to(root)): file_hash(p) for p in sorted(root.rglob("*"))
            if p.is_file() and p.name != "delivery_manifest.json"}


def check_seal(root):
    found = files(root)
    if found != read(root / "delivery_manifest.json")["files"]:
        raise O4Error("delivery_drift", str(root))
    return found


def _experiment(root):
    root = Path(root).resolve()
    before = check_seal(root)
    frozen = root / "frozen_plan"
    check_seal(frozen)
    manifest, plan = read(frozen / "manifest.json"), read(frozen / "plan.json")
    inputs = read(frozen / "private/input_snapshot.json")
    config = read(frozen / "config.snapshot.json")
    for key, value in (("plan", plan), ("input", inputs), ("config", config)):
        if manifest[key + "_digest"] != digest(value):
            raise O4Error("manifest_mismatch", key)
    if any(j["kind"] != "fixed" for j in plan["jobs"]):
        raise ValueError("this rescorer accepts fixed/compile-smoke jobs only")
    cases = {c["case_id"]: c for c in inputs["fixed"]}
    records = {p.stem: read(p) for p in sorted((root / "responses").glob("D*.json"))}
    run, attempts = read(root / "run.json"), read(root / "audit/attempts.json")
    flattened = [a for record in records.values() for a in record["attempts"]]
    if flattened != attempts or len(attempts) > run["budget"] or [a["attempt_id"] for a in attempts] != list(range(1, len(attempts) + 1)):
        raise O4Error("ledger_mismatch")
    provider_ids = []
    for identifier, record in records.items():
        if identifier != record["compilation_id"] or record["test_double"] != run["test_double"]:
            raise O4Error("ledger_mismatch", "compilation identity")
        for attempt in record["attempts"]:
            if attempt["raw_text"] is not None:
                try:
                    payload = json.loads(attempt["raw_text"])
                except ValueError:
                    payload = None
                if payload != attempt["payload"]:
                    raise O4Error("response_mismatch", "raw text")
            payload = attempt["payload"]
            if isinstance(payload, dict):
                if payload.get("usage") != attempt["usage"]:
                    raise O4Error("ledger_mismatch", "usage")
                if payload.get("id"):
                    provider_ids.append(payload["id"])
        if record["response"] is not None:
            last = record["attempts"][-1]["payload"]["choices"][0]
            if last.get("finish_reason") != "stop" or json.loads(last["message"]["content"]) != record["response"]:
                raise O4Error("response_mismatch", "accepted AST")
            attached = record["envelope"]["public_request"]
            for key in ("request_id", "state_hash", "observation_digest", "instruction_digest"):
                if record["response"][key] != attached[key]:
                    raise O4Error("response_mismatch", "binding")
    rows, groups, seen_records = [], defaultdict(list), set()
    expected_paths = {j["job_id"] + ".json" for j in plan["jobs"]}
    if {p.name for p in (root / "jobs").glob("*.json")} != expected_paths:
        raise O4Error("job_mismatch", "missing/extra job")
    for planned in plan["jobs"]:
        job = read(root / "jobs" / (planned["job_id"] + ".json"))
        if any(job[key] != value for key, value in planned.items()):
            raise O4Error("job_mismatch", job["job_id"])
        case = cases[job["case_id"]]
        identifier = job["compilation_id"]
        if identifier is not None:
            record = records[identifier]
            if record["source"] != case["request"] or record["response"] != job["response"]:
                raise O4Error("response_mismatch", job["job_id"])
            seen_records.add(identifier)
        new = compilation_metrics(case["request"], job["response"], case["reference_policy"], case["candidates"])
        old = job["metrics"]
        # Candidate verdicts are not part of the requested equivalence change.
        unchanged = all(new[k] == old[k] for k in ("valid_ast", "allowed_set_equal", "reference_allowed_ids", "method_allowed_ids", "false_allow_ids", "false_reject_ids"))
        row = {"experiment": root.name, "job_id": job["job_id"], "case_id": job["case_id"],
               "backend": job["backend"], "compilation_id": identifier, "legacy_metrics": old,
               "evaluation_v2": new, "candidate_verdicts_unchanged": unchanged,
               "semantic_metric_changed": new["semantic_equal"] != old["semantic_equal"]}
        rows.append(row)
        groups[job["backend"]].append(new)
    if seen_records != set(records):
        raise O4Error("response_mismatch", "unconsumed response record")
    if files(root) != before:
        raise O4Error("original_experiment_changed")
    return {"experiment": str(root), "sealed_files_checked": len(before), "source_plan_profile": plan["profile"],
            "existing_response_records": len(records), "existing_api_attempts": len(attempts),
            "test_double": run["test_double"], "original_files_unchanged": True,
            "provider_ids": provider_ids, "summaries": {key: summarize(value) for key, value in groups.items()}, "rows": rows}


def rescore(experiments, output):
    roots = [Path(p).resolve() for p in experiments]
    if len(set(roots)) != len(roots):
        raise ValueError("duplicate experiment")
    target = Path(output).resolve()
    if any(target == p or p in target.parents or target in p.parents for p in roots):
        raise ValueError("output must be separate from the source experiments")
    package = Path(__file__).resolve().parents[1]
    workspace = package.parents[2]
    for protected in (workspace / "semantic_pallet_dataset_v1", workspace / "semantic_pallet_planner/src",
                      workspace / "semantic_pallet_planner/tests", workspace / "semantic_pallet_planner/configs"):
        if target == protected or protected in target.parents:
            raise ValueError("output must not be inside data, source, tests or configs")
    if any((parent / "delivery_manifest.json").exists() for parent in target.parents):
        raise ValueError("output must not be inside a sealed artifact")
    if target.exists():
        raise FileExistsError(target)
    results = [_experiment(p) for p in roots]
    target.mkdir(parents=True, exist_ok=False)
    rows = [row for result in results for row in result["rows"]]
    write(target / "rows.json", rows)
    write(target / "summary.json", [{k: v for k, v in result.items() if k != "rows"} for result in results])
    columns = ["experiment", "job_id", "case_id", "backend", "legacy_semantic_equal", "v2_semantic_equal",
               "v2_objects_equal", "v2_limits_equal", "v2_conditions_equal", "v2_overrides_equal", "candidate_verdicts_unchanged"]
    with (target / "comparison.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            v2 = row["evaluation_v2"]
            writer.writerow({**{key: row[key] for key in columns[:4]},
                "legacy_semantic_equal": row["legacy_metrics"]["semantic_equal"], "v2_semantic_equal": v2["semantic_equal"],
                "v2_objects_equal": v2["applicable_objects_equal"], "v2_limits_equal": v2["limits_equal"],
                "v2_conditions_equal": v2["conditions_exceptions_equal"], "v2_overrides_equal": v2["overrides_equal"],
                "candidate_verdicts_unchanged": row["candidate_verdicts_unchanged"]})
    sources = [Path(__file__), Path(__file__).with_name("evaluation_v2.py"), Path(__file__).with_name("evaluator.py"), Path(__file__).with_name("common.py")]
    write(target / "manifest.json", {"evaluator_version": VERSION, "source_sha256": {str(p): file_hash(p) for p in sources},
          "input_delivery_sha256": {str(p): file_hash(p / "delivery_manifest.json") for p in roots},
          "new_api_calls": 0, "original_scores_rewritten": False, "full_replay_repeated": False})
    report = {"status": "PASS" if all(r["candidate_verdicts_unchanged"] for r in rows) else "FAIL",
              "evaluator_version": VERSION, "experiments": len(roots), "job_records": len(rows),
              "existing_response_records": sum(r["existing_response_records"] for r in results),
              "existing_api_attempts": sum(r["existing_api_attempts"] for r in results),
              "semantic_metric_changes": sum(r["semantic_metric_changed"] for r in rows),
              "candidate_verdicts_unchanged": all(r["candidate_verdicts_unchanged"] for r in rows),
              "sealed_files_checked": sum(r["sealed_files_checked"] for r in results),
              "original_files_unchanged": True, "new_api_calls": 0}
    write(target / "evaluation_report.json", report)
    write(target / "delivery_manifest.json", {"files": files(target)})
    return report
