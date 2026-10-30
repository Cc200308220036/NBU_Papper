"""Frozen study plans, explicit API budgets, full failure denominators and replay."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil

from ...config import WORKSPACE
from ..buffer.buffer_evaluation import stable
from ..common import O4Error, digest, read, write
from ..remote.audit import audit_episode
from ..remote.transport import ChatTransport, ModelConfig
from ..remote_v2.compiler import RecordedCompiler, RemoteCompiler, audit_records
from ..remote_v2.experiment import (aggregate, compact_result, episode_csv, file_manifest,
                                    new_directory, source_hashes, verify_sources)
from ..remote_v2.protocol import CONTRACT_VERSION, PROMPT_VERSION, response_schema
from ..visual.bundle import audit_asset
from . import VERSION
from .data import verify as verify_corpus
from .episode import BACKENDS, PLANNERS, compile_source, episode
from .metrics import compilation_metrics, summarize
from .parser import VERSION as PARSER_VERSION


def planned_jobs(units, kind, repeats, planner):
    jobs = []
    for unit in units:
        for repeat in range(repeats):
            for backend in BACKENDS:
                jobs.append({"job_id": f"J{len(jobs) + 1:07d}", "kind": kind,
                             "unit_id": unit["case_id"] if kind == "fixed" else unit["task_id"],
                             "backend": backend, "repeat": repeat + 1, "planner": planner,
                             **{key: unit[key] for key in ("source_order_key", "track", "family", "template_family")}})
    return jobs


def prepare(corpus, output, model, *, mode="fixed", split="development", planner=None):
    if mode not in ("fixed", "online") or split not in ("development", "calibration", "test"):
        raise ValueError("invalid study mode/split")
    corpus = Path(corpus).resolve()
    verify_corpus(corpus)
    design = read(corpus / "design.json")
    model.validate()
    planner = planner or design["online_planner"]
    if planner not in PLANNERS:
        raise ValueError("invalid planner")
    data = read(corpus / "private/input_snapshot.json")
    kind = "fixed" if mode == "fixed" else "episode"
    units = [row for row in data["fixed" if kind == "fixed" else "tasks"] if row["split"] == split]
    repeats = design["fixed_repeats" if kind == "fixed" else "online_repeats"][split]
    jobs = planned_jobs(units, kind, repeats, planner)
    maximum = 4 * repeats * (len(units) if kind == "fixed" else sum(row["planned_items"] for row in units))
    plan = {"version": VERSION, "contract_version": CONTRACT_VERSION, "prompt_version": PROMPT_VERSION,
            "parser_version": PARSER_VERSION, "mode": mode, "split": split, "repeats": repeats,
            "jobs": jobs, "planned_jobs": len(jobs), "units": len(units), "maximum_api_attempts": maximum,
            "independent_sources": len({row["source_order_key"] for row in units}),
            "backends": list(BACKENDS), "planner": planner, "design": design,
            "template_scope": read(corpus / "manifest.json")["template_origin"],
            "source_scope": "new raw order keys/windows absent from recorded historical provenance",
            "power_certified": False, "human_review": "NOT_PERFORMED", "api_executed": False}
    sids = {row["scenario_id"] for row in units}
    inputs = {"units": units, "scenarios": {sid: data["scenarios"][sid] for sid in sids},
              "attributes": {sid: data["attributes"][sid] for sid in sids}, "generator_config": data["generator_config"]}
    root = new_directory(output)
    write(root / "plan.json", plan)
    write(root / "private/input_snapshot.json", inputs)
    write(root / "config.snapshot.json", model.snapshot())
    write(root / "protocol/response_single.schema.json", response_schema(False))
    write(root / "protocol/response_buffer.schema.json", response_schema(True))
    write(root / "audit/source_registry.json", [r for r in read(corpus / "private/source_registry.json") if r["scenario_id"] in sids])
    write(root / "audit/corpus_manifest.json", read(corpus / "manifest.json"))
    sources = source_hashes()
    for name in sources:
        target = root / "code_snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WORKSPACE / name, target)
    write(root / "manifest.json", {"version": VERSION, "plan_digest": digest(plan), "input_digest": digest(inputs),
                                  "config_digest": digest(model.snapshot()), "source_sha256": sources})
    write(root / "delivery_manifest.json", {"files": file_manifest(root)})
    return {key: value for key, value in plan.items() if key != "jobs"}


def verify_plan(root):
    root = Path(root)
    if file_manifest(root) != read(root / "delivery_manifest.json")["files"]:
        raise O4Error("delivery_drift")
    manifest = read(root / "manifest.json")
    plan, inputs, config = (read(root / name) for name in ("plan.json", "private/input_snapshot.json", "config.snapshot.json"))
    if (plan["version"] != VERSION or plan["contract_version"] != CONTRACT_VERSION
            or plan["prompt_version"] != PROMPT_VERSION or plan["parser_version"] != PARSER_VERSION):
        raise O4Error("manifest_mismatch", "version")
    for key, value in (("plan", plan), ("input", inputs), ("config", config)):
        if manifest[key + "_digest"] != digest(value):
            raise O4Error("manifest_mismatch", key)
    kind = "fixed" if plan["mode"] == "fixed" else "episode"
    repeats = plan["design"]["fixed_repeats" if kind == "fixed" else "online_repeats"][plan["split"]]
    expected_jobs = planned_jobs(inputs["units"], kind, repeats, plan["planner"])
    if (plan["jobs"] != expected_jobs or plan["planned_jobs"] != len(expected_jobs)
            or plan["repeats"] != repeats or plan["backends"] != list(BACKENDS)
            or any(row["split"] != plan["split"] for row in inputs["units"])):
        raise O4Error("manifest_mismatch", "job matrix")
    for buffered, mode in ((False, "single"), (True, "buffer")):
        if read(root / f"protocol/response_{mode}.schema.json") != response_schema(buffered):
            raise O4Error("manifest_mismatch", "schema")
    verify_sources(manifest["source_sha256"])
    return plan, inputs, ModelConfig(**config)


def evaluate_job(job, inputs, compiler, on_event=None):
    unit = next(row for row in inputs["units"] if row.get("case_id", row.get("task_id")) == job["unit_id"])
    if job["kind"] == "fixed":
        response, status, identifier = compile_source(unit["request"], job["backend"], compiler,
            unit["reference_policy"] if job["backend"] == "oracle_ast" else None)
        measures = compilation_metrics(unit["request"], response, unit["reference_policy"], unit["candidates"])
        return {**job, "status": status, "response": response, "compilation_id": identifier, "metrics": measures}
    scenario = inputs["scenarios"][unit["scenario_id"]]
    summary, events = episode(scenario, inputs["attributes"][unit["scenario_id"]], unit, job["backend"],
                              job["planner"], inputs["generator_config"], compiler, on_event)
    return {**job, "status": summary["termination_reason"], "summary": summary, "events": events}


def study_rows(results):
    return [{**{key: result[key] for key in ("kind", "unit_id", "repeat", "source_order_key", "track", "family", "template_family", "backend", "status")},
             "measures": result["metrics"] if result["kind"] == "fixed" else result["summary"]} for result in results]


def acceptance(plan, results, records, *, test_double, replayed=False):
    errors = {"budget_exhausted", "provider_error", "missing_api_key", "image_limit", "request_limit"}
    complete = len(results) == len(plan["jobs"]) and not any(r["status"] in errors for r in records)
    physical = sum(result.get("summary", {}).get("physical_violations", 0) for result in results)
    return {"version": VERSION, "scope": "OFFLINE_STUDY_PROTOCOL" if test_double else "REAL_CONTROLLED_HOLDOUT_STUDY",
            "status": "PASS" if complete and physical == 0 else "PARTIAL", "test_double": test_double,
            "planned_jobs": len(plan["jobs"]), "recorded_jobs": len(results), "mode": plan["mode"], "split": plan["split"],
            "physical_violations": physical, "parser_unsupported_retained": sum(r["status"] == "unsupported_construct" for r in results),
            "real_api_attempts": 0 if test_double else sum(len(record["attempts"]) for record in records),
            "D4": replayed, "power_certified": False, "confirmatory_claim": False,
            "unseen_generalization": "NOT_MEASURED" if test_double else "CONTROLLED_HOLDOUT_ONLY" if plan["split"] == "test" and complete else "NOT_ESTABLISHED",
            "full_o4_status": "INCOMPLETE"}


def execute(plan_root, output, *, budget, remote=False, transport=None):
    plan_root = Path(plan_root).resolve()
    plan, inputs, config = verify_plan(plan_root)
    if type(budget) is not int or budget < 1:
        raise ValueError("positive explicit API attempt budget required")
    if remote and (transport is not None or not os.environ.get(config.api_key_env)):
        raise ValueError("remote requires an environment key and forbids injected transport")
    if not remote and (transport is None or not transport.test_double):
        raise ValueError("choose explicit remote or a labelled offline transport")
    if transport is not None and transport.config != config:
        raise ValueError("transport config mismatch")
    root = new_directory(output)
    shutil.copytree(plan_root, root / "frozen_plan")
    write(root / "run.json", {"version": VERSION, "budget": budget, "test_double": not remote, "status": "RUNNING"})
    compiler = RemoteCompiler(root, transport or ChatTransport(config), budget)
    results, event_audits = [], []
    for job in plan["jobs"]:
        path = root / "episodes" / (job["job_id"] + ".jsonl")

        def save(event):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(canonical_json_line(event))

        result = evaluate_job(job, inputs, compiler, save)
        if job["kind"] == "episode":
            unit = next(u for u in inputs["units"] if u["task_id"] == job["unit_id"])
            event_audits.append({"job_id": job["job_id"], **audit_episode(result["events"], inputs["scenarios"][unit["scenario_id"]], unit["reference_policy"])})
        compact = compact_result(result)
        results.append(compact)
        write(root / "jobs" / (job["job_id"] + ".json"), compact)
    write(root / "audit/attempts.json", compiler.ledger.rows)
    write(root / "audit/events.json", event_audits)
    write(root / "metrics/summary.json", aggregate(results, compiler.records, compiler.ledger.rows))
    write(root / "metrics/study_summary.json", summarize(study_rows(results), plan["design"]))
    write(root / "metrics/rows.json", study_rows(results))
    (root / "metrics/per_episode.csv").write_text(episode_csv(results), encoding="utf-8")
    report = acceptance(plan, results, compiler.records, test_double=not remote)
    write(root / "acceptance_report.json", report)
    write(root / "run.json", {"version": VERSION, "budget": budget, "test_double": not remote, "status": report["status"]})
    write(root / "delivery_manifest.json", {"files": file_manifest(root)})
    try:
        replay(root)
    except (O4Error, ValueError, OSError, KeyError):
        report.update(status="FAIL", D4=False)
        write(root / "acceptance_report.json", report)
        write(root / "delivery_manifest.json", {"files": file_manifest(root)})
        raise
    report["D4"] = True
    write(root / "acceptance_report.json", report)
    write(root / "delivery_manifest.json", {"files": file_manifest(root)})
    return report


def canonical_json_line(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n"


def replay(output):
    root = Path(output).resolve()
    if file_manifest(root) != read(root / "delivery_manifest.json")["files"]:
        raise O4Error("delivery_drift")
    plan, inputs, config = verify_plan(root / "frozen_plan")
    run = read(root / "run.json")
    records = [read(path) for path in sorted((root / "responses").glob("D*.json"))]
    attempts = read(root / "audit/attempts.json")
    if attempts != [a for record in records for a in record["attempts"]] or any(r["test_double"] != run["test_double"] for r in records):
        raise O4Error("ledger_mismatch")
    audit_records(records, ChatTransport(config), root, run["budget"])
    for attempt in attempts:
        text = attempt.get("raw_text")
        if text is not None:
            try:
                payload = json.loads(text)
                digest(payload)
            except (ValueError, TypeError):
                payload = None
            if payload != attempt["payload"]:
                raise O4Error("replay_mismatch", "raw payload")
        usage = attempt["payload"].get("usage") if isinstance(attempt["payload"], dict) else None
        if usage != attempt["usage"]:
            raise O4Error("replay_mismatch", "usage")
    assets = read(root / "public/assets.json") if records else {}
    for asset in assets.values():
        audit_asset(root, asset, assets)
    compiler = RecordedCompiler(records)
    results, event_audits = [], []
    for job in plan["jobs"]:
        computed = evaluate_job(job, inputs, compiler)
        saved = read(root / "jobs" / (job["job_id"] + ".json"))
        if stable(saved) != stable(compact_result(computed)):
            raise O4Error("replay_mismatch", job["job_id"])
        if job["kind"] == "episode":
            lines = [json.loads(line) for line in (root / "episodes" / (job["job_id"] + ".jsonl")).read_text().splitlines()]
            if stable(lines) != stable(computed["events"]):
                raise O4Error("replay_mismatch", "event journal")
            unit = next(u for u in inputs["units"] if u["task_id"] == job["unit_id"])
            event_audits.append({"job_id": job["job_id"], **audit_episode(computed["events"], inputs["scenarios"][unit["scenario_id"]], unit["reference_policy"])})
        results.append(compact_result(computed))
    if compiler.cursor != len(records) or aggregate(results, records, attempts) != read(root / "metrics/summary.json"):
        raise O4Error("replay_mismatch", "compilation/metrics")
    if study_rows(results) != read(root / "metrics/rows.json") or summarize(study_rows(results), plan["design"]) != read(root / "metrics/study_summary.json"):
        raise O4Error("replay_mismatch", "study statistics")
    if event_audits != read(root / "audit/events.json") or episode_csv(results) != (root / "metrics/per_episode.csv").read_text():
        raise O4Error("replay_mismatch", "events/CSV")
    saved = read(root / "acceptance_report.json")
    if saved != acceptance(plan, results, records, test_double=run["test_double"], replayed=saved["D4"]):
        raise O4Error("replay_mismatch", "acceptance")
    return {"status": "PASS", "read_only": True, "network_calls": 0, "jobs": len(results),
            "compilations": len(records), "attempts": len(attempts)}
