"""Contract regression against public facts and unmodified real V1 failures."""
import copy
import io
import json

import pytest
from jsonschema import Draft202012Validator

from semantic_pallet_planner.config import WORKSPACE
from semantic_pallet_planner.o4.common import CATEGORIES, O4Error, canonical, read
from semantic_pallet_planner.o4.compiler import parse_instruction, response_for
from semantic_pallet_planner.o4.fixtures import gold_cases
from semantic_pallet_planner.o4.remote.transport import ChatTransport, ModelConfig
from semantic_pallet_planner.o4.remote_v2.compiler import RemoteCompiler, audit_records
from semantic_pallet_planner.o4.remote_v2.protocol import (
    CONTRACT_VERSION, ProtocolError, parse_response, repair_context,
    response_schema, system_prompt, validate_response,
)


def public_response():
    case = gold_cases()[0]
    return case["request"], response_for(case["request"], copy.deepcopy(case["reference_policy"]))


@pytest.mark.parametrize("buffered", [False, True])
def test_schema_is_valid_and_prompt_publishes_all_enums(buffered):
    Draft202012Validator.check_schema(response_schema(buffered))
    text = system_prompt(buffered)
    assert CONTRACT_VERSION in text
    for value in (*CATEGORIES, "light", "medium", "heavy"):
        assert value in text


@pytest.mark.parametrize("field,value,op,valid", [
    ("cargo_category", "glassware", "eq", True),
    ("cargo_category", "glass", "eq", False),
    ("cargo_category", "cleaning_supplies", "eq", False),
    ("cargo_category", "清洁用品", "eq", False),
    ("cargo_category", "food", "lt", False),
    ("weight_class", "heavy", "eq", True),
    ("weight_class", "重", "eq", False),
    ("fragile", True, "eq", True),
    ("fragile", 1, "eq", False),
    ("mass_kg", 2.5, "ge", True),
    ("mass_kg", True, "eq", False),
    ("mass_kg", "2", "eq", False),
    ("mass_kg", -1, "eq", False),
])
def test_schema_runtime_agree_on_field_types(field, value, op, valid):
    source, response = public_response()
    response["policy_ast"]["rules"][0]["target"] = {op: {"field": field, "value": value}}
    assert Draft202012Validator(response_schema()).is_valid(response) == valid
    before = copy.deepcopy(response)
    if valid:
        assert validate_response(response, source) == before
    else:
        with pytest.raises(ProtocolError) as caught:
            validate_response(response, source)
        assert caught.value.issues[0]["path"].startswith("/policy_ast/rules/0/target/")
    assert response == before  # no coercion, alias substitution or rule repair


@pytest.mark.parametrize("depth,valid", [(4, True), (5, False)])
def test_depth_schema_matches_runtime(depth, valid):
    source, response = public_response()
    selector = {"all": True}
    for _ in range(depth - 1):
        selector = {"not": selector}
    response["policy_ast"]["rules"][0]["target"] = selector
    assert Draft202012Validator(response_schema()).is_valid(response) == valid
    if valid:
        validate_response(response, source)
    else:
        with pytest.raises(ProtocolError, match="selector_depth"):
            validate_response(response, source)


@pytest.mark.parametrize("field", ["request_id", "state_hash", "observation_digest", "instruction_digest"])
def test_binding_diagnostic_is_specific_and_never_rewrites(field):
    source, response = public_response()
    response[field] = "stale"
    with pytest.raises(ProtocolError) as caught:
        validate_response(response, source)
    assert caught.value.code == "invalid_binding"
    assert caught.value.issues == [{"path": "/" + field, "reason": "binding_mismatch", "expected": source[field]}]
    assert response[field] == "stale"


@pytest.mark.parametrize("choices", [[], None, [None], [{"message": None, "finish_reason": "stop"}]])
def test_malformed_provider_choice_has_public_diagnostic(choices):
    source, _ = public_response()
    with pytest.raises(ProtocolError) as caught:
        parse_response({"choices": choices}, source)
    assert caught.value.issues[0]["reason"] == "response_json_required"


