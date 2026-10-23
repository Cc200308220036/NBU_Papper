"""O4-D failure, fairness and transmission contracts (no provider calls)."""
import base64
import copy
from dataclasses import replace
import io
import json
from pathlib import Path
from urllib import error

import pytest

from semantic_pallet_planner.config import generator_config, load_config
from semantic_pallet_planner.o4.common import O4Error, digest, read
from semantic_pallet_planner.o4.fixtures import gold_cases
from semantic_pallet_planner.o4.online.cases import diagnostic_scenario
from semantic_pallet_planner.o4.online.episode import episode as legacy_single
from semantic_pallet_planner.o4.buffer.buffer_evaluation import episode as legacy_buffer
from semantic_pallet_planner.o4.remote.compiler import RecordedCompiler, RemoteCompiler
from semantic_pallet_planner.o4.remote.audit import audit_episode
from semantic_pallet_planner.o4.remote.episode import PLANNERS, episode
from semantic_pallet_planner.o4.remote.evaluation import compilation_metrics
from semantic_pallet_planner.o4.remote.protocol import validate_envelope
from semantic_pallet_planner.o4.remote.protocol import validate_response
from semantic_pallet_planner.o4.remote.testing import ProtocolServiceDouble
from semantic_pallet_planner.o4.remote.transport import ChatTransport, ModelConfig, NoRedirect


@pytest.fixture
def model():
    return ModelConfig("https://api.deepseek.com/chat/completions", "deepseek-flash", api_key_env="O4_TEST_KEY")


@pytest.fixture
def source():
    return gold_cases()[0]["request"]


def compiler_at(root, model, monkeypatch, faults=(), budget=20):
    monkeypatch.setenv(model.api_key_env, "PRIVATE_TEST_SENTINEL_0123456789")
    service = ProtocolServiceDouble(faults)
    client = ChatTransport(model, opener=service, test_double=True)
    return RemoteCompiler(root, client, budget), service


@pytest.mark.parametrize("faults,attempts,first,repaired,status", [
    ([], 1, True, False, "valid"),
    (["malformed", "valid"], 2, False, True, "valid"),
    (["stale", "valid"], 2, False, True, "valid"),
    (["malformed", "stale", "valid"], 2, False, False, "invalid_binding"),
    (["timeout", "valid"], 1, False, False, "provider_error"),
])
def test_first_repair_failure_contract(tmp_path, model, source, monkeypatch,
                                      faults, attempts, first, repaired, status):
    compiler, service = compiler_at(tmp_path, model, monkeypatch, faults)
    record = compiler.compile(source, "image")
    assert len(service.requests) == attempts
    assert (record["first_valid"], record["repaired_valid"], record["status"]) == (first, repaired, status)
    assert len(compiler.ledger.rows) == attempts
    assert RecordedCompiler([record]).compile(source, "image") == record
    for request in service.requests:
        public_text = request["messages"][1]["content"][0]["text"]
        assert "reference_policy" not in public_text
        assert "candidates" not in public_text
        assert "PRIVATE_TEST_SENTINEL" not in public_text
    if attempts == 2:
        repaired_input = json.loads(service.requests[1]["messages"][1]["content"][0]["text"])
        assert repaired_input["repair_error"] in ("invalid_ast", "invalid_binding")


def test_exact_png_bytes_and_same_facts(tmp_path, model, source, monkeypatch):
    compiler, service = compiler_at(tmp_path, model, monkeypatch)
    text = compiler.compile(source, "text")
    image = compiler.compile(source, "image")
    assert len(service.requests[0]["messages"][1]["content"]) == 1
    assert text["envelope"]["visual_facts"] == image["envelope"]["visual_facts"]
    assert text["envelope"]["public_request"]["placed_objects"] == image["envelope"]["public_request"]["placed_objects"]
    for asset, data in zip(image["envelope"]["images"], service.image_bytes):
        assert data == (tmp_path / asset["path"]).read_bytes()
    assert service.requests[0]["model"] == service.requests[1]["model"] == "deepseek-flash"
    assert service.requests[0]["messages"][0] == service.requests[1]["messages"][0]


