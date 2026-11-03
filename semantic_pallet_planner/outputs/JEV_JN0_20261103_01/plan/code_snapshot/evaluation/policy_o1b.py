"""O1b conditional policy envelope; resolve from the public current item only."""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .policy_v2 import validate_policy

SCHEMA = Path(__file__).resolve().parents[1] / 'schemas/policy_o1b.schema.json'


def validate_envelope(envelope):
    Draft202012Validator(json.loads(SCHEMA.read_text())).validate(envelope)
    validate_policy(envelope['then_policy'])
    validate_policy(envelope['else_policy'])
    return envelope


def resolve(envelope, public_request):
    """Return a V2 policy; never inspect hidden annotations or future arrivals."""
    validate_envelope(envelope)
    items = public_request['available_items']
    if len(items) != 1 or public_request['buffer_size'] != 1:
        raise ValueError('O1b requires exactly one currently available item')
    condition = envelope['condition']
    return envelope['then_policy'] if items[0][condition['field']] == condition['equals'] else envelope['else_policy']
