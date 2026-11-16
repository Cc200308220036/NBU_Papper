"""GP1 QA: immutable archive geometry checks plus one public error-contract probe.

No candidates, physical admission, orders, LP, model calls or source edits.
Nonzero exit intentionally records a reproduced contract failure.
"""
from decimal import Decimal
from fractions import Fraction
import hashlib
import importlib.abc
from itertools import product
import json
from pathlib import Path
import platform
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[3]
QA = Path(__file__).resolve().parent
DELIVERY = ROOT / 'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP1_20261116_01'
PACKAGE = ROOT / 'semantic_pallet_planner/src/semantic_pallet_planner'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(p):
    def pairs(items):
        d = {}
        for k, v in items:
            assert k not in d, (str(p), k)
            d[k] = v
        return d
    return json.loads(p.read_text(), parse_float=Decimal, object_pairs_hook=pairs,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def q(value):
    return Fraction(Decimal(value)) if isinstance(value, str) else Fraction(value)


def inside(point, bounds):
    return all(bounds[d] < point[d] < bounds[d+3] for d in range(3))


class SpaceImportsOnly(importlib.abc.MetaPathFinder):
    allowed = {'semantic_pallet_planner.planner', 'semantic_pallet_planner.planner.space_candidates',
               'semantic_pallet_planner.planner.space_candidates.contracts',
               'semantic_pallet_planner.planner.space_candidates.empty_spaces',
               'semantic_pallet_planner.planner.space_candidates.surface_spaces'}

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('semantic_pallet_planner.') and fullname not in self.allowed:
            raise RuntimeError('forbidden project import: ' + fullname)
        if fullname.split('.')[0] in {'numpy', 'scipy', 'torch', 'requests', 'httpx'}:
            raise RuntimeError('forbidden external import: ' + fullname)


def audit(event, args):
    if event.startswith(('socket.', 'subprocess.')) or event in {'os.system', 'os.fork', 'os.posix_spawn'}:
        raise RuntimeError('forbidden operation: ' + event)
    if event == 'open' and any(t in str(args[0]).lower() for t in ('credentials', 'secrets.json', 'api_key', '.pem', '.env')):
        raise RuntimeError('forbidden credential path')


def main():
    assert len(sys.argv) == 3 and sys.argv[1] == '--output'
    output = (ROOT / sys.argv[2]).resolve()
    assert output.is_relative_to(QA) and not output.exists()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    seal = load(DELIVERY / 'delivery_manifest.json')
    members = {p.relative_to(DELIVERY).as_posix(): sha(p) for p in DELIVERY.rglob('*')
               if p.is_file() and p.name != 'delivery_manifest.json'}
    assert members == seal['package_files']
    external = []
    for name, expected in seal['external_delivery_files'].items():
        assert sha(ROOT / name) == expected
        external.append({'path': name, 'sha256': expected, 'verified_before_qa_navigation': True})
    source = load(DELIVERY / 'source_manifest.json')
    actual = {p.relative_to(PACKAGE).as_posix(): sha(p) for p in PACKAGE.rglob('*')
              if p.is_file() and p.suffix in ('.py', '.json')
              and not {'tests', '__pycache__'}.intersection(p.relative_to(PACKAGE).parts)}
    assert actual == source['files']
    old_ref = source['gp0_source_manifest']
    assert sha(ROOT / old_ref['path']) == old_ref['sha256']
    old = load(ROOT / old_ref['path'])['files']
    assert all(actual[name] == digest for name, digest in old.items())
    assert set(actual) - set(old) == set(source['new_production_files'])
    protected = source['protected_artifacts'] + source['entry_documents']
    assert all(sha(ROOT / r['path']) == r['sha256'] for r in protected)
    scene_results = []
    for file in sorted((DELIVERY / 'constructed').glob('*_input.json')):
        name = file.name.removesuffix('_input.json')
        scene = load(file)
        result = load(DELIVERY / 'constructed' / (name + '_index.json'))
        length, width, height = (q(scene['container'][k]) for k in ('length_mm', 'width_mm', 'max_height_mm'))
        container = (-length/2, -width/2, Fraction(0), length/2, width/2, height)
        occupied = []
        for obj in scene['placed_items']:
            x, y, z = (q(obj['pose'][k]) for k in ('x_mm', 'y_mm', 'z_base_mm'))
            sx, sy, sz = map(q, obj['oriented_size_mm'])
            occupied.append((x-sx/2, y-sy/2, z, x+sx/2, y+sy/2, z+sz))
        proposed, ems = [], []
        for space in result['spaces']:
            bounds = tuple(map(q, space['bounds_mm']))
            assert all(container[d] <= bounds[d] < bounds[d+3] <= container[d+3] for d in range(3))
            assert all(any(bounds[d+3] <= b[d] or b[d+3] <= bounds[d] for d in range(3)) for b in occupied)
            assert space['space_id'] == 'space_' + hashlib.sha256(canonical(space['bounds_mm'])).hexdigest()
            proposed.append(bounds)
            if 'EMS_STYLE_3D' in space['source_types']:
                ems.append(bounds)
        assert proposed == sorted(set(proposed))
        assert not any(a != b and all(b[d] <= a[d] and a[d+3] <= b[d+3] for d in range(3))
                       for a in ems for b in ems)
        # Independent small-cell union check: no summation of overlapping volumes.
        axes = [sorted({container[d], container[d+3]} | {b[k] for b in occupied + proposed for k in (d, d+3)}) for d in range(3)]
        mids = [[(lo+hi)/2 for lo, hi in zip(a, a[1:])] for a in axes]
        free_cells = blocked_cells = 0
        for point in product(*mids):
            blocked = any(inside(point, b) for b in occupied)
            covered = any(inside(point, b) for b in ems)
            assert blocked != covered, (name, tuple(map(str, point)))
            blocked_cells += int(blocked)
            free_cells += int(not blocked)
        expected_digest = hashlib.sha256(canonical({k: v for k, v in result.items()
                                                  if k not in {'source_bytes_sha256', 'semantic_digest'}})).hexdigest()
        assert expected_digest == result['semantic_digest']
        scene_results.append({'scene': name, 'status': 'PASS', 'spaces': len(proposed),
                              'free_partition_cells': free_cells, 'occupied_partition_cells': blocked_cells,
                              'scope': 'Six archived constructions only; not global maximal-space enumeration.'})
    assert len(scene_results) == 6
    # Only the reviewed new space modules can load for this direct production API probe.
    sys.meta_path.insert(0, SpaceImportsOnly())
    sys.addaudithook(audit)
    from semantic_pallet_planner.planner.space_candidates import build_space_index
    raw = b'{"version":"geometry_space_input_v1","container":{"length_mm":1e999999999999999999999999,"width_mm":10,"max_height_mm":10},"placed_items":[]}'
    probe = {'case_id': 'numeric_decimal_exponent_out_of_range', 'input_utf8': raw.decode(),
             'input_sha256': hashlib.sha256(raw).hexdigest(), 'entry': 'build_space_index(raw)',
             'unmodified_production_entry': True, 'stubs_or_budget_changes': False,
             'expected': 'Structured technical ERROR, spaces=[], surface=null; no exception escapes.',
             'contract': 'Main plan section 6 numeric error -> ERROR; public GP1 entry atomic error result.'}
    try:
        result = build_space_index(raw)
        probe.update(returned=True, status=result['status'], error=result['error'],
                     passed=result['status'] == 'ERROR' and result['spaces'] == [] and result['surface'] is None)
    except Exception as exc:
        probe.update(returned=False, passed=False, exception_type=type(exc).__module__ + '.' + type(exc).__name__,
                     exception_message=str(exc), traceback=traceback.format_exc())
    data = {'version': 'geometry_gp1_independent_qa_v1', 'date': '2026-11-17', 'timezone': 'Asia/Shanghai',
            'head': head, 'python': platform.python_version(), 'package_files': len(members),
            'external_documents_and_sources': external,
            'source_files': len(actual), 'old_files_unchanged': len(old), 'new_production_files': source['new_production_files'],
            'protected_references_verified': len(protected), 'archived_geometry': scene_results,
            'numeric_error_probe': probe, 'status': 'PASS' if probe['passed'] else 'FAIL_NUMERIC_ERROR_CONTRACT',
            'boundary': {'candidates': 0, 'physical_admission': 0, 'orders': 0, 'forks': 0, 'LP': 0,
                         'models': 0, 'project_import_scope': 'new space modules only',
                         'numeric_probe_algorithm_stage': 'input parsing, before free-space algorithms'},
            'limit': 'Does not disprove normal construction geometry or establish behavior on real orders.'}
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': data['status'], 'source_files': len(actual), 'archived_scenes': len(scene_results),
                      'numeric_exception': probe.get('exception_type'), 'output': output.relative_to(ROOT).as_posix()}, ensure_ascii=False))
    raise SystemExit(0 if probe['passed'] else 1)


if __name__ == '__main__':
    main()
