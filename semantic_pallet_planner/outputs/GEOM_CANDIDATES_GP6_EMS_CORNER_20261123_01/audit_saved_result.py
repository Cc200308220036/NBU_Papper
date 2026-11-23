"""Saved facts only: no candidate generation, model, solver, commit or replay."""
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys
ROOT=Path(__file__).parent
REPO=ROOT.parents[2]
sys.path.insert(0,str(REPO/'semantic_pallet_planner/src'))
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.ledger import write

def read(p):return json.loads(Path(p).read_text())
def main():
 spec=read(ROOT/'single_experiment_plan_FROZEN.json');plan=read(ROOT/'runtime_plan_FROZEN.json')
 control=Path(spec['baseline']);run=ROOT/'run'
 cp=read(run/'jobs/G01/checkpoint.json');old_cp=read(control/'record.json')['checkpoint']
 events=[e for e in cp['events'] if e.get('context',{}).get('request_body')]
 old_events=[e for e in old_cp['events'] if e.get('context',{}).get('request_body')]
 ledger=read(ROOT/'ledgers/requests/requests.json');calls=read(ROOT/'ledgers/calls/calls.json')
 assert len(ledger['requests'])==len(events)==4 and all(r['job_id']=='G01' for r in ledger['requests'])
 assert [p.name for p in (run/'jobs').iterdir()]==['G01']
 event_map={e['decision_id']:e for e in events}
 wires=sorted((run/'sent_requests').glob('[0-9][0-9].json'))
 assert len(wires)==len(ledger['requests'])<=19
 instruction=(ROOT/'final_selection_instructions.txt').read_text()
 for p in wires:
  bind=read(p.with_suffix('.binding.json'));wire=read(p);base=event_map[bind['decision_id']]['context']['request_body']
  assert hashlib.sha256(p.read_bytes()).hexdigest()==bind['actual_wire_body_sha256']
  assert bind['experiment_plan_digest']==digest(spec) and bind['runtime_plan_digest']==digest(plan)
  assert digest(base)==bind['base_context_body_digest']
  assert wire['questions']['next_action']['instructions']==base['questions']['next_action']['instructions']+'\n\n'+spec['placement_instruction']==instruction
  assert p.with_suffix('.instructions.txt').read_text()==instruction
  original=copy.deepcopy(wire);original['questions']['next_action']['instructions']=base['questions']['next_action']['instructions']
  assert original==base
 m=read(run/'jobs/G01/metrics.json');old=read(control/'metrics.json')
 cfg=read(run/'jobs/G01/config.json');old_cfg=read(control/'config.json')
 differences=[k for k in cfg if cfg[k]!=old_cfg.get(k)]
 allowed={'admission_digest','kernel_receipt_digest','plan_digest','runtime_identity','shared_max_sends'}
 assert set(differences)<=allowed,differences
 assert {k:v for k,v in cfg['runtime_identity'].items() if k!='strategy_identity'}=={k:v for k,v in old_cfg['runtime_identity'].items() if k!='strategy_identity'}
 assert cfg['stability_monitor']==old_cfg['stability_monitor'] and cfg['packaging_top_load_limit_enabled'] is False
 first=events[0];pool=first['bundle']['physical_candidates'];old_pool=old_events[0]['bundle']['physical_candidates']
 def published_content(c): return {k:v for k,v in c.items() if k not in ('candidate_id','candidate_fingerprint')}
 assert [published_content(c) for c in pool]==[published_content(c) for c in old_pool],'FIRST_POOL_CONTENT_DRIFT'
 sel=first['selection'];box=next(c for c in pool if c['candidate_id']==sel['selected_candidate_id'])
 container=first['before']['container'];min_x=-container['length_mm']/2;min_y=-container['width_mm']/2
 def corner(c):
  pose=c['pose'];l,w,_=c['oriented_size_mm']
  return abs(pose['x_mm']-l/2-min_x)<1e-6 and abs(pose['y_mm']-w/2-min_y)<1e-6 and abs(pose['z_base_mm'])<1e-6
 assert any(corner(c) for c in pool) and any(c['pose']['x_mm']==c['pose']['y_mm']==0 for c in pool)
 monitors=[e['monitor']['status'] for e in cp['events'] if e.get('monitor')]
 assert len(monitors)==m['counts']['assessment_entries']==4 and all(x=='STABLE' for x in monitors)
 placed=[e for e in cp['events'] if e.get('event')=='PLACE']
 assert len(placed)==m['placed_items']==len(cp['state']['placed_items'])
 assert all(e['action']==e['proposed_action'] for e in placed)
 for e in placed:
  c=next(c for c in e['bundle']['physical_candidates'] if c['candidate_id']==e['selection']['selected_candidate_id'])
  obj=next(x for x in e['after']['placed_items'] if x['item_id']==c['pick_item_id'])
  assert obj['pose']==c['pose'] and obj['oriented_size_mm']==c['oriented_size_mm']
 assert not any(x['state']=='STARTED' for x in calls['calls'])
 assert all(r['state']=='SELECTION_SAVED' and r['transport']['http_status']==200 for r in ledger['requests'])
 assert m['cost']['failed_requests']==m['cost']['unknown_sends']==0
 assert read(run/'driver_receipt.json')['dispatched_jobs']==['G01']
 assert (ROOT/'exit_code.txt').read_text().strip()=='0'
 # Check only the existing authorized key in memory; never store or display it.
 from semantic_pallet_planner.jev_select.transport import credential
 key=credential('TYPESAFE_API_KEY',Path('typesafe_api_key.md')).encode()
 assert all(key not in p.read_bytes() for p in ROOT.rglob('*') if p.is_file())
 del key
 result={'version':'gp6_corner_saved_audit_v1','status':'PASS_SAVED_FACTS_ONLY','head':spec['head'],'runtime_plan_digest':digest(plan),'experiment_plan_digest':digest(spec),
  'first_box':{'Cxx':sel['selected_display_id'],'item_id':box['pick_item_id'],'pose':box['pose'],'oriented_size_mm':box['oriented_size_mm'],'pallet_min_x_mm':min_x,'pallet_min_y_mm':min_y,'box_min_x_mm':box['pose']['x_mm']-box['oriented_size_mm'][0]/2,'box_min_y_mm':box['pose']['y_mm']-box['oriented_size_mm'][1]/2,'touches_requested_corner':corner(box),'monitor':first['monitor']['status']},
  'first_pool':{'count':len(pool),'bytewise_equal_to_control':pool==old_pool,'all_content_except_identity_equal':True,'identity_difference_fields':['candidate_id','candidate_fingerprint'],'requested_corner_candidates':sum(corner(c) for c in pool),'center_candidates':sum(c['pose']['x_mm']==c['pose']['y_mm']==0 for c in pool)},
  'comparison':{'baseline_placed':old['placed_items'],'placed':m['placed_items'],'placed_delta':m['placed_items']-old['placed_items'],'baseline_fixed_container_utilization':old['fixed_container_utilization'],'fixed_container_utilization':m['fixed_container_utilization'],'utilization_delta_percentage_points':100*(m['fixed_container_utilization']-old['fixed_container_utilization']),'same_selected_labels':[e['selection']['selected_display_id'] for e in events]==[e['selection']['selected_display_id'] for e in old_events],'same_exact_placement_actions':[e['action'] for e in placed]==[e['action'] for e in old_cp['events'] if e.get('event')=='PLACE']},
  'termination_reason':m['termination_reason'],'termination_class':m['termination_class'],'monitor_statuses':dict(Counter(monitors)),'counts':m['counts'],'send_reservations':sum(r['send_started'] for r in ledger['requests']),'network_attempts':sum(r['transport']['network_attempted'] is True for r in ledger['requests']),'request_failures':m['cost']['failed_requests'],'unknown_sends':m['cost']['unknown_sends'],'exit_code':0,'config_difference_keys':differences,'actual_wire_instruction_saved':True,'only_instructions_changed':True,'key_not_found_in_artifacts':True,'new_independent_review':False,'no_replay':True}
 write(ROOT/'saved_result_audit.json',result)
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
