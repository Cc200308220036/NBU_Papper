"""Check the delivered bytes and draft bindings without importing the planner."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

from jsonschema import Draft202012Validator

BASE = 'fba934ea558a26b9d6691aacc6acf868d1780c20'
HEAD = '43028c00c7a870310bafc042130162a2692d801c'
O = Path('semantic_pallet_planner/outputs')
P = O / 'GEOM_CANDIDATES_GP6_F0_PRELAUNCH_MATERIALS_20261122_01'
SOURCE = Path('semantic_pallet_planner/src/semantic_pallet_planner')
SCHEMAS = SOURCE / 'jev_select/schemas'


def read(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                          allow_nan=False).encode())


def git(*args):
    return subprocess.check_output(['git', *map(str, args)])


def blob(commit, path):
    return git('show', f'{commit}:{path}')


def refs(value, found):
    if isinstance(value, dict):
        if set(value) == {'path', 'sha256'}:
            path, expected = value['path'], value['sha256']
            if path not in found:
                raw = Path(path).read_bytes()
                assert sha(raw) == sha(blob(HEAD, path)) == expected, path
                found[path] = expected
                try:
                    nested = json.loads(raw)
                except (ValueError, UnicodeError):
                    return
                refs(nested, found)
            else:
                assert found[path] == expected
        else:
            for child in value.values():
                refs(child, found)
    elif isinstance(value, list):
        for child in value:
            refs(child, found)


def main():
    delivery = read(P / 'delivery_manifest.json')
    for entry in delivery['files']:
        raw = blob(HEAD, entry['path'])
        assert (len(raw), sha(raw)) == (entry['bytes'], entry['sha256']), entry['path']
        assert Path(entry['path']).read_bytes() == raw, entry['path']
    assert len(delivery['files']) == delivery['file_count']
    assert not git('diff', '--name-only', BASE, HEAD, '--', SOURCE, 'semantic_pallet_planner/tests',
                   'semantic_pallet_planner/outputs/*GP5*')
    env = read(P / 'environment_evidence.json')
    past = env['gp5_reference_snapshot']
    for name in ('real_kernel_receipt', 'source_manifest', 'monitor_snapshot'):
        path, expected = past[f'{name}_path'], past[f'{name}_sha256']
        assert sha(Path(path).read_bytes()) == sha(blob(HEAD, path)) == expected
    old_source = read(Path(past['source_manifest_path']))
    monitor = read(Path(past['monitor_snapshot_path']))
    old_receipt = read(Path(past['real_kernel_receipt_path']))
    assert digest(old_source['files']) == old_receipt['source_identity'] == past['source_identity']
    assert digest(monitor) == old_receipt['monitor_digest'] == past['monitor_digest']
    assert digest(monitor['algorithm_identity']) == past['algorithm_digest']
    assert digest(env['live_environment']) == env['live_environment_digest'] == old_receipt['environment_digest']
    assert env['live_monitor_execution_environment'] == monitor['execution_environment']
    algo = monitor['algorithm_identity']
    assert env['live_solver_dependencies'] == algo['dependencies']
    assert digest(algo['dependencies']) == env['live_dependency_digest'] == algo['dependency_digest']
    for path, expected in algo['files_sha256'].items():
        assert sha((SOURCE / 'jev_select/stability' / path).read_bytes()) == expected
    hist = env['historical_source_copy_provenance']
    with tarfile.open(fileobj=io.BytesIO(git('archive', hist['commit'], SOURCE))) as archive:
        hashed = {}
        for row in archive.getmembers():
            if row.isfile():
                path = Path(row.name).relative_to(SOURCE)
                if path.suffix in ('.py', '.json') and not {'tests', '__pycache__'}.intersection(path.parts):
                    hashed[path.as_posix()] = sha(archive.extractfile(row).read())
    assert hashed == old_source['files']
    assert hist['file_count'] == len(hashed)
    found = {}
    refs(old_receipt, found)
    assert len(found) == 38
    for row in env['historical_reference_checks']:
        assert row['expected_sha256'] == row['actual_sha256'] == found[row['path']]

    plan = read(P / 'gp6_f0_order_plan_DRAFT.json')
    denom = read(P / 'run_denominator_NOT_RUN.json')
    for filename, data in (('geometry_jev_plan_v1', plan), ('geometry_jev_run_v1', denom)):
        Draft202012Validator(read(SCHEMAS / f'{filename}.schema.json')).validate(data)
    assert plan['status'] == 'DRAFT' and digest(plan) == denom['plan_digest']
    assert [j['job_id'] for j in plan['jobs']] == [r['job_id'] for r in denom['rows']] == ['G00', 'G01', 'G02', 'G03']
    assert all(r['status'] == 'NOT_RUN' and r['metrics'] is None for r in denom['rows'])
    assert plan['per_job_max_sends'] == 19 and plan['shared_max_sends'] == plan['model_calls_max'] == 76
    assert not Path(plan['request_ledger_path']).exists() and not Path(plan['call_ledger_path']).exists()
    data = O / 'DATA_JEV_PACKAGING_LOAD_20261102_02'
    assert read(data / 'manifest.json')['data_identity'] == plan['data_identity']
    for task in plan['tasks']:
        path = data / 'tasks' / f"{task['task_id']}.json"
        raw = path.read_bytes()
        row = json.loads(raw)
        assert sha(raw) == task['raw_sha256']
        assert row['partition'] == 'train' and len(row['items']) == 19
        assert row['source_group_id'] == task['source_group_id'] == 'SG_901bbb22f834c63f'
    pending = read(P / 'kernel_applicability_review_PENDING.json')
    bridge = read(P / 'kernel_bridge_PENDING.json')
    delta = [{k: row[k] for k in ('path', 'before', 'after')} for row in pending['changes']]
    assert len(delta) == 28 and digest(delta) == pending['diff_digest']
    qa = read(O / 'GEOM_CANDIDATES_GP6_F0_BUDGET_REC_FIX_QA_20261121_01' / 'readonly_results.json')
    assert delta == qa['source_delta']
    assert plan['source_identity'] == qa['source_identity'] == delivery['source_identity']
    assert pending['target'] == bridge['target']
    for k in ('source_identity', 'environment_digest', 'runtime_version', 'publication_policy_digest'):
        assert pending['target'][k] == plan[k]
    assert pending['target']['monitor_digest'] == past['monitor_digest']
    assert pending['target']['algorithm_digest'] == past['algorithm_digest']
    assert pending['target']['plan_digest'].startswith('<PENDING')
    assert not Path(bridge['historical_package_root']).exists()

    print(json.dumps({'reviewed_commit': HEAD, 'delivery_manifest_entries': len(delivery['files']),
                      'historical_git_source_files': len(hashed), 'historical_receipt_and_references': len(found) + 1,
                      'algorithm_identity_files': len(algo['files_sha256']), 'source_delta_rows': len(delta),
                      'draft_plan_digest': digest(plan), 'draft_and_denominator_schema': 'PASS',
                      'draft_raw_tasks': 2, 'draft_jobs_not_run': 4,
                      'linux_archive_consistency': 'PASS', 'linux_live_rerun': 'NOT_RUN',
                      'historical_worker_rerun': 'NOT_RUN', 'model_calls': 0}, indent=2))


if __name__ == '__main__':
    main()
