"""Independent R1 saved-fact QA. No project imports, dispatch, fork or replay."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

OUT=Path(__file__).parent
DEV=OUT.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01'
SRC=Path('semantic_pallet_planner/src/semantic_pallet_planner')
HEAD='cb9575d0e3c8f719b371effdc16eaad517e66e1e'
def read(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def enc(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return sha(enc(v))
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

manifest=read(DEV/'delivery_manifest.json')
for row in manifest['files']:
    raw=(subprocess.check_output(['git','show',HEAD+':'+row['path']])
         if Path(row['path']).name=='README.md' else Path(row['path']).read_bytes())
    assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'],row['path']
source=read(DEV/'source_manifest.json');base=read(DEV/'baseline_receipt.json')
actual={str(p.relative_to(SRC)):sha(p.read_bytes()) for p in SRC.rglob('*')
        if p.is_file() and p.suffix in ('.py','.json')
        and not {'tests','__pycache__'}.intersection(p.relative_to(SRC).parts)}
assert actual==source['files'] and digest(actual)==source['source_identity']
changed=[k for k,h in actual.items() if h!=base['files'].get(k)]
assert changed==['jev_select/schemas/checkpoint_v17.schema.json']
schemas=SRC/'jev_select/schemas'
old=read(DEV/'checkpoint_v17.before.schema.json');new=read(schemas/'checkpoint_v17.schema.json')
old['$defs']['monitor_result']['properties']['candidate_id'].pop('pattern')
assert old==new
assert new['$defs']['monitor_result']==read(schemas/'checkpoint_v16.schema.json')['$defs']['monitor_result']
historical=0
for group in base['manifests']:
    p=Path(group['manifest']);assert sha(p.read_bytes())==group['sha256']
    for row in read(p)['files']:
        raw=(subprocess.check_output(['git','show',group['navigation_revision']+':'+row['path']])
             if Path(row['path']).name=='README.md' else Path(row['path']).read_bytes())
        assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'];historical+=1

episode=read(DEV/'E/jobs/J00/episode.json');run=read(DEV/'E/run.json')
account=read(DEV/'E/jobs/J00/accounting.json');calls=read(DEV/'call_accounting.json')
suite=read(DEV/'E_results.json');stop=read(DEV/'stop.json');cp=episode['checkpoint']
assert cp['phase']=='TERMINATED' and cp['reason']=='ALL_ITEMS_PLACED'
assert cp['record_digest']==digest({k:v for k,v in cp.items() if k!='record_digest'})
assert episode['summary']['completed'] and episode['summary']['placed_items']==2
assert len(run['rows'])==8 and run['rows'][0]['status']=='COMPLETE'
assert all(r['status']=='NOT_RUN' for r in run['rows'][1:])
assert suite[0]['status']=='TECHNICAL_FAILURE' and suite[0]['summary']['completed']
assert account['invocations'][-1]['status']=='RETURNED'
expected={'selector_calls':1,'singleton_executions':1,'monitor_entries':2,'monitor_reuses':0,'commit_attempts':2,'commit_successes':2}
assert account['cumulative']==expected and episode['summary']['accounting']['cumulative']==expected
assert calls['old_failed_E_monitors']==1 and calls['R1_E_monitors']==2 and calls['E_cumulative']==3
assert calls['R1_R_monitors']==calls['R1_X_H_monitors']==0
events=[e for e in episode['events'] if e['event']=='PLACE'];assert len(events)==2
facts=[];refs=0
blobdir=DEV/'E/jobs/J00/blobs'
for event in events:
    candidate=next(c for c in event['bundle']['physical_candidates'] if c['candidate_id']==event['selection']['selected_candidate_id'])
    item=next(p['item'] for p in event['before']['pending_items'] if p['item']['item_id']==candidate['pick_item_id'])
    axes=('length','width','height') if candidate['pose']['yaw_deg']==0 else ('width','length','height')
    correct=[item['dimensions_mm'][k] for k in axes]
    assert candidate['oriented_size_mm']==correct
    assert all(type(a) is type(b) for a,b in zip(candidate['oriented_size_mm'],correct))
    assert re.fullmatch(r'GP5N3_[0-9a-f]{64}',candidate['candidate_id'])
    monitor=event['monitor'];assert monitor['status']=='STABLE' and monitor['result']['diagnostics']['TEST_DOUBLE'] is True
    assert monitor['result']['candidate_id']==candidate['pick_item_id']
    assert monitor['result_digest']==digest(monitor['result'])
    assert monitor['credential_digest']==digest({k:v for k,v in monitor.items() if k!='credential_digest'})
    assert event['action']==event['proposed_action']
    artifact=read(blobdir/event['geometry_ref']['sha256'])
    for key,hx in artifact['audit']['publication']['blobs'].items():
        raw=bytes.fromhex(hx);assert sha(raw)==key and (blobdir/key).read_bytes()==raw;refs+=1
    facts.append({'candidate_id':candidate['candidate_id'],'box_id':candidate['pick_item_id'],'axes':axes,'size':correct,'size_types':[type(v).__name__ for v in correct]})
for p in blobdir.iterdir():
    if p.is_file():assert sha(p.read_bytes())==p.name
summary=episode['summary']
assert summary['fixed_container_utilization']==2/3 and summary['envelope_utilization']==1
assert summary['max_height_mm']==120 and summary['placed_volume_mm3']==960000
source_item=read(DEV/'GP5_SYNTH_K02_INT.raw.json')['items'][0]
bad=list(source_item['dimensions_mm'].values());right=[source_item['dimensions_mm'][k] for k in ('length','width','height')]
assert bad==[60,100,80] and right==[100,80,60] and cp['state']['placed_items'][0]['oriented_size_mm']==right
text=(DEV/'run_bounded_validation.py').read_text(encoding='utf-8');ast.parse(text)
assert 'list(tasks[job[\'task_id\']][\'runtime\'][\'items\'][0][\'dimensions_mm\'].values())' in text
assert stop['group']=='E' and 'AssertionError' in stop['traceback'] and stop['no_retry'] is True
pattern_count=0
for name in ('candidate_bundle_v17','decision_context_v17','selection_result_v17','checkpoint_v17'):
    def scan(v):
        global pattern_count
        if isinstance(v,dict):
            if v.get('pattern')=='^GP5N3_[0-9a-f]{64}$':pattern_count+=1
            for x in v.values():scan(x)
        elif isinstance(v,list):
            for x in v:scan(x)
    scan(read(schemas/(name+'.schema.json')))
assert pattern_count==13
save('saved_evidence_verification.json',{'status':'PASS_SAVED_FACTS_ONLY','manifest_members':len(manifest['files']),
    'historical_members':historical,'source_files':len(actual),'source_identity':source['source_identity'],
    'source_drift':False,'single_production_change':changed,'monitor_result_equals_v16':True,'published_id_patterns_retained':pattern_count,
    'schema_issue':'CLOSED_LIMITED_STATIC_AND_SAVED_E2_RUNTIME_EVIDENCE','production_E':{'complete':1,'not_run':7,'failed':0},
    'suite_validation':'FAIL_HARNESS_AFTER_PRODUCTION_SUCCESS','schema_roles':facts,'accounting':expected,
    'E_monitor_cumulative':3,'E_monitor_limit':17,'remaining_E_monitor_allowance':14,
    'publication_blob_reference_occurrences_not_unique':refs,'saved_named_axis_result':{'bad_values':bad,'correct_axes':right},
    'R_runtimeX_H_ADMIN':'NOT_RUN','schema_business_tests':'NOT_RUN_LOCAL_JSONSCHEMA_UNAVAILABLE',
    'production_imports':0,'candidate_order_shadow_fork_recovery_kernel_solver_model_execution':0})
save('harness_issue_evidence.json',{'issue':'GP5-NUM-N1-R1-HARNESS-01','status':'CONFIRMED_TEST_HARNESS_DEFECT',
    'literal_source_key_order':list(source_item['dimensions_mm']),'wrong_values_order':bad,'correct_named_axes':right,
    'raw_production_status':'COMPLETE','raw_suite_status':'TECHNICAL_FAILURE_WITH_COMPLETED_SUMMARY',
    'script_line':next(i for i,l in enumerate(text.splitlines(),1) if "list(tasks[job['task_id']]['runtime']['items'][0]['dimensions_mm'].values())" in l),
    'raw_files_preserved':True,'no_production_failure_inferred':True,'no_replay':True})
print('PASS saved identities/single-field schema diff/J00 completed trajectory; harness axis-order defect confirmed; no replay')
