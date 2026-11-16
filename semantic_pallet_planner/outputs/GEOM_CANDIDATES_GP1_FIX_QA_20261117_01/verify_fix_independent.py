"""Independent E01 closure using preserved input bytes and archived normal results.

Only reviewed space modules are imported. No candidates, physics, orders or LP.
"""
import hashlib
import importlib.abc
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
QA = Path(__file__).resolve().parent
FIX = ROOT / 'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP1_FIX_20261117_01'
ORIGINAL = ROOT / 'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP1_20261116_01'
OLD_QA = ROOT / 'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP1_QA_20261117_01'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    def pairs(items):
        d = {}
        for k, v in items:
            assert k not in d, (str(path), k)
            d[k] = v
        return d
    return json.loads(path.read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))


class SpaceOnly(importlib.abc.MetaPathFinder):
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
    seal = load(FIX / 'delivery_manifest.json')
    actual = {p.relative_to(FIX).as_posix(): sha(p) for p in FIX.rglob('*')
              if p.is_file() and p.name != 'delivery_manifest.json'}
    assert actual == seal['package_files']
    external = []
    for name, expected in seal['external_delivery_files'].items():
        assert sha(ROOT / name) == expected
        blob = subprocess.check_output(['git', 'show', head + ':' + name], cwd=ROOT)
        assert hashlib.sha256(blob).hexdigest() == expected
        external.append({'path': name, 'sha256': expected, 'delivery_commit': head})
    source = load(FIX / 'source_manifest.json')
    package = ROOT / source['package_root']
    current = {p.relative_to(package).as_posix(): sha(p) for p in package.rglob('*')
               if p.is_file() and p.suffix in ('.py', '.json')
               and not {'tests', '__pycache__'}.intersection(p.relative_to(package).parts)}
    assert current == source['files']
    previous = load(ORIGINAL / 'source_manifest.json')['files']
    changed = sorted(k for k in previous if previous[k] != current[k])
    assert set(current) == set(previous) and changed == sorted(source['changed_production_files'])
    assert changed == ['planner/space_candidates/__init__.py', 'planner/space_candidates/contracts.py']
    for reference in source['protected_files']:
        assert sha(ROOT / reference['path']) == reference['sha256']
    old_probe = load(OLD_QA / 'independent_checks.json')['numeric_error_probe']
    assert old_probe['passed'] is False and old_probe['returned'] is False
    assert old_probe['exception_type'] == 'decimal.InvalidOperation'
    raw = old_probe['input_utf8'].encode('utf-8')
    assert hashlib.sha256(raw).hexdigest() == old_probe['input_sha256']
    before, after = (load(FIX / p) for p in ('before_fix_probe.json', 'after_fix_probe.json'))
    assert before['status'] == 'FAIL_CONFIRMED_BEFORE_FIX'
    assert before['input_sha256'] == after['input_sha256'] == old_probe['input_sha256']
    assert before['input_utf8'] == after['input_utf8'] == old_probe['input_utf8']
    # All Git subprocesses precede the import/runtime guard.
    sys.meta_path.insert(0, SpaceOnly())
    sys.addaudithook(audit)
    from semantic_pallet_planner.planner.space_candidates import build_space_index
    result = build_space_index(raw)
    assert result == after['returned']
    assert result['status'] == 'ERROR' and result['error']['code'] == 'UNSUPPORTED_GEOMETRY_NUMBER'
    assert result['spaces'] == [] and result['surface'] is None and result['input_digest'] is None
    assert all(v == 0 for v in result['budget_usage']['used'].values())
    normal = []
    for name in ('empty', 'overhead_cavity'):
        path = ORIGINAL / 'constructed' / (name + '_input.json')
        saved = load(ORIGINAL / 'constructed' / (name + '_index.json'))
        actual_result = build_space_index(path.read_bytes())
        assert {k: v for k, v in actual_result.items() if k != 'source_bytes_sha256'} == {
            k: v for k, v in saved.items() if k != 'source_bytes_sha256'}
        normal.append({'scene': name, 'status': 'PASS', 'comparison': 'complete result except source-byte hash',
                       'saved_input_sha256': sha(path), 'semantic_digest': actual_result['semantic_digest']})
    data = {'version': 'geometry_gp1_fix_independent_closure_v1', 'date': '2026-11-17',
            'timezone': 'Asia/Shanghai', 'head': head, 'python': platform.python_version(),
            'status': 'PASS', 'issue_id': 'QA-GP1-E01', 'package_files': len(actual),
            'external_delivery_snapshots': external, 'source_files': len(current),
            'changed_production_files': changed, 'protected_files_verified': len(source['protected_files']),
            'old_qa_failure_preserved': True, 'developer_before_failure_preserved': True,
            'input_sha256': old_probe['input_sha256'], 'current_public_result': result,
            'matches_archived_after_fix_result': True, 'normal_result_comparisons': normal,
            'boundary': {'source_entry': 'current public build_space_index', 'stubs': False,
                         'budget_overrides': False, 'schema_replacement': False,
                         'candidate_generation': 0, 'physical_admission': 0, 'orders': 0,
                         'forks': 0, 'LP': 0, 'model_calls': 0},
            'limits': 'Closure of the reported Decimal parsing class; not exhaustive numeric/OS exception coverage, production runner integration or order benefit.'}
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': data['status'], 'source_files': len(current), 'changed': changed,
                      'issue': 'QA-GP1-E01', 'input_sha256': old_probe['input_sha256'],
                      'current_outcome': result['status'], 'normal_controls': len(normal)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
