"""Closed N1 byte/number contracts. Not a provider, run or checkpoint protocol."""
import hashlib
import json
import math
import platform
import struct
import sys
from decimal import Decimal, DecimalException
from fractions import Fraction

from ..planner.space_candidates.contracts import GeometryError, text

NATIVE = 'geometry_runtime_state_snapshot_v1'
INPUT = 'geometry_runtime_public_input_v1'
PROFILE = 'geometry_runtime_shortest_decimal_v1'
ADAPTER = 'geometry_runtime_snapshot_adapter_v1'
BINDING = 'geometry_runtime_binding_v1'
SERIALIZER = 'geometry_runtime_cpython_json_v1'
GENERATION = 'geometry_runtime_generation_v1'
AUDIT = 'geometry_runtime_generation_audit_v1'
CONTRACTS = {NATIVE, INPUT, BINDING}
STATE_KEYS = {'container','buffer_capacity','pending_items','placed_items','arrived_ids',
              'attributes','event_index','arrival_count','placed_count','end_of_stream'}
ITEM_KEYS = {'item_id','dimensions_mm','mass_kg','stackable','top_load_limit_kg_synthetic',
             'fragile','weight_class','product_category'}
PLACED_KEYS = ITEM_KEYS | {'pose','oriented_size_mm','supported_load_kg','support_fractions'}
CONTAINER_KEYS = {'container_id','length_mm','width_mm','max_height_mm','max_payload_kg','coordinate_frame'}
IDENTITY_KEYS = {'data_identity','task_identity','monitor_identity'}
BINDING_KEYS = {'version','native_snapshot_sha256','geometry_input_sha256','effective_state_digest',
                'geometry_values_digest','observation_digest','profile','adapter_version','adapter_source_digest',
                'source_manifest_digest','config_digest','backend','physical_identity','monitor_identity',
                'data_identity','task_identity','environment_digest','serializer_version','record_digest'}


def require(ok, detail, code='RUNTIME_INPUT_INVALID'):
    if not ok:
        raise GeometryError(code, detail)


def closed(obj, keys):
    require(type(obj) is dict, 'object required')
    require(all(type(k) is str for k in obj), 'string object keys required')
    missing = set(keys) - obj.keys()
    require(not missing, 'missing fields: ' + ','.join(sorted(missing)), 'RUNTIME_INPUT_MISSING_FIELD')
    require(set(obj) == set(keys), 'unknown fields: ' + ','.join(sorted(set(obj)-set(keys))))


def sha(raw):
    require(type(raw) is bytes, 'raw bytes required')
    return hashlib.sha256(raw).hexdigest()


def hash_string(value):
    require(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
            'SHA256 hex required')


def native_number(value):
    require(type(value) in (int, float), 'native int/float required; bool is not a number')
    try:
        f = float(value)
    except (OverflowError, ValueError) as exc:
        raise GeometryError('RUNTIME_NUMBER_UNREPRESENTABLE', 'binary64 conversion') from exc
    require(math.isfinite(f), 'nonfinite native number')
    require(type(value) is not int or int(f) == value, 'integer loses binary64 precision',
            'RUNTIME_NUMBER_UNREPRESENTABLE')
    return value


def exact_decimal_float(value):
    """Decode numeric text at a binary64 boundary without overflow/underflow."""
    try:
        d = Decimal(value)
        f = float(d)
        require(d.is_finite() and math.isfinite(f) and (d == 0 or f != 0),
                'nonfinite/overflow/nonzero underflow', 'RUNTIME_NUMBER_UNREPRESENTABLE')
    except (DecimalException, OverflowError, ValueError) as exc:
        if isinstance(exc, GeometryError):
            raise
        raise GeometryError('RUNTIME_NUMBER_UNREPRESENTABLE', 'invalid decimal conversion') from exc
    return f


def numeric_text(value):
    native_number(value)
    return text(Fraction(value) if type(value) is int else Fraction(Decimal(repr(value))))


def check_native_tree(value):
    if type(value) in (int, float):
        native_number(value)
    elif type(value) is dict:
        require(all(type(k) is str for k in value), 'string object keys required')
        for child in value.values():
            check_native_tree(child)
    elif type(value) is list:
        for child in value:
            check_native_tree(child)
    else:
        require(type(value) in (str, bool), 'unsupported native leaf')


def encode(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError) as exc:
        raise GeometryError('RUNTIME_INPUT_INVALID', 'not finite UTF-8 JSON') from exc


def decode(raw):
    require(type(raw) is bytes, 'bytes required')
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'duplicate JSON key: ' + k)
            result[k] = v
        return result
    def invalid(value):
        raise GeometryError('RUNTIME_INPUT_INVALID', 'nonfinite JSON constant: ' + value)
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                           parse_float=exact_decimal_float, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, GeometryError):
            raise
        raise GeometryError('RUNTIME_INPUT_INVALID', 'invalid UTF-8 JSON') from exc
    require(encode(value) == raw, 'noncanonical or altered original bytes', 'RUNTIME_SNAPSHOT_MISMATCH')
    return value


def same_native(a, b):
    """Recursive exact type/bit identity; never rely on Python numeric equality."""
    if type(a) is not type(b):
        return False
    if type(a) is float:
        return struct.pack('>d', a) == struct.pack('>d', b)
    if type(a) is dict:
        return a.keys() == b.keys() and all(same_native(a[k], b[k]) for k in a)
    if type(a) is list:
        return len(a) == len(b) and all(same_native(x, y) for x, y in zip(a, b))
    return a == b


def environment():
    from importlib.metadata import version, PackageNotFoundError
    require(platform.python_implementation() == 'CPython' and
            sys.float_info.radix == 2 and sys.float_info.mant_dig == 53, 'unsupported float/serializer environment')
    deps = {}
    for name in ('jsonschema','numpy','scipy'):
        try:
            deps[name] = version(name)
        except PackageNotFoundError:
            deps[name] = 'NOT_INSTALLED'
    return {'python': platform.python_version(), 'implementation': platform.python_implementation(),
            'radix': sys.float_info.radix, 'mant_dig': sys.float_info.mant_dig,
            'serializer': SERIALIZER, 'dependencies': deps}
