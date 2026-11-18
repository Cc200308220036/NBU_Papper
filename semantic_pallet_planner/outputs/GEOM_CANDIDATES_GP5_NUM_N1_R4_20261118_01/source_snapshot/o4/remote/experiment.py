"""Frozen O4-D plans, four-arm matrices and read-only deterministic replay."""
from __future__ import annotations

from collections import defaultdict
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil

from ...config import WORKSPACE
from ..buffer.buffer_evaluation import stable
from ..common import O4Error, digest, read, write
from ..visual.bundle import audit_asset
from . import VERSION
from .audit import audit_episode
from .compiler import RecordedCompiler, RemoteCompiler, audit_records
from .episode import BACKENDS, PLANNERS, compile_source, episode
from .evaluation import compilation_metrics, summarize_compilations
from .protocol import PROMPT_VERSION
from .transport import ChatTransport, ModelConfig


DEFAULT_C = WORKSPACE / "semantic_pallet_planner/outputs/EXP_O4_C_ONLINE_20261021_01"
DEFAULT_F = WORKSPACE / "semantic_pallet_planner/outputs/EXP_O4_F_BUFFER_20261021_01"
DEFAULT_A5 = WORKSPACE / "semantic_pallet_planner/outputs/EXP_O4_A5_VISUAL_20261022_02"
SMOKE_IDS = (
    "no_top_load_1", "no_top_load_2", "max_top_load_2", "max_top_load_4",
    "forbidden_contact_1", "forbidden_contact_2", "sets_3", "sets_4",
    "conditions_2", "conditions_3", "overrides_3", "overrides_5",
)
PROFILES = ("compile-smoke", "fixed", "orders-smoke", "orders", "full")


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_manifest(root: Path) -> dict:
    return {str(path.relative_to(root)): file_hash(path)
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.name != "delivery_manifest.json"}


