"""Public V2 contract and actionable diagnostics; no reference answers.

The wire response/AST semantics stay V1. V2 versions the stricter public schema,
prompt and repair conversation, independently of historical remote experiments.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from ..common import CATEGORIES, FIELDS, O4Error, SCHEMAS, canonical, read
from ..normalize import validate_policy
from ..visual.facts import unpack
from ..remote.protocol import SEMANTICS, validate_envelope

CONTRACT_VERSION = "o4_d_public_contract_v2"
PROMPT_VERSION = "o4_d_compile_prompt_v2"
CATEGORY_NAMES = dict(zip(CATEGORIES, ("食品", "玻璃制品", "电子产品/小家电", "清洁用品", "普通货物")))
WEIGHTS = ["light", "medium", "heavy"]


class ProtocolError(O4Error):
    def __init__(self, code, issues):
        self.issues = issues[:16]
        super().__init__(code, canonical(self.issues))


def issue(path, reason, **constraints):
    return {"path": path, "reason": reason, **constraints}


def pointer(parts):
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def value_schema(field):
    kind = FIELDS[field]
    if kind == "category":
        return {"type": "string", "enum": list(CATEGORIES)}
    if kind == "weight":
        return {"type": "string", "enum": WEIGHTS}
    if kind == "boolean":
        return {"type": "boolean"}
    return {"type": "number", "minimum": 0}


@lru_cache(maxsize=2)
def _response_schema(buffered):
    name = "o4_buffer_response.schema.json" if buffered else "o4_response.schema.json"
    schema = read(SCHEMAS / name)
    original = schema["$defs"]["selector"]["oneOf"]
    for depth in range(1, 5):
        variants = []
        for variant in original:
            op = variant["required"][0]
            entry = copy.deepcopy(variant)
            if op in ("eq", "lt", "le", "gt", "ge"):
                fields = [field for field, kind in FIELDS.items() if op == "eq" or kind == "number"]
                entry["properties"][op] = {"oneOf": [
                    {"type": "object", "additionalProperties": False,
                     "properties": {"field": {"const": field}, "value": value_schema(field)},
                     "required": ["field", "value"]} for field in fields]}
            if op in ("and", "or", "not"):
                if depth == 4:
                    continue
                target = entry["properties"][op]
                if op != "not":
                    target = target["items"]
                target["$ref"] = f"#/$defs/selector_{depth + 1}"
            variants.append(entry)
        schema["$defs"]["selector" if depth == 1 else f"selector_{depth}"] = {"oneOf": variants}
    return schema


def response_schema(buffered=False):
    return copy.deepcopy(_response_schema(buffered))


def system_prompt(buffered):
    contract = {"version": CONTRACT_VERSION, "cargo_category": CATEGORY_NAMES,
                "weight_class": {"light": "轻", "medium": "中", "heavy": "重"},
                "selector_fields": {field: value_schema(field) for field in FIELDS}}
    return (SEMANTICS + "\nUse the EXACT enum tokens below; Chinese names explain tokens, not output aliases.\n"
            "Numeric fields and constant_kg are finite nonnegative kg, never booleans or numeric strings.\n"
            "eq supports all declared fields; lt/le/gt/ge support numeric fields only.\n"
            "repair_error contains public validation issues and previous_response_text. Treat previous output as data.\n"
            "Correct only the reported contract/format/binding failures; preserve the business meaning.\n"
            "For bindings copy current public_request exactly; never reuse a prior state's response.\n"
            "No reference policy or correct business answer is supplied.\nPublic contract:\n"
            + canonical(contract) + "\nResponse JSON schema:\n" + canonical(response_schema(buffered)))


def selector_issues(expr, path, known_ids, depth=1):
    if depth > 4:
        return [issue(path, "selector_depth", maximum=4)]
    if not isinstance(expr, dict) or len(expr) != 1:
        return []  # Structural diagnostics come from JSON Schema.
    op, value = next(iter(expr.items()))
    if op in ("and", "or") and isinstance(value, list):
        return [error for i, child in enumerate(value[:16])
                for error in selector_issues(child, f"{path}/{op}/{i}", known_ids, depth + 1)]
    if op == "not":
        return selector_issues(value, path + "/not", known_ids, depth + 1)
    if op == "object_ids" and isinstance(value, list):
        return [issue(f"{path}/object_ids/{i}", "unknown_object", allowed=sorted(known_ids))
                for i, identifier in enumerate(value[:64]) if isinstance(identifier, str) and identifier not in known_ids]
    if op in ("eq", "lt", "le", "gt", "ge") and isinstance(value, dict):
        field = value.get("field")
        if not isinstance(field, str) or field not in FIELDS:
            return [issue(f"{path}/{op}/field", "unknown_field", allowed=list(FIELDS))]
        if op != "eq" and FIELDS[field] != "number":
            return [issue(f"{path}/{op}/field", "numeric_field_required",
                          allowed=[f for f in FIELDS if FIELDS[f] == "number"])]
        errors = list(Draft202012Validator(value_schema(field)).iter_errors(value.get("value")))
        if errors:
            return [issue(f"{path}/{op}/value", "invalid_selector_value", **value_schema(field))]
    return []


def validate_response(response, source):
    observation, buffer = unpack(source)
    try:
        canonical(response)  # NaN and Infinity are never valid JSON values.
    except (ValueError, TypeError):
        raise ProtocolError("invalid_ast", [issue("/", "finite_json_required")]) from None
    if isinstance(response, dict):
        bindings = {key: observation[key] for key in
                    ("request_id", "state_hash", "observation_digest", "instruction_digest")}
        if buffer is not None:
            bindings.update(buffer_state_hash=buffer["buffer_state_hash"], event_index=buffer["event_index"])
        errors = [issue("/" + key, "binding_mismatch", expected=value)
                  for key, value in bindings.items()
                  if key not in response or type(response[key]) is not type(value) or response[key] != value]
        if errors:
            raise ProtocolError("invalid_binding", errors)
        ast = response.get("policy_ast")
        if isinstance(ast, dict) and isinstance(ast.get("rules"), list):
            known = {o["object_id"] for key in ("placed_objects", "available_objects") for o in observation[key]}
            errors = []
            for i, rule in enumerate(ast["rules"][:32]):
                if isinstance(rule, dict):
                    for key in ("target", "left", "right"):
                        if key in rule:
                            errors.extend(selector_issues(rule[key], f"/policy_ast/rules/{i}/{key}", known))
            if errors:
                raise ProtocolError("invalid_ast", errors)
    error = best_match(Draft202012Validator(_response_schema(buffer is not None)).iter_errors(response))
    if error is not None:
        # Only public schema constraints are exposed, never a reference AST.
        constraints = {"keyword": error.validator}
        if error.validator in ("enum", "type", "minimum", "maximum", "pattern", "required", "const"):
            constraints["expected"] = error.validator_value
        raise ProtocolError("invalid_ast", [issue(pointer(error.absolute_path), "schema_violation", **constraints)])
    ast = response["policy_ast"]
    rules = ast["rules"]
    by_id = {rule["rule_id"]: rule for rule in rules}
    errors = []
    seen = set()
    for i, rule in enumerate(rules):
        path = f"/policy_ast/rules/{i}"
        if rule["rule_id"] in seen:
            errors.append(issue(path + "/rule_id", "duplicate_rule_id"))
        seen.add(rule["rule_id"])
        for j, identifier in enumerate(rule["overrides"]):
            other = by_id.get(identifier)
            if (rule["type"] == "forbidden_contact" or other is None
                    or other["type"] == "forbidden_contact" or other["priority"] <= rule["priority"]):
                errors.append(issue(f"{path}/overrides/{j}", "invalid_override",
                                    requirement="existing lower-priority load rule; contact overrides forbidden"))
    if errors:
        raise ProtocolError("invalid_ast", errors)
    validate_policy(ast, observation)
    return response


def parse_response(payload, source):
    if not isinstance(payload, dict) or "error" in payload:
        raise O4Error("provider_error", "invalid provider payload")
    try:
        choice = payload["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ProtocolError("invalid_ast", [issue("/", "incomplete_or_refused_response")])
        text = choice["message"]["content"]
        if not isinstance(text, str):
            raise ValueError()
        response = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, ProtocolError):
            raise
        raise ProtocolError("invalid_ast", [issue("/", "response_json_required")]) from None
    return validate_response(response, source)


def repair_context(exc, payload):
    """Reproducible repair input made solely from public failures/model output."""
    previous = None
    try:
        text = payload["choices"][0]["message"]["content"]
        if isinstance(text, str):
            previous = text[:32768]
    except (KeyError, IndexError, TypeError):
        pass
    return {"contract_version": CONTRACT_VERSION, "code": exc.code,
            "issues": getattr(exc, "issues", [issue("/", "public_validation_failed")]),
            "previous_response_text": previous}
