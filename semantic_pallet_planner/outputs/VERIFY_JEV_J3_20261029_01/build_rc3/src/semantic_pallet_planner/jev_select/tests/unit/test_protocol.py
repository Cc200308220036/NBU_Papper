import copy
import json

import pytest

from semantic_pallet_planner.o4.extensions.e2.protocol import rebind
from semantic_pallet_planner.jev_select.config import load_config, generator_config
from semantic_pallet_planner.jev_select.context import ContextBuilder, resolve_display_id, validate_context
from semantic_pallet_planner.jev_select.contracts import (
    DecisionContext, JevSelectError, MemorySnapshot, PublicPolicyContext, canonical, digest, validate_schema,
)


@pytest.mark.parametrize("key,value", [
    ("endpoint", "https://api.typesafe.ai/v1/chat/completions"), ("model", "jev-latest"),
    ("per_object_top_k", 17), ("joint_candidates_max", 49), ("buffer_capacity", 4),
    ("max_retries", True), ("unknown", 1), ("timeout_s", float("nan")),
    ("memory_mode", "dynamic"), ("feature_version", "features_layout_v1"),
    ("selectable_pool", "physical_only"),
])
def test_closed_config_rejects_unsupported_values(tmp_path, key, value):
    config = load_config()
    config[key] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(JevSelectError):
        load_config(path)


def test_resources_do_not_depend_on_working_directory(tmp_path, monkeypatch):
    expected = load_config()
    monkeypatch.chdir(tmp_path)
    assert load_config() == expected
    assert generator_config()["candidate_generator"]["top_k"] == 16


def test_joint_48_options_and_complete_action_mapping(pipeline):
    case, config, _, bundle, context = pipeline
    value = context.data
    assert len(value["criteria"]) == 48
    assert set(value["request_body"]) == {"model", "state", "questions"}
    assert value["request_body"]["questions"]["next_action"]["type"] == "choice"
    actions = [resolve_display_id(context, label, case["observation"], bundle, config)
               for label in value["criteria"]]
    assert len({c["pick_item_id"] for c in actions}) == 3
    assert {c["candidate_id"] for c in actions} == {c["candidate_id"] for c in bundle.data["selectable_candidates"]}
    assert all(len({str(c["pose"]) for c in actions if c["pick_item_id"] == pick}) > 1
               for pick in {c["pick_item_id"] for c in actions})


def test_snapshots_are_not_mutated_by_readers(pipeline):
    _, _, _, bundle, context = pipeline
    before = context.data
    context.data["display_mapping"].clear()
    bundle.data["physical_candidates"].clear()
    assert context.data == before
    assert len(bundle.data["physical_candidates"]) == 48


@pytest.mark.parametrize("field", ["request_body", "display_mapping", "local_binding"])
def test_tampering_is_rejected(pipeline, field):
    case, config, _, bundle, context = pipeline
    value = context.data
    if field == "request_body":
        value[field]["questions"]["next_action"]["criteria"]["C01"]["pose"]["x_mm"] += 1
    elif field == "display_mapping":
        value[field]["C01"]["candidate_id"] = "forged"
    else:
        value[field]["memory_digest"] = "0" * 64
    with pytest.raises(JevSelectError):
        validate_context(DecisionContext.from_dict(value), case["observation"], bundle, config)


def test_stale_observation_and_unknown_choice_rejected(pipeline):
    case, config, _, bundle, context = pipeline
    newer = copy.deepcopy(case["observation"])
    newer["request_id"] = "next-decision"
    newer = rebind(newer)
    with pytest.raises(JevSelectError, match="stale"):
        resolve_display_id(context, "C01", newer, bundle, config)
    with pytest.raises(JevSelectError, match="unknown_display"):
        resolve_display_id(context, "C99", case["observation"], bundle, config)


def test_private_answers_and_raw_candidate_ids_absent(pipeline):
    _, _, _, bundle, context = pipeline
    body = context.data["request_body"]
    encoded = canonical(body)
    for name in ("policy_ast", "reference_policy", "source_order_key", "future_items", "split", "candidate_fingerprint"):
        assert f'"{name}"' not in encoded
    for c in bundle.data["physical_candidates"]:
        assert c["candidate_id"] not in encoded
        assert c["pick_item_id"] not in encoded
    assert body["state"]["memories"] == []


def test_nonempty_memory_rejected_in_j0(pipeline):
    case, config, policy, bundle, _ = pipeline
    with pytest.raises(JevSelectError, match="memory_not_implemented"):
        ContextBuilder(config).build(case["observation"], bundle, policy,
                                    MemorySnapshot.from_dict({"version": "other", "cards": ["advice"]}))


def test_resigned_wrong_pick_mapping_still_rejected(pipeline):
    case, config, _, bundle, context = pipeline
    value = context.data
    value["criteria"]["C01"]["pick_object"] = "B999"
    value["request_body"]["questions"]["next_action"]["criteria"] = copy.deepcopy(value["criteria"])
    value["local_binding"]["criteria_digest"] = digest(value["criteria"])
    value["local_binding"]["request_body_digest"] = digest(value["request_body"])
    with pytest.raises(JevSelectError, match="changed_candidate_mapping"):
        validate_context(DecisionContext.from_dict(value), case["observation"], bundle, config)


def test_request_budget_rejects_without_dropping_options(pipeline):
    case, config, policy, bundle, _ = pipeline
    config = dict(config, max_request_bytes=1000)
    with pytest.raises(JevSelectError, match="request_too_large"):
        ContextBuilder(config).build(case["observation"], bundle, policy)


@pytest.mark.parametrize("capacity,expected", [(1, 16), (2, 32), (3, 48)])
def test_supported_buffer_sizes(capacity, expected):
    from semantic_pallet_planner.jev_select.experiment import constructed_cases, _compute
    case = constructed_cases(capacity)[0]
    config = dict(load_config(), buffer_capacity=capacity)
    bundle, context = _compute(case, config)
    assert len(bundle["physical_candidates"]) == len(context["criteria"]) == expected
