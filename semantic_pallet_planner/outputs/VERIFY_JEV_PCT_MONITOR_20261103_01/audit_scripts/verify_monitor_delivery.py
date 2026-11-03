from pathlib import Path
import json,shutil
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.experiment import file_manifest
from semantic_pallet_planner.jev_select.stability.runtime import validate
from semantic_pallet_planner.jev_select.stability import balance_adapter,balance_network
from semantic_pallet_planner.jev_select.candidates import CandidateProvider
from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
r=Path('/home/cyw/NBU_Papper/semantic_pallet_planner/outputs/VERIFY_JEV_PCT_MONITOR_20261103_01')
def forbidden(*a,**kw):raise AssertionError('validation called solver/selector/candidate generation')
balance_adapter.assess_candidate=forbidden;balance_network.linprog=forbidden
CandidateProvider.build=forbidden;LocalPackagingDouble.select=forbidden
checks={k:validate(r/k) for k in ('smoke_off','smoke_on')}
write(r/'record_validation.json',checks)
pairs=[]
for jid in ('P00','P01'):
 off=read(r/'smoke_off/jobs'/jid/'episode.json');on=read(r/'smoke_on/jobs'/jid/'episode.json')
 assert off['final_state']==on['final_state'] and len(off['events'])==len(on['events'])==8
 count=0
 for a,b in zip(off['events'],on['events']):
  assert a['before']==b['before'] and a['after']==b['after'] and a['event']==b['event']
  if a.get('context'):
   for key in ('request_body','criteria','model_state','display_mapping'):assert a['context'][key]==b['context'][key]
   for key in ('physical_candidates','selectable_candidates','physical_digest','selectable_digest'):assert a['bundle'][key]==b['bundle'][key]
   assert a['action']==b['action'];count+=1
 pairs.append({'job':jid,'decisions':count,'same_candidates_order_ids_and_body':True,'same_actions_and_committed_state':True})
write(r/'paired_comparison.json',pairs)
rows=[]
for case in ('scope','config','result','snapshot','stage'):
 root=r/'negative_records'/case;shutil.copytree(r/'smoke_on',root)
 if case=='scope':
  p=root/'scope.json';v=read(p);v['event_limit']=9
 elif case=='config':
  p=root/'jobs/P00/config.snapshot.json';v=read(p);v['stability_monitor']['enabled']=False
 elif case=='result':
  p=root/'jobs/P00/checkpoint.json';v=read(p);next(e for e in v['events'] if e.get('monitor'))['monitor']['result']['status']='UNSTABLE'
 elif case=='snapshot':
  p=root/'code_snapshot/jev_select/stability/monitor.py';p.write_text(p.read_text()+'\n# explicit tamper\n');v=None
 else:
  p=next((root/'jobs/P00/stages').glob('*/MONITORED.json'));v=read(p);v['pending_event']['proposed_action']['candidate_id']='TAMPERED'
 if v is not None:write(p,v)
 write(root/'delivery_manifest.json',file_manifest(root))
 try:validate(root)
 except ValueError as exc:rows.append({'case':case,'rejected':True,'code':getattr(exc,'code',type(exc).__name__)})
 else:raise AssertionError('accepted '+case)
write(r/'negative_record_checks.json',rows)
print(json.dumps({'record_checks':'PASS','paired':pairs,'negative':rows},indent=2))