def test_valid_wrong_ast_never_repaired(tmp_path, model, source, monkeypatch):
    compiler, service = compiler_at(tmp_path, model, monkeypatch, ["drop_rules"])
    record = compiler.compile(source, "text")
    case = gold_cases()[0]
    metrics = compilation_metrics(source, record["response"], case["reference_policy"], case["candidates"])
    assert record["first_valid"] and len(service.requests) == 1
    assert not metrics["semantic_equal"] and metrics["false_allow_ids"] == ["TOP"]


@pytest.mark.parametrize("budget,faults,expected_attempts", [(0, [], 0), (1, ["malformed"], 1)])
def test_budget_includes_repairs(tmp_path, model, source, monkeypatch, budget, faults, expected_attempts):
    compiler, service = compiler_at(tmp_path, model, monkeypatch, faults, budget)
    record = compiler.compile(source, "image")
    assert record["status"] == "budget_exhausted" and record["response"] is None
    assert len(service.requests) == len(compiler.ledger.rows) == expected_attempts
    RecordedCompiler([record]).compile(source, "image")


@pytest.mark.parametrize("field,value", [
    ("max_images", 1), ("max_image_bytes", 1), ("max_image_pixels", 1),
    ("max_image_side", 1), ("max_request_bytes", 1),
])
def test_attachment_limits_fail_before_http(tmp_path, model, source, monkeypatch, field, value):
    compiler, service = compiler_at(tmp_path, replace(model, **{field: value}), monkeypatch)
    record = compiler.compile(source, "image")
    assert record["response"] is None and not service.requests and not compiler.ledger.rows
    assert record["status"] in ("image_limit", "request_limit")


def test_missing_usage_and_no_secret_artifacts(tmp_path, model, source, monkeypatch):
    compiler, _ = compiler_at(tmp_path, model, monkeypatch, ["missing_usage"])
    record = compiler.compile(source, "text")
    assert record["attempts"][0]["usage"] is None
    for path in tmp_path.rglob("*.json"):
        assert "PRIVATE_TEST_SENTINEL_0123456789" not in path.read_text()


def test_changed_public_state_cannot_reuse_envelope(tmp_path, model, source, monkeypatch):
    compiler, _ = compiler_at(tmp_path, model, monkeypatch)
    record = compiler.compile(source, "image")
    changed = copy.deepcopy(source)
    changed["instruction_text"] += " changed"
    with pytest.raises(O4Error):
        validate_envelope(record["envelope"], changed)
    with pytest.raises(O4Error):
        RecordedCompiler([record]).compile(changed, "image")


def test_credentials_only_in_header_and_http_failure_sanitized(tmp_path, model, source, monkeypatch):
    compiler, service = compiler_at(tmp_path, model, monkeypatch)
    seen = []

    def failing_opener(request, timeout):
        seen.append(request)
        raise error.HTTPError(request.full_url, 429, "secret response", {}, io.BytesIO(b"API_KEY_SECRET"))

    compiler.transport = ChatTransport(model, opener=failing_opener, test_double=True)
    record = compiler.compile(source, "image")
    assert record["status"] == "provider_error" and len(seen) == 1
    assert seen[0].get_header("Authorization").startswith("Bearer ")
    assert b"PRIVATE_TEST_SENTINEL" not in seen[0].data
    assert "API_KEY_SECRET" not in json.dumps(record)


def test_non_json_http_reply_kept_without_retry(tmp_path, model, source, monkeypatch):
    compiler, _ = compiler_at(tmp_path, model, monkeypatch)
    compiler.transport = ChatTransport(model, opener=lambda *args, **kwargs: io.BytesIO(b"maintenance page"), test_double=True)
    record = compiler.compile(source, "text")
    assert record["status"] == "provider_error" and len(record["attempts"]) == 1
    assert record["attempts"][0]["raw_text"] == "maintenance page"
    assert RecordedCompiler([record]).compile(source, "text") == record


@pytest.mark.parametrize("endpoint", ["http://example.com/chat/completions", "https://u:p@example.com/chat/completions",
                                      "https://example.com/chat/completions?key=secret", "https://example.com/"])
def test_endpoint_validation(endpoint):
    with pytest.raises(ValueError):
        ModelConfig(endpoint, "deepseek-flash").validate()


def test_redirect_and_unlabelled_injection_rejected(model):
    with pytest.raises(O4Error):
        NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example")
    with pytest.raises(ValueError):
        ChatTransport(model, opener=lambda *args: None)
    with pytest.raises(ValueError):
        ChatTransport(model, test_double=True)


