"""Persistent O4-D plans, failure denominators and independently replayed runs."""
import copy
import json
import shutil

import pytest

from semantic_pallet_planner.config import generator_config, load_config
from semantic_pallet_planner.o4.common import O4Error, read, write
from semantic_pallet_planner.o4.fixtures import gold_cases
from semantic_pallet_planner.o4.online.cases import diagnostic_scenario
from semantic_pallet_planner.o4.remote.experiment import (
    execute, file_manifest, prepare, replay,
)
from semantic_pallet_planner.o4.remote.testing import ProtocolServiceDouble
from semantic_pallet_planner.o4.remote.transport import ChatTransport, ModelConfig


@pytest.fixture
def model():
    return ModelConfig("https://api.deepseek.com/chat/completions", "deepseek-flash", api_key_env="O4_INTEGRATION_KEY")


@pytest.fixture
def baseline(tmp_path):
    """Explicit small test baseline, never presented as a production C run."""
    scenario, attributes, task = diagnostic_scenario()
    task["planned_items"] = 3
    root = tmp_path / "test_baseline"
    inputs = {"data": {"gold": gold_cases(), "pairs": gold_cases()[:2],
                       "attributes": {scenario["scenario_id"]: {"objects": attributes}}},
              "tasks": [task], "scenarios": {scenario["scenario_id"]: scenario},
              "generator_config": generator_config(load_config())}
    write(root / "private/input_snapshot.json", inputs)
    write(root / "offline_acceptance.json", {"status": "PASS", "criteria": {"C1": True}})
    write(root / "delivery_manifest.json", {"files": file_manifest(root)})
    return root


def transport(model, monkeypatch, faults=()):
    monkeypatch.setenv(model.api_key_env, "OFFLINE_INTEGRATION_SENTINEL")
    return ChatTransport(model, opener=ProtocolServiceDouble(faults), test_double=True)


def seal(root):
    write(root / "delivery_manifest.json", {"files": file_manifest(root)})


def test_four_backends_both_modes_and_read_only_replay(tmp_path, baseline, model, monkeypatch):
    plan = tmp_path / "plan"
    frozen = prepare(plan, model, profile="orders-smoke", baseline=baseline)
    assert frozen["planned_episodes"] == 16
    root = tmp_path / "run"
    report = execute(plan, root, budget=100, transport=transport(model, monkeypatch))
    assert report["status"] == "PASS" and report["real_api_attempts"] == 0
    before = file_manifest(root)
    # Replay must not even attempt to read an API key or open a provider request.
    monkeypatch.delenv(model.api_key_env)
    monkeypatch.setattr(ChatTransport, "complete", lambda *args: pytest.fail("network during replay"))
    result = replay(root)
    assert result["jobs"] == 16 and result["network_calls"] == 0
    assert before == file_manifest(root)
    rows = read(root / "metrics/summary.json")["episodes"]
    assert len(rows) == 16 and all(row["physical_violations"] == 0 for row in rows)
    for planner in {row["planner"] for row in rows}:
        clean = [row["clean_completed"] for row in rows if row["planner"] == planner]
        assert len(set(clean)) == 1


def test_budget_partial_keeps_every_planned_job(tmp_path, baseline, model, monkeypatch):
    plan = tmp_path / "plan"
    prepare(plan, model, profile="orders-smoke", baseline=baseline)
    root = tmp_path / "run"
    report = execute(plan, root, budget=1, transport=transport(model, monkeypatch, ["malformed"]))
    assert report["status"] == "PARTIAL" and report["recorded_jobs"] == report["planned_jobs"] == 16
    assert not report["D6"]
    assert len(read(root / "audit/attempts.json")) == 1
    assert replay(root)["status"] == "PASS"  # honest partial results can replay successfully


def test_service_failure_partial_and_missing_usage(tmp_path, baseline, model, monkeypatch):
    plan = tmp_path / "plan"
    prepare(plan, model, profile="fixed", baseline=baseline)
    root = tmp_path / "run"
    report = execute(plan, root, budget=20,
                     transport=transport(model, monkeypatch, ["timeout", "missing_usage"]))
    assert report["status"] == "PARTIAL"
    summary = read(root / "metrics/summary.json")
    assert summary["api"]["missing_usage"] == 2
    assert summary["compilation"]["remote_text"]["planned_compilations"] == 2
    assert summary["api"]["cost"] is None


@pytest.mark.parametrize("target", ["metrics", "response", "attempts", "acceptance", "raw_text", "csv"])
def test_resigned_artifact_tampering_rejected(tmp_path, baseline, model, monkeypatch, target):
    plan = tmp_path / "plan"
    prepare(plan, model, profile="fixed", baseline=baseline)
    root = tmp_path / "run"
    execute(plan, root, budget=20, transport=transport(model, monkeypatch))
    if target == "metrics":
        path = root / "metrics/summary.json"
        value = read(path)
        value["api"]["first_valid"] = 999
    elif target == "response":
        path = next((root / "responses").glob("*.json"))
        value = read(path)
        value["response"]["policy_ast"]["rules"] = []
    elif target == "attempts":
        path = root / "audit/attempts.json"
        value = read(path)
        value[0]["body_digest"] = "0" * 64
    elif target == "raw_text":
        path = next((root / "responses").glob("*.json"))
        value = read(path)
        value["attempts"][0]["raw_text"] = "{}"
    elif target == "csv":
        (root / "metrics/per_episode.csv").write_text("fabricated\n")
        seal(root)
        with pytest.raises(O4Error):
            replay(root)
        return
    else:
        path = root / "acceptance_report.json"
        value = read(path)
        value["real_api_attempts"] = 999
    write(path, value)
    seal(root)
    with pytest.raises(O4Error):
        replay(root)


def test_overwrite_and_implicit_remote_rejected(tmp_path, baseline, model):
    root = tmp_path / "plan"
    prepare(root, model, profile="fixed", baseline=baseline)
    with pytest.raises(FileExistsError):
        prepare(root, model, profile="fixed", baseline=baseline)
    with pytest.raises(ValueError):
        execute(root, tmp_path / "run", budget=10)
    with pytest.raises(ValueError):
        execute(root, tmp_path / "run", budget=0)


def test_smoke_plan_is_predeclared_before_api_calls(tmp_path, baseline, model):
    root = tmp_path / "plan"
    plan = prepare(root, model, baseline=baseline)
    assert plan["fixed_cases"] == 12 and plan["maximum_api_attempts"] == 48
    assert plan["planned_episodes"] == 0
    assert len({job["case_id"] for job in plan["jobs"]}) == 12
    assert not (root / "responses").exists()
    assert read(root / "config.snapshot.json")["model"] == "deepseek-flash"
