"""Static JN3-C delivery verifier; stdlib only, no runtime dispatch."""
import argparse
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--output', required=True)
p.add_argument('--repo', default='.')
a = p.parse_args()
root, repo = Path(a.output).resolve(), Path(a.repo).resolve()
read = lambda f: json.loads(f.read_text())
sha = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
manifest = read(root / 'delivery_manifest.json')
actual = {f.relative_to(root).as_posix(): sha(f) for f in root.rglob('*')
          if f.is_file() and f != root / 'delivery_manifest.json'}
assert actual == manifest['files_sha256'], 'delivery bytes/inventory changed'
assert 'plan/delivery_manifest.json' in actual and 'run/delivery_manifest.json' in actual
for name, value in manifest['documentation_sha256'].items():
    assert sha(repo / name) == value, 'documentation changed: ' + name
source = read(root / 'source_manifest.json')
assert source == read(root / 'plan/plan.json')['source_manifest']
package = repo / 'semantic_pallet_planner/src/semantic_pallet_planner'
current = {f.relative_to(package).as_posix(): sha(f) for f in package.rglob('*')
           if f.is_file() and f.suffix in ('.py', '.json')
           and not {'tests', '__pycache__'}.intersection(f.relative_to(package).parts)}
assert current == source, 'current source bytes/inventory changed'
assert all(sha(root / 'plan/code_snapshot' / n) == v for n, v in source.items())
aux = read(root / 'plan/algorithm_archive_manifest.json')
assert all(sha(root / 'plan/code_snapshot/jev_select/stability' / n) == v
           and sha(package / 'jev_select/stability' / n) == v for n, v in aux.items())
protected = read(root / 'protected_before.json')
assert all((repo / n).is_file() and sha(repo / n) == v for n, v in protected.items())
for parent in read(root / 'parent_verification.json'):
    path = repo / parent['path']
    declared = read(path / 'delivery_manifest.json')['files_sha256']
    found = {f.relative_to(path).as_posix(): sha(f) for f in path.rglob('*')
             if f.is_file() and f.name != 'delivery_manifest.json'}
    assert declared == found, 'parent inventory or bytes changed'
    assert sha(path / 'delivery_manifest.json') == parent['manifest_sha256']
tests = read(root / 'test_source_manifest.json')
assert all(sha(repo / n) == v and sha(root / 'test_snapshot' / n) == v
           for n, v in tests.items())
owner = repo / 'semantic_pallet_planner/outputs/JEV_JN3_C_ACCOUNTING_V1/owner.json'
assert owner.read_bytes() == (root / 'global_budget_owner.json').read_bytes()
plan = read(root / 'plan/plan.json')
ledger = read(root / 'run/request_ledger/requests.json')['requests']
assert len(ledger) <= plan['request_budget']['global']
for job, limit in plan['request_budget']['per_job'].items():
    assert sum(row['job_id'] == job for row in ledger) <= limit
print(json.dumps({'status': 'PASS', 'delivery_files': len(actual),
                  'source_files': len(source), 'protected_files': len(protected),
                  'test_files': len(tests), 'send_reservations': len(ledger),
                  'nested_manifests_bound': True}))