def source_hashes() -> dict:
    package = WORKSPACE / "semantic_pallet_planner/src/semantic_pallet_planner"
    return {str(path.relative_to(WORKSPACE)): file_hash(path)
            for path in sorted(package.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts}


def verify_sources(expected: dict) -> None:
    # Added files do not invalidate historical runs; every frozen dependency must
    # still match. The complete captured package is included in code_snapshot/.
    for name, fingerprint in expected.items():
        path = WORKSPACE / name
        if not path.is_file() or file_hash(path) != fingerprint:
            raise O4Error("source_drift", name)


def new_directory(output) -> Path:
    root = Path(output).resolve()
    protected = [WORKSPACE / "semantic_pallet_dataset_v1",
                 WORKSPACE / "semantic_pallet_planner/src",
                 WORKSPACE / "semantic_pallet_planner/configs",
                 WORKSPACE / "semantic_pallet_planner/tests"]
    if any(root == path or path in root.parents for path in protected):
        raise ValueError("output must not be inside data, code, configs or tests")
    if any((ancestor / "delivery_manifest.json").exists() for ancestor in root.parents):
        raise ValueError("output must not be nested inside a sealed plan or experiment")
    root.mkdir(parents=True, exist_ok=False)
    return root


def load_baseline(root: Path) -> dict:
    """Verify the frozen files actually used, without rewriting their manifests."""
    delivery = read(root / "delivery_manifest.json")["files"]
    for relative in ("private/input_snapshot.json", "offline_acceptance.json"):
        if file_hash(root / relative) != delivery[relative]:
            raise O4Error("baseline_drift", relative)
    acceptance = read(root / "offline_acceptance.json")
    if acceptance["status"] != "PASS" or not all(acceptance["criteria"].values()):
        raise O4Error("invalid_baseline")
    return read(root / "private/input_snapshot.json")


def prerequisites() -> dict:
    evidence = {}
    for stage, root, filename in (("F", DEFAULT_F, "buffer_acceptance.json"),
                                  ("A5", DEFAULT_A5, "visual_acceptance.json")):
        report = read(root / filename)
        fingerprint = file_hash(root / filename)
        if report["status"] != "PASS" or read(root / "delivery_manifest.json")["files"][filename] != fingerprint:
            raise O4Error("invalid_prerequisite", stage)
        evidence[stage] = {"status": "PASS", "path": str(root / filename), "sha256": fingerprint}
    return evidence


def prepare(output, config: ModelConfig, *, profile="compile-smoke",
            baseline=DEFAULT_C, task_limit=2) -> dict:
    config.validate()
    if profile not in PROFILES or type(task_limit) is not int or task_limit < 1:
        raise ValueError("invalid profile/task limit")
    inputs = load_baseline(Path(baseline))
    prerequisite_evidence = prerequisites()
    data = inputs["data"]
    fixed = ([case for identifier in SMOKE_IDS for case in data["gold"]
              if case["case_id"] == identifier] if profile == "compile-smoke"
             else data["pairs"] if profile in ("fixed", "full") else [])
    if profile == "compile-smoke" and len(fixed) != 12:
        raise O4Error("invalid_baseline", "missing predeclared smoke cases")
    tasks = inputs["tasks"] if profile in ("orders", "full") else (
        inputs["tasks"][:task_limit] if profile == "orders-smoke" else [])
    jobs = []
    for case in fixed:
        for backend in BACKENDS:
            jobs.append({"kind": "fixed", "case_id": case["case_id"], "backend": backend})
    for task in tasks:
        for planner in PLANNERS:
            for backend in BACKENDS:
                jobs.append({"kind": "episode", "task_id": task["task_id"],
                             "planner": planner, "backend": backend})
    for index, job in enumerate(jobs, 1):
        job["job_id"] = f"J{index:06d}"
    upper = 2 * (2 * len(fixed) + 2 * len(PLANNERS) * sum(task["planned_items"] for task in tasks))
    plan = {"version": VERSION, "profile": profile, "jobs": jobs,
            "maximum_api_attempts": upper, "fixed_cases": len(fixed),
            "order_tasks": len(tasks), "planned_episodes": len(tasks) * len(PLANNERS) * len(BACKENDS),
            "backends": list(BACKENDS), "planners": list(PLANNERS),
            "prompt_version": PROMPT_VERSION, "role": "development",
            "human_review": "NOT_REQUIRED_BY_USER", "unseen_test": False,
            "independent_order_sources": len({task["source_order_key"] for task in tasks}),
            "fixed_development_sources": 12 if profile in ("fixed", "full") else 0,
            "smoke_case_ids": list(SMOKE_IDS), "repairs_per_compilation": 1,
            "receiver": "fill_then_plan", "eos_mode": "empty_read"}
    snapshot = {"fixed": fixed, "tasks": tasks, "scenarios": inputs["scenarios"],
                "attributes": data["attributes"], "generator_config": inputs["generator_config"]}
    root = new_directory(output)
    write(root / "plan.json", plan)
    write(root / "private/input_snapshot.json", snapshot)
    write(root / "config.snapshot.json", config.snapshot())
    sources = source_hashes()
    for name in sources:
        target = root / "code_snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WORKSPACE / name, target)
    write(root / "manifest.json", {"version": VERSION, "plan_digest": digest(plan),
          "input_digest": digest(snapshot), "config_digest": digest(config.snapshot()),
          "source_sha256": sources, "baseline": str(Path(baseline).resolve()),
          "prerequisites": prerequisite_evidence,
          "baseline_input_sha256": file_hash(Path(baseline) / "private/input_snapshot.json")})
    write(root / "delivery_manifest.json", {"files": file_manifest(root)})
    return plan


def verify_plan(root: Path) -> tuple[dict, dict, ModelConfig]:
    if file_manifest(root) != read(root / "delivery_manifest.json")["files"]:
        raise O4Error("delivery_drift")
    manifest = read(root / "manifest.json")
    plan, inputs, config = (read(root / path) for path in (
        "plan.json", "private/input_snapshot.json", "config.snapshot.json"))
    for key, value in (("plan", plan), ("input", inputs), ("config", config)):
        if digest(value) != manifest[key + "_digest"]:
            raise O4Error("manifest_mismatch", key)
    verify_sources(manifest["source_sha256"])
    model = ModelConfig(**config)
    model.validate()
    return plan, inputs, model


def evaluate_job(job: dict, inputs: dict, compiler, on_event=None) -> dict:
    backend = job["backend"]
    if job["kind"] == "fixed":
        case = next(case for case in inputs["fixed"] if case["case_id"] == job["case_id"])
        response, status, compilation_id = compile_source(
            case["request"], backend, compiler,
            case["reference_policy"] if backend == "oracle_ast" else None,
        )
        metrics = compilation_metrics(case["request"], response, case["reference_policy"], case["candidates"])
        return {**job, "status": status, "response": response,
                "compilation_id": compilation_id, "metrics": metrics}
    task = next(task for task in inputs["tasks"] if task["task_id"] == job["task_id"])
    scenario = inputs["scenarios"][task["scenario_id"]]
    summary, events = episode(scenario, inputs["attributes"][task["scenario_id"]]["objects"], task,
                              backend, job["planner"], inputs["generator_config"], compiler, on_event)
    return {**job, "status": summary["termination_reason"], "summary": summary, "events": events}


def aggregate(results: list[dict], records: list[dict], attempts: list[dict]) -> dict:
    compiled = defaultdict(list)
    episodes = defaultdict(list)
    for result in results:
        key = result["backend"]
        if result["kind"] == "fixed":
            compiled[key].append(result["metrics"])
        else:
            episodes[(key, result["planner"])].append(result["summary"])
            compiled[key].extend(result["compilations"])
    usages = [row["usage"] for row in attempts]
    tokens = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        known = [usage.get(key) for usage in usages if isinstance(usage, dict) and isinstance(usage.get(key), int)]
        tokens[key] = {"known_sum": sum(known), "missing_attempts": len(attempts) - len(known)}
    latencies = sorted(row["latency_s"] for row in attempts if row["latency_s"] is not None)
    conditions = {}
    for condition in ("text", "image"):
        subset = [record for record in records if record["condition"] == condition]
        conditions[condition] = {"compilations": len(subset),
            "attempts": sum(len(record["attempts"]) for record in subset),
            "first_valid": sum(record["first_valid"] for record in subset),
            "repaired_valid": sum(record["repaired_valid"] for record in subset),
            "final_valid": sum(record["response"] is not None for record in subset)}
    return {
        "compilation": {key: summarize_compilations(rows) for key, rows in compiled.items()},
        "episodes": [{"backend": backend, "planner": planner, "planned": len(rows),
                      "completed": sum(row["completed"] for row in rows),
                      "clean_completed": sum(row["clean_completed"] for row in rows),
                      "mean_item_ratio": sum(row["placed_item_ratio"] for row in rows) / len(rows),
                      "mean_volume_ratio": sum(row["placed_volume_ratio"] for row in rows) / len(rows),
                      "physical_violations": sum(row["physical_violations"] for row in rows),
                      "business_violations": sum(row["final_business_violation_count"] for row in rows)}
                     for (backend, planner), rows in sorted(episodes.items())],
        "api": {"compilations": len(records), "attempts": len(attempts),
                "first_valid": sum(record["first_valid"] for record in records),
                "repaired_valid": sum(record["repaired_valid"] for record in records),
                "final_valid": sum(record["response"] is not None for record in records),
                "repairs": sum(row["repair"] for row in attempts),
                "provider_failures": sum(row["status"] == "provider_error" for row in attempts),
                "missing_usage": sum(value is None for value in usages), "tokens": tokens,
                "latency_p50_s": latencies[len(latencies) // 2] if latencies else None,
                "latency_p95_s": latencies[min(len(latencies) - 1, int(len(latencies) * .95))] if latencies else None,
                "latency_max_s": max(latencies) if latencies else None, "cost": None,
                "by_condition": conditions,
                "served_models": sorted({str(row["payload"].get("model")) for row in attempts
                                         if isinstance(row.get("payload"), dict)})},
    }


def per_source(results: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for result in results:
        if result["kind"] == "episode":
            row = result["summary"]
            groups[(row["source_order_key"], row["backend"], row["planner"])].append(row)
    return [{"source_order_key": source, "backend": backend, "planner": planner,
             "dependent_tasks": len(rows), "clean_completed": sum(row["clean_completed"] for row in rows),
             "mean_item_ratio": sum(row["placed_item_ratio"] for row in rows) / len(rows),
             "role": "development; configurations are not independent sources"}
            for (source, backend, planner), rows in sorted(groups.items())]


def episode_csv(results: list[dict]) -> str:
    columns = ["task_id", "source_order_key", "configuration", "backend", "planner", "capacity",
               "planned_items", "placed_items", "completed", "clean_completed", "placed_item_ratio",
               "placed_volume_ratio", "termination_reason", "physical_violations",
               "final_business_violation_count", "wait_requests", "successful_receives", "place_events"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(result["summary"] for result in results if result["kind"] == "episode")
    return stream.getvalue()


def acceptance(plan: dict, results: list[dict], records: list[dict], attempts: list[dict],
               *, test_double: bool) -> dict:
    operational_errors = {"budget_exhausted", "provider_error", "missing_api_key", "image_limit", "request_limit"}
    incomplete = any(record["status"] in operational_errors for record in records)
    complete = len(results) == len(plan["jobs"]) and not incomplete
    physical = sum(result.get("summary", {}).get("physical_violations", 0) for result in results)
    return {"scope": "O4_D_OFFLINE_PROTOCOL" if test_double else "O4_D_REAL_DEVELOPMENT_MATRIX",
            "status": "PASS" if complete and physical == 0 else "PARTIAL",
            "profile": plan["profile"], "full_development_matrix": plan["profile"] == "full" and complete,
            "test_double": test_double, "real_api_attempts": 0 if test_double else len(attempts),
            "planned_jobs": len(plan["jobs"]), "recorded_jobs": len(results),
            "full_o4_status": "INCOMPLETE", "unseen_generalization": "NOT_MEASURED",
            "D1": len(results) == len(plan["jobs"]),
            "D2": "OFFLINE_ONLY" if test_double else True, "D3": physical == 0,
            "D4": "REPLAY_REQUIRED", "D5": True, "D6": complete,
            "human_review": "NOT_REQUIRED_BY_USER"}


def compact_result(result: dict) -> dict:
    """Keep one episode in memory at a time; full events live in their journal."""
    if result["kind"] == "fixed":
        return result
    return {key: value for key, value in result.items() if key != "events"} | {
        "compilations": [event["compilation_metrics"] for event in result["events"]
                         if event["compilation_metrics"] is not None],
    }


def execute(plan_root, output, *, budget: int, remote=False,
            transport: ChatTransport | None = None) -> dict:
    """A run always uses a new directory. Resuming paid requests is not offered."""
    plan_root = Path(plan_root).resolve()
    plan, inputs, config = verify_plan(plan_root)
    if type(budget) is not int or budget < 1:
        raise ValueError("positive explicit API attempt budget required")
    if remote and transport is not None:
        raise ValueError("remote runs cannot inject a transport")
    if remote and not os.environ.get(config.api_key_env):
        raise ValueError("API key environment variable is unset")
    if not remote and (transport is None or not transport.test_double):
        raise ValueError("use --remote explicitly, or a labelled offline service double")
    if transport is not None and transport.config != config:
        raise ValueError("transport/config mismatch")
    root = new_directory(output)
    shutil.copytree(plan_root, root / "frozen_plan")
    write(root / "run.json", {"budget": budget, "remote": remote, "test_double": not remote,
                             "version": VERSION, "status": "RUNNING"})
    compiler = RemoteCompiler(root, transport or ChatTransport(config), budget)
    results = []
    event_audits = []
    for job in plan["jobs"]:
        event_path = root / "episodes" / (job["job_id"] + ".jsonl")

        def save_event(event):
            event_path.parent.mkdir(parents=True, exist_ok=True)
            with event_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")

        result = evaluate_job(job, inputs, compiler, save_event)
        if job["kind"] == "episode":
            task = next(task for task in inputs["tasks"] if task["task_id"] == job["task_id"])
            event_audits.append({"job_id": job["job_id"], **audit_episode(
                result["events"], inputs["scenarios"][task["scenario_id"]], task["reference_policy"],
            )})
        compact = compact_result(result)
        results.append(compact)
        write(root / "jobs" / (job["job_id"] + ".json"), compact)
    write(root / "audit/attempts.json", compiler.ledger.rows)
    write(root / "metrics/summary.json", aggregate(results, compiler.records, compiler.ledger.rows))
    write(root / "metrics/per_source.json", per_source(results))
    (root / "metrics/per_episode.csv").write_text(episode_csv(results), encoding="utf-8")
    write(root / "audit/events.json", event_audits)
    report = acceptance(plan, results, compiler.records, compiler.ledger.rows, test_double=not remote)
    write(root / "acceptance_report.json", report)
    write(root / "run.json", {"budget": budget, "remote": remote, "test_double": not remote,
                             "version": VERSION, "status": report["status"]})
    write(root / "delivery_manifest.json", {"files": file_manifest(root)})
    try:
        replay(root)
    except (O4Error, ValueError, OSError, KeyError):
        report.update(status="FAIL", D4=False)
        write(root / "acceptance_report.json", report)
        write(root / "run.json", {"budget": budget, "remote": remote, "test_double": not remote,
                                 "version": VERSION, "status": "FAIL"})
        write(root / "delivery_manifest.json", {"files": file_manifest(root)})
        raise
    report["D4"] = True
    write(root / "acceptance_report.json", report)
    write(root / "delivery_manifest.json", {"files": file_manifest(root)})
    return report


def replay(output) -> dict:
    """Rebuild all planning from the saved responses, including failed tasks."""
    root = Path(output).resolve()
    if file_manifest(root) != read(root / "delivery_manifest.json")["files"]:
        raise O4Error("delivery_drift")
    plan, inputs, config = verify_plan(root / "frozen_plan")
    records = [read(path) for path in sorted((root / "responses").glob("D*.json"))]
    attempts = read(root / "audit/attempts.json")
    run = read(root / "run.json")
    if len(attempts) > run["budget"] or [row["attempt_id"] for row in attempts] != list(range(1, len(attempts) + 1)):
        raise O4Error("ledger_mismatch")
    flattened = [attempt for record in records for attempt in record["attempts"]]
    if flattened != attempts or any(record["test_double"] != run["test_double"] for record in records):
        raise O4Error("ledger_mismatch")
    # Reconstruct exact HTTP body digests and image bytes without credentials.
    encoder = ChatTransport(config)
    audit_records(records, encoder, root, run["budget"])
    for record in records:
        for attempt in record["attempts"]:
            raw_text = attempt.get("raw_text")
            if raw_text is not None:
                try:
                    raw_payload = json.loads(raw_text)
                    digest(raw_payload)  # reject non-finite provider JSON
                except (ValueError, TypeError):
                    raw_payload = None
                if raw_payload != attempt["payload"]:
                    raise O4Error("replay_mismatch", "raw provider payload")
            usage = attempt["payload"].get("usage") if isinstance(attempt["payload"], dict) else None
            if usage != attempt["usage"]:
                raise O4Error("replay_mismatch", "usage accounting")
    assets = read(root / "public/assets.json") if records else {}
    for asset in assets.values():
        audit_asset(root, asset, assets)
    compiler = RecordedCompiler(records)
    results = []
    event_audits = []
    for job in plan["jobs"]:
        saved = read(root / "jobs" / (job["job_id"] + ".json"))
        computed = evaluate_job(job, inputs, compiler)
        if stable(saved) != stable(compact_result(computed)):
            raise O4Error("replay_mismatch", job["job_id"])
        if job["kind"] == "episode":
            lines = [json.loads(line) for line in (root / "episodes" / (job["job_id"] + ".jsonl")).read_text().splitlines()]
            if stable(lines) != stable(computed["events"]):
                raise O4Error("replay_mismatch", "event journal")
            task = next(task for task in inputs["tasks"] if task["task_id"] == job["task_id"])
            event_audits.append({"job_id": job["job_id"], **audit_episode(
                computed["events"], inputs["scenarios"][task["scenario_id"]], task["reference_policy"],
            )})
        results.append(compact_result(computed))
    if compiler.cursor != len(records):
        raise O4Error("replay_mismatch", "unused responses")
    if aggregate(results, records, attempts) != read(root / "metrics/summary.json"):
        raise O4Error("replay_mismatch", "metrics")
    if per_source(results) != read(root / "metrics/per_source.json") or event_audits != read(root / "audit/events.json"):
        raise O4Error("replay_mismatch", "source/event audit")
    if episode_csv(results) != (root / "metrics/per_episode.csv").read_text():
        raise O4Error("replay_mismatch", "episode CSV")
    expected = acceptance(plan, results, records, attempts, test_double=run["test_double"])
    saved_report = read(root / "acceptance_report.json")
    expected["D4"] = saved_report["D4"]
    if saved_report != expected:
        raise O4Error("replay_mismatch", "acceptance report")
    return {"status": "PASS", "read_only": True, "network_calls": 0,
            "jobs": len(results), "compilations": len(records), "attempts": len(attempts)}
