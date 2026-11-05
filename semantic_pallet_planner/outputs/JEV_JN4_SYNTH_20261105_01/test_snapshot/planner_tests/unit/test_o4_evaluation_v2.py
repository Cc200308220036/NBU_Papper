"""Declared equivalences, independent components and counterexamples."""
import ast
import copy
from pathlib import Path

import pytest

from semantic_pallet_planner.o4.common import O4Error
from semantic_pallet_planner.o4.evaluation_v2 import compare_policies, compilation_metrics, normalized_signature, summarize
from semantic_pallet_planner.o4.evaluator import reference_state
from semantic_pallet_planner.o4.fixtures import eq, fixture_request, item, policy, rule, candidate, task_policy
from semantic_pallet_planner.o4.compiler import response_for


def test_zero_load_alias_is_equal_without_mutating_inputs():
    actual, expected = policy([rule(kind="no_top_load")]), policy([rule(limit=0)])
    before = copy.deepcopy((actual, expected))
    result = compare_policies(actual, expected)
    assert result["semantic_equal"] and not result["raw_ast_equal"]
    assert all(result[key] for key in ("limits_equal", "priority_equal", "overrides_equal", "selector_structure_equal"))
    assert (actual, expected) == before


@pytest.mark.parametrize("limit", [1., 1e-12, 1e-6, "label"])
def test_positive_or_field_limit_is_not_zero(limit):
    result = compare_policies(policy([rule(kind="no_top_load")]), policy([rule(limit=limit)]))
    assert not result["semantic_equal"] and not result["limits_equal"]
    assert result["applicable_objects_equal"] and result["conditions_exceptions_equal"]


def test_wrong_limit_does_not_become_wrong_object_or_condition():
    base = item("base")
    req = fixture_request([base], item("top"), policy([rule(limit=2)]))
    result = compilation_metrics(req, response_for(req, policy([rule(limit=3)])), policy([rule(limit=2)]), [candidate()])
    assert result["valid_ast"] and not result["semantic_equal"] and not result["limits_equal"]
    assert result["applicable_objects_equal"] and result["selector_structure_equal"]
    assert result["conditions_exceptions_equal"] and result["overrides_equal"]
    assert result["allowed_set_equal"]  # one current action can conceal a wrong threshold


def test_wrong_selector_can_match_current_objects_but_not_full_policy():
    glass = item("base", category="glassware")
    req = fixture_request([glass], item("top", category="glassware"), policy([rule(limit=0)]))
    wrong = policy([rule(kind="no_top_load", target=eq("cargo_category", "glassware"))])
    result = compilation_metrics(req, response_for(req, wrong), policy([rule(limit=0)]), [candidate()])
    assert result["applicable_objects_equal"] and result["allowed_set_equal"]
    assert not result["selector_structure_equal"] and not result["semantic_equal"]
    assert result["limits_equal"] is None and result["component_alignment"] == "SCOPE_MISMATCH"


def test_changed_priority_is_preserved():
    a, b = policy([rule(kind="no_top_load", priority=10)]), policy([rule(limit=0, priority=20)])
    result = compare_policies(a, b)
    assert not result["semantic_equal"] and not result["priority_equal"]
    assert result["limits_equal"] and result["conditions_exceptions_equal"]


def test_missing_override_is_wrong_even_with_same_current_action():
    expected = task_policy(4)
    actual = copy.deepcopy(expected)
    actual["rules"][-1]["overrides"] = []
    result = compare_policies(actual, expected)
    assert not result["semantic_equal"] and not result["overrides_equal"] and not result["conditions_exceptions_equal"]
    assert result["selector_structure_equal"] and result["limits_equal"] and result["priority_equal"]


