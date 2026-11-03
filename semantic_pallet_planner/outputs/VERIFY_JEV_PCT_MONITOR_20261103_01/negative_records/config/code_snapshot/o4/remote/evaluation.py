"""Downstream independent semantic metrics; never used to select actions."""
from __future__ import annotations

from ..common import canonical
from ..evaluator import _accept, audit_reference, compare_policies, semantic_signature
from ..executor import evaluate_candidates


def applicability(policy: dict, objects: list[dict]) -> list:
    """Compare rule meaning and object sets independent of rule IDs/order."""
    result = []
    for rule in policy["rules"]:
        if "target" in rule:
            targets = sorted(obj["object_id"] for obj in objects if _accept(obj, rule["target"]))
        else:
            targets = sorted([
                sorted(obj["object_id"] for obj in objects if _accept(obj, rule[side]))
                for side in ("left", "right")
            ])
        signature = semantic_signature({"rules": [dict(rule, overrides=[])]})
        result.append([signature, targets])
    return sorted(result, key=canonical)


def compilation_metrics(observation: dict, response: dict | None,
                        reference: dict, candidates: list[dict]) -> dict:
    expected = audit_reference(observation, reference, candidates)
    result = {"valid_ast": response is not None, "semantic_equal": False,
              "applicable_objects_equal": False, "conditions_exceptions_equal": False,
              "allowed_set_equal": False, "false_allow_ids": [], "false_reject_ids": [],
              "reference_allowed_ids": expected["allowed_ids"], "method_allowed_ids": None,
              "policy_comparison": None}
    if response is None:
        return result
    actual = response["policy_ast"]
    objects = observation["placed_objects"] + observation["available_objects"]
    comparison = compare_policies(actual, reference, objects)
    allowed = evaluate_candidates(observation, actual, candidates)["allowed_ids"]
    actual_ids, expected_ids = set(allowed), set(expected["allowed_ids"])
    result.update(
        semantic_equal=comparison["semantic_equal"],
        applicable_objects_equal=applicability(actual, objects) == applicability(reference, objects),
        conditions_exceptions_equal=comparison["semantic_equal"],
        allowed_set_equal=actual_ids == expected_ids,
        false_allow_ids=sorted(actual_ids - expected_ids),
        false_reject_ids=sorted(expected_ids - actual_ids),
        method_allowed_ids=allowed, policy_comparison=comparison,
    )
    return result


def summarize_compilations(rows: list[dict]) -> dict:
    keys = ("valid_ast", "semantic_equal", "applicable_objects_equal",
            "conditions_exceptions_equal", "allowed_set_equal")
    return {"planned_compilations": len(rows), **{
        key: sum(bool(row[key]) for row in rows) for key in keys
    }, "false_allow_count": sum(len(row["false_allow_ids"]) for row in rows),
        "false_reject_count": sum(len(row["false_reject_ids"]) for row in rows),
        "denominator": "all planned compilation opportunities; failures retained"}
