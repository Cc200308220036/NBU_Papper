import copy

import pytest

from semantic_pallet_planner.o4.extensions.e2.data import candidate, object_at, policy, request, gold_cases
from semantic_pallet_planner.o4.extensions.e2.protocol import rebind, validate_candidates
from semantic_pallet_planner.o4.fixtures import rule
from semantic_pallet_planner.jev_select.candidates import (
    CandidateProvider, PublicBusinessGuard, decision_route, validate_bundle,
)
from semantic_pallet_planner.jev_select.config import generator_config, load_config
from semantic_pallet_planner.jev_select.context import ContextBuilder
from semantic_pallet_planner.jev_select.contracts import CandidateBundle, JevSelectError, PublicPolicyContext, digest


@pytest.mark.parametrize("count", [0, 1, 2, 48])
def test_boundary_routes(pipeline, count):
    case, config, policy_context, bundle, _ = pipeline
    raw = bundle.data
    raw["physical_candidates"] = raw["physical_candidates"][:count]
    raw["physical_digest"] = digest(raw["physical_candidates"])
    raw["selectable_candidates"] = []
    raw["selectable_digest"] = digest([])
    raw["policy_digest"] = None
    raw["selectable_pool"] = "unfiltered"
    filtered = PublicBusinessGuard().filter(case["observation"], policy_context, CandidateBundle.from_dict(raw), config)
    context = ContextBuilder(config).build(case["observation"], filtered, policy_context)
    expected = "STOP_NO_PHYSICAL_CANDIDATE" if count == 0 else "SINGLETON_BYPASS" if count == 1 else "CHOICE_REQUIRED"
    assert decision_route(filtered) == context.data["route"] == expected
    assert (context.data["request_body"] is None) == (count < 2)


def test_more_than_joint_limit_rejected(pipeline):
    case, _, _, bundle, _ = pipeline
    candidates = bundle.data["physical_candidates"]
    extra = copy.deepcopy(candidates[0]); extra["candidate_id"] = "another"
    with pytest.raises(ValueError):
        validate_candidates(case["observation"], candidates + [extra])


def test_future_environment_metadata_cannot_change_request(pipeline):
    case, config, policy_context, bundle, context = pipeline
    future = copy.deepcopy(case["state"])
    future.update(future_items=[{"secret": "next-100-boxes"}], reference_policy={"secret": "answer"}, source_order_key="private-order")
    future["pending_items"][0]["item"]["private_debug_answer"] = "do not expose"
    fresh = CandidateProvider().build(future, case["observation"], generator_config())
    fresh = PublicBusinessGuard().filter(case["observation"], policy_context, fresh, config)
    assert fresh.data == bundle.data
    assert ContextBuilder(config).build(case["observation"], fresh, policy_context).data == context.data


def test_provider_rejects_stale_public_facts(pipeline):
    case, *_ = pipeline
    state = copy.deepcopy(case["state"])
    state["pending_items"][0]["item"]["mass_kg"] += 1
    with pytest.raises(JevSelectError, match="stale_observation"):
        CandidateProvider().build(state, case["observation"], generator_config())


def test_hidden_policy_cannot_override_public_instruction(pipeline):
    case, config, policy_context, bundle, _ = pipeline
    forged = policy_context.data
    forged["response"]["policy_ast"] = policy([rule("secret", "no_top_load")])
    with pytest.raises(JevSelectError, match="invalid_public_policy"):
        PublicBusinessGuard().filter(case["observation"], PublicPolicyContext.from_dict(forged), bundle, config)


def test_hard_pool_is_not_old_soft_budget(pipeline):
    case, config, policy_context, bundle, _ = pipeline
    legacy = dict(config, selectable_pool="legacy_soft_eligible")
    result = PublicBusinessGuard().filter(case["observation"], policy_context, bundle, legacy)
    assert {c["candidate_id"] for c in result.data["selectable_candidates"]} <= {c["candidate_id"] for c in bundle.data["selectable_candidates"]}
    assert result.data["selectable_pool"] == "legacy_soft_eligible"


@pytest.mark.parametrize("limit,expected", [(2., False), (3., True)])
def test_indirect_load_uses_cumulative_public_rule(limit, expected):
    req, _ = request(policy([rule("load", target={"object_ids": ["base"]}, limit=limit)]),
                     placed=[object_at("base"), object_at("middle", z=100, mass=1.)],
                     available=[object_at("top", mass=2.)])
    c = candidate(z=200, pick="top")
    guard = PublicBusinessGuard()
    result = guard.evaluate(req, guard.resolve(req), [c]).data
    assert bool(result["allowed_ids"]) == expected
    assert result["evaluations"][0]["after"]["loads_kg"]["base"] == 3.


def test_no_top_load_and_contact_are_checked():
    for ast, base, top, c in [
        (policy([rule("no_top", "no_top_load", target={"object_ids": ["base"]})]),
         object_at("base"), object_at("top"), candidate(z=100, pick="top")),
        (policy([rule("contact", "forbidden_contact")]), object_at("base", "food"),
         object_at("top", "household_cleaner"), candidate(x=100, pick="top")),
    ]:
        req, _ = request(ast, placed=[base], available=[top])
        guard = PublicBusinessGuard()
        assert guard.evaluate(req, guard.resolve(req), [c]).data["allowed_ids"] == []


def test_request_generation_does_not_mutate_state(pipeline):
    case, *_ = pipeline
    before = copy.deepcopy(case)
    CandidateProvider().build(case["state"], case["observation"], generator_config())
    assert case == before


@pytest.mark.parametrize("case", gold_cases(), ids=lambda c: c["purpose"])
def test_public_guard_preserves_region_and_relative_semantics(case):
    # Feed only public request and action facts, never the fixture's reference AST.
    guard = PublicBusinessGuard()
    result = guard.evaluate(case["request"], guard.resolve(case["request"]), case["candidates"])
    assert result.data["allowed_ids"] == case["expected_allowed_ids"]


def test_unsupported_instruction_fails_without_model(pipeline):
    case, *_ = pipeline
    req = copy.deepcopy(case["observation"])
    req["instruction_text"] = "请发挥想象力摆好。"
    req = rebind(req)
    with pytest.raises(ValueError, match="unsupported"):
        PublicBusinessGuard().resolve(req)
