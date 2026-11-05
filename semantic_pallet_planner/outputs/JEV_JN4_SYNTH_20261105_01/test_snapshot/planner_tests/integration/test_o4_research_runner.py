"""Real encoding offline, full denominators, source isolation and sealed replay."""
import copy
import json
from pathlib import Path
import shutil

import pytest

from semantic_pallet_planner.o4.common import O4Error, digest, read, write
from semantic_pallet_planner.o4.remote.transport import ChatTransport, ModelConfig
from semantic_pallet_planner.o4.remote_v2.experiment import file_manifest
from semantic_pallet_planner.o4.research.data import DEFAULT_CONFIG, build, verify
from semantic_pallet_planner.o4.research.experiment import execute, prepare, replay
from semantic_pallet_planner.o4.research.testing import StudyServiceDouble
from semantic_pallet_planner.o4.research.overlay import import_expressions


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    base = tmp_path_factory.mktemp("study")
    design = read(DEFAULT_CONFIG)
    design["sources"] = {key: 2 for key in design["sources"]}
    design["items_per_order"] = 3
    design["fixed_repeats"] = {key: 1 for key in design["sources"]}
    design["fixed_repeats"]["test"] = 2
    design["bootstrap_samples"] = 100
    design["online_repeats"] = {key: 1 for key in design["sources"]}
    write(base / "design.json", design)
    raw = {f"TEST_SOURCE_{i}": {"properties": {"order_nr": f"TEST_SOURCE_{i}"}, "item_sequence": {
        str(j): {"length/mm": 100 + i, "width/mm": 100, "height/mm": 100,
                 "weight/kg": 1., "sequence": j + 1} for j in range(3)}} for i in range(8)}
    write(base / "bed.json", raw)
    root = base / "corpus"
    report = build(root, base / "design.json", base / "bed.json")
    assert report["status"] == "PASS" and report["sources"] == 6
    return root


@pytest.fixture
def model():
    return ModelConfig("https://api.deepseek.com/chat/completions", "deepseek-flash", api_key_env="O4_STUDY_TEST_KEY")


def transport(model, monkeypatch, faults=()):
    monkeypatch.setenv(model.api_key_env, "STUDY_PRIVATE_SENTINEL")
    service = StudyServiceDouble(faults)
    return ChatTransport(model, opener=service, test_double=True), service


def test_corpus_sources_template_families_and_compositions_are_separate(corpus):
    before = file_manifest(corpus)
    assert verify(corpus)["fixed_cases"] == 76
    assert file_manifest(corpus) == before
    registry = read(corpus / "private/source_registry.json")
    groups = {split: {r["source_order_key"] for r in registry if r["split"] == split} for split in ("development", "calibration", "test")}
    assert not groups["development"] & groups["test"] and not groups["calibration"] & groups["test"]
    data = read(corpus / "private/input_snapshot.json")
    assert all(r["split"] == "test" for r in data["fixed"] if r["track"] == "combination")
    for r in data["fixed"]:
        text = json.dumps(r["request"])
        assert "source_order_key" not in text and "reference_policy" not in text and "candidates" not in text
        assert set(r["request"]["available_objects"][0]) >= {"object_id", "mass_kg"}


def test_external_expression_import_keeps_references_and_originals(tmp_path, corpus):
    before = file_manifest(corpus)
    data = read(corpus / "private/input_snapshot.json")
    cases = [c for c in data["fixed"] if c["split"] == "test" and c["track"] == "expression"]
    overlay = {"schema_version": "o4_research_expression_overlay_v1", "provenance": "test-only authored input, not real human review",
               "split": "test", "rows": [{"case_id": c["case_id"], "text": "外部表达测试：" + c["request"]["instruction_text"],
                                           "template_family": "external_test_family"} for c in cases]}
    write(tmp_path / "overlay.json", overlay)
    result = import_expressions(corpus, tmp_path / "overlay.json", tmp_path / "new")
    assert result["status"] == "PASS" and file_manifest(corpus) == before
    imported = read(tmp_path / "new/private/input_snapshot.json")
    assert [c["reference_policy"] for c in imported["fixed"]] == [c["reference_policy"] for c in data["fixed"]]
    assert read(tmp_path / "new/audit/expression_overlay.json")["human_signature"] is None
    assert all(t["instruction_text"].startswith("外部表达测试：") for t in imported["tasks"] if t["split"] == "test" and t["track"] == "expression")


