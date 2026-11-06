"""Only after execution exits: validate saved facts and collect audit metadata."""
import datetime
import json
import subprocess
import sys
from pathlib import Path
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.packaging_source_audit import sha
from semantic_pallet_planner.jev_select import packaging_evaluation_orders as common
B=Path(__file__).parent
assert (B/'execution_exit.json').exists(),'execution is still active'
run=Path('semantic_pallet_planner/outputs/JEV_JN4_REMAIN24_20261106_01/run')
command=[sys.executable,'-m','semantic_pallet_planner.jev_select.packaging_exact_orders','validate-run','--output',str(run)]
if (B/'saved_validation.json').exists():
    validation=read(B/'saved_validation.json');returncode=validation['returncode']
else:
    with (B/'validate_run.log').open('w') as out:
        result=subprocess.run(command,stdout=out,stderr=subprocess.STDOUT,check=False)
    returncode=result.returncode
    write(B/'saved_validation.json',{'command':'PYTHONPATH=semantic_pallet_planner/src python3 -m semantic_pallet_planner.jev_select.packaging_exact_orders validate-run --output '+str(run),'returncode':returncode,'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'dispatch':'NONE_SAVED_FACTS_ONLY'})
account=Path('semantic_pallet_planner/outputs/JEV_JN4_EXACT_SUPPLEMENT_ACCOUNTING_V1')
write(B/'owner_records.json',{name:{'record':read(account/name),'sha256':sha(account/name)} for name in ('owner.json','remaining24_owner.json')})
p=read(run.parent/'plan/plan.json');summary=read(run/'summary.json');requests=read(run/'request_ledger/requests.json')['requests'];stops=[]
for j in p['jobs']:
 root=run/'jobs'/j['job_id'];s=read(root/'status.json')
 if s['category'] in common.STOP:
  cp=read(root/'checkpoint.json') if (root/'checkpoint.json').exists() else None
  event=(cp['events'][-1] if cp and cp['events'] else None)
  stops.append({'run':str(run),'job_id':j['job_id'],'method_id':j['method_id'],'status':s,
   'checkpoint_phase':cp['phase'] if cp else 'UNKNOWN','termination_reason':cp['reason'] if cp else 'UNKNOWN',
   'placed_count':cp['state']['placed_count'] if cp else 'UNKNOWN','last_event':event['event'] if event else 'UNKNOWN',
   'last_event_before_after_equal':event['before']==event['after'] if event else 'UNKNOWN',
   'requests':[{'attempt_id':r['attempt_id'],'decision_id':r['decision_id'],'state':r['state'],'request_digest':digest(r),
       'transport':r['transport']} for r in requests if r['job_id']==j['job_id'] and r['state'] in ('UNKNOWN_SEND','FAILED')]})
write(B/'stop_diagnosis.json',{'run_status':summary['status'],'new_technical_stops':stops,
 'technical_failure':read(run/'technical_failure.json') if (run/'technical_failure.json').exists() else None,
 'resumes':0,'retries':0,'extra_probes':0,'old_unknown_send_preserved':True})
print('saved validation returncode',returncode,'technical stop jobs',len(stops))
