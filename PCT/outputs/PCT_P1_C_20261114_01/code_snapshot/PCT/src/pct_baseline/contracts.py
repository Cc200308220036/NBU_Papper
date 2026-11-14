"""Canonical identities and dependency-free data checks, not a Schema replacement."""
import hashlib
import json
from pathlib import Path


class ContractError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ContractError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    canonical(value)
    return value


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def schema(name):
    from .protocol import SCHEMAS
    require(name in SCHEMAS, 'unknown_schema')
    return read(Path(__file__).parent / 'schemas' / (name + '.schema.json'))


def validate(name, value):
    # Full JSON Schema validation is an explicit optional runtime dependency for
    # the stdlib data CLI. Its absence is reported, never replaced with a stub.
    from jsonschema import Draft202012Validator
    document = schema(name)
    Draft202012Validator.check_schema(document)
    Draft202012Validator(document).validate(value)
    from .protocol import validate_value
    validate_value(name, value)
