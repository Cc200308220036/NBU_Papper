"""Arithmetic declarations for new compositions; no parser-derived expectations."""
from ..evaluator import reference_state
from ..executor import evaluate_state
from ..fixtures import item
from ..observation import public_object
from .specifications import specification


def reference_gold():
    rows = []
    # Each tuple declares the expected effective limit independently of the AST.
    profiles = [
        ("glassware", True, False, 4., 5., 1.5),
        ("electronics", True, False, 4., 5., 1.5),
        ("electronics", True, False, 1., 5., 5.),
        ("glassware", True, True, 4., 0., 0.),
        ("general", True, False, 4., 5., 5.),
        ("glassware", False, False, 4., 5., 1.5),
    ]
    for index, (category, reinforced, marked, mass, contact_limit, mass_limit) in enumerate(profiles):
        for family, expected in (("contact_exclusion", contact_limit), ("mass_override", mass_limit)):
            base = item("base", category=category, reinforced=reinforced, no_top=marked, mass=mass)
            top = item("top", category="general", mass=2., z=100)
            objects = [public_object(o, o["_attributes"], True) for o in (base, top)]
            ast = specification(family)
            a, b = evaluate_state(objects, ast), reference_state(objects, ast)
            violations = ["load:base"] if 2. > expected + 1e-6 else []
            passed = (a["limits_kg"]["base"] == b["limits_kg"]["base"] == expected
                      and a["violations"] == b["violations"] == violations)
            rows.append({"case_id": f"load_{index}_{family}", "expected_limit_kg": expected,
                         "expected_violations": violations, "passed": passed})
    for reinforced in (False, True):
        for gap in (0., 1.):
            a = item("a", category="food", reinforced=reinforced)
            b = item("b", category="household_cleaner", x=100. + gap)
            objects = [public_object(o, o["_attributes"], True) for o in (a, b)]
            expected = ["contact:a:b"] if not reinforced and gap == 0 else []
            runtime = evaluate_state(objects, specification("contact_exclusion"))
            reference = reference_state(objects, specification("contact_exclusion"))
            rows.append({"case_id": f"contact_{reinforced}_{gap}", "expected_violations": expected,
                         "passed": runtime["violations"] == reference["violations"] == expected})
    return {"status": "PASS" if all(r["passed"] for r in rows) else "FAIL", "cases": rows,
            "expectation_source": "explicit limit/contact arithmetic, not parser/executor-generated answers",
            "human_review": "NOT_PERFORMED"}
