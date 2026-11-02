"""Separate declarative semantics, finite witnesses and candidate outcomes."""
from collections import defaultdict
from functools import lru_cache
import copy
import json

import numpy as np

from ..common import canonical
from ..evaluator import _accept, audit_reference, reference_state, semantic_signature
from ..executor import evaluate_candidates
from ..fixtures import item
from ..observation import public_object


def policy_signature(value):
    # Selectors in the historical signature contain serialized JSON strings;
    # canonicalize numeric representations before producing those strings.
    def numbers(obj):
        if type(obj) in (int, float):
            return float(obj)
        if isinstance(obj, list):
            return [numbers(v) for v in obj]
        if isinstance(obj, dict):
            return {k: numbers(v) for k, v in obj.items()}
        return obj
    return semantic_signature(numbers(value))


def applicability(policy, objects):
    result = []
    for rule in policy["rules"]:
        targets = (sorted(obj["object_id"] for obj in objects if _accept(obj, rule["target"])) if "target" in rule
                   else sorted([sorted(obj["object_id"] for obj in objects if _accept(obj, rule[side])) for side in ("left", "right")]))
        result.append([policy_signature({"rules": [dict(rule, overrides=[])]}), targets])
    return sorted(result, key=canonical)


def witness_states():
    """Both matching/nonmatching conditions, load boundaries and contact pairs."""
    profiles = [("glassware", True, False, 4), ("glassware", False, False, 4),
                ("glassware", True, True, 4), ("electronics", True, False, 4),
                ("electronics", True, False, 1), ("general", False, False, 4),
                ("food", True, False, 4), ("food", False, False, 4)]
    for category, reinforced, marked, mass in profiles:
        for load in (0., 1e-6, 2e-6, 1.5, 1.500002, 2., 2.000002, 5., 5.000002):
            base = item("w_base", category=category, reinforced=reinforced, no_top=marked, mass=mass)
            upper = item("w_top", category="household_cleaner", mass=load, z=100)
            yield [public_object(o, o["_attributes"], True) for o in (base, upper)]
    for left, right in (("food", "household_cleaner"), ("glassware", "household_cleaner"), ("food", "general")):
        for reinforced in (False, True):
            for gap in (0., 1.):
                a = item("w_a", category=left, reinforced=reinforced)
                b = item("w_b", category=right, x=100 + gap)
                yield [public_object(o, o["_attributes"], True) for o in (a, b)]


@lru_cache(maxsize=512)
def finite_witnesses(actual_text, expected_text):
    actual, expected = json.loads(actual_text), json.loads(expected_text)
    failures, count = [], 0
    for objects in witness_states():
        a, b = reference_state(objects, actual), reference_state(objects, expected)
        count += 1
        if any(a[key] != b[key] for key in ("limits_kg", "violations", "contact_pairs")):
            failures.append(count)
    return {"finite_behavior_equal": not failures, "probe_count": count,
            "counterexample_indices": failures,
            "scope": "84 declared load/contact states; finite evidence, not general logical equivalence"}


def compilation_metrics(observation, response, reference, candidates):
    expected = audit_reference(observation, reference, candidates)["allowed_ids"]
    out = {"valid_ast": response is not None, "semantic_equal": False, "applicable_objects_equal": False,
           "conditions_exceptions_equal": False, "finite_behavior_equal": False, "allowed_set_equal": False,
           "false_allow_ids": [], "false_reject_ids": [], "reference_allowed_ids": expected,
           "method_allowed_ids": None, "reference_feasible": bool(expected), "witnesses": None}
    if response is None:
        return out
    actual = response["policy_ast"]
    semantic = policy_signature(actual) == policy_signature(reference)
    objects = observation["placed_objects"] + observation["available_objects"]
    allowed = evaluate_candidates(observation, actual, candidates)["allowed_ids"]
    witnesses = finite_witnesses(canonical(actual), canonical(reference))
    out.update(valid_ast=True, semantic_equal=semantic, conditions_exceptions_equal=semantic,
               applicable_objects_equal=applicability(actual, objects) == applicability(reference, objects),
               finite_behavior_equal=witnesses["finite_behavior_equal"], witnesses=copy.deepcopy(witnesses),
               allowed_set_equal=set(allowed) == set(expected), method_allowed_ids=allowed,
               false_allow_ids=sorted(set(allowed) - set(expected)), false_reject_ids=sorted(set(expected) - set(allowed)))
    return out


