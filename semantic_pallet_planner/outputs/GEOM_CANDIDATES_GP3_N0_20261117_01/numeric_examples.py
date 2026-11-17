"""GP3-N0 DESIGN_ONLY arithmetic illustrations, standard library only.

No production imports, geometry generation, order, checkpoint runner or kernel.
The small JSON object below is a numeric fixture, NOT a runnable state/envelope.
Run from repository root; write only this package's numeric_examples.json.
"""
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
import hashlib
import json
import math
import platform
import struct
import sys

OUT = Path(__file__).resolve().parent
assert sys.float_info.radix == 2 and sys.float_info.mant_dig == 53


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def finite_decimal(v):
    """Context-independent, exact finite-decimal text for a Fraction."""
    n, d = v.numerator, v.denominator
    twos = fives = 0
    while d % 2 == 0:
        d //= 2
        twos += 1
    while d % 5 == 0:
        d //= 5
        fives += 1
    assert d == 1
    scale = max(twos, fives)
    n *= 2 ** (scale - twos) * 5 ** (scale - fives)
    digits = str(abs(n)).zfill(scale + 1)
    s = digits if not scale else (digits[:-scale] + '.' + digits[-scale:]).rstrip('0').rstrip('.')
    return ('-' if n < 0 else '') + s if n else '0'


def q(v):
    return finite_decimal(Fraction(round(v * 1000), 1000))


def short(v):
    return Fraction(Decimal(repr(v)))


def bits(v):
    return struct.pack('>d', v).hex()


def evidence(v):
    return {'repr': repr(v), 'binary64_be_hex': bits(v),
            'shortest_decimal': finite_decimal(short(v)),
            'exact_binary64_decimal': str(Decimal.from_float(v))}


raw = [b'{"height":0.1}', b'{"height":0.10000000000000001}']
parsed = [json.loads(r)['height'] for r in raw]
exact = [json.loads(r, parse_float=Decimal)['height'] for r in raw]
assert parsed[0] == parsed[1] and exact[0] != exact[1]

v = 0.0005
quant = {'input': evidence(v), 'quantum_mm': '0.001', 'rounding': 'HALF_EVEN',
         'shortest_result_mm': q(short(v)),
         'binary64_exact_result_mm': q(Fraction(v))}
assert quant['shortest_result_mm'] == '0' and quant['binary64_exact_result_mm'] == '0.001'

# Distinguish profile conversion of a saved value from exact internal addition.
a, b, saved_sum, literal = 0.1, 0.2, 0.1 + 0.2, 0.3
contact = {'saved_native_sum': evidence(saved_sum), 'saved_native_literal': evidence(literal),
           'native_equal': saved_sum == literal,
           'shortest_saved_levels_equal': short(saved_sum) == short(literal),
           'binary64_saved_levels_equal': Fraction(saved_sum) == Fraction(literal),
           'shortest_internal_a_plus_b': finite_decimal(short(a) + short(b)),
           'binary64_internal_a_plus_b': finite_decimal(Fraction(a) + Fraction(b)),
           'shortest_internal_sum_equals_literal': short(a) + short(b) == short(literal),
           'binary64_internal_sum_equals_literal': Fraction(a) + Fraction(b) == Fraction(literal),
           'native_difference_mm': repr(saved_sum - literal),
           'hypothetical_compare_to_1e_6': abs(saved_sum - literal) <= 1e-6,
           'scope': 'arithmetic only; last comparison is not a physical oracle/monitor result; no snapping authorized'}
assert not contact['native_equal'] and not contact['shortest_saved_levels_equal']
assert not contact['binary64_saved_levels_equal']
assert contact['shortest_internal_sum_equals_literal']
assert not contact['binary64_internal_sum_equals_literal']

# Numerical analogy to a ledger update; never reconstruct a real order ledger.
prior, mass, share = 0.2, 0.1, 1 / 3
increment = mass * share
stored = prior + increment
recalculated = short(prior) + short(mass) * short(share)
ledger = {'prior': evidence(prior), 'mass': evidence(mass), 'share': evidence(share),
          'native_increment': evidence(increment), 'native_stored_load': evidence(stored),
          'shortest_recomputed_from_operands': str(recalculated),
          'recomputed_equals_observed_snapshot': recalculated == short(stored),
          'rule': 'retain the observed stored load and share; never replace them by new exact-decimal arithmetic'}
assert recalculated != short(stored)

fixture = {'load_kg': stored, 'share': share, 'z_mm': saved_sum,
           'integer': 1, 'float_integer': 1.0, 'negative_zero': -0.0}
snapshot = canonical(fixture)
restored = json.loads(snapshot)
assert canonical(restored) == snapshot
assert type(restored['integer']) is int and type(restored['float_integer']) is float
for k in ('load_kg', 'share', 'z_mm', 'float_integer', 'negative_zero'):
    assert bits(restored[k]) == bits(fixture[k])
changed = dict(restored, load_kg=math.nextafter(restored['load_kg'], math.inf))
assert canonical(changed) != snapshot
pretty = json.dumps(fixture, ensure_ascii=False, sort_keys=True, indent=2).encode()
assert json.loads(pretty) == restored and sha(pretty) != sha(snapshot)
binding_a = canonical({'profile': 'geometry_runtime_shortest_decimal_v1', 'snapshot_sha256': sha(snapshot)})
binding_b = canonical({'profile': 'geometry_runtime_binary64_exact_v1', 'snapshot_sha256': sha(snapshot)})
assert sha(binding_a) != sha(binding_b)
try:
    canonical({'x': float('nan')})
except ValueError:
    nonfinite_rejected = True
else:
    raise AssertionError('NaN not rejected')

result = {'version': 'geometry_gp3_n0_numeric_examples_v1', 'status': 'PASS_ARITHMETIC_ONLY',
          'python': platform.python_version(), 'implementation': platform.python_implementation(),
          'float_radix': sys.float_info.radix, 'float_mant_dig': sys.float_info.mant_dig,
          'two_lexemes': {'raw': [r.decode() for r in raw], 'sha256': [sha(r) for r in raw],
                          'source_decimals': list(map(str, exact)), 'parsed_equal': True,
                          'parsed': evidence(parsed[0])},
          'half_even': quant, 'contact_height': contact, 'derived_ledger': ledger,
          'json_and_recovery_bytes': {
              'fixture_scope': 'non-executable numeric fixture, not production schema/checkpoint',
              'snapshot_utf8': snapshot.decode(), 'snapshot_sha256': sha(snapshot),
              'json_roundtrip_bytes_equal': True, 'float_bits_and_types_retained': True,
              'negative_zero_native_retained': bits(restored['negative_zero']),
              'negative_zero_geometry_canonical': finite_decimal(short(restored['negative_zero'])),
              'one_ulp_drift_sha256': sha(canonical(changed)), 'one_ulp_drift_rejected_by_hash': True,
              'same_values_different_spacing_sha256': sha(pretty),
              'raw_byte_identity_requires_saved_original_blob': True,
              'profile_a_binding_sha256': sha(binding_a), 'profile_b_binding_sha256': sha(binding_b),
              'profile_drift_changes_binding': True, 'NaN_encoding_rejected': nonfinite_rejected},
          'production_imports': 0, 'candidate_generation': 0, 'order_runs': 0,
          'PCT_LP_calls': 0, 'model_calls': 0,
          'limitations': 'No production schema, adapter, generator, checkpoint or physical validation was executed.'}
(OUT / 'numeric_examples.json').write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
print('PASS: four bounded arithmetic examples; candidate/order/PCT/model calls=0; runtime integration NOT_RUN')
