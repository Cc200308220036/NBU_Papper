"""Standard-library saved-fact audit after stop; no production imports/replay."""
import hashlib,json,subprocess
from pathlib import Path
OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N1_R2_20261118_01')
OLD=OUT.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01'
def read(f):return json.loads(f.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(v):return sha(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def hashes(root):return {str(f.relative_to(root)):sha(f.read_bytes()) for f in root.rglob('*') if f.is_file()}
base=read(OUT/'baseline_receipt.json');src=Path('semantic_pallet_planner/src/semantic_pallet_planner');source=read(OUT/'source_manifest.json')
actual={str(f.relative_to(src)):sha(f.read_bytes()) for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
assert actual==source['files'] and digest(actual)==base['source_identity']
for group in base['manifests']:
    m=Path(group['manifest']);assert sha(m.read_bytes())==group['sha256']
    for r in read(m)['files']:
        f=Path(r['path']);raw=subprocess.check_output(['git','show',group['navigation_revision']+':'+str(f)]) if f.name=='README.md' else f.read_bytes()
        assert sha(raw)==r['sha256'] and len(raw)==r['size_bytes']
provenance=read(OUT/'prefix_provenance.json');assert hashes(OLD/'E')==hashes(OUT/'prefix_snapshot')==provenance['files']
assert hashes(OUT/'continuation/jobs/J00')==hashes(OLD/'E/jobs/J00')
for n in ('plan.json','admission.json','configs.json','monitor_snapshot.json','validation_scope.json','source_manifest.json','GP5_SYNTH_K02_INT.raw.json','GP5_SYNTH_K02.raw.json'):
    assert (OUT/n).read_bytes()==(OLD/n).read_bytes()
run=read(OUT/'continuation/run.json');assert [r['status'] for r in run['rows']]==['COMPLETE','COMPLETE','TECHNICAL_FAILURE']+['NOT_RUN']*5
j1=read(OUT/'continuation/jobs/J01/episode.json');j2=read(OUT/'continuation/jobs/J02/episode.json')
assert j1['summary']['completed'] and len(j1['final_state']['placed_items'])==2
assert j2['summary']['termination_reason']=='NUM_BRIDGE_IDENTITY_MISMATCH' and j2['summary']['placed_items']==0
failure=next(e for e in j2['events'] if e.get('error'));ref=failure['geometry_ref'];raw=(OUT/'continuation/jobs/J02/blobs'/ref['sha256']).read_bytes();assert sha(raw)==ref['sha256'];artifact=json.loads(raw)
audit=artifact['audit'];pool=json.loads(bytes.fromhex(audit['raw_pool_bytes_hex']));candidate=pool[0]
row=next(x for item in audit['generation']['audit']['items'] for x in item['raw_valid_candidates'] if x['candidate']['candidate_fingerprint']==candidate['candidate_fingerprint'])
raw_key=row['action_key'];assert raw_key==['synth_1','100','80','60','0','0','0','0']
# Literal metadata contrast only: bridge.action_key's yaw slot is the native pose yaw.
bridge_key=list(raw_key);bridge_key[4]=candidate['pose']['yaw_deg'];assert type(bridge_key[4]) is int and bridge_key[4]==0 and raw_key!=bridge_key
accounts={jid:read(OUT/('continuation/jobs/'+jid+'/accounting.json')) for jid in ('J01','J02')}
assert accounts['J01']['cumulative']['monitor_entries']==accounts['J01']['cumulative']['commit_successes']==2
assert all(accounts['J02']['cumulative'][k]==0 for k in accounts['J02']['cumulative'])
sp=read(OUT/'R_snapshot_provenance.json');assert len(sp)==3
prefix_counts=[]
for s in sp:
    root=Path(s['root']);cp=read(root/'jobs/J01/checkpoint.json');a=read(root/'jobs/J01/accounting.json')
    assert digest(cp)==s['checkpoint_digest'] and sha((root/'jobs/J01/accounting.json').read_bytes())==s['accounting_sha256']
    assert cp['phase']==s['phase'] and cp['state']['end_of_stream'] and len(cp['pending_event']['before']['placed_items'])==1
    assert a['invocations'][-1]['status']=='ERROR' and s['parent_prefix_unchanged']
    prefix_counts.append({'phase':s['phase'],'cumulative':a['cumulative'],'status':'SAVED_PREFIX_ONLY_NO_RESUME'})
calls=read(OUT/'call_accounting.json');assert calls['E_R2_added']==2 and calls['E_cumulative']==5
save('failure_analysis.json',{'issue':'GP5-NUM-N1-R2-KEY-01','status':'OPEN_PRODUCTION_PUBLICATION_KEY_TYPE_MISMATCH','job_id':'J02','production_reason':j2['summary']['termination_reason'],'saved_error':failure['error'],
 'scope':'Read source and original audit metadata only, no republish/re-evaluation or new candidate',
 'raw_generation_key':raw_key,'raw_key_types':[type(x).__name__ for x in raw_key],'bridge_contract_key_metadata':bridge_key,'bridge_key_types':[type(x).__name__ for x in bridge_key],'mismatch_index':4,'mismatch_role':'yaw: original generator key string 0 versus bridge action_key native int0',
 'explanation':'The bridge compares the entire keys using Python equality, so string0 != int0. The saved pose has yaw int0. This is an integration representation mismatch, not evidence that the physical pose/value differs. No conversion/production change is attempted in this test-only task.',
 'source_locations':['jev_select/geometry_native_shape_bridge.py::action_key','jev_select/geometry_native_shape_bridge.py::publish_native_shape_pool_v3 raw/publication action key check','planner/space_candidates/generator.py saved raw_valid_candidates action_key'],
 'audit_blob':ref,'audit_blob_sha256':sha(raw),'generation_status':audit['generation']['status'],'raw_pool_size':len(pool),'published_bundle_saved':False,'J02_selection_monitor_commit_counts':accounts['J02']['cumulative'],
 'harness_status':'Correctly reported incomplete production job and stopped; does not overwrite production status','retry':False,'production_modified':False})
save('saved_verification.json',{'status':'PASS_BYTES_AND_STOPPED_FACTS_ONLY','source_files':len(actual),'source_identity':digest(actual),'old_manifest_members':sum(g['members'] for g in base['manifests']),
 'old_E_and_preserved_prefix_unchanged':True,'copied_J00_bytes_unchanged':True,'plan_config_data_monitor_bytes_unchanged':True,'E_statuses':[r['status'] for r in run['rows']],
 'snapshot_prefixes':prefix_counts,'snapshots_resumed':0,'new_E_monitor_calls':2,'E_cumulative':5,'R_X_H_ADMIN':'NOT_RUN','production_imports':0})
print('PASS preserved identities/bytes; J01 COMPLETE; J02 raw yaw string vs bridge yaw int mismatch confirmed; no replay')
