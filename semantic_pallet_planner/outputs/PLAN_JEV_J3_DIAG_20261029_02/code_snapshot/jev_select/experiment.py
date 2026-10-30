"""J0 constructed inputs and deterministic request export. No episode or HTTP."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sys

from semantic_pallet_planner.o4.extensions.data import region
from semantic_pallet_planner.o4.extensions.e2.data import object_at, policy, request
from semantic_pallet_planner.o4.fixtures import CONTAINER, eq, rule

from .candidates import CandidateProvider, PublicBusinessGuard
from .config import generator_config, load_config
from .context import ContextBuilder
from .contracts import JevSelectError, canonical, digest


def constructed_cases(capacity: int = 3) -> list[dict]:
    """Public specifications only; cases are engineering checks, not test orders."""
    specs = [
        ("multi_choice", policy([]), [object_at(f"box_{i}", size=(100+i*20, 100, 100)) for i in range(capacity)],
         [region("R", -400, 400, -400, 400)], None, "CHOICE_REQUIRED"),
        ("mixed_attributes", policy([rule("labels", limit="label"),
            rule("no_top", "no_top_load", eq("labels.no_top_load", True), priority=10, overrides=["labels"]),
            rule("contact", "forbidden_contact")]),
         [object_at("food", "food", label=5.), object_at("clean", "household_cleaner"),
          object_at("glass", "glassware", reinforced=True, no_top=True)][:capacity],
         [region("R", -400, 400, -400, 400)], None, "CHOICE_REQUIRED"),
        ("business_empty", policy([{"rule_id": "region", "type": "inside_region", "target": {"all": True},
                                    "region_id": "tiny", "priority": 20, "overrides": []}]),
         [object_at("large")], [region("tiny", -5, 5, -5, 5)], None, "STOP_NO_BUSINESS_CANDIDATE"),
        ("physical_empty", policy([]), [object_at("oversize", size=(200, 200, 200))], [],
         {**CONTAINER, "length_mm": 100, "width_mm": 100, "max_height_mm": 100}, "STOP_NO_PHYSICAL_CANDIDATE"),
    ]
    cases = []
    for name, requirements, available, regions, container, expected in specs:
        obs, state = request(requirements, available=available, regions=regions, capacity=capacity, container=container)
        cases.append({"case_id": name, "source_kind": "constructed_j0",
                      "observation": obs, "state": state, "expected_route": expected})
    return cases


def source_manifest() -> dict[str, str]:
    package = Path(__file__).resolve().parents[1]
    return {p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(package.rglob("*")) if p.is_file() and p.suffix in (".py", ".json")
            and not {"tests", "__pycache__"}.intersection(p.relative_to(package).parts)}


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_manifest(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and p.name != "delivery_manifest.json"}


def _compute(case: dict, config: dict) -> tuple[dict, dict]:
    guard = PublicBusinessGuard()
    policy_context = guard.resolve(case["observation"])
    bundle = CandidateProvider().build(case["state"], case["observation"], generator_config())
    bundle = guard.filter(case["observation"], policy_context, bundle, config)
    context = ContextBuilder(config).build(case["observation"], bundle, policy_context)
    return bundle.data, context.data


def export_j0(output: str | Path, config: dict | None = None) -> dict:
    config = load_config() if config is None else config
    cases = constructed_cases(config["buffer_capacity"])
    # Compute and validate everything before creating a new output directory.
    generated = [(c, *_compute(c, config)) for c in cases]
    root = Path(output).resolve()
    package = Path(__file__).resolve().parents[1]
    repo = package.parents[2]
    protected = [package, repo / "semantic_pallet_dataset_v1", repo / ".git",
                 repo / "semantic_pallet_planner/configs", repo / "semantic_pallet_planner/tests"]
    if root.exists() or any(root.is_relative_to(p) or p.is_relative_to(root) for p in protected):
        raise JevSelectError("unsafe_output", "new output outside protected sources/data required")
    if any((p / "delivery_manifest.json").exists() for p in root.parents):
        raise JevSelectError("sealed_parent")
    root.mkdir(parents=True)
    _write(root / "config.snapshot.json", config)
    _write(root / "generator.snapshot.json", generator_config())
    _write(root / "source_manifest.json", source_manifest())
    _write(root / "environment.json", {"python": platform.python_version(), "executable": sys.executable,
                                      "scope": "J0_OFFLINE_REQUEST_EXPORT", "model_api_calls": 0})
    rows = []
    for case, bundle, context in generated:
        folder = root / "cases" / case["case_id"]
        _write(folder / "input.json", case)
        _write(folder / "candidate_bundle.json", bundle)
        _write(folder / "decision_context.json", context)
        _write(folder / "request.json", context["request_body"])
        rows.append({"case_id": case["case_id"], "route": context["route"],
                     "expected_route": case["expected_route"], "physical_candidates": len(bundle["physical_candidates"]),
                     "selectable_candidates": len(bundle["selectable_candidates"]),
                     "route_matches": context["route"] == case["expected_route"]})
    report = {"scope": "J0_OFFLINE_REQUEST_EXPORT", "status": "PASS" if all(r["route_matches"] for r in rows) else "FAIL",
              "model_api_calls": 0, "cases": rows, "model_quality": "NOT_MEASURED",
              "J1": "NOT_IMPLEMENTED", "J2": "NOT_RUN"}
    _write(root / "acceptance_report.json", report)
    _write(root / "delivery_manifest.json", file_manifest(root))
    return report


def validate_j0(artifact: str | Path) -> dict:
    root = Path(artifact).resolve()
    if file_manifest(root) != _read(root / "delivery_manifest.json"):
        raise JevSelectError("artifact_changed")
    if source_manifest() != _read(root / "source_manifest.json"):
        raise JevSelectError("source_changed")
    config = _read(root / "config.snapshot.json")
    if generator_config() != _read(root / "generator.snapshot.json"):
        raise JevSelectError("generator_changed")
    expected_cases = constructed_cases(config["buffer_capacity"])
    if sorted(p.name for p in (root / "cases").iterdir()) != sorted(c["case_id"] for c in expected_cases):
        raise JevSelectError("case_registry_changed")
    rows = []
    for case in expected_cases:
        folder = root / "cases" / case["case_id"]
        if _read(folder / "input.json") != case:
            raise JevSelectError("input_changed")
        bundle, context = _compute(case, config)
        if bundle != _read(folder / "candidate_bundle.json") or context != _read(folder / "decision_context.json") or context["request_body"] != _read(folder / "request.json"):
            raise JevSelectError("derived_request_changed")
        rows.append({"case_id": case["case_id"], "route": context["route"],
                     "expected_route": case["expected_route"], "physical_candidates": len(bundle["physical_candidates"]),
                     "selectable_candidates": len(bundle["selectable_candidates"]),
                     "route_matches": context["route"] == case["expected_route"]})
    report = _read(root / "acceptance_report.json")
    expected_report = {"scope": "J0_OFFLINE_REQUEST_EXPORT", "status": "PASS" if all(r["route_matches"] for r in rows) else "FAIL",
                       "model_api_calls": 0, "cases": rows, "model_quality": "NOT_MEASURED", "J1": "NOT_IMPLEMENTED", "J2": "NOT_RUN"}
    if report != expected_report:
        raise JevSelectError("report_changed")
    return {"status": report["status"], "scope": report["scope"], "verified_cases": len(rows), "model_api_calls": 0}


# J1 frozen order plans. Imports of E5 fixtures are lazy: J0 stays lightweight.
METHODS = ("shared_geometry", "shared_constrained_first", "jev_choice")


class InputAdapter:
    def load(self, profile="constructed-smoke", input_snapshot=None):
        if profile in ("constructed-smoke", "jev-smoke"):
            if input_snapshot is not None:
                raise JevSelectError("unexpected_input_snapshot")
            from semantic_pallet_planner.o4.extensions.e5.data import construct_tasks
            tasks = json.loads(canonical(construct_tasks()))
            return tasks[:1] if profile == "jev-smoke" else tasks, {"adapter": "constructed_v1", "input_sha256": None}, None
        if profile not in ("orders-smoke", "orders") or input_snapshot is None:
            raise JevSelectError("input_snapshot_required")
        path = Path(input_snapshot)
        if not path.is_file():
            raise JevSelectError("missing_input_snapshot", str(path))
        raw = path.read_bytes()
        snapshot = json.loads(raw)
        tasks = self.from_frozen(snapshot, hashlib.sha256(raw).hexdigest())
        if profile == "orders-smoke":
            tasks = tasks[:4]  # First two frozen sources, both public rule configurations.
        return tasks, {"adapter": "e5_frozen_snapshot_v1", "input_sha256": hashlib.sha256(raw).hexdigest()}, snapshot

    def from_frozen(self, snapshot, source_sha):
        import copy
        from semantic_pallet_planner.o4.extensions.e5.data import rules_for, regions_for
        from semantic_pallet_planner.o4.extensions.e2.compiler import render_policy
        sources = sorted(snapshot["data"]["sources"], key=lambda r: str(r["source_order_key"]))
        if len(sources) != 12 or len({str(r["source_order_key"]) for r in sources}) != 12:
            raise JevSelectError("invalid_source_registry")
        tasks = []
        for index, source in enumerate(sources):
            sid = source["scenario_id"]; scenario = snapshot["scenarios"][sid]
            attrs = snapshot["data"]["attributes"][sid]
            if attrs["attribute_source"] != "synthetic":
                raise JevSelectError("unknown_attribute_source")
            arrival = scenario["arrival_order"]; items = {o["item_id"]: o for o in scenario["items"]}
            if len(items) != len(scenario["items"]) or len(set(arrival)) != len(arrival) or len(arrival) < 4 or any(i not in items for i in arrival):
                raise JevSelectError("invalid_source_arrivals")
            selected = arrival[:12]
            for configuration in (0, 1):
                ast = rules_for(index, configuration)
                tasks.append({"task_id": f"E5_SRC{index:02d}_C{configuration}", "source_kind": "development_order",
                              "source_order_key": str(source["source_order_key"]), "negative": False,
                              "configuration": configuration, "container": copy.deepcopy(scenario["container"]),
                              "items": [copy.deepcopy(items[i]) for i in selected],
                              "attributes": {i: copy.deepcopy(attrs["objects"][i]) for i in selected},
                              "regions": regions_for(scenario["container"]), "instruction_text": render_policy(ast),
                              "reference_policy": ast, "provenance": {"source_sha256": source_sha,
                                  "scenario_id": sid, "original_arrival_order": arrival, "selected_arrival_order": selected,
                                  "attribute_source": "synthetic", "role": "development"}})
        return tasks


def validate_tasks(tasks):
    from semantic_pallet_planner.o4.buffer.buffer_state import initial, receive, can_wait
    from semantic_pallet_planner.o4.extensions.e2.protocol import validate_policy, observation
    from semantic_pallet_planner.o4.extensions.e2.compiler import parse_instruction
    if not isinstance(tasks, list) or not tasks or len({t["task_id"] for t in tasks}) != len(tasks):
        raise JevSelectError("invalid_task_registry")
    for task in tasks:
        canonical(task)
        ids = [o["item_id"] for o in task["items"]]
        if not ids or len(set(ids)) != len(ids) or set(task["attributes"]) != set(ids):
            raise JevSelectError("invalid_task_items")
        validate_policy(task["reference_policy"])
        parse_instruction(task["instruction_text"])
        # Validate every arrival's public attributes without revealing future facts to selection.
        for obj in task["items"]:
            s = receive(initial(task["container"], 1), obj, task["attributes"][obj["item_id"]])
            observation(s, task["instruction_text"], task["regions"])


def _new_output(output):
    root = Path(output).resolve()
    package = Path(__file__).resolve().parents[1]
    repo = package.parents[2]
    protected = (package.parent, repo / "semantic_pallet_dataset_v1", repo / ".git",
                 repo / "semantic_pallet_planner/tests", repo / "semantic_pallet_planner/configs")
    if root.exists() or any(root.is_relative_to(p) or p.is_relative_to(root) for p in protected):
        raise JevSelectError("unsafe_output")
    if any((p / "delivery_manifest.json").exists() for p in root.parents):
        raise JevSelectError("sealed_parent")
    return root


def prepare_plan(output, *, profile="constructed-smoke", config=None, input_snapshot=None,
                 methods=METHODS, offline_scenario="normal", global_attempts=128, per_job_attempts=32,
                 mode="offline", api_budget=None, dataset_root=None, spec_config=None, split_manifest=None, partitions=None, source_limit=None):
    from .config import is_v2, load_v2_config
    if profile in ('dataset-orders','dataset-dev','dataset-validation','constructed-eval') or (config is not None and is_v2(config)):
        from .batch import prepare_plan_v2
        return prepare_plan_v2(output,profile=profile,dataset_root=dataset_root,config=config,
                               spec_config=spec_config,split_manifest=split_manifest,methods=methods,
                               mode=mode,api_budget=api_budget,partitions=partitions,source_limit=source_limit,
                               offline_scenario=offline_scenario)
    import shutil
    from .contracts import validate_schema
    from .ledger import write
    config = load_config() if config is None else config
    validate_schema("config", config)
    if not methods or len(set(methods)) != len(methods) or any(m not in METHODS for m in methods):
        raise JevSelectError("invalid_methods")
    if mode not in ("offline", "remote"):
        raise JevSelectError("invalid_execution_mode")
    if mode == "remote":
        if profile != "jev-smoke" or tuple(methods) != ("jev_choice",):
            raise JevSelectError("remote_requires_jev_smoke")
        if api_budget != "unlimited" and (type(api_budget) is not int or not 1 <= api_budget <= 10000):
            raise JevSelectError("explicit_api_budget_required")
        global_attempts = per_job_attempts = None if api_budget == "unlimited" else api_budget
    # Scenario names are frozen metadata, not an imported service replacement.
    if offline_scenario not in ("normal", "pick_last", "invalid_choice", "wrong_model", "wrong_probabilities", "non_json", "timeout", "http_429", "http_529"):
        raise JevSelectError("invalid_offline_scenario")
    if any(n is not None and (type(n) is not int or not 0 <= n <= 10000) for n in (global_attempts, per_job_attempts)):
        raise JevSelectError("invalid_attempt_budget")
    tasks, provenance, original = InputAdapter().load(profile, input_snapshot)
    validate_tasks(tasks)
    root = _new_output(output); root.mkdir(parents=True)
    write(root / "config.snapshot.json", config)
    write(root / "private/input_snapshot.json", {"tasks": tasks})
    if original is not None:
        # Preserve original bytes as well as the parsed snapshot for source-hash verification.
        (root / "private/imported_snapshot.json").write_bytes(Path(input_snapshot).read_bytes())
    sources = source_manifest(); write(root / "source_manifest.json", sources)
    package = Path(__file__).resolve().parents[1]
    for relative in sources:
        target = root / "code_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package / relative, target)
    jobs = [{"job_id": f"J{i:04d}", "task_id": t["task_id"], "method": method}
            for i, (t, method) in enumerate((t, m) for t in tasks for m in methods)]
    plan = {"version": "jev_plan_v1", "profile": profile, "provenance": provenance,
            "methods": list(methods), "mode": mode, "offline_scenario": offline_scenario if mode == "offline" else None,
            "pricing": {"currency": "USD", "input_per_million": 0.042, "output_per_million": 0.,
                        "source": "https://docs.typesafe.ai/models", "verified_date": "2026-10-29"},
            "budget": {"global_attempts": global_attempts, "per_job_attempts": per_job_attempts},
            "task_registry": [{"task_id": t["task_id"], "task_digest": digest(t)} for t in tasks], "jobs": jobs}
    write(root / "plan.json", plan)
    write(root / "delivery_manifest.json", file_manifest(root))
    return validate_plan(root)


def validate_plan(plan_root):
    if _read(Path(plan_root)/'plan.json').get('version') == 'jev_plan_v2':
        from .batch import validate_plan_v2
        return validate_plan_v2(plan_root)
    from .contracts import validate_schema
    root = Path(plan_root)
    if file_manifest(root) != _read(root / "delivery_manifest.json"):
        raise JevSelectError("plan_changed")
    sources = _read(root / "source_manifest.json")
    if sources != source_manifest():
        raise JevSelectError("source_changed")
    for relative, expected in sources.items():
        if hashlib.sha256((root / "code_snapshot" / relative).read_bytes()).hexdigest() != expected:
            raise JevSelectError("source_snapshot_changed")
    config = _read(root / "config.snapshot.json"); validate_schema("config", config)
    tasks = _read(root / "private/input_snapshot.json")["tasks"]; validate_tasks(tasks)
    plan = _read(root / "plan.json")
    if plan["version"] != "jev_plan_v1" or plan["mode"] not in ("offline", "remote"):
        raise JevSelectError("unsupported_plan")
    if any(n is not None and (type(n) is not int or not 0 <= n <= 10000) for n in plan["budget"].values()) or set(plan["budget"]) != {"global_attempts", "per_job_attempts"}:
        raise JevSelectError("invalid_attempt_budget")
    if plan["profile"] in ("constructed-smoke", "jev-smoke"):
        expected, provenance, _ = InputAdapter().load(plan["profile"])
    else:
        expected, provenance, _ = InputAdapter().load(plan["profile"], root / "private/imported_snapshot.json")
    if tasks != expected or plan["provenance"] != provenance:
        raise JevSelectError("input_provenance_changed")
    methods = plan["methods"]
    if not methods or len(set(methods)) != len(methods) or any(m not in METHODS for m in methods):
        raise JevSelectError("invalid_methods")
    if plan["mode"] == "remote" and (plan["profile"] != "jev-smoke" or methods != ["jev_choice"] or plan["offline_scenario"] is not None):
        raise JevSelectError("invalid_remote_plan")
    pricing = plan["pricing"]
    if pricing != {"currency": "USD", "input_per_million": 0.042, "output_per_million": 0.,
                   "source": "https://docs.typesafe.ai/models", "verified_date": "2026-10-29"}:
        raise JevSelectError("pricing_changed")
    registry = [{"task_id": t["task_id"], "task_digest": digest(t)} for t in tasks]
    jobs = [{"job_id": f"J{i:04d}", "task_id": t["task_id"], "method": m}
            for i, (t, m) in enumerate((t, m) for t in tasks for m in methods)]
    if plan["task_registry"] != registry or plan["jobs"] != jobs:
        raise JevSelectError("plan_registry_changed")
    return {"status": "PASS", "scope": "J1_FROZEN_PLAN", "planned_tasks": len(tasks), "planned_jobs": len(jobs),
            "source_orders": len({t["source_order_key"] for t in tasks}), "model_api_calls": 0}


def load_plan(root):
    validate_plan(root)
    root = Path(root)
    return _read(root / "plan.json"), _read(root / "config.snapshot.json"), _read(root / "private/input_snapshot.json")["tasks"]


def _save_exact(path, value):
    from .ledger import read, write
    if Path(path).exists():
        if read(path) != value:
            raise JevSelectError("saved_decision_changed", str(path))
    else:
        write(path, value)


def run_experiment(plan_root, output, *, offline=False, remote=False, api_budget=None, api_key_file=None, resume=False, hook=None):
    if _read(Path(plan_root)/'plan.json').get('version') == 'jev_plan_v2':
        from .batch import run_experiment_v2
        return run_experiment_v2(plan_root,output,offline=offline,remote=remote,api_budget=api_budget,
                                 api_key_file=api_key_file,resume=resume,hook=hook)
    import shutil
    from .episode import run_episode
    from .ledger import Ledger, exclusive, read, write
    from .selector import JevSelector, LocalSelector
    from .evaluation import aggregate
    if (offline is True) == (remote is True):
        raise JevSelectError("explicit_execution_mode_required")
    plan, config, tasks = load_plan(plan_root)
    mode = "remote" if remote else "offline"
    if plan["mode"] != mode:
        raise JevSelectError("plan_mode_mismatch")
    if api_budget is not None and (mode != "remote" or (None if api_budget == "unlimited" else api_budget) != plan["budget"]["global_attempts"]):
        raise JevSelectError("runtime_budget_changed")
    root = Path(output).resolve()
    identity = {"version": "jev_experiment_v1", "mode": mode, "plan_digest": digest(file_manifest(Path(plan_root)))}
    if not resume:
        if remote:
            from .transport import credential
            credential(config["api_key_env"], api_key_file)
        root = _new_output(root); root.mkdir(parents=True)
        shutil.copytree(plan_root, root / "plan")
        write(root / "manifest.json", identity)
    elif not root.is_dir() or read(root / "manifest.json") != identity:
        raise JevSelectError("resume_identity_changed")
    with exclusive(root):
        if (root / "delivery_manifest.json").exists():
            if not resume: raise JevSelectError("experiment_already_sealed")
            from .replay import replay_experiment
            return replay_experiment(root)
        saved_plan, saved_config, saved_tasks = load_plan(root / "plan")
        if (saved_plan, saved_config, saved_tasks) != (plan, config, tasks):
            raise JevSelectError("run_plan_changed")
        ledger = Ledger(root, plan["budget"], hook=hook, origin="jev" if remote else "test_double")
        if offline:
            from .testing import OfflineTransport
        else:
            from .transport import JevTransport
        tasks_by_id = {t["task_id"]: t for t in tasks}; rows = []; statuses = []
        for job in plan["jobs"]:
            job_id, method = job["job_id"], job["method"]
            cfg = dict(config, selector=method)
            if method == "jev_choice":
                transport = OfflineTransport(cfg, plan["offline_scenario"]) if offline else JevTransport(cfg, api_key_file=api_key_file)
                selector = JevSelector(cfg, ledger, job_id, transport)
            else:
                selector = LocalSelector(method)
            cp_path = root / "checkpoints" / f"{job_id}.json"
            cp = read(cp_path) if cp_path.exists() else None
            def event_hook(phase, value):
                if phase == "decision_ready":
                    did = value["decision_id"]
                    _save_exact(root / "requests" / job_id / f"{did}.json", value["context"]["request_body"])
                    _save_exact(root / "mappings" / job_id / f"{did}.json", value["context"])
                if hook: hook(phase, value)
            result = run_episode(tasks_by_id[job["task_id"]], selector, cfg, job_id=job_id, method=method, resume=cp,
                                 on_checkpoint=lambda value: write(cp_path, value), hook=event_hook)
            write(cp_path, result["checkpoint"])
            _save_exact(root / "episodes" / f"{job_id}.json", result)
            rows.append(result["summary"])
            statuses.append({**job, "status": "RECORDED", "termination_reason": result["summary"]["termination_reason"]})
            write(root / "audit/jobs.json", statuses)
        write(root / "metrics/rows.json", rows)
        write(root / "metrics/summary.json", aggregate(rows, ledger.data["attempts"], mode=mode, pricing=plan["pricing"]))
        from .replay import replay_experiment
        report = replay_experiment(root, require_seal=False)
        write(root / "replay_report.json", report)
        write(root / "acceptance_report.json", report)
        write(root / "delivery_manifest.json", file_manifest(root))
        return report



def preflight(plan_root, *, api_key_file=None):
    if _read(Path(plan_root)/'plan.json').get('version') == 'jev_plan_v2':
        from .batch import preflight_v2
        return preflight_v2(plan_root,api_key_file=api_key_file)
    import os
    from semantic_pallet_planner.o4.buffer.buffer_state import initial, receive, can_wait
    from .episode import decision_inputs
    plan, config, tasks = load_plan(plan_root)
    task = tasks[0]; job = plan["jobs"][0]
    state = initial(task["container"], config["buffer_capacity"])
    cursor = 0
    while can_wait(state):
        if cursor < len(task["items"]):
            item = task["items"][cursor]; state = receive(state, item, task["attributes"][item["item_id"]]); cursor += 1
        else:
            state = receive(state, eos=True)
    cfg = dict(config, selector=job["method"])
    _, _, bundle, context = decision_inputs(state, task, cfg, job["job_id"], f"{job['job_id']}_D0000")
    encoded = canonical(context.data["request_body"]).encode("utf-8")
    from .transport import credential
    ready = plan["mode"] == "offline"
    if not ready:
        try:
            credential(config["api_key_env"], api_key_file); ready = True
        except (OSError, JevSelectError):
            pass
    return {"status": "PASS" if ready else "NEEDS_API_KEY", "scope": "J2_PREFLIGHT", "mode": plan["mode"],
            "requested_model": config["model"], "endpoint": config["endpoint"], "credential_present": ready if plan["mode"] == "remote" else None,
            "first_selectable_candidates": len(bundle.data["selectable_candidates"]), "first_route": context.data["route"],
            "first_request_bytes": len(encoded), "first_request_digest": digest(context.data["request_body"]),
            "budget": plan["budget"], "pricing": plan["pricing"], "planned_jobs": len(plan["jobs"]),
            "natural_decision_upper_bound": sum(len(t["items"]) for t in tasks), "model_api_calls": 0,
            "token_limit_verified_by_service": False}
