import json
from functools import lru_cache
from pathlib import Path
from jsonschema import Draft202012Validator

@lru_cache(None)
def validator(name):
    return Draft202012Validator(json.loads((Path(__file__).parent/'schemas'/f'{name}.schema.json').read_text()))

def validate(name, value):
    try:
        validator(name).validate(value)
    except Exception as exc:
        raise ValueError(f'{name} schema: {exc.message if hasattr(exc,"message") else exc}') from exc
