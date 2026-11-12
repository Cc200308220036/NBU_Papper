"""Saved artifact audit only, no business/LP/transport calls or candidate rebuild."""
import json,hashlib
from pathlib import Path
out=Path(__file__).resolve().parent
load=lambda p:json.loads(Path(p).read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
for r in load(out/'delivery_manifest.json')['files']:
 p=Path(r['path']);assert p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],r['path']
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
base=Path('semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01')
assert source_manifest()==load(base/'source_manifest.json')
f=load(base/'formal_freeze.json');assert f['receipt_digest']=='255afe2a80736838105c759a46597aa8853bdba736b7795672a491b86bbbcce1'
b=load(out/'baseline_receipt.json');assert b['planned_jobs']==6 and b['unknown_sends']==0
assert b['actual_requests']==sum(j['requests'] for j in b['jobs'])<=103
for i,j in enumerate(f['jobs'],1):
 root=Path(j['storage_root']);rows=load(root/'ledger/requests.json')['requests'];cp=load(root/'episode.json')['checkpoint']
 assert sum(x['send_started'] for x in rows)==b['jobs'][i-1]['requests']<=j['max_sends']
 assert all(x['state']=='SELECTION_SAVED' for x in rows)
 assert all(e['context']['request_body']['state']['memories']==[] for e in cp['events'] if e.get('context') and e['context'].get('request_body') is not None)
fp=load(out/'fork_plan.json');assert fp['artifact_digest']==digest({k:v for k,v in fp.items() if k!='artifact_digest'})
assert len(fp['points'])<=12 and not fp['suffix_execution_authorized'] and fp['suffix_sends']==0
assert len({p['point_id'] for p in fp['points']})==len(fp['points'])
repeats=load(out/'repeat_plan.json')['selected_point_ids'];assert len(repeats)<=4
for j in fp['jobs']:
 ref=j['execution_ref'];assert sha(ref['path'])==ref['sha256'];ex=load(ref['path'])
 assert ex['allocation_id']==j['allocation_id'] and ex['max_sends']==j['max_sends']
 assert not Path(j['storage_root']).exists()
 assert j['status']=='NOT_RUN_NOT_AUTHORIZED'
 assert ex['kind']=='FORK' and ex['forced_label']==j['forced_label']
budget=load(out/'concrete_budget_receipt.json')
assert sum(j['max_sends'] for j in fp['jobs'])==budget['suffix_send_upper']<=774
assert all(j['point_id'] in repeats for j in fp['jobs'] if j['repeat_slot']=='r1')
print(json.dumps(dict(status='PASS_SAVED_DELIVERY_ONLY',baseline_requests=b['actual_requests'],points=len(fp['points']),suffix_jobs=len(fp['jobs']),suffix_sends=0,source_count=505),ensure_ascii=False))