def test_nonfinite_and_unknown_object_and_override_diagnostics():
    source, response = public_response()
    response["policy_ast"]["rules"][0]["target"] = {"eq": {"field": "mass_kg", "value": float("nan")}}
    with pytest.raises(ProtocolError, match="finite_json_required"):
        validate_response(response, source)
    source, response = public_response()
    response["policy_ast"]["rules"][0]["target"] = {"object_ids": ["future"]}
    with pytest.raises(ProtocolError, match="unknown_object"):
        validate_response(response, source)
    response["policy_ast"]["rules"][0]["target"] = {"all": True}
    response["policy_ast"]["rules"][0]["overrides"] = ["missing"]
    with pytest.raises(ProtocolError, match="invalid_override"):
        validate_response(response, source)


def test_existing_gold_and_fixed_public_grammar_still_validate():
    root = WORKSPACE / "semantic_pallet_planner/outputs/EXP_O4_AB_OFFLINE_20261021_01"
    data = read(root / "private/data.json")
    cases = data["gold"] + data["pairs"]
    assert len(cases) == 180
    for case in cases:
        source = case["request"]
        response = response_for(source, parse_instruction(source["instruction_text"]))
        assert validate_response(response, source) == response


def test_repair_uses_previous_output_and_public_diagnostics_and_replays(tmp_path, monkeypatch):
    source, response = public_response()
    response["policy_ast"]["rules"][0]["target"] = {"eq": {"field": "cargo_category", "value": "glass"}}
    seen = []

    def opener(request, timeout):
        body = json.loads(request.data)
        user = json.loads(body["messages"][1]["content"][0]["text"])
        seen.append(user)
        if len(seen) == 2:
            diagnostic = user["repair_error"]
            assert diagnostic["issues"][0]["path"] == "/policy_ast/rules/0/target/eq/value"
            assert diagnostic["issues"][0]["enum"] == list(CATEGORIES)
            previous = json.loads(diagnostic["previous_response_text"])
            assert previous == response
            previous["policy_ast"]["rules"][0]["target"]["eq"]["value"] = "glassware"
        else:
            previous = response
        payload = {"choices": [{"finish_reason": "stop", "message": {"content": canonical(previous)}}]}
        return io.BytesIO(canonical(payload).encode())

    model = ModelConfig("https://api.deepseek.com/chat/completions", "deepseek-flash")
    monkeypatch.setenv(model.api_key_env, "TEST_SECRET")
    encoder = ChatTransport(model, opener=opener, test_double=True)
    compiler = RemoteCompiler(tmp_path, encoder, 2)
    record = compiler.compile(source, "text")
    assert record["repaired_valid"] and not record["first_valid"]
    assert len(record["attempts"]) == 2
    assert seen[0]["repair_error"] is None
    assert "reference_policy" not in canonical(seen)
    audit_records([record], encoder, tmp_path, 2)
    altered = copy.deepcopy(record)
    altered["attempts"][0]["repair_diagnostic"]["issues"] = []
    with pytest.raises(O4Error, match="repair diagnostic"):
        audit_records([altered], encoder, tmp_path, 2)


def test_all_real_v1_terminal_failures_get_diagnostics_without_mutation():
    counts = {}
    checked = 0
    for name in ("EXP_O4_D_COMPILE_SMOKE_REAL_20261023_01", "EXP_O4_D_ORDERS_REAL_20261023_01"):
        for path in sorted((WORKSPACE / "semantic_pallet_planner/outputs" / name / "responses").glob("D*.json")):
            record = read(path)
            if record["status"] not in ("invalid_ast", "invalid_binding"):
                continue
            before = canonical(record)
            with pytest.raises(ProtocolError) as caught:
                parse_response(record["attempts"][-1]["payload"], record["envelope"]["public_request"])
            diagnostic = repair_context(caught.value, record["attempts"][-1]["payload"])
            assert diagnostic["issues"] and diagnostic["previous_response_text"]
            assert canonical(record) == before
            reason = diagnostic["issues"][0]["reason"]
            counts[reason] = counts.get(reason, 0) + 1
            checked += 1
    assert checked == 247
    assert counts["invalid_selector_value"] == 237
    assert counts["binding_mismatch"] >= 7
