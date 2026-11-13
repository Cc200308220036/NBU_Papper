"""One-shot sequential C2 orchestration. Frozen v13 owns execution and recovery."""
import sys,time,json
from pathlib import Path
from semantic_pallet_planner.jev_select import packaging_jev_v13 as v
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.ledger import read,write,exclusive
from semantic_pallet_planner.jev_select.transport import JevTransport,credential
OUT=Path(__file__).resolve().parent
assert sys.executable=='/home/cyw/anaconda3/bin/python'
def main():
 with exclusive(OUT):
  assert not (OUT/'dispatch_started.json').exists(),'NO_IMPLICIT_BATCH_RESTART'
  order=read(OUT/'execution_order.json')['jobs'];auth=read(OUT/'authorization_receipt.json')
  assert len(order)==18 and sum(j['max_sends'] for j in order)==242
  assert {j['allocation_id'] for j in order}=={j['allocation_id'] for j in auth['execution_bindings']}
  for j in order:
   ex=v.load_ref(j['execution_ref']);v.validate_execution(ex)
   assert digest(ex)==j['execution_digest'] and not Path(ex['storage_root']).exists()
   v.validate_send_permit(ex,v.ref(OUT/'permits'/(ex['job_id']+'.json')))
  # Existing credential parser; never print, fingerprint or persist its result.
  secret=credential('TYPESAFE_API_KEY',Path('typesafe_api_key.md'));del secret
  write(OUT/'dispatch_started.json',dict(version='jm_c2_dispatch_v1',authorization_ref=v.ref(OUT/'authorization_receipt.json'),jobs=18,max_sends=242))
  stopped=False;receipts=[]
  for ordinal,j in enumerate(order,1):
   path=OUT/'job_receipts'/(j['job_id']+'.json')
   assert not path.exists()
   if stopped:
    rec=dict(version='jm_c2_job_receipt_v1',ordinal=ordinal,job_id=j['job_id'],status='NOT_RUN',technical_valid=False,reason='PRIOR_TECHNICAL_STOP',execution_digest=j['execution_digest'],cost='UNKNOWN',storage_root=j['storage_root'])
   else:
    ex=v.load_ref(j['execution_ref']);root=Path(ex['storage_root']);started=time.monotonic()
    def progress(cp):
     print(json.dumps(dict(ordinal=ordinal,job=ex['job_id'],phase=cp['phase'],placed=cp['state']['placed_count'],reason=cp['reason'])),flush=True)
    write(OUT/'dispatch_intents'/(ex['job_id']+'.json'),dict(version='jm_c2_dispatch_intent_v1',execution_digest=digest(ex),allocation_id=ex['allocation_id'],max_sends=ex['max_sends'],ordinal=ordinal))
    try:
     transport=JevTransport(ex['config'],api_key_file=Path('typesafe_api_key.md'));v.validate_transport_binding(ex,transport)
     v.run_execution(ex,root=root,transport=transport,permit=v.ref(OUT/'permits'/(ex['job_id']+'.json')),on_checkpoint=progress)
     saved=v.validate_saved_execution(root,expected_execution=ex);cp=saved['checkpoint'];counts=read(root/'counts.json')
     technical=cp['phase']=='TERMINATED' and cp['reason'] in ('ALL_ITEMS_PLACED','STOP_NO_PHYSICAL_CANDIDATE','PREDICTED_STATIC_INSTABILITY','STABILITY_UNASSESSABLE') and not any(s in ('UNKNOWN_SEND','SENDING','FAILED') for s in saved['states'])
     rec=dict(version='jm_c2_job_receipt_v1',ordinal=ordinal,job_id=ex['job_id'],status='TERMINATED' if technical else 'TECHNICAL_STOP',technical_valid=technical,reason=cp['reason'],phase=cp['phase'],placed_count=cp['state']['placed_count'],counts=counts,ledger_states=saved['states'],execution_digest=digest(ex),allocation_id=ex['allocation_id'],storage_root=str(root),elapsed_s=time.monotonic()-started,cost='UNKNOWN',saved_validation='PASS_NO_REPLAY')
     stopped=not technical
    except BaseException as e:
     # Safe class/code only. Preserve original run bytes; never retry.
     rec=dict(version='jm_c2_job_receipt_v1',ordinal=ordinal,job_id=ex['job_id'],status='TECHNICAL_STOP',technical_valid=False,error_class=type(e).__name__,error_code=getattr(e,'code','UNKNOWN'),execution_digest=digest(ex),storage_root=str(root),elapsed_s=time.monotonic()-started,cost='UNKNOWN')
     stopped=True
   write(path,rec);receipts.append(rec)
   print(json.dumps(dict(ordinal=ordinal,status=rec['status'],reason=rec.get('reason'),error_code=rec.get('error_code'))),flush=True)
  write(OUT/'batch_receipt.json',dict(version='jm_c2_batch_v1',status='TECHNICAL_STOP' if stopped else 'COMPLETE',jobs=receipts,not_run=sum(r['status']=='NOT_RUN' for r in receipts),implicit_retries=0))
  return 2 if stopped else 0
if __name__=='__main__':sys.exit(main())