def test_missing_rules_and_ambiguous_rules_do_not_get_free_component_credit():
    assert not compare_policies(policy([]), policy([rule(limit=0)]))["semantic_equal"]
    p = policy([rule("a", limit=0), rule("b", limit=1)])
    result = compare_policies(p, copy.deepcopy(p))
    assert result["semantic_equal"] and result["component_alignment"] == "AMBIGUOUS"
    assert result["limits_equal"] is result["overrides_equal"] is None
    summary = summarize([compilation_metrics(fixture_request([], item("top"), p), None, p, [])])
    assert summary["metrics"]["semantic_equal"]["correct"] == 0
    assert summary["metrics"]["limits_equal"]["not_comparable"] == 1
    assert summary["metrics"]["limits_equal"]["planned_denominator"] == 1


def test_ids_order_subexpressions_and_contact_symmetry():
    expected = task_policy(5)
    actual = copy.deepcopy(expected)
    names = {r["rule_id"]: "renamed_" + r["rule_id"] for r in actual["rules"]}
    for r in actual["rules"]:
        r["rule_id"] = names[r["rule_id"]]
        r["overrides"] = [names[t] for t in r["overrides"]]
        if "target" in r and "and" in r["target"]:
            r["target"]["and"].reverse()
        if r["type"] == "forbidden_contact":
            r["left"], r["right"] = r["right"], r["left"]
    actual["rules"].reverse()
    result = compare_policies(actual, expected)
    assert result["semantic_equal"] and result["overrides_equal"]


def test_contact_exclusion_is_not_erased():
    actual = policy([rule(kind="forbidden_contact")])
    expected = copy.deepcopy(actual)
    expected["rules"][0]["left"] = {"and": [eq("cargo_category", "food"), {"not": eq("packaging.reinforced", True)}]}
    assert not compare_policies(actual, expected)["semantic_equal"]
    same = compare_policies(actual, actual)
    assert same["semantic_equal"] and same["limits_equal"] is None


def test_exact_numeric_representation_and_large_integer_precision():
    a, b = policy([rule(limit=2)]), policy([rule(limit=2)])
    a["rules"][0]["target"] = {"ge": {"field": "mass_kg", "value": 3}}
    b["rules"][0]["target"] = {"ge": {"field": "mass_kg", "value": 3.0}}
    assert compare_policies(a, b)["semantic_equal"]
    a["rules"][0]["target"]["ge"]["value"] = 9007199254740993
    b["rules"][0]["target"]["ge"]["value"] = 9007199254740992
    assert not compare_policies(a, b)["semantic_equal"]


@pytest.mark.parametrize("bad", [False, float("nan"), float("inf"), -1, "0"])
def test_invalid_zero_like_limits_are_rejected(bad):
    p = policy([rule(limit=0)])
    p["rules"][0]["limit"]["constant_kg"] = bad
    with pytest.raises(O4Error):
        normalized_signature(p)


def test_invalid_override_and_unknown_object_are_rejected():
    p = policy([rule(limit=0, overrides=["missing"])])
    with pytest.raises(O4Error):
        normalized_signature(p)
    req = fixture_request([], item("top"), policy([rule()]))
    wrong = policy([rule(target={"object_ids": ["future"]})])
    assert not compilation_metrics(req, response_for(req, wrong), policy([rule()]), [candidate(z=0)])["valid_ast"]


@pytest.mark.parametrize("load", [0, 1e-6, 1.000001e-6, 1, 3])
def test_alias_has_identical_independent_load_behavior(load):
    a, b = policy([rule(kind="no_top_load")]), policy([rule(limit=0)])
    req = fixture_request([item("base")], item("top", mass=load, z=100), a)
    objects = req["placed_objects"] + [dict(req["available_objects"][0], pose={"x_mm": 0, "y_mm": 0, "z_base_mm": 100, "yaw_deg": 0}, oriented_size_mm=[100, 100, 100])]
    assert reference_state(objects, a) == reference_state(objects, b)


def test_evaluator_has_no_runtime_or_client_imports():
    from semantic_pallet_planner.o4 import evaluation_v2
    tree = ast.parse(Path(evaluation_v2.__file__).read_text())
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(any(word in module for word in ("executor", "normalize", "compiler", "remote", "planner")) for module in modules)
