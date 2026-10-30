"""Independent, versioned evaluation of declared O4 rule equivalences.

No compiler, runtime normalizer/executor, planner or client imports. This module
only scores policy copies; it cannot repair responses or influence actions.
"""
from collections import Counter, defaultdict
from decimal import Decimal
from functools import lru_cache
import math

from .common import CATEGORIES, FIELDS, O4Error, canonical, validate
from .evaluator import _accept, audit_reference

VERSION = "o4_equivalence_evaluator_v2"
SCOPE = "zero-load alias, exact numeric value, ID/order and existing selector/contact symmetry; not arbitrary logical equivalence"


def _number(value):
    """Exact decimal representation of a JSON number; no epsilon rounding."""
    if type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)):
        raise O4Error("invalid_ast", "finite numeric value required")
    text = format(Decimal(str(value)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _validate(policy, objects):
    # Independent protocol checks, not a call to the runtime normalizer.
    validate("policy", policy)
    ids = {o["object_id"] for o in objects} if objects is not None else None

    def selector(expr, depth=1):
        if depth > 4:
            raise O4Error("invalid_ast", "selector depth exceeds 4")
        op, value = next(iter(expr.items()))
        if op in ("and", "or"):
            for child in value:
                selector(child, depth + 1)
        elif op == "not":
            selector(value, depth + 1)
        elif op == "object_ids":
            if ids is not None and not set(value) <= ids:
                raise O4Error("invalid_ast", "unknown object")
        elif op != "all":
            kind, v = FIELDS[value["field"]], value["value"]
            if op != "eq" and kind != "number":
                raise O4Error("invalid_ast", "ordered comparison requires numeric field")
            if kind == "number":
                _number(v)
                if v < 0:
                    raise O4Error("invalid_ast", "negative selector")
            elif kind == "boolean" and type(v) is not bool:
                raise O4Error("invalid_ast", "boolean selector required")
            elif kind == "category" and v not in CATEGORIES:
                raise O4Error("invalid_ast", "unknown category")
            elif kind == "weight" and v not in ("light", "medium", "heavy"):
                raise O4Error("invalid_ast", "unknown weight class")

    lookup = {r["rule_id"]: r for r in policy["rules"]}
    if len(lookup) != len(policy["rules"]):
        raise O4Error("invalid_ast", "duplicate rule id")
    for r in policy["rules"]:
        for key in ("target", "left", "right"):
            if key in r:
                selector(r[key])
        for target in r["overrides"]:
            other = lookup.get(target)
            if (r["type"] == "forbidden_contact" or other is None
                    or other["type"] == "forbidden_contact" or other["priority"] <= r["priority"]):
                raise O4Error("invalid_ast", "invalid override graph")


def _selector(expr):
    op, value = next(iter(expr.items()))
    if op in ("and", "or"):
        return {op: sorted({canonical(_selector(child)) for child in value})}
    if op == "not":
        return {op: _selector(value)}
    if op == "object_ids":
        return {op: sorted(value)}
    if op == "all":
        return {op: value}
    v = {"number": _number(value["value"])} if FIELDS[value["field"]] == "number" else value["value"]
    return {op: {"field": value["field"], "value": v}}


def _scope(rule):
    if rule["type"] == "forbidden_contact":
        return {"family": "contact", "sides": sorted([_selector(rule["left"]), _selector(rule["right"])], key=canonical)}
    return {"family": "load", "target": _selector(rule["target"])}


def _limit(rule):
    if rule["type"] == "no_top_load":
        return {"constant_kg": "0"}
    if rule["type"] == "max_top_load":
        if "constant_kg" in rule["limit"]:
            return {"constant_kg": _number(rule["limit"]["constant_kg"])}
        return {"field": rule["limit"]["field"]}
    return None


def _signature(policy):
    lookup = {r["rule_id"]: r for r in policy["rules"]}

    @lru_cache(maxsize=32)
    def node(identifier):
        r = lookup[identifier]
        # Priorities and the explicit graph are retained, even where a priority
        # change alone happens to have no effect in the current state.
        return {"scope": _scope(r), "limit": _limit(r), "priority": _number(r["priority"]),
                "overrides": sorted([node(target) for target in r["overrides"]], key=canonical)}

    return sorted([node(r["rule_id"]) for r in policy["rules"]], key=canonical)


def normalized_signature(policy):
    _validate(policy, None)
    return {"version": VERSION, "rules": _signature(policy)}


def _object_sets(policy, objects):
    rows = []
    for r in policy["rules"]:
        if r["type"] == "forbidden_contact":
            sets = sorted([sorted(o["object_id"] for o in objects if _accept(o, r[side])) for side in ("left", "right")])
            rows.append({"family": "contact", "sets": sets})
        else:
            rows.append({"family": "load", "objects": sorted(o["object_id"] for o in objects if _accept(o, r["target"]))})
    return sorted(rows, key=canonical)


def compare_policies(actual, reference, objects=None):
    objects = tuple(objects) if objects is not None else None
    _validate(actual, objects)
    _validate(reference, objects)
    left, right = defaultdict(list), defaultdict(list)
    for policy, target in ((actual, left), (reference, right)):
        for r in policy["rules"]:
            target[canonical(_scope(r))].append(r)
    scope_equal = Counter({k: len(v) for k, v in left.items()}) == Counter({k: len(v) for k, v in right.items()})
    alignment = "UNIQUE" if scope_equal and all(len(v) == 1 for v in left.values()) else "AMBIGUOUS" if scope_equal else "SCOPE_MISMATCH"
    limits = priorities = overrides = None
    if alignment == "UNIQUE":
        load_scopes = [k for k in left if left[k][0]["type"] != "forbidden_contact"]
        limits = all(_limit(left[k][0]) == _limit(right[k][0]) for k in load_scopes) if load_scopes else None
        priorities = all(_number(left[k][0]["priority"]) == _number(right[k][0]["priority"]) for k in left)

        def edges(policy, groups):
            names = {r["rule_id"]: canonical(_scope(r)) for r in policy["rules"]}
            return {k: sorted(names[t] for t in v[0]["overrides"]) for k, v in groups.items()}

        overrides = edges(actual, left) == edges(reference, right)
    return {"evaluator_version": VERSION, "equivalence_scope": SCOPE,
            "raw_ast_equal": actual == reference, "semantic_equal": _signature(actual) == _signature(reference),
            "rule_count_equal": len(actual["rules"]) == len(reference["rules"]),
            "selector_structure_equal": scope_equal,
            "applicable_objects_equal": _object_sets(actual, objects or ()) == _object_sets(reference, objects or ()),
            "limits_equal": limits, "priority_equal": priorities, "overrides_equal": overrides,
            "conditions_exceptions_equal": False if not scope_equal else overrides,
            "component_alignment": alignment,
            "component_note": "scope-based unique rule alignment; null means unidentifiable or no applicable load rule, not correct",
            "actual_signature": _signature(actual), "reference_signature": _signature(reference)}


def compilation_metrics(observation, response, reference, candidates):
    objects = observation["placed_objects"] + observation["available_objects"]
    _validate(reference, objects)
    expected = audit_reference(observation, reference, candidates)["allowed_ids"]
    out = {"evaluator_version": VERSION, "valid_ast": False, "validation_error": None,
           "raw_ast_equal": False, "semantic_equal": False, "rule_count_equal": None,
           "selector_structure_equal": None, "applicable_objects_equal": None,
           "limits_equal": None, "priority_equal": None, "overrides_equal": None,
           "conditions_exceptions_equal": None, "component_alignment": "NO_VALID_AST",
           "allowed_set_equal": False, "reference_allowed_ids": expected, "method_allowed_ids": None,
           "false_allow_ids": [], "false_reject_ids": [], "policy_comparison": None}
    if response is None:
        return out
    try:
        comparison = compare_policies(response["policy_ast"], reference, objects)
    except (O4Error, KeyError, TypeError, ValueError) as exc:
        out["validation_error"] = str(exc)
        return out
    actual = audit_reference(observation, response["policy_ast"], candidates)["allowed_ids"]
    for key in ("raw_ast_equal", "semantic_equal", "rule_count_equal", "selector_structure_equal", "applicable_objects_equal",
                "limits_equal", "priority_equal", "overrides_equal", "conditions_exceptions_equal", "component_alignment"):
        out[key] = comparison[key]
    out.update(valid_ast=True, policy_comparison=comparison, method_allowed_ids=actual,
               allowed_set_equal=set(actual) == set(expected), false_allow_ids=sorted(set(actual) - set(expected)),
               false_reject_ids=sorted(set(expected) - set(actual)))
    return out


def summarize(rows):
    keys = ("valid_ast", "raw_ast_equal", "semantic_equal", "rule_count_equal", "selector_structure_equal",
            "applicable_objects_equal", "limits_equal", "priority_equal", "overrides_equal",
            "conditions_exceptions_equal", "allowed_set_equal")
    return {"evaluator_version": VERSION, "planned_records": len(rows), "metrics": {
        key: {"correct": sum(r[key] is True for r in rows), "comparable": sum(r[key] is not None for r in rows),
              "not_comparable": sum(r[key] is None for r in rows), "planned_denominator": len(rows)} for key in keys},
        "false_allow_count": sum(len(r["false_allow_ids"]) for r in rows),
        "false_reject_count": sum(len(r["false_reject_ids"]) for r in rows)}
