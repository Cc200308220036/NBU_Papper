"""Serialization and schema validation, with no business decisions."""
import hashlib
import json
from pathlib import Path
from functools import lru_cache
from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).resolve().parents[1] / 'schemas'
CATEGORIES = ('food', 'glassware', 'electronics', 'household_cleaner', 'general')
FIELDS = {
    'cargo_category': 'category', 'packaging.reinforced': 'boolean',
    'labels.no_top_load': 'boolean', 'labels.max_top_load_kg': 'number',
    'physical_top_load_limit_kg': 'number', 'mass_kg': 'number',
    'fragile': 'boolean', 'weight_class': 'weight',
}

class O4Error(ValueError):
    def __init__(self, code, detail=''):
        self.code = code
        super().__init__(code + (': ' + detail if detail else ''))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)+'\n')


@lru_cache(maxsize=4)
def _validator(name):
    return Draft202012Validator(read(SCHEMAS / f'o4_{name}.schema.json'))


def validate(name, value, code='invalid_ast'):
    try:
        canonical(value)
        _validator(name).validate(value)
    except Exception as exc:
        # The stable public code is deliberately independent of jsonschema messages.
        raise O4Error(code, str(exc).splitlines()[0][:160]) from exc
    return value


def field_value(obj, field):
    value = obj
    for key in field.split('.'):
        value = value[key]
    return value
