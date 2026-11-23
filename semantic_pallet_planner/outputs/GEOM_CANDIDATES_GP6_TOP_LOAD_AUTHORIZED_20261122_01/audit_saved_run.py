"""Read saved facts only: no replay, transport, monitor, commit or ledger mutation."""
from pathlib import Path
import json
import hashlib
import sys
REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO/'semantic_pallet_planner/src'))
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
OUT=Path(__file__).parent
BASE=REPO/'semantic_pallet_planner/outputs'
RUN=BASE/'GEOM_CANDIDATES_GP6_TOP_LOAD_DISABLED_RUN_20261122_01'
LED=BASE/'GEOM_CANDIDATES_GP6_TOP_LOAD_DISABLED_LEDGERS_20261122_01'
def read(p):return json.loads(p.read_text())
def keys(v):
 if isinstance(v,dict):return set(v)|set().union(*(keys(a) for a in v.values()))
 if isinstance(v,list):return set().union(*(keys(a) for a in v))
 return set()
def main():
 plan=read(OUT/'gp6_top_load_plan_FROZEN.json');pd=digest(plan)
 assert pd=='f5bb85910e1b44017b19c1ada506b4d48da87f2f74be4e87ce7f6addf42d6f73'
 assert digest(source_manifest())==plan['source_identity']
 driver=read(RUN/'driver_receipt.json');run=read(RUN/'run.json');req=read(LED/'requests/requests.json');calls=read(LED/'calls/calls.json')
 assert driver['plan_digest']==run['plan_digest']==req['plan_digest']==calls['plan_digest']==pd
 assert len(run['rows'])==2 and [r['job_id'] for r in run['rows']]==['G00','G01']
 sent=[r for r in req['requests'] if r['send_started']]
 assert len(sent)<=38 and all(sum(r['job_id']==j for r in sent)<=19 for j in ('G00','G01'))
 rows=[];payload_count=0
 forbidden={'max_top_load_kg','effective_top_permission_kg','remaining_top_load_kg','capacity_utilization','utilization_status','top_load_limit_kg_synthetic'}
 for row in run['rows']:
  jid=row['job_id'];p=RUN/'jobs'/jid/'checkpoint.json';m=row['metrics']
  stats={'job_id':jid,'status':row['status'],'send_reservations':sum(r['job_id']==jid for r in sent),'metrics':m}
  if p.exists():
   cp=read(p);cfg=read(p.parent/'config.json')
   assert cfg['packaging_top_load_limit_enabled'] is False and cfg['stability_monitor']['enabled'] is True
   assert cfg['monitor_evidence']=='REAL_KERNEL' and cfg['transport_evidence']=='REAL_JEV'
   assert cfg['model']=='jev-1.14.0' and cfg['max_retries']==0
   events=cp['events'];placed=[e for e in events if e['event']=='PLACE']
   for ev in events:
    ctx=ev.get('context')
    if ctx:
     body=ctx['request_body']
     if body:
      assert body['state']['packaging_top_load_limit_enabled'] is False
      assert not (keys(body)&forbidden)
      assert 'mass_kg' in keys(body) and 'support_ratio' in keys(body)
      payload_count+=1
    if ev['event']=='PLACE':
     assert ev['monitor']['status']=='STABLE' and ev['action']==ev['proposed_action']
     sel=ev['selection'];mapped=ctx['display_mapping'][sel['selected_display_id']]
     c=next(c for c in ev['bundle']['physical_candidates'] if c['candidate_id']==mapped['candidate_id'])
     assert digest(c)==mapped['candidate_digest'] and c['candidate_id']==sel['selected_candidate_id']
     obj=next(o for o in ev['after']['placed_items'] if o['item_id']==c['pick_item_id'])
     assert obj['pose']==c['pose'] and obj['oriented_size_mm']==c['oriented_size_mm']
   if m:
    assert m['placed_items']==len(placed)==len(cp['state']['placed_items'])
    assert m['packaging_top_load_compliance']=='NOT_APPLICABLE'
   stats.update(placed_events=len(placed),termination_reason=cp['reason'],monitor_statuses=[e['monitor']['status'] for e in events if e.get('monitor')])
  rows.append(stats)
 assert all(c['state']!='STARTED' for c in calls['calls'])
 # Secret is compared in memory only; no token or token fingerprint is recorded.
 from semantic_pallet_planner.jev_select.transport import credential
 token=credential('TYPESAFE_API_KEY',REPO/'typesafe_api_key.md').encode()
 for root in (OUT,RUN,LED):
  for p in root.rglob('*'):
   if p.is_file():assert token not in p.read_bytes(), 'SECRET_PRESENT_IN_ARTIFACT_'+str(p)
 summary={'status':'SAVED_FACTS_AUDITED','plan_digest':pd,'driver_status':driver['status'],'planned_jobs':2,'rows':rows,
   'send_reservations':len(sent),'network_attempted':sum(r['transport'] is not None and r['transport']['network_attempted'] is True for r in sent),
   'request_states':[{'job_id':r['job_id'],'state':r['state'],'transport_status':(r.get('transport') or {}).get('status')} for r in req['requests']],
   'call_counts':calls['counts'],'disabled_payloads_checked':payload_count,'secret_scan':'ABSENT_IN_NEW_ARTIFACTS',
   'service_cost_usd':'UNKNOWN','no_replay':True,'model':'jev-1.14.0'}
 (OUT/'saved_run_audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:summary[k] for k in ('status','driver_status','planned_jobs','send_reservations','network_attempted','call_counts')},ensure_ascii=False))
if __name__=='__main__':main()