def _interval(values, seed, draws):
    array = np.asarray(values, dtype=float)
    if len(array) < 2:
        return None
    rng = np.random.default_rng(seed)
    means = array[rng.integers(0, len(array), size=(draws, len(array)))].mean(axis=1)
    return [float(np.quantile(means, .025)), float(np.quantile(means, .975))]


def summarize(rows, design):
    """Pair methods, average repeats within case, then average within source.

    CIs condition on the frozen synthetic template bank. They do not establish
    generalization to an independent population of language template families.
    """
    grouped, comparisons, invariance = defaultdict(list), [], []
    for row in rows:
        grouped[(row["track"], row["backend"])].append(row)
    groups = []
    for (track, backend), subset in sorted(grouped.items()):
        keys = ("clean_completed", "placed_item_ratio") if subset[0]["kind"] == "episode" else (
            "valid_ast", "semantic_equal", "finite_behavior_equal", "applicable_objects_equal", "allowed_set_equal")
        groups.append({"track": track, "backend": backend, "planned_records": len(subset),
                       "source_groups": len({r["source_order_key"] for r in subset}),
                       "status_counts": {status: sum(r["status"] == status for r in subset) for status in sorted({r["status"] for r in subset})},
                       "metrics": {key: sum(float(r["measures"].get(key, False)) for r in subset) / len(subset) for key in keys}})
    primary = "clean_completed" if rows and rows[0]["kind"] == "episode" else "semantic_equal"
    lookup = {(r["unit_id"], r["repeat"], r["backend"]): r for r in rows}
    for track in sorted({r["track"] for r in rows}):
        for left, right in (("remote_text", "normalized_parser"), ("remote_image", "normalized_parser"),
                            ("remote_image", "remote_text")):
            by_source, progress = defaultdict(list), defaultdict(list)
            by_template = defaultdict(list)
            for row in rows:
                if row["track"] != track or row["backend"] != left:
                    continue
                other = lookup.get((row["unit_id"], row["repeat"], right))
                if other is None:
                    continue
                difference = float(row["measures"].get(primary, False)) - float(other["measures"].get(primary, False))
                by_source[row["source_order_key"]].append(difference)
                by_template[row["template_family"]].append(difference)
                if row["kind"] == "episode":
                    progress[row["source_order_key"]].append(row["measures"]["placed_item_ratio"] - other["measures"]["placed_item_ratio"])
            values = [sum(v) / len(v) for _, v in sorted(by_source.items())]
            ci = _interval(values, design["seed"], design["bootstrap_samples"])
            mean = sum(values) / len(values) if values else None
            progress_ci = _interval([sum(v) / len(v) for _, v in sorted(progress.items())], design["seed"], design["bootstrap_samples"])
            comparisons.append({"track": track, "left": left, "right": right, "metric": primary,
                                "paired_sources": len(values), "mean_difference": mean, "exploratory_95_interval": ci,
                                "template_family_means": {key: sum(v) / len(v) for key, v in by_template.items()},
                                "practical_gain_threshold": design["practical_gain"],
                                "exploratory_gain_criterion_met": bool(ci and ci[0] > 0 and mean >= design["practical_gain"]
                                    and (not progress or (progress_ci and progress_ci[0] >= -design["progress_noninferiority_margin"]))),
                                "progress_difference_interval": progress_ci, "confirmatory_claim": False})
    pairs = defaultdict(dict)
    for row in rows:
        if row["kind"] == "fixed" and row["track"] in ("control", "expression"):
            pairs[(row["source_order_key"], row["family"], row["backend"], row["repeat"])][row["track"]] = row
    for backend in sorted({row["backend"] for row in rows}):
        subset = [pair for key, pair in pairs.items() if key[2] == backend and set(pair) == {"control", "expression"}]
        if subset:
            invariance.append({"backend": backend, "pairs": len(subset),
                "both_semantic_correct": sum(p["control"]["measures"]["semantic_equal"] and p["expression"]["measures"]["semantic_equal"] for p in subset),
                "both_valid_and_same_allowed_set": sum(p["control"]["measures"]["valid_ast"] and p["expression"]["measures"]["valid_ast"]
                    and p["control"]["measures"]["method_allowed_ids"] == p["expression"]["measures"]["method_allowed_ids"] for p in subset)})
    return {"groups": groups, "comparisons": comparisons, "expression_pairs": invariance,
            "primary_metric": primary, "failures_retained": True,
            "inference": design["inference"], "power_certified": False,
            "interval_scope": "paired source-clustered; conditional on synthetic template bank; no population-level language CI",
            "multiplicity": "exploratory intervals, no multiplicity-adjusted confirmatory claim"}
