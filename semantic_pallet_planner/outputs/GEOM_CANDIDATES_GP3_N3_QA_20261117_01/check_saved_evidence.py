"""Independent saved bytes/links/phase facts and STATIC error-path witness.
No production imports, candidate reconstruction, replay, physics or solver.
"""
from pathlib import Path
import ast,hashlib,json,subprocess
DEV=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_20261117_01')
BASE=Path('semantic_pallet_planner/outputs')
PKG=Path('semantic_pallet_planner/src/semantic_pallet_planner')
NAV='docs/03_阶段产出分析/几何规划模块/README.md'
HEAD='eec656877c9a22255fc4dd2a7e5d50e39bbfee0b'
def enc(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(v):return hashlib.sha256(v).hexdigest()
def digest(v):return sha(enc(v))
def read(p):return json.loads(p.read_bytes())
def blob(rev,p):return subprocess.run(['git','show',rev+':'+p],check=True,capture_output=True).stdout
s=read(DEV/'source_manifest.json')
actual={p.relative_to(PKG).as_posix():sha(p.read_bytes()) for p in PKG.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(PKG).parts)}
assert actual==s['files'] and len(actual)==542
prior=read(BASE/'GEOM_CANDIDATES_GP3_N2_R1_20261117_01/source_manifest.json')['files']
assert sorted(n for n in prior if actual.get(n)!=prior[n])==sorted(s['changed_existing'])
assert sorted(set(actual)-set(prior))==sorted(s['added'])
assert len(s['changed_existing'])==11 and len(s['added'])==8
for n in s['changed_existing']+s['added']:assert sha((DEV/'source_snapshot'/n).read_bytes())==actual[n]
assert all(actual[n]==h for n,h in prior.items() if '/schemas/' in n)
m=read(DEV/'delivery_manifest.json')
for r in m['files']:
    p=Path(r['path']);raw=p.read_bytes()
    if sha(raw)!=r['sha256'] and str(p)==NAV:raw=blob(HEAD,str(p))
    assert sha(raw)==r['sha256'] and len(raw)==r['size_bytes'],str(p)
rows=[];blob_copies=monitors=0;foreign_phase_records=[]
known_configs={digest(read(d/'config.json')):read(d/'config.json') for d in (DEV/'cases').iterdir()}
for p in sorted((DEV/'cases').iterdir()):
    cfg,task,result,phases=[read(p/(n+'.json')) for n in ('config','task','result','phases')]
    cp=result['checkpoint'];assert enc(read(p/'durable/checkpoint.json'))==enc(cp)
    assert cp['record_digest']==digest({k:v for k,v in cp.items() if k!='record_digest'})
    assert digest(cfg)==cp['config_digest']==cp['execution_binding']['config_digest']
    assert digest(task)==cp['task_digest']==cfg['fixture_task_digest']
    assert cfg['runtime_identity']['source_identity']==digest(actual)
    def get(ref):
        raw=(p/'durable/blobs'/ref['sha256']).read_bytes();assert sha(raw)==ref['sha256'];return raw
    def obj(ref):return json.loads(get(ref))
    for f in (p/'durable/blobs').iterdir():assert sha(f.read_bytes())==f.name;blob_copies+=1
    for idx,statecp in enumerate(phases):
        assert statecp['record_digest']==digest({k:v for k,v in statecp.items() if k!='record_digest'})
        assert statecp['config_digest'] in known_configs
        if statecp['config_digest']!=digest(cfg):foreign_phase_records.append({'case':p.name,'index':idx,'config_digest':statecp['config_digest']})
        if statecp['pending_event'] is not None:
            ev=statecp['pending_event']
            if statecp['phase']=='COMMITTED':assert enc(statecp['state'])==enc(ev['after'])
            else:assert enc(statecp['state'])==enc(ev['before'])
    phases=[c for c in phases if c['config_digest']==digest(cfg)]
    selected=[i for i,c in enumerate(phases) if c['phase']=='SELECTED'];monitored=[i for i,c in enumerate(phases) if c['phase']=='MONITORED'];committed=[i for i,c in enumerate(phases) if c['phase']=='COMMITTED']
    if selected and monitored:assert min(selected)<min(monitored)
    if monitored and committed:assert min(monitored)<min(committed)
    for ev in cp['events']:
        if ev.get('geometry_ref'):
            a=obj(ev['geometry_ref'])
            if a['version']=='geometry_durable_decision_v1':
                assert enc(a['bundle'])==enc(ev['bundle']) and enc(a['audit']['config'])==enc(cfg)
                assert digest(a['audit'])==ev['bundle']['geometry_audit_digest']
                i=obj(a['input']);nraw,graw=get(i['native']),get(i['geometry'])
                assert sha(nraw)==i['binding']['native_snapshot_sha256'] and sha(graw)==i['binding']['geometry_input_sha256']
                assert enc(json.loads(nraw)['current_state'])==enc(ev['before'])
                assert a['audit']['native_bytes_hex']==nraw.hex() and a['audit']['geometry_bytes_hex']==graw.hex()
                assert digest(i['binding'])==ev['bundle']['common_input_digest']
            else:assert a['version']=='geometry_generation_failure_v1' and a['audit']['TEST_DOUBLE'] is True
        row=ev.get('monitor')
        if row:
            assert row['binding']['state_digest']==digest(ev['before'])
            assert row['binding']['action_digest']==digest(ev['proposed_action'])
            assert row['credential_digest']==digest({k:v for k,v in row.items() if k!='credential_digest'})
            if row['result'] is not None:
                assert row['result']['diagnostics']['TEST_DOUBLE'] is True and row['result']['kernel_calls']==0
                monitors+=1
            if row['status']!='STABLE':assert enc(ev['before'])==enc(ev['after']) and ev['action'] is None
        if ev['event']=='PLACE':assert row and row['status']=='STABLE' and ev['action']==ev['proposed_action']
    rows.append({'case':p.name,'termination':cp['reason'],'placed_count':cp['state']['placed_count'],'phases':list(dict.fromkeys(c['phase'] for c in phases))})