def test_fixed_five_backends_repeat_pairing_and_network_free_replay(tmp_path, corpus, model, monkeypatch):
    plan, run = tmp_path / "plan", tmp_path / "run"
    p = prepare(corpus, plan, model, split="test")
    assert p["units"] == 28 and p["planned_jobs"] == 280 and p["maximum_api_attempts"] == 224
    client, service = transport(model, monkeypatch)
    result = execute(plan, run, budget=224, transport=client)
    assert result["status"] == "PASS" and result["D4"] and result["real_api_attempts"] == 0
    assert result["parser_unsupported_retained"] > 0
    attempts = read(run / "audit/attempts.json")
    assert len(attempts) == len(service.requests) == 112
    text_rows = read(run / "metrics/study_summary.json")
    assert all(c["paired_sources"] == 2 and not c["confirmatory_claim"] for c in text_rows["comparisons"])
    before = file_manifest(run)
    monkeypatch.delenv(model.api_key_env)
    monkeypatch.setattr(ChatTransport, "complete", lambda *a: pytest.fail("network during replay"))
    assert replay(run)["network_calls"] == 0
    assert file_manifest(run) == before


@pytest.mark.parametrize("planner", ["single_greedy", "buffer_fifo", "buffer_heuristic", "buffer_search"])
def test_online_keeps_unsupported_failures_and_audits_events(tmp_path, corpus, model, monkeypatch, planner):
    plan, run = tmp_path / "plan", tmp_path / "run"
    p = prepare(corpus, plan, model, mode="online", split="development", planner=planner)
    assert p["planned_jobs"] == 40
    client, _ = transport(model, monkeypatch)
    report = execute(plan, run, budget=p["maximum_api_attempts"], transport=client)
    assert report["status"] == "PASS" and report["physical_violations"] == 0
    assert report["parser_unsupported_retained"] == 4
    assert len(read(run / "audit/events.json")) == 40
    assert all(a["status"] == "PASS" for a in read(run / "audit/events.json"))
    rows = read(run / "metrics/rows.json")
    assert all(r["measures"]["planned_items"] == 3 for r in rows)


@pytest.mark.parametrize("faults", [["malformed"], ["timeout"]])
def test_budget_or_service_failure_partial_keeps_all_jobs(tmp_path, corpus, model, monkeypatch, faults):
    plan, run = tmp_path / "plan", tmp_path / "run"
    p = prepare(corpus, plan, model, split="calibration")
    client, _ = transport(model, monkeypatch, faults)
    report = execute(plan, run, budget=1, transport=client)
    assert report["status"] == "PARTIAL" and report["recorded_jobs"] == p["planned_jobs"]
    assert len(read(run / "audit/attempts.json")) == 1
    assert len(read(run / "metrics/rows.json")) == p["planned_jobs"]


def test_re_signed_statistics_tampering_is_rejected(tmp_path, corpus, model, monkeypatch):
    plan, run = tmp_path / "plan", tmp_path / "run"
    p = prepare(corpus, plan, model, split="development")
    client, _ = transport(model, monkeypatch)
    execute(plan, run, budget=p["maximum_api_attempts"], transport=client)
    value = read(run / "metrics/study_summary.json")
    value["comparisons"][0]["mean_difference"] = 999
    write(run / "metrics/study_summary.json", value)
    write(run / "delivery_manifest.json", {"files": file_manifest(run)})
    with pytest.raises(O4Error, match="study statistics"):
        replay(run)


def test_implicit_remote_overwrite_and_cross_version_are_rejected(tmp_path, corpus, model):
    plan = tmp_path / "plan"
    prepare(corpus, plan, model)
    with pytest.raises(FileExistsError):
        prepare(corpus, plan, model)
    with pytest.raises(ValueError):
        execute(plan, tmp_path / "run", budget=10)
    altered = read(plan / "plan.json")
    altered["version"] = "o4_d_remote_v2"
    write(plan / "plan.json", altered)
    manifest = read(plan / "manifest.json")
    manifest["plan_digest"] = digest(altered)
    write(plan / "manifest.json", manifest)
    write(plan / "delivery_manifest.json", {"files": file_manifest(plan)})
    with pytest.raises(O4Error, match="version"):
        execute(plan, tmp_path / "run", budget=10)
