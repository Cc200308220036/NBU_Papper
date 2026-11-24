"""Read saved mandatory-text run only; never send, reselect, replay or solve."""
import copy
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).parent

def read(p):return json.loads(Path(p).read_text())
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    spec=read(ROOT/'single_experiment_plan_FROZEN.json');plan=read(ROOT/'runtime_plan_FROZEN.json')
    assert spec['driver_sha256']==sha(ROOT/'single_ems_driver.py')
    assert spec['audit_policy']['file']['sha256']==sha(ROOT/'audit_rules_v1.py')
    assert digest(plan)==spec['runtime_plan_digest']
    cp=read(ROOT/'run/jobs/G01/checkpoint.json');m=read(ROOT/'run/jobs/G01/metrics.json')
    ledger=read(ROOT/'ledgers/requests/requests.json');calls=read(ROOT/'ledgers/calls/calls.json')
    assert ledger['plan_digest']==calls['plan_digest']==digest(plan)
    assert list((ROOT/'run/jobs').iterdir())==[ROOT/'run/jobs/G01']
    assert all(r['job_id']=='G01' for r in ledger['requests'])
    assert len(ledger['requests'])<=19
    assert not any(r['state']=='STARTED' for r in calls['calls'])
    events={e['decision_id']:e for e in cp['events'] if e.get('context',{}).get('request_body')}
    wires=sorted((ROOT/'run/sent_requests').glob('[0-9][0-9].json'))
    assert len(wires)==len(ledger['requests'])
    full=(ROOT/'final_selection_instructions.txt').read_text()
    for p in wires:
        wire=read(p);binding=read(p.with_suffix('.binding.json'));body=events[binding['decision_id']]['context']['request_body']
        assert binding['actual_wire_body_sha256']==sha(p)
        assert binding['base_context_body_digest']==digest(body)
        assert binding['experiment_plan_digest']==digest(spec) and binding['runtime_plan_digest']==digest(plan)
        assert wire['questions']['next_action']['instructions']==body['questions']['next_action']['instructions']+'\n\n'+spec['placement_instruction']==full
        assert p.with_suffix('.instructions.txt').read_text()==full
        stripped=copy.deepcopy(wire);stripped['questions']['next_action']['instructions']=body['questions']['next_action']['instructions']
        assert stripped==body
    cfg=read(ROOT/'run/jobs/G01/config.json');control=Path(spec['baseline']);basecfg=read(control/'config.json')
    assert cfg['packaging_top_load_limit_enabled'] is False and cfg['max_retries']==0
    diff=[k for k in cfg if cfg[k]!=basecfg.get(k)]
    assert set(diff)<={'admission_digest','kernel_receipt_digest','plan_digest','runtime_identity','shared_max_sends'},diff
    assert {k:v for k,v in cfg['runtime_identity'].items() if k!='strategy_identity'}=={k:v for k,v in basecfg['runtime_identity'].items() if k!='strategy_identity'}
    audit_spec=importlib.util.spec_from_file_location('saved_rule_audit',ROOT/'audit_rules_v1.py');audit=importlib.util.module_from_spec(audit_spec);audit_spec.loader.exec_module(audit)
    rules=audit.audit_checkpoint(cp,m,ledger)
    rules['instruction_delivery_verified']=True
    rules['instruction_delivery_note']='Every saved wire body verified against the frozen mandatory text, binding and unchanged base state/criteria; network attempts counted separately from wire files.'
    (ROOT/'offline_rule_audit.json').write_text(json.dumps(rules,ensure_ascii=False,indent=2)+'\n')
    placed=[e for e in cp['events'] if e.get('event')=='PLACE']
    assert len(placed)==m['placed_items']==len(cp['state']['placed_items'])
    for e in placed:
        assert e['monitor']['status']=='STABLE' and e['action']==e['proposed_action']
        c=next(c for c in e['bundle']['physical_candidates'] if c['candidate_id']==e['selection']['selected_candidate_id'])
        obj=next(o for o in e['after']['placed_items'] if o['item_id']==c['pick_item_id'])
        assert obj['pose']==c['pose'] and obj['oriented_size_mm']==c['oriented_size_mm']
    first=next((s for s in rules['steps'] if 'original_selected_Cxx' in s),None)
    first_box=None
    if placed:
        e=placed[0];c=next(c for c in e['bundle']['physical_candidates'] if c['candidate_id']==e['selection']['selected_candidate_id'])
        scores=audit.candidate_scores(c,e['before'])
        first_box={'Cxx':e['selection']['selected_display_id'],'item_id':c['pick_item_id'],'pose':c['pose'],'oriented_size_mm':c['oriented_size_mm'],'touches_requested_corner':scores['touches_both_corner_edges'],'clearance_x_mm':scores['clearance_x_mm'],'clearance_y_mm':scores['clearance_y_mm']}
    controlcp=read(control/'record.json')['checkpoint']
    first_ev=next((e for e in cp['events'] if e.get('context',{}).get('request_body')),None)
    baseline_ev=next(e for e in controlcp['events'] if e.get('context',{}).get('request_body'))
    physical=lambda c:{k:v for k,v in c.items() if k not in ('candidate_id','candidate_fingerprint')}
    same_pool=first_ev is not None and [physical(c) for c in first_ev['bundle']['physical_candidates']]==[physical(c) for c in baseline_ev['bundle']['physical_candidates']]
    assert same_pool
    result={'version':'gp6_mandatory_saved_run_audit_v1','status':'PASS_SAVED_FACTS_ONLY','experiment_plan_digest':digest(spec),'runtime_plan_digest':digest(plan),'first_committed_box':first_box,
      'per_step':[{'decision_id':s.get('decision_id'),'Cxx':s.get('original_selected_Cxx'),'status':s['status'],'violation_rule':s.get('violation_rule'),'compliant_Cxx':s.get('hard_rule_finalists_Cxx'),'raw_choice_evidence':s.get('raw_choice_ledger_verification')} for s in rules['steps']],
      'placed_items':m['placed_items'],'planned_items':m['planned_items'],'fixed_container_utilization':m['fixed_container_utilization'],'termination_reason':m['termination_reason'],'termination_class':m['termination_class'],
      'monitor_statuses':dict(Counter(e['monitor']['status'] for e in cp['events'] if e.get('monitor'))),'counts':m['counts'],
      'send_reservations':sum(r['send_started'] for r in ledger['requests']),'network_attempts':sum((r.get('transport') or {}).get('network_attempted') is True for r in ledger['requests']),
      'failed_requests':m['cost']['failed_requests'],'unknown_sends':m['cost']['unknown_sends'],'only_instructions_changed':True,'first_published_pool_content_unchanged':same_pool,'no_reselection':True,'base_config_changed_keys':diff,
      'exit_code':int((ROOT/'exit_code.txt').read_text()),'new_audit_model_calls':0,'new_audit_kernel_calls':0,'new_independent_review':False}
    (ROOT/'saved_result_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
