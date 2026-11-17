"""GP3 pre-integration audit; stdlib only, no project imports or simulation.

Run from repository root. Writes only a new observation in this GP3 package.
Never generates candidates, restores an order, loads credentials or calls LP.
"""
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
import hashlib
import json
import platform

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
PKG = ROOT / 'semantic_pallet_planner/src/semantic_pallet_planner'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    sort_keys=True, allow_nan=False) + '\n')


assert (ROOT / 'AGENTS.md').is_file() and PKG.is_dir()
assert OUT.parent == ROOT / 'semantic_pallet_planner/outputs'
gp2 = ROOT / 'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP2_20261117_01'
qa = ROOT / 'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP2_QA_20261117_01'
manifest_checks = []
for base in (gp2, qa):
    # Observe current hashes before new navigation is appended. Historical
    # navigation drift is recorded, not repaired or treated as source drift.
    rows = []
    for entry in read(base / 'delivery_manifest.json')['files']:
        path = ROOT / entry['path']
        actual = sha(path) if path.is_file() else None
        rows.append({'path': entry['path'], 'exists': path.is_file(),
                     'matches': actual == entry['sha256'],
                     'expected_sha256': entry['sha256'], 'actual_sha256': actual})
    manifest_checks.append({'manifest': str((base / 'delivery_manifest.json').relative_to(ROOT)),
                            'files': rows})

source = {p.relative_to(PKG).as_posix(): sha(p) for p in sorted(PKG.rglob('*'))
          if p.is_file() and p.suffix in ('.py', '.json')
          and not {'tests', '__pycache__'}.intersection(p.relative_to(PKG).parts)}
prior = read(gp2 / 'source_manifest.json')['files']
assert source == prior, 'unexpected production source drift'
write('source_manifest.json', {'version': 'geometry_gp3_stopped_source_manifest_v1',
                             'files': source, 'production_changed': [],
                             'matches_gp2': True, 'count': len(source)})

names = ('jev_packaging_geometry_compare_v14', 'jev_candidate_bundle_v14',
         'jev_decision_context_v14', 'jev_selection_result_v14', 'jev_checkpoint_v14',
         'geometry_compare_plan_v1', 'geometry_compare_execution_v1', 'geometry_compare_run_v1')
hits = {n: [p for p in source if n in (PKG / p).read_text()] for n in names}
assert not any(hits.values()), 'proposed GP3 name occupied'

# A many-to-one parse: no function of this float can recover both source values.
raw_a, raw_b = b'{"height":0.1}', b'{"height":0.10000000000000001}'
a, b = json.loads(raw_a), json.loads(raw_b)
ea, eb = json.loads(raw_a, parse_float=Decimal), json.loads(raw_b, parse_float=Decimal)
assert a == b and ea != eb
serialized = json.dumps(a, sort_keys=True, separators=(',', ':')).encode()
assert json.loads(serialized, parse_float=Decimal) != eb
f = a['height']
native = str(Decimal.from_float(f))
assert Fraction(Decimal(native)) == Fraction(f)
assert Decimal(native) != ea['height'] and Decimal(native) != eb['height']
write('input_boundary_evidence.json', {
    'version': 'geometry_gp3_input_boundary_probe_v1', 'python': platform.python_version(),
    'scope': 'stdlib constructed numeric parse only; no order/candidate/kernel execution',
    'source_a': raw_a.decode(), 'source_b': raw_b.decode(),
    'source_sha256': [hashlib.sha256(x).hexdigest() for x in (raw_a, raw_b)],
    'parsed_type': type(f).__name__, 'parsed_equal': a == b,
    'source_exact_values_differ': ea != eb,
    'reserialized': serialized.decode(), 'second_source_value_lost': True,
    'native_binary64_exact_decimal': native,
    'native_binary64_is_neither_source_decimal': True,
    'interpretation': 'Neither shortest roundtrip text nor exact native binary64 decimal recovers original source decimal semantics. Both are possible NEW contracts, not existing GP2 input provenance.',
    'version_occupancy': hits, 'production_files': len(source),
    'manifest_checks_before_new_navigation': manifest_checks,
    'historical_height_error': {
        'path': str((gp2 / 'faults/real_height_disagreement.json').relative_to(ROOT)),
        'sha256': sha(gp2 / 'faults/real_height_disagreement.json'),
        'error': read(gp2 / 'faults/real_height_disagreement.json')['error'],
        'verification': 'archive read/hash only; generation NOT_RUN'},
})
print(json.dumps({'numeric_probe': 'PASS', 'source_files': len(source),
                  'source_matches_gp2': True, 'version_names_unoccupied': True,
                  'missing_archive_files': sum(not r['exists'] for m in manifest_checks for r in m['files']),
                  'historical_hash_differences': [r['path'] for m in manifest_checks for r in m['files'] if not r['matches']],
                  'A03': 'BLOCKED_INPUT_CONTRACT_NOT_IMPLEMENTED'}, ensure_ascii=False))
