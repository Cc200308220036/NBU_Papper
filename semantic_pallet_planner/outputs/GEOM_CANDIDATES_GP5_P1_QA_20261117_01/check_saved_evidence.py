"""Independent saved-fact QA only. No project imports or business execution."""
import hashlib
import json
import math
import subprocess
from pathlib import Path

OUT = Path(__file__).parent
DEV = OUT.parent / 'GEOM_CANDIDATES_GP5_P1_20261117_01'
SRC = Path('semantic_pallet_planner/src/semantic_pallet_planner')

def read(p):
    return json.loads(p.read_bytes())

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def digest(v):
    return sha(json.dumps(v, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode())

def save(name, v):
    (OUT / name).write_text(json.dumps(v, ensure_ascii=False, indent=2) + '\n')

manifest = read(DEV / 'delivery_manifest.json')
for row in manifest['files']:
    # Shared navigation changes with QA. Verify sealed delivery-time Git bytes.
    raw = (subprocess.check_output(['git', 'show',
           'c7f99638e4d5ab603b3a6e86c02f589555ea7b55:' + row['path']])
           if Path(row['path']).name == 'README.md' else Path(row['path']).read_bytes())
    assert sha(raw) == row['sha256'] and len(raw) == row['size_bytes'], row['path']
before = read(DEV / 'before_source_manifest.json')['files']
current = {str(p.relative_to(SRC)): sha(p.read_bytes()) for p in SRC.rglob('*')
           if p.is_file() and p.suffix in ('.py', '.json')
           and not {'tests', '__pycache__'}.intersection(p.relative_to(SRC).parts)}
source = read(DEV / 'source_manifest.json')
assert current == source['files'] and digest(current) == source['source_identity']
modified = sorted(k for k in before if before[k] != current.get(k))
added = sorted(set(current) - set(before))
assert len(modified) == 10 and len(added) == 18 and not set(before) - set(current)
assert read(DEV.parent / 'GEOM_CANDIDATES_GP5_P0_20261117_01/source_inventory.json')['files'] == before
for rel in modified + added:
    assert (DEV / 'code_snapshot' / rel).read_bytes() == (SRC / rel).read_bytes()

ev = DEV / 'final_evidence'
k02 = []
for i in range(4):
    root = ev / 'test_two_backends_two_methods_complete_and_k02_exact_target' / ('job' + str(i))
    d, task = read(root / 'episode.json'), read(root / 'task.json')
    phases = read(root / 'phases.json')
    events = [e for e in d['events'] if e['event'] == 'PLACE']
    assert len(events) == 2
    for j, e in enumerate(events):
        pool = e['bundle']['physical_candidates']
        selected = next(c for c in pool if c['candidate_id'] == e['selection']['selected_candidate_id'])
        assert len(pool) == (2 if j == 0 else 1)
        assert selected['pose'] == {'x_mm': 0, 'y_mm': 0, 'z_base_mm': 60*j, 'yaw_deg': 0}
        assert all(c['pose'] == selected['pose'] for c in pool)
        assert e['action'] == e['proposed_action']
        m = e['monitor']
        assert m['status'] == 'STABLE' and m['result']['diagnostics']['TEST_DOUBLE'] is True
        assert m['result_digest'] == digest(m['result'])
        assert m['credential_digest'] == digest({k:v for k,v in m.items() if k != 'credential_digest'})
        for phase in ('SELECTED', 'MONITORED', 'COMMITTED'):
            assert any(c['phase'] == phase and c['pending_event']['decision_id'] == e['decision_id'] for c in phases)
    placed = d['final_state']['placed_items']
    vol = sum(math.prod(o['oriented_size_mm']) for o in placed)
    height = max(o['pose']['z_base_mm'] + o['oriented_size_mm'][2] for o in placed)
    metric = d['summary']
    assert metric['planned_items'] == metric['placed_items'] == 2
    assert metric['placed_volume_ratio'] == metric['placed_mass_ratio'] == metric['placed_item_ratio'] == 1
    assert metric['fixed_container_utilization'] == vol/(100*80*180) == 2/3
    assert metric['envelope_utilization'] == vol/(100*80*height) == 1
    assert metric['counts'] == {'assessment_entries':0, 'solver_calls':0, 'test_double_assessments':2}
    k02.append({'backend':metric['candidate_backend'], 'method':metric['method'],
                'pool_sizes':[2,1], 'selected_z':[0,60], 'evidence':'TEST_DOUBLE', 'saved_arithmetic':'PASS'})

recovery = {}
rr = ev / 'test_resume_selected_monitored_committed_no_duplicate_work'
for phase, expected in [('SELECTED',[1,1]), ('MONITORED',[0,1]), ('COMMITTED',[0,0])]:
    counts = read(rr / phase / 'counts.json')
    delta = [a-b for a,b in zip(counts['after'], counts['before'])]
    assert delta == expected
    recovery[phase] = {'monitor_commit_delta':delta, 'evidence':'archived test counter, not locally rerun'}
stops = {}
for status in ('UNSTABLE', 'UNASSESSABLE', 'ERROR'):
    d = read(ev / 'test_stop_classification_failed_box_not_committed' / (status+'.json'))
    assert d['summary']['placed_items'] == 0 and d['events'][-1]['before'] == d['events'][-1]['after']
    stops[status] = d['summary']['termination_reason']
integer = read(ev / 'test_integer_multistep_type_conflict_is_preserved_technical_failure/integer_type_conflict.json')
assert integer['summary']['termination_reason'] == 'RUNTIME_INPUT_INVALID'
assert integer['summary']['placed_items'] == 1
obj = integer['final_state']['placed_items'][0]
assert all(type(x) is int for x in obj['dimensions_mm'].values())
assert [type(x).__name__ for x in obj['oriented_size_mm']] == ['float', 'float', 'int']

real = ev / 'test_real_tasks_admin_adaptation_and_formal_gates_before_episode'
plan = read(real / 'plan_draft.json')
denominator = read(real / 'run_denominator.json')
identities = read(real / 'identities.json')
assert len(denominator['rows']) == 8 and all(r['status'] == 'NOT_RUN' for r in denominator['rows'])
assert len({r['source_group_id'] for r in identities}) == 1
data = DEV.parent / 'DATA_JEV_PACKAGING_LOAD_20261102_02'
for row in identities:
    raw = (data / 'tasks' / (row['task_id']+'.json')).read_bytes()
    task = json.loads(raw)
    assert sha(raw) == row['raw_sha256'] and digest(task) == row['normalized_digest']
    assert len(task['items']) == 19 and task['arrival_order'] == [i['item_id'] for i in task['items']]

# Enumerate structural holes; schema checks are not production bypass probes.
holes = []
for rel in added:
    if not rel.endswith('.json'): continue
    def walk(v, pointer=''):
        if isinstance(v, dict):
            if v.get('type') == 'object' and set(v) == {'type'}:
                holes.append({'file':rel, 'pointer':pointer, 'schema':v})
            for k,x in v.items(): walk(x, pointer+'/'+k)
        elif isinstance(v, list):
            for i,x in enumerate(v): walk(x, pointer+'/'+str(i))
    walk(read(SRC / rel))
save('schema_open_objects.json', {'unconstrained_object_nodes':holes,
     'typed_maps_not_classified_as_holes':True, 'limit':'semantic validators may reject; no production bypass reproduction'})
save('saved_evidence_verification.json', {
    'status':'PASS_SAVED_FACTS_ONLY', 'manifest_members':len(manifest['files']),
    'production_files':len(current), 'source_identity':source['source_identity'],
    'modified':modified, 'added':added, 'unchanged_old_files':len(before)-len(modified),
    'source_drift':False, 'K02':k02, 'recovery':recovery, 'stop_classification':stops,
    'integer_issue':{'id':'GP5-P1-NUM-01','status':'OPEN','placed':1,
                     'dimensions_types':['int']*3,'oriented_types':['float','float','int']},
    'real_tasks':{'counts':[19,19],'source_families':1,'jobs':8,'all_jobs':'NOT_RUN'},
    'local_business_tests':'NOT_RUN', 'production_imports':0,
    'candidate_order_kernel_solver_freeze_model_execution':0})
print('PASS: independent saved identities, K02, arithmetic, recovery counts, stop facts and raw tasks; no production imports')
