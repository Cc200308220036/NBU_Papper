"""Independently verify frozen GP6 launch inputs without planner execution."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

from jsonschema import Draft202012Validator

HEAD = '89f56f4994784375ef8cad3c59b305be8c5e54f4'
BASE = 'd131f3d3033aa8d1885c68691eeeb451cd4e7652'
OUT = Path('semantic_pallet_planner/outputs')
P = OUT / 'GEOM_CANDIDATES_GP6_F0_FINAL_FREEZE_20261122_01'
RUNNER = OUT / 'GEOM_CANDIDATES_GP6_F0_FORMAL_RUNNER_20261122_01'
SOURCE = Path('semantic_pallet_planner/src/semantic_pallet_planner')


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode())


def git(*args):
    return subprocess.check_output(['git', *map(str, args)])


def check_manifest():
    manifest = read(P / 'delivery_manifest.json')
    entries = {Path(e['path']): e for e in manifest['files']}
    assert set(entries) == {p for p in P.rglob('*') if p.is_file() and p.name != 'delivery_manifest.json'}
    for path, entry in entries.items():
        raw = git('show', f'{HEAD}:{path}')
        assert (len(raw), sha(raw)) == (entry['size_bytes'], entry['sha256'])
        assert raw == path.read_bytes()
    return len(entries)


def main():
    entries = check_manifest()
    assert not git('diff', '--name-only', BASE, HEAD, '--', SOURCE, RUNNER,
                   'semantic_pallet_planner/outputs/*GP5*')
    identity = read(P / 'freeze_identity.json')
    source = read(OUT / 'GEOM_CANDIDATES_GP6_F0_BUDGET_REC_FIX_20261121_01/source_identity.json')
    files = {p.relative_to(SOURCE).as_posix(): sha(p.read_bytes()) for p in SOURCE.rglob('*')
             if p.is_file() and p.suffix in ('.py', '.json')
             and not {'tests', '__pycache__'}.intersection(p.relative_to(SOURCE).parts)}
    assert files == source['files'] and digest(files) == identity['source_identity']
    prior_qa = read(OUT / 'GEOM_CANDIDATES_GP6_F0_FORMAL_RUNNER_QA_20261122_01/next_stage_admission.json')
    assert sha(Path(identity['driver_path']).read_bytes()) == identity['driver_sha256'] == prior_qa['driver_sha256']
    draft = read(RUNNER / 'gp6_f0_order_plan_DRAFT_v2.json')
    plan_path = P / 'gp6_f0_order_plan_FROZEN.json'
    plan = read(plan_path)
    schema = read(SOURCE / 'jev_select/schemas/geometry_jev_plan_v1.schema.json')
    Draft202012Validator(schema).validate(plan)
    assert set(draft) == set(plan) and draft['status'] == 'DRAFT' and plan['status'] == 'FROZEN'
    differences = {k for k in plan if plan[k] != draft[k]}
    assert differences == {'status', 'request_ledger_path', 'call_ledger_path'}
    assert digest(draft) == identity['draft_digest'] == prior_qa['draft_plan_digest']
    pd = digest(plan)
    assert pd == identity['plan_digest']
    assert sha(plan_path.read_bytes()) == identity['plan_file_sha256']
    assert [row['job_id'] for row in plan['jobs']] == ['G00', 'G01', 'G02', 'G03']
    assert plan['per_job_max_sends'] == 19 and plan['shared_max_sends'] == plan['model_calls_max'] == 76
    assert (plan['assessment_limit'], plan['solver_limit']) == (76, 4096)
    target = read(P / 'target_binding.json')
    run = Path(target['run_root'])
    repo = Path(target['repo_root'])
    assert not run.exists() and target['run_root_exists'] is False
    assert repo / run == Path(target['run_root_absolute'])
    req = Path(plan['request_ledger_path'])
    call = Path(plan['call_ledger_path'])
    assert req.name == 'requests.json' and req.parent == call.parent == P / 'ledgers'
    assert not any(p.resolve().is_relative_to(run.resolve()) for p in (req, call))
    assert repo / req == Path(target['request_ledger_absolute'])
    assert repo / call == Path(target['call_ledger_absolute'])
    assert {p.name for p in req.parent.iterdir()} == {req.name, call.name}
    assert sha(req.read_bytes()) == identity['request_ledger_sha256']
    assert sha(call.read_bytes()) == identity['call_ledger_sha256']
    request = read(req)
    body = {'version': 'geometry_jev_requests_v1', 'plan_digest': pd,
            'per_job_max_sends': 19, 'max_sends': 76, 'requests': []}
    assert request == {**body, 'record_digest': digest(body)}
    zero = {'assessment_entries': 0, 'solver_calls': 0, 'test_double_assessments': 0}
    assert read(call) == {
        'version': 'geometry_call_ledger_v1', 'plan_digest': pd, 'evidence': 'REAL_KERNEL',
        'limits': {'assessment_entries': 76, 'solver_calls': 4096}, 'calls': [], 'counts': zero,
    }
    pending = {path.stem: read(path) for path in P.glob('*_PENDING.json')}
    assert len(pending) == 5 and all('PENDING' in x['status'] for x in pending.values())
    bridge = pending['kernel_bridge_PENDING']
    app = pending['kernel_applicability_review_PENDING']
    assert app['target'] == bridge['target']
    assert bridge['target']['plan_digest'] == pd
    for key in ('source_identity', 'runtime_version', 'publication_policy_digest', 'environment_digest'):
        assert bridge['target'][key] == plan[key]
    for key in ('historical_source_manifest', 'historical_monitor', 'evidence_receipt'):
        ref = bridge[key]
        assert ref == app[key] and sha(Path(ref['path']).read_bytes()) == ref['sha256']
    monitor = read(bridge['historical_monitor']['path'])
    assert digest(monitor) == bridge['target']['monitor_digest']
    assert digest(monitor['algorithm_identity']) == bridge['target']['algorithm_digest']
    rows = [{k: row[k] for k in ('path', 'before', 'after')} for row in app['changes']]
    assert len(rows) == 28 and digest(rows) == app['diff_digest']
    previous = read(OUT / 'GEOM_CANDIDATES_GP6_F0_BUDGET_REC_FIX_QA_20261121_01/readonly_results.json')
    assert rows == previous['source_delta']
    for name in ('scope_authorization_PENDING', 'scope_review_PENDING', 'order_admission_PENDING'):
        assert pending[name]['plan_digest'] == pd and pending[name]['scope'] == plan['scope']
    assert pending['scope_authorization_PENDING']['real_calls_authorized'] == 0
    admission = pending['order_admission_PENDING']
    assert all(admission[k] == bridge['target'][k] for k in
               ('runtime_version', 'publication_policy_digest', 'source_identity', 'environment_digest', 'monitor_digest'))
    commands = [shlex.split(row) for row in (P / 'commands.sh').read_text().splitlines()
                if row.strip() and not row.lstrip().startswith('#')]
    preflight, execute = commands
    assert execute == [*preflight, '--execute'] and preflight[:4] == ['python3', '-I', '-B', identity['driver_path']]
    assert preflight[preflight.index('--run-root')+1] == str(run)
    assert preflight[preflight.index('--plan')+1] == str(plan_path)
    for flag in ('--kernel-bridge', '--admission'):
        assert preflight[preflight.index(flag)+1].endswith('_PENDING.json')

    print(json.dumps({'reviewed_commit': HEAD, 'delivery_entries': entries, 'production_files': len(files),
                      'plan_digest': pd, 'driver_sha256': identity['driver_sha256'],
                      'changed_fields_only': sorted(differences), 'freeze_schema': 'PASS',
                      'request_rows': len(request['requests']), 'call_counts': zero,
                      'pending_documents_checked': len(pending), 'source_delta_rows': len(rows),
                      'same_new_run_root': True, 'reviewed_launch_commands_use_unsigned_paths': True,
                      'formal_preflight': 'NOT_RUN', 'formal_jobs': 'ALL_NOT_RUN'}, indent=2))


if __name__ == '__main__':
    main()
