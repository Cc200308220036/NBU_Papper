"""Study separation, declared semantics, fair normalization and negative witnesses."""
import copy
from pathlib import Path

import pytest

from semantic_pallet_planner.config import WORKSPACE
from semantic_pallet_planner.o4.common import O4Error, read
from semantic_pallet_planner.o4.fixtures import gold_cases, policy
from semantic_pallet_planner.o4.research.data import DEFAULT_CONFIG, select_sources, validate_design
from semantic_pallet_planner.o4.research.episode import compile_source
from semantic_pallet_planner.o4.research.metrics import compilation_metrics, finite_witnesses, summarize
from semantic_pallet_planner.o4.research.parser import parse_normalized
from semantic_pallet_planner.o4.research.specifications import CORE, COMBINATIONS, instruction, specification
from semantic_pallet_planner.o4.compiler import response_for
from semantic_pallet_planner.o4.common import canonical


@pytest.mark.parametrize("family", CORE + COMBINATIONS)
@pytest.mark.parametrize("style", ["canonical", "development", "calibration", "heldout"])
def test_published_normalizer_and_declared_specification(family, style):
    from semantic_pallet_planner.o4.research.metrics import policy_signature
    assert policy_signature(parse_normalized(instruction(family, style))) == policy_signature(specification(family))


@pytest.mark.parametrize("family", CORE)
@pytest.mark.parametrize("style", ["natural_development", "natural_calibration", "natural_heldout"])
def test_natural_clauses_and_numeric_equivalence(family, style):
    from semantic_pallet_planner.o4.research.metrics import policy_signature
    assert policy_signature(parse_normalized(instruction(family, style))) == policy_signature(specification(family))
    a = specification("mass_override")
    b = copy.deepcopy(a)
    b["rules"][-1]["target"]["and"][1]["ge"]["value"] = 3.0
    assert policy_signature(a) == policy_signature(b)


def test_unsupported_parser_is_a_measured_failure():
    case = gold_cases()[0]
    source = copy.deepcopy(case["request"])
    source["instruction_text"] = "当前解析器不支持的完整表达。"
    from semantic_pallet_planner.o4.observation import rebind
    source = rebind(source)
    response, status, identifier = compile_source(source, "public_parser")
    assert response is None and status == "unsupported_construct" and identifier is None


def test_wrong_rules_and_contact_exceptions_have_finite_counterexamples():
    for family in ("marked", "exception", "contact", *COMBINATIONS):
        result = finite_witnesses(canonical(policy([])), canonical(specification(family)))
        assert not result["finite_behavior_equal"] and result["probe_count"] == 84
    changed = specification("contact_exclusion")
    changed["rules"][-1]["left"] = {"eq": {"field": "cargo_category", "value": "food"}}
    assert not finite_witnesses(canonical(changed), canonical(specification("contact_exclusion")))["finite_behavior_equal"]


def test_invalid_counts_against_all_opportunities():
    case = gold_cases()[0]
    result = compilation_metrics(case["request"], None, case["reference_policy"], case["candidates"])
    assert not result["valid_ast"] and not result["semantic_equal"] and not result["allowed_set_equal"]


def test_repetitions_do_not_inflate_source_count_and_missing_is_failure():
    design = read(DEFAULT_CONFIG)
    rows = []
    for source in ("a", "b"):
        for repeat in range(3):
            for backend in ("remote_text", "remote_image", "normalized_parser"):
                rows.append({"kind": "fixed", "unit_id": source, "repeat": repeat,
                    "source_order_key": source, "track": "expression", "family": "marked",
                    "template_family": "heldout", "backend": backend, "status": "invalid_ast" if backend == "remote_text" else "valid",
                    "measures": {"semantic_equal": backend != "remote_text", "valid_ast": backend != "remote_text"}})
    summary = summarize(rows, design)
    comparison = next(r for r in summary["comparisons"] if r["left"] == "remote_text")
    assert comparison["paired_sources"] == 2 and comparison["mean_difference"] == -1
    assert not comparison["confirmatory_claim"]
    assert all(group["source_groups"] == 2 and group["planned_records"] == 6 for group in summary["groups"])


def test_raw_source_selection_excludes_ids_and_geometry_clones():
    design = read(DEFAULT_CONFIG)
    design["sources"] = {key: 2 for key in design["sources"]}
    design["items_per_order"] = 3
    raw = {}
    for i in range(9):
        raw[str(i)] = {"properties": {"order_nr": str(i)}, "item_sequence": {
            str(j): {"length/mm": 100 + i, "width/mm": 100, "height/mm": 100,
                     "weight/kg": 1, "sequence": j} for j in range(3)}}
    raw["8"]["item_sequence"] = copy.deepcopy(raw["0"]["item_sequence"])
    selected, _ = select_sources(raw, {"excluded_source_values": ["0"]}, design)
    assert len(selected) == 6 and not {"0", "8"} & {r[0] for r in selected}
    assert selected == select_sources(raw, {"excluded_source_values": ["0"]}, design)[0]


def test_design_rejects_silent_scope_change():
    design = read(DEFAULT_CONFIG)
    design["primary_fixed_metric"] = "valid_ast"
    with pytest.raises(ValueError):
        validate_design(design)


def test_independently_declared_new_reference_gold():
    from semantic_pallet_planner.o4.research.validation import reference_gold
    report = reference_gold()
    assert report["status"] == "PASS" and len(report["cases"]) == 16
    assert any(r["expected_violations"] for r in report["cases"])
    assert any(not r["expected_violations"] for r in report["cases"])
