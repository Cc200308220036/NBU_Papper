"""Independent R2 saved metadata checks. No production import/replay/physics."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

OUT=Path(__file__).parent
DEV=OUT.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R2_20261118_01'
OLD=OUT.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01'
SRC=Path('semantic_pallet_planner/src/semantic_pallet_planner')
HEAD='1db7a7f78b7389105046bcaf6a6ddbfdf6ccb0ae'
def read(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def enc(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return sha(enc(v))
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def hashes(root):return {str(p.relative_to(root)):sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}

manifest=read(DEV/'delivery_manifest.json')
for row in manifest['files']:
    raw=(subprocess.check_output(['git','show',HEAD+':'+row['path']])
         if Path(row['path']).name=='README.md' else Path(row['path']).read_bytes())
    assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'],row['path']
source=read(DEV/'source_manifest.json');base=read(DEV/'baseline_receipt.json')
actual={str(p.relative_to(SRC)):sha(p.read_bytes()) for p in SRC.rglob('*')
        if p.is_file() and p.suffix in ('.py','.json')
        and not {'tests','__pycache__'}.intersection(p.relative_to(SRC).parts)}
assert actual==source['files']==read(OLD/'source_manifest.json')['files']
assert digest(actual)==source['source_identity']==base['source_identity']
history=0
for group in base['manifests']:
    p=Path(group['manifest']);assert sha(p.read_bytes())==group['sha256']
    for row in read(p)['files']:
        raw=(subprocess.check_output(['git','show',group['navigation_revision']+':'+row['path']])
             if Path(row['path']).name=='README.md' else Path(row['path']).read_bytes())
        assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'];history+=1
provenance=read(DEV/'prefix_provenance.json')
assert hashes(OLD/'E')==hashes(DEV/'prefix_snapshot')==provenance['files']
assert hashes(DEV/'continuation/jobs/J00')==hashes(OLD/'E/jobs/J00')
for name in ('plan.json','admission.json','configs.json','monitor_snapshot.json','validation_scope.json','source_manifest.json','GP5_SYNTH_K02_INT.raw.json','GP5_SYNTH_K02.raw.json'):
    assert (DEV/name).read_bytes()==(OLD/name).read_bytes()
run=read(DEV/'continuation/run.json')
assert [r['status'] for r in run['rows']]==['COMPLETE','COMPLETE','TECHNICAL_FAILURE']+['NOT_RUN']*5
one=read(DEV/'continuation/jobs/J01/episode.json');two=read(DEV/'continuation/jobs/J02/episode.json')
assert one['summary']['completed'] and one['summary']['placed_items']==2
assert two['summary']['termination_reason']=='NUM_BRIDGE_IDENTITY_MISMATCH' and two['summary']['placed_items']==0
for episode in (one,two):
    cp=episode['checkpoint'];assert cp['record_digest']==digest({k:v for k,v in cp.items() if k!='record_digest'})
for event in one['events']:
    if event['event']!='PLACE':continue
    candidate=next(c for c in event['bundle']['physical_candidates'] if c['candidate_id']==event['selection']['selected_candidate_id'])
    item=next(p['item'] for p in event['before']['pending_items'] if p['item']['item_id']==candidate['pick_item_id'])
    axes=('length','width','height') if candidate['pose']['yaw_deg']==0 else ('width','length','height')
    target=[item['dimensions_mm'][k] for k in axes]
    assert candidate['oriented_size_mm']==target and all(type(a) is type(b) for a,b in zip(target,candidate['oriented_size_mm']))
    monitor=event['monitor'];assert monitor['result']['diagnostics']['TEST_DOUBLE'] is True
    assert monitor['result']['candidate_id']==candidate['pick_item_id'] and monitor['status']=='STABLE'
    assert monitor['result_digest']==digest(monitor['result']) and monitor['credential_digest']==digest({k:v for k,v in monitor.items() if k!='credential_digest'})
    assert event['action']==event['proposed_action']
failed=next(e for e in two['events'] if e.get('error'));ref=failed['geometry_ref']
raw=(DEV/'continuation/jobs/J02/blobs'/ref['sha256']).read_bytes();assert sha(raw)==ref['sha256']
audit=json.loads(raw)['audit'];pool=json.loads(bytes.fromhex(audit['raw_pool_bytes_hex']))
assert audit['generation']['status']=='OK' and len(pool)==2 and failed['bundle'] is None
candidate=pool[0]
row=next(r for item in audit['generation']['audit']['items'] for r in item['raw_valid_candidates'] if r['candidate']['candidate_fingerprint']==candidate['candidate_fingerprint'])
key=row['action_key'];assert key==['synth_1','100','80','60','0','0','0','0']
assert all(type(x) is str for x in key) and type(candidate['pose']['yaw_deg']) is int
assert key[4]!=candidate['pose']['yaw_deg'] and key[4]=='0' and candidate['pose']['yaw_deg']==0
accounts={j:read(DEV/('continuation/jobs/'+j+'/accounting.json')) for j in ('J01','J02')}
assert accounts['J01']['cumulative']['monitor_entries']==accounts['J01']['cumulative']['commit_successes']==2
assert all(x==0 for x in accounts['J02']['cumulative'].values())
assert accounts['J02']['invocations'][-1]['status']=='RETURNED'
snapshots=[]
for row in read(DEV/'R_snapshot_provenance.json'):
    root=DEV/'R_saved'/('J01_'+row['phase']);cp=read(root/'jobs/J01/checkpoint.json');a=read(root/'jobs/J01/accounting.json')
    assert digest(cp)==row['checkpoint_digest'] and sha((root/'jobs/J01/accounting.json').read_bytes())==row['accounting_sha256']
    assert cp['phase']==row['phase'] and cp['state']['end_of_stream'] and len(cp['pending_event']['before']['placed_items'])==1
    assert a['invocations'][-1]['status']=='ERROR' and row['parent_prefix_unchanged']
    assert row['new_generation_bridge_selection_monitor_commit']==0
    expected={'SELECTED':(1,1),'MONITORED':(2,1),'COMMITTED':(2,2)}[row['phase']]
    assert (a['cumulative']['monitor_entries'],a['cumulative']['commit_successes'])==expected
    snapshots.append({'phase':row['phase'],'monitor_commit_at_save':expected,'resumed':False})
assert len(snapshots)==3
calls=read(DEV/'call_accounting.json');assert calls['E_previously_consumed']==3 and calls['E_R2_added']==2 and calls['E_cumulative']==5
assert calls['R_monitor_added']==calls['R_commit_added']==calls['X_H_monitor_added']==0
gen=(SRC/'planner/space_candidates/generator.py').read_text()
bridge=(SRC/'jev_select/geometry_native_shape_bridge.py').read_text()
assert 'str(yaw)' in gen and "candidate['pose']['yaw_deg']" in bridge
assert "require(key==action_key(q),'raw/publication action key disagreement')" in bridge
assert "p['raw_action_key']==action_key(q),'saved raw key'" in bridge
save('key_contract_review.json',{'issue':'GP5-NUM-N1-R2-KEY-01','status':'CONFIRMED_STATIC_AND_SAVED_METADATA',
    'raw_key':key,'raw_types':[type(x).__name__ for x in key],'candidate_yaw':candidate['pose']['yaw_deg'],
    'candidate_yaw_type':'int','mismatch_slot':4,'raw_yaw_equals_native_yaw':False,
    'raw_generation_status':'OK','raw_pool_size':2,'published_bundle':None,'J02_counts':accounts['J02']['cumulative'],
    'affected_checks':['FRESH raw/publication key equality at192','SAVED raw key equality at239'],
    'limit':'Comparison of saved metadata and source only; no production action_key/publish/generator call or candidate reconstruction'})
save('saved_evidence_verification.json',{'status':'PASS_SAVED_FACTS_ONLY','manifest_members':len(manifest['files']),
    'historical_members':history,'production_files':len(actual),'source_identity':source['source_identity'],'source_drift':False,
    'original_E_prefix_and_copied_J00_bytes_unchanged':True,'plan_config_data_monitor_bytes_unchanged':True,
    'E_current_statuses':[r['status'] for r in run['rows']],'E2_J01':'COMPLETE_VALIDATED_SAVED_FACTS',
    'J02':'TECHNICAL_FAILURE_BEFORE_SELECTION_MONITOR_COMMIT','E_monitor_consumed':5,'E_old_limit':17,
    'R_saved_prefixes':snapshots,'R_actual_resumes':0,'X_H_ADMIN':'NOT_RUN',
    'HARNESS-01':'supported by local pure2 tests + saved J00/J01','production_imports':0,
    'candidate_order_shadow_fork_recovery_kernel_solver_model_execution':0})
print('PASS identities/preserved prefixes/J01 success/J02 key-type failure/3 saved-only snapshots; no production imports or replay')