@pytest.mark.parametrize("planner", PLANNERS)
def test_all_planners_preserve_frozen_trajectories(planner):
    scenario, attributes, task = diagnostic_scenario()
    # Real datasets have unplaced item facts without cached physics fields.
    for item in scenario["items"]:
        item.pop("supported_load_kg", None)
        item.pop("support_fractions", None)
    config = generator_config(load_config())
    result, events = episode(scenario, attributes, task, "public_parser", planner, config)
    expected, old_events, _ = legacy_buffer(scenario, attributes, task, planner, "public_parser", config)
    assert result["placed_sequence"] == expected["placed_sequence"]
    assert result["termination_reason"] == expected["termination_reason"]
    assert result["physical_violations"] == result["final_business_violation_count"] == 0
    if planner == "single_greedy":
        single, _ = legacy_single(scenario, attributes, task, "public_parser", config)
        assert result["placed_items"] == single["placed_items"]
    assert all(event["search_trace"]["evaluations"] <= 256 for event in events if event["search_trace"])
    assert audit_episode(events, scenario, task["reference_policy"])["status"] == "PASS"


@pytest.mark.parametrize("planner", ["single_greedy", "buffer_search"])
def test_wrong_model_ast_commits_visible_business_errors(tmp_path, model, monkeypatch, planner):
    scenario, attributes, task = diagnostic_scenario()
    compiler, service = compiler_at(tmp_path, model, monkeypatch, ["drop_rules"] * 10)
    summary, events = episode(scenario, attributes, task, "remote_image", planner,
                              generator_config(load_config()), compiler)
    assert summary["completed"] and not summary["clean_completed"]
    assert summary["final_business_violation_count"] > 0 and summary["physical_violations"] == 0
    assert len(service.requests) == len(compiler.records)  # no repair for semantic mistakes
    assert summary["wait_requests"] > 0
    for record in compiler.records:
        assert all(not key.startswith("reference") for key in record["envelope"])


def test_model_failure_keeps_pending_boxes(tmp_path, model, monkeypatch):
    scenario, attributes, task = diagnostic_scenario()
    compiler, service = compiler_at(tmp_path, model, monkeypatch, ["timeout"])
    summary, events = episode(scenario, attributes, task, "remote_image", "buffer_search",
                              generator_config(load_config()), compiler)
    assert summary["termination_reason"] == "provider_error"
    assert len(summary["pending_ids"]) == 3 and summary["placed_items"] == 0
    assert len(service.requests) == 1 and not any(event["search_trace"] for event in events)


def test_swap_slots_rejects_old_response_even_with_resigned_state(tmp_path, model, monkeypatch):
    scenario, attributes, task = diagnostic_scenario()
    compiler, _ = compiler_at(tmp_path, model, monkeypatch)
    episode(scenario, attributes, task, "remote_image", "buffer_search",
            generator_config(load_config()), compiler)
    record = compiler.records[0]
    source = copy.deepcopy(record["envelope"]["public_request"])
    a, b = source["pending_items"][:2]
    a["slot"], b["slot"] = b["slot"], a["slot"]
    source["buffer_state_hash"] = digest({key: value for key, value in source.items() if key != "buffer_state_hash"})
    with pytest.raises(O4Error, match="invalid_binding"):
        validate_response(record["response"], source)


def test_changed_future_does_not_change_first_buffer_request(tmp_path, model, monkeypatch):
    scenario, attributes, task = diagnostic_scenario()
    # Make a fourth box that is outside the initial three public arrivals.
    extra = copy.deepcopy(scenario["items"][-1])
    extra["item_id"] = "future"
    scenario["items"].append(extra)
    scenario["arrival_order"].append("future")
    attributes["future"] = dict(copy.deepcopy(attributes["third"]), object_id="future")
    compiler, _ = compiler_at(tmp_path / "a", model, monkeypatch)
    episode(scenario, attributes, task, "remote_text", "buffer_search", generator_config(load_config()), compiler)
    altered = copy.deepcopy(scenario)
    altered["items"][-1]["mass_kg"] = 99
    other, _ = compiler_at(tmp_path / "b", model, monkeypatch)
    episode(altered, attributes, task, "remote_text", "buffer_search", generator_config(load_config()), other)
    assert compiler.records[0]["source"] == other.records[0]["source"]
