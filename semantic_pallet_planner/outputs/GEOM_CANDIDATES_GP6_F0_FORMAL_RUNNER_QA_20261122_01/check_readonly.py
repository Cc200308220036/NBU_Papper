"""Validate delivery identities and the unsent four-job plan with saved facts."""
import hashlib
import json
from pathlib import Path
import subprocess

from jsonschema import Draft202012Validator

BASE = '431f16d30c179f596e3d787d4674aeb069da6070'
HEAD = '92e205420909eea86ad86327cd279ac74ccc658e'
O = Path('semantic_pallet_planner/outputs')
P = O / 'GEOM_CANDIDATES_GP6_F0_FORMAL_RUNNER_20261122_01'
PREP = O / 'GEOM_CANDIDATES_GP6_F0_PRELAUNCH_MATERIALS_20261122_01'
SOURCE = Path('semantic_pallet_planner/src/semantic_pallet_planner')
SCHEMAS = SOURCE / 'jev_select/schemas'


def read(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode())


def git(*args):
    return subprocess.check_output(['git', *map(str, args)])


def main():
    manifest = read(P / 'delivery_manifest.json')
    entries = manifest['files']
    assert len(entries) == manifest['file_count'] == len({e['path'] for e in entries})
    for entry in entries:
        path = Path(entry['path'])
        raw = git('show', f'{HEAD}:{path.as_posix()}')
        assert (len(raw), sha(raw)) == (entry['bytes'], entry['sha256']), path
        assert path.read_bytes() == raw, path
    assert not git('diff', '--name-only', BASE, HEAD, '--', SOURCE,
                   'semantic_pallet_planner/tests', 'semantic_pallet_planner/outputs/*GP5*', PREP)
    files = {p.relative_to(SOURCE).as_posix(): sha(p.read_bytes()) for p in SOURCE.rglob('*')
             if p.is_file() and p.suffix in ('.py', '.json')
             and not {'tests', '__pycache__'}.intersection(p.relative_to(SOURCE).parts)}
    source = read(O / 'GEOM_CANDIDATES_GP6_F0_BUDGET_REC_FIX_20261121_01/source_identity.json')
    assert files == source['files'] and digest(files) == source['source_identity'] == manifest['source_identity']
    plan = read(P / 'gp6_f0_order_plan_DRAFT_v2.json')
    v1 = read(PREP / 'gp6_f0_order_plan_DRAFT.json')
    diff = [k for k in sorted(plan.keys() | v1.keys()) if plan.get(k) != v1.get(k)]
    assert diff == ['call_ledger_path', 'request_ledger_path']
    assert plan['status'] == 'DRAFT'
    assert Path(plan['request_ledger_path']).name == 'requests.json'
    assert Path(plan['call_ledger_path']).parent == Path(plan['request_ledger_path']).parent
    assert not Path(plan['request_ledger_path']).exists() and not Path(plan['call_ledger_path']).exists()
    run = read(P / 'run_denominator_NOT_RUN.json')
    assert run['plan_digest'] == digest(plan)
    assert [r['job_id'] for r in run['rows']] == ['G00', 'G01', 'G02', 'G03']
    assert all(r['status'] == 'NOT_RUN' and r['metrics'] is None for r in run['rows'])
    for name, doc in (('geometry_jev_plan_v1', plan), ('geometry_jev_run_v1', run)):
        Draft202012Validator(read(SCHEMAS / f'{name}.schema.json')).validate(doc)
    driver_sha = sha((P / 'formal_jev_driver.py').read_bytes())
    handoff = read(P / 'handoff.json')
    freeze = read(P / 'gp6_f0_final_freeze_binding_spec.json')
    assert driver_sha == handoff['driver_sha256'] == freeze['driver_sha256'] == manifest['driver_sha256']
    assert digest(plan) == handoff['draft_plan_v2_digest'] == freeze['draft_plan_v2_digest']
    assert all(Path(path).exists() for path in handoff['deliverables'].values())
    assert all('PENDING' in read(p)['status'] for p in P.glob('*_PENDING.json'))
    targets = [read(P / p) for p in ('kernel_applicability_review_PENDING.json', 'kernel_bridge_PENDING.json')]
    assert targets[0]['target'] == targets[1]['target']
    previous = read(PREP / 'kernel_bridge_PENDING.json')
    for key in ('evidence_receipt', 'historical_source_manifest', 'historical_monitor', 'target'):
        assert targets[1][key] == previous[key]

    print(json.dumps({'reviewed_commit': HEAD, 'delivery_entries': len(entries),
                      'production_files': len(files), 'source_identity': digest(files),
                      'driver_sha256': driver_sha, 'draft_plan_digest': digest(plan),
                      'draft_changed_fields': diff, 'draft_and_denominator_schema': 'PASS',
                      'jobs_not_run': 4, 'formal_launch': 'NOT_RUN'}, indent=2))


if __name__ == '__main__':
    main()