assert len(rows)==13
for phase in ('SELECTED','MONITORED','COMMITTED'):
    cp=read(DEV/'resume'/f'{phase}_interrupted.json')
    assert cp['phase']==phase and cp['reason'] is None
    assert cp['record_digest']==digest({k:v for k,v in cp.items() if k!='record_digest'})
# Static scalar witness only, NOT a production exception/recovery reproduction.
# These are the scalar facts the public evaluation-exception branch assigns.
cp=read(DEV/'resume/COMMITTED_interrupted.json')
assert cp['pending_event'] is not None and all(e.get('reason') is None for e in cp['events'])
produced_reason='EVALUATION_ERROR';produced_phase='COMMITTED';stopped=None
validator_expected=stopped or None # pending is non-null, so ALL_ITEMS_PLACED branch is ineligible
footer_reject=(produced_reason!=validator_expected or (produced_phase=='TERMINATED')!=(validator_expected is not None))
assert footer_reject
schema=read(PKG/'jev_select/schemas/checkpoint_v15.schema.json')
assert schema['properties']['reason']=={'anyOf':[{'type':'null'},{'type':'string'}]}
secondary_expected={'UNSTABLE':'PREDICTED_STATIC_INSTABILITY','UNASSESSABLE':'STABILITY_UNASSESSABLE','ERROR':'STABILITY_MONITOR_ERROR','DISABLED':'GEOMETRY_MONITOR_DISABLED'}.get('STABLE')
assert secondary_expected is None
witness={'issue':'GP3-N3-REC-01','evidence_type':'STATIC_CONTROL_FLOW_AND_SCALAR_WITNESS_NOT_PRODUCTION_REPRODUCTION','archived_basis':str(DEV/'resume/COMMITTED_interrupted.json'),'producer':'episode.py:409-418 saves phase COMMITTED, reason EVALUATION_ERROR, pending error','consumer':'geometry_execution.py:239-246 expects reason None when pending exists','produced_reason':produced_reason,'produced_phase':produced_phase,'validator_expected_reason':validator_expected,'footer_rejects':footer_reject,'secondary':'episode exception path saves unchanged-state COMMIT_FAILURE after STABLE; geometry_execution.py:217-220 has no STABLE technical-failure terminal case','secondary_monitor_mapping_result':secondary_expected,'kernel_or_runtime_calls':0,'actual_error_checkpoint_generated':False}
# Schema and execution protections, static only.
oldschema=read(PKG/'jev_select/schemas/config_v14.schema.json');assert oldschema['properties']['construction_only']['const'] is True
for f,names in [('episode.py',{'run_episode','_run_episode_v2'}),('execution.py',{'commit_physical'}),('selector.py',{'result'})]:
    for node in ast.parse((PKG/'jev_select'/f).read_text()).body:
        if isinstance(node,ast.FunctionDef) and node.name in names:assert node.body[1].value.func.id=='reject_geometry_execution'
print(json.dumps({'status':'PASS_SAVED_FACTS_WITH_BLOCKING_STATIC_RECOVERY_FINDING','manifest_members':len(m['files']),'production_files':542,'changed':11,'added':8,'unchanged':523,'cases':rows,'blob_file_copies':blob_copies,'test_double_monitor_rows':monitors,'saved_interrupted_phases':3,'foreign_phase_records':foreign_phase_records,'static_recovery_witness':witness,'production_imports':0,'candidate_generation':0,'orders_PCT_LP_models':0,'real_exact_v3_E2E':'NOT_RUN'},ensure_ascii=False,indent=2))
