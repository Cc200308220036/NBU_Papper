"""Validate A5 inputs and O4 responses without reading private reference data."""
from __future__ import annotations

import copy
import json

from ..common import O4Error, SCHEMAS, canonical, digest, read, validate
from ..compiler import validate_response as validate_single_response
from ..normalize import validate_policy
from ..visual.facts import unpack
from ..visual.verify import audit_facts


PROMPT_VERSION = "o4_d_compile_prompt_v1"
SEMANTICS = """You compile explicit Chinese pallet business instructions into JSON.
All supplied observations are exact simulated public facts, not reference answers.
Return ONLY the response object defined below. Copy binding fields exactly from
public_request (buffer: its observation, plus buffer_state_hash/event_index).
no_top_load means cumulative top load <= 0; max_top_load uses a constant kg or
each target's labels.max_top_load_kg. Loads include indirect support propagation.
forbidden_contact is symmetric direct positive-area face contact, not edge/point.
Category, reinforced packaging and fragile do not automatically imply rules.
Keep attribute selectors symbolic for future arrivals; explicit IDs may reference
only currently observed objects. No guesses, coordinates, actions or explanations.
Smaller priority is higher; overrides explicitly replace lower-priority load rules
only on matching objects. Contact exceptions use selector exclusions. Other load
rules conjoin (strictest limit). Business rules never relax independent physics.
Allowed selector fields: cargo_category, packaging.reinforced, labels.no_top_load,
labels.max_top_load_kg, physical_top_load_limit_kg, mass_kg, fragile, weight_class.
Maximum selector depth 4; maximum rules 32. Numeric selectors use kg.
If repair_error is present, fix format/bindings only. No answer is supplied.
"""


def system_prompt(buffered: bool) -> str:
    schema_name = "o4_buffer_response.schema.json" if buffered else "o4_response.schema.json"
    return SEMANTICS + "\nResponse JSON schema:\n" + canonical(read(SCHEMAS / schema_name))


def validate_envelope(envelope: dict, source: dict) -> None:
    keys = {"schema_version", "public_request", "visual_facts", "visual_facts_digest",
            "images", "condition", "binding_digest"}
    if set(envelope) != keys or envelope["schema_version"] != "o4_visual_input_v1":
        raise O4Error("invalid_visual_binding")
    condition = envelope["condition"]
    if condition not in ("text", "image") or bool(envelope["images"]) != (condition == "image"):
        raise O4Error("invalid_visual_binding")
    if envelope["binding_digest"] != digest({k: v for k, v in envelope.items() if k != "binding_digest"}):
        raise O4Error("invalid_visual_binding")
    observation, buffer = unpack(envelope["public_request"])
    if observation["images"] != envelope["images"]:
        raise O4Error("invalid_visual_binding")
    # Rebuild the image-free source. Changes to slots/EOS/instruction cannot reuse images.
    restored = copy.deepcopy(envelope["public_request"])
    obs = restored["observation"] if buffer else restored
    obs["images"] = []
    obs["observation_digest"] = digest({k: v for k, v in obs.items()
                                        if k not in ("request_id", "observation_digest")})
    if buffer:
        restored["buffer_state_hash"] = digest({k: v for k, v in restored.items() if k != "buffer_state_hash"})
    if restored != source:
        raise O4Error("invalid_visual_binding", "source changed")
    audit_facts(source, envelope["visual_facts"])
    if envelope["visual_facts_digest"] != envelope["visual_facts"]["facts_digest"]:
        raise O4Error("invalid_visual_binding")


def validate_response(response: dict, source: dict) -> dict:
    observation, buffer = unpack(source)
    if buffer is None:
        return validate_single_response(response, source)
    validate("buffer_response", response)
    bindings = {key: observation[key] for key in (
        "request_id", "state_hash", "observation_digest", "instruction_digest")}
    bindings.update(buffer_state_hash=buffer["buffer_state_hash"], event_index=buffer["event_index"])
    if any(response[key] != value for key, value in bindings.items()):
        raise O4Error("invalid_binding", "stale compilation response")
    validate_policy(response["policy_ast"], observation)
    return response


def parse_response(payload: dict, source: dict) -> dict:
    if payload is None or (isinstance(payload, dict) and "error" in payload):
        raise O4Error("provider_error", "invalid provider payload")
    try:
        choice = payload["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise O4Error("invalid_ast", "incomplete/refused response")
        content = choice["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("content is not JSON text")
        # No markdown extraction, coercion, default rules or reference correction.
        response = json.loads(content)
    except (KeyError, IndexError, TypeError, ValueError):
        raise O4Error("invalid_ast", "invalid response JSON") from None
    return validate_response(response, source)
