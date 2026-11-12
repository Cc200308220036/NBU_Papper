"""Authorized C1 driver only; frozen v13 loop/transport; one registered job, no retries."""
import json,sys,subprocess,time,hashlib
from pathlib import Path
from semantic_pallet_planner.jev_select import packaging_jev_v13 as v, packaging_jev_training_freeze as freeze
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.transport import JevTransport,credential
from semantic_pallet_planner.jev_select.ledger import write,read
OUT=Path(__file__).resolve().parent;BASE=Path('semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01')
def save(name,val):write(OUT/name,val)
f=read(BASE/'formal_freeze.json');plan=read(BASE/'materials/training_plan.json');i=int(sys.argv[1]);assert 1<=i<=6
ex=read(f['jobs'][i-1]['execution_ref']['path']);root=Path(ex['storage_root'])
status_path=OUT/f'job_{i}_receipt.json'
assert not status_path.exists(), 'NO_IMPLICIT_RERUN'
freeze.validate_frozen_plan(f,root=Path.cwd());v.validate_execution(ex)
assert sys.executable=='/home/cyw/anaconda3/bin/python' and not root.exists()
assert [j['max_sends'] for j in f['jobs']]==[19,14,18,19,15,18]
# Prior receipts determine technical continuation, never terminal performance.
for k in range(1,i):
 prior=read(OUT/f'job_{k}_receipt.json');assert prior['technical_valid'] is True,'PRIOR_TECHNICAL_STOP'
if i==4: assert read(OUT/'wave1_continue_gate.json')['technical_continue'] is True
transport=JevTransport(ex['config'],api_key_file=Path('typesafe_api_key.md'))
v.validate_transport_binding(ex,transport)
# Existing parser only. Never print, hash, copy or persist the credential.
secret=credential(ex['config']['api_key_env'],transport.api_key_file);del secret
permit_path=OUT/'permits'/f'baseline_{i}.json'
write(permit_path,dict(version='jev_jm_v13_send_permit_v1',execution_digest=digest(ex),allocation_id=ex['allocation_id'],max_sends=ex['max_sends'],authorized=True))
permit=v.ref(permit_path);v.validate_send_permit(ex,permit)
save(f'job_{i}_admission.json',dict(version='jm_c1_authorized_job_admission_v1',ordinal=i,execution_digest=digest(ex),job_id=ex['job_id'],allocation_id=ex['allocation_id'],max_sends=ex['max_sends'],permit_ref=permit,credential_load='VALID_NO_SECRET_SAVED',memory='NONE_memories_empty',official_protocol='official_protocol_receipt.json',freeze_receipt=f['receipt_digest']))
started=time.monotonic()
def progress(cp):
 print(json.dumps(dict(job=i,phase=cp['phase'],placed=cp['state']['placed_count'],reason=cp['reason']),ensure_ascii=False),flush=True)
try:
 ep=v.run_scheduled(read(plan['schedule_ref']['path']),allocation_id=ex['allocation_id'],transport=transport,permit=permit,on_checkpoint=progress)
 saved=v.validate_saved_execution(root,expected_execution=ex);cp=saved['checkpoint']
 rows=read(root/'ledger/requests.json')['requests'];counts=read(root/'counts.json')
 natural=('ALL_ITEMS_PLACED','STOP_NO_PHYSICAL_CANDIDATE','PREDICTED_STATIC_INSTABILITY','STABILITY_UNASSESSABLE')
 technical=cp['reason'] in natural and not any(s in ('UNKNOWN_SEND','SENDING','FAILED') for s in saved['states'])
 receipt=dict(version='jm_c1_baseline_job_receipt_v1',ordinal=i,job_id=ex['job_id'],task_id=ex['task']['task_id'],status='TERMINATED',technical_valid=technical,reason=cp['reason'],phase=cp['phase'],placed_count=cp['state']['placed_count'],counts=counts,ledger_states=saved['states'],elapsed_s=time.monotonic()-started,requests=[dict(decision_id=r['decision_id'],state=r['state'],send_started=r['send_started'],usage=(r['selection'] or {}).get('usage')) for r in rows],cost='UNKNOWN',runtime_root=str(root),suffix_sends=0)
 save(f'job_{i}_receipt.json',receipt)
 print(json.dumps(receipt,ensure_ascii=False),flush=True)
except Exception as e:
 # Error text may contain sensitive input in general: save only class and safe known code.
 code=getattr(e,'code',None)
 if code is None and type(e).__module__.startswith('semantic_pallet_planner'):code=str(e) if len(str(e))<100 else 'UNKNOWN'
 save(f'job_{i}_receipt.json',dict(version='jm_c1_baseline_job_receipt_v1',ordinal=i,job_id=ex['job_id'],task_id=ex['task']['task_id'],status='TECHNICAL_STOP',technical_valid=False,error_class=type(e).__name__,error_code=code or 'UNKNOWN',runtime_root=str(root),elapsed_s=time.monotonic()-started,cost='UNKNOWN',suffix_sends=0))
 print(json.dumps(dict(job=i,status='TECHNICAL_STOP',error_class=type(e).__name__,error_code=code or 'UNKNOWN')),flush=True)
 sys.exit(2)
