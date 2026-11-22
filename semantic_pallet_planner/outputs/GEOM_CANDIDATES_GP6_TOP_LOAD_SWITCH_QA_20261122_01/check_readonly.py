"""Verify shipped switch artifacts without executing a planner, monitor or transport."""
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator

HEAD = 'd7603db0a6ce60ca5ce25d7b4a39cc3b9f1d68f4'
O = Path('semantic_pallet_planner/outputs')
DEV = O / 'GEOM_CANDIDATES_GP6_TOP_LOAD_SWITCH_20261122_01'
SRC = Path('semantic_pallet_planner/src/semantic_pallet_planner')


def read(p):
    return json.loads(p.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                          allow_nan=False).encode())


def keys(value):
    if isinstance(value, dict):
        return set(value) | set().union(*(keys(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(keys(v) for v in value))
    return set()


def main():
    manifest = read(DEV / 'delivery_manifest.json')['files']
    for path, expected in manifest.items():
        archived = subprocess.check_output(['git', 'show', f'{HEAD}:{path}'])
        assert sha(archived) == sha(Path(path).read_bytes()) == expected, path
    source = {p.relative_to(SRC).as_posix(): sha(p.read_bytes()) for p in SRC.rglob('*')
              if p.is_file() and p.suffix in ('.py', '.json')
              and not {'tests', '__pycache__'}.intersection(p.relative_to(SRC).parts)}
    identity = read(DEV / 'source_identity.json')
    assert source == identity['files'] and digest(source) == identity['source_identity']
    monitor_path = O / 'GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01/monitor_snapshot.json'
    monitor = read(monitor_path)
    algorithm_files = monitor['algorithm_identity']['files_sha256']
    assert all(sha((SRC / 'jev_select/stability' / p).read_bytes()) == h for p, h in algorithm_files.items())

    test = ET.parse(DEV / 'offline_checks.xml').find('testsuite')
    assert (test.attrib['tests'], test.attrib['failures'], test.attrib['errors'], test.attrib['skipped']) == ('2','0','0','0')
    assert {x.attrib['name'] for x in test.findall('testcase')} == {
        'test_overload_fixture_both_backends', 'test_actual_disabled_request'}
    fixture = read(DEV / 'fixture_receipt.json')
    assert fixture['status'] == 'PASS' and fixture['real_calls'] == 0
    assert len(fixture['rows']) == 4
    assert {(x['backend'], x['enabled'], x['placed']) for x in fixture['rows']} == {
        (b, enabled, 1 if enabled else 2)
        for b in ('e2_original_v1', 'ems_surface_hybrid_v1') for enabled in (True, False)}

    request = read(DEV / 'disabled_request.json')
    state = request['state']
    choice = request['questions']['next_action']
    assert set(request) == {'model','state','questions'} and request['model'] == 'jev-1.14.0'
    assert set(request['questions']) == {'next_action'} and choice['type'] == 'choice'
    assert state['packaging_top_load_limit_enabled'] is False and state['memories'] == []
    forbidden = {'max_top_load_kg','effective_top_permission_kg','remaining_top_load_kg',
                 'capacity_utilization','utilization_status','top_load_limit_kg_synthetic'}
    assert not keys(request).intersection(forbidden)
    assert not any('remaining' in k or ('capacity' in k and k != 'capacity') for k in keys(request))
    assert state['buffer']['capacity'] == 3 and 'mass_kg' in keys(state['available_objects'])
    assert all({'support_ratio','support_fractions'} <= x['features'].keys() for x in choice['criteria'].values())
    for value in (choice['instructions'], state['objective']):
        assert 'preserve load' not in value.lower() and 'and capacity' not in value.lower()
    receipt = read(DEV / 'request_receipt.json')
    assert receipt['selected_label'] in choice['criteria'] and receipt['monitor_enabled'] is True
    assert receipt['status'] == 'PASS' and receipt['algorithm'] == monitor['algorithm']

    plan = read(DEV / 'gp6_top_load_disabled_plan_DRAFT.json')
    layout = read(DEV / 'run_layout_DRAFT.json')
    schema = read(SRC / 'jev_select/schemas/geometry_jev_plan_v2.schema.json')
    Draft202012Validator(schema).validate(plan)
    pd = digest(plan)
    assert pd == layout['plan_digest'] == read(DEV / 'handoff.json')['plan_digest']
    assert plan['status'] == 'DRAFT' and plan['source_identity'] == identity['source_identity']
    assert plan['packaging_top_load_limit_enabled'] is False
    task, = plan['tasks']
    assert task['task_id'] == 'NEW_00100027_controlled_base' and task['origin'] == 'EXPOSED_TRAIN'
    data = O / 'DATA_JEV_PACKAGING_LOAD_20261102_02'
    assert plan['data_identity'] == read(data / 'manifest.json')['data_identity']
    assert all(sha((data / p).read_bytes()) == h for p, h in layout['data_checks'].items())
    assert sha((data / 'tasks' / f"{task['task_id']}.json").read_bytes()) == task['raw_sha256']
    assert [(x['job_id'],x['task_id'],x['backend'],x['method']) for x in plan['jobs']] == [
        (j,task['task_id'],b,'jev_no_memory') for j,b in
        zip(('G00','G01'),('e2_original_v1','ems_surface_hybrid_v1'))]
    assert (plan['per_job_max_sends'],plan['shared_max_sends'],plan['model_calls_max']) == (19,38,38)
    assert layout['authorized_for_api_calls'] is False
    for name in ('request_ledger_path','call_ledger_path'):
        path = Path(plan[name])
        assert str(path) == layout[name] and not path.exists()
        assert not path.resolve().is_relative_to(Path(layout['run_root']).resolve())
    assert Path(plan['request_ledger_path']).name == 'requests.json'
    assert not Path(layout['run_root']).exists()
    prospective = {**plan,'status':'FROZEN'}
    Draft202012Validator(schema).validate(prospective)
    print(json.dumps({
        'reviewed_head':HEAD,'development_manifest_entries':len(manifest),'source_files':len(source),
        'source_identity':digest(source),'algorithm_identity_files_unchanged':len(algorithm_files),
        'offline_cases_archived':2,'fixture_rows':fixture['rows'],'sample_choice_count':len(choice['criteria']),
        'request_projection':'PASS_SAVED_BYTES','draft_plan_digest':pd,
        'prospective_plan_digest_status_change_only':digest(prospective),
        'prospective_plan_written':False,'formal_joint_preflight':'NOT_RUN','real_model_calls':0,
    },ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
