"""QA-JMV13-01: current-identity construction; saved-byte checks never dispatch."""
import copy
import hashlib
from pathlib import Path
import pytest
from test_packaging_jev_v13 import setup,run,FakeTransport
from semantic_pallet_planner.jev_select import packaging_jev_v13 as v13
from semantic_pallet_planner.jev_select.contracts import JevSelectError,digest,CandidateBundle
from semantic_pallet_planner.jev_select.ledger import read,write


def files(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def mutate(e,case):
    s=e['after']
    if case=='arrival_mass':s['pending_items'][-1]['item']['mass_kg']+=1
    elif case=='arrival_size':s['pending_items'][-1]['item']['dimensions_mm']['width']+=1
    elif case=='arrival_packaging':s['attributes'][s['arrived_ids'][-1]]['packaging']['reinforced']=True
    elif case=='arrival_slot':s['pending_items'][-1]['slot']=2
    elif case=='arrival_index':s['pending_items'][-1]['arrival_index']+=1
    elif case=='arrival_ids':s['arrived_ids'][0]='WRONG'
    elif case=='arrival_cursor':s['arrival_count']+=1
    elif case=='arrival_old_buffer':s['pending_items'][0]['item']['mass_kg']+=1
    elif case=='arrival_container':s['container']['max_payload_kg']+=1
    elif case=='arrival_event_index':s['event_index']+=1
    elif case=='arrival_eos':s['end_of_stream']=True
    elif case=='eos_payload':s['pending_items'][0]['item']['mass_kg']+=1
    elif case=='eos_geometry':s['placed_items'][0]['pose']['x_mm']+=1
    elif case=='eos_flag':s['end_of_stream']=False
    elif case=='eos_container':s['container']['length_mm']+=1
    elif case=='eos_attributes':s['attributes']['A']['packaging']['reinforced']=True
    elif case=='new_pose':s['placed_items'][-1]['pose']['x_mm']+=1
    elif case=='new_yaw':s['placed_items'][-1]['pose']['yaw_deg']=90
    elif case=='new_size':s['placed_items'][-1]['oriented_size_mm'][0]+=1
    elif case=='new_dimensions':s['placed_items'][-1]['dimensions_mm']['length']+=1
    elif case=='new_mass':s['placed_items'][-1]['mass_kg']+=1
    elif case=='new_packaging':s['placed_items'][-1]['top_load_limit_kg_synthetic']+=1
    elif case=='new_stackable':s['placed_items'][-1]['stackable']=False
    elif case=='new_load':s['placed_items'][-1]['supported_load_kg']+=1
    elif case=='new_edges':s['placed_items'][-1]['support_fractions']=[{'item_id':'A','fraction':1.0}]
    elif case=='remaining_buffer':s['pending_items'][0]['item']['mass_kg']+=1
    elif case=='remaining_slot':s['pending_items'][0]['slot']=0
    elif case=='old_pose':s['placed_items'][0]['pose']['x_mm']+=1
    elif case=='old_mass':s['placed_items'][0]['mass_kg']+=1
    elif case=='old_size':s['placed_items'][0]['dimensions_mm']['width']+=1
    elif case=='old_packaging':s['placed_items'][0]['top_load_limit_kg_synthetic']+=1
    elif case=='old_load':s['placed_items'][0]['supported_load_kg']+=1
    elif case=='old_edges':s['placed_items'][0]['support_fractions']=[{'item_id':'B','fraction':1.0}]
    elif case=='place_container':s['container']['max_payload_kg']+=1
    elif case=='place_attributes':s['attributes']['A']['packaging']['reinforced']=True
    elif case=='place_event_index':s['event_index']+=1
    else:raise AssertionError(case)


def test_production_negative_and_legal_saved_transitions(setup,tmp_path,monkeypatch):
    ex,_,_=setup;run(ex);root=Path(ex['storage_root']);original=files(root)
    stages=[(p,read(p)) for p in sorted((root/'stages').glob('*.json'))]
    def target(kind,count=None):
        for p,r in stages:
            cp=r['checkpoint'];e=cp['pending_event'] or (cp['events'][-1] if cp['events'] else None)
            if e and e['event']==kind and (count is None or e['after']['placed_count']==count):return p,r
        raise AssertionError((kind,count))
    cases=['arrival_mass','arrival_size','arrival_packaging','arrival_slot','arrival_index','arrival_ids','arrival_cursor',
           'arrival_old_buffer','arrival_container','arrival_event_index','arrival_eos','eos_payload','eos_geometry','eos_flag','eos_container','eos_attributes',
           'new_pose','new_yaw','new_size','new_dimensions','new_mass','new_packaging','new_stackable','new_load','new_edges',
           'remaining_buffer','remaining_slot','old_pose','old_mass','old_size','old_packaging','old_load','old_edges','place_container','place_attributes','place_event_index']
    from semantic_pallet_planner.jev_select import episode,execution
    from semantic_pallet_planner.jev_select.stability import monitor
    from semantic_pallet_planner.o4.buffer import buffer_state
    calls={k:0 for k in ('model','candidate','monitor','commit','receive')}
    def forbidden(key):
        def no(*a,**kw):calls[key]+=1;pytest.fail('saved validator dispatched '+key)
        return no
    monkeypatch.setattr(FakeTransport,'complete',forbidden('model'))
    monkeypatch.setattr(episode,'decision_inputs',forbidden('candidate'))
    monkeypatch.setattr(monitor,'monitor_selected_action',forbidden('monitor'))
    monkeypatch.setattr(execution,'commit_physical',forbidden('commit'))
    monkeypatch.setattr(buffer_state,'receive',forbidden('receive'))
    # Every archived checkpoint phase and all legitimate arrival/EOS/place deltas.
    phases=set()
    for _,r in stages:
        v13.validate_saved_checkpoint(r['checkpoint'],ex);phases.add(r['checkpoint']['phase'])
    v13.validate_saved_execution(root);run(ex)
    assert files(root)==original
    receipts=[]
    for case in cases:
        if case.startswith('arrival_'):p,r=target('WAIT_RECEIVE') if case!='arrival_old_buffer' else next((p,r) for p,r in stages if len(r['checkpoint']['state']['pending_items'])==2 and r['checkpoint']['events'][-1]['event']=='WAIT_RECEIVE')
        elif case.startswith('eos_'):p,r=target('EOS')
        else:p,r=target('PLACE',2 if case.startswith('old_') else 1)
        raw=p.read_bytes();bad=copy.deepcopy(r);cp=bad['checkpoint'];e=cp['pending_event'] or cp['events'][-1]
        mutate(e,case);cp['state']=copy.deepcopy(e['after']);v13.seal(cp);v13.seal(bad)
        write(p,bad);before=files(root);errors=[]
        for entry in ('validate_saved_execution','run_execution'):
            with pytest.raises((JevSelectError,ValueError)) as caught:
                if entry=='validate_saved_execution':v13.validate_saved_execution(root)
                else:run(ex)
            errors.append({'entry':entry,'error':str(caught.value)})
            assert files(root)==before
        assert not any(calls.values())
        evidence=tmp_path/'negative_cases'/case
        write(evidence/'mutated_journal.json',bad)
        receipts.append({'case':case,'original_journal':p.relative_to(root).as_posix(),'original_sha256':hashlib.sha256(raw).hexdigest(),
                         'mutated_sha256':before[p.relative_to(root).as_posix()],'rejections':errors,'dispatches':dict(calls),
                         'mutated_and_other_saved_bytes_unchanged_by_both_entries':True})
        p.write_bytes(raw);assert files(root)==original
    v13.validate_saved_execution(root);assert not any(calls.values())
    write(tmp_path/'production_rejection_receipt.json',{'scope':'CONSTRUCTED_ONLY','qa_issue':'QA-JMV13-01',
          'prior_static_witness':'NOT claimed to be prior production PASS; current identity constructed counterparts rejected',
          'positive_checkpoint_phases':sorted(phases),'negative_cases':receipts,'original_root_byte_identity':digest(original),
          'original_unchanged':files(root)==original,'dispatches':calls})


def test_stacked_area_load_positive_and_negative(setup,tmp_path,monkeypatch):
    # A new constructed singleton pool stacks all four boxes. No generator/LP.
    ex,_,_=setup
    from semantic_pallet_planner.jev_select import episode
    from semantic_pallet_planner.jev_select.packaging_runtime import build_context,no_policy
    from semantic_pallet_planner.jev_select.selector import bind_decision
    from semantic_pallet_planner.o4.extensions.e2.protocol import observation
    fixture=read(Path(__file__).parents[1]/'fixtures/jm_a1_frozen_pool.json')
    template=fixture['candidates'][0]
    def inputs(s,task,cfg,job_id,did,**kw):
        req=observation(s,task['instruction_text'],[]);item=s['pending_items'][0]['item'];c=copy.deepcopy(template)
        c.update(candidate_id='constructed_stack_'+item['item_id'],pick_item_id=item['item_id'],candidate_fingerprint=digest(['CONSTRUCTED_STACK',item['item_id']]),
                 pose={'x_mm':0,'y_mm':0,'z_base_mm':20*s['placed_count'],'yaw_deg':0},oriented_size_mm=[20,30,20])
        c['support']['support_item_ids']=[s['placed_items'][-1]['item_id']] if s['placed_items'] else []
        c['resulting_geometry'].update(max_height_mm=20*(s['placed_count']+1),
            volume_utilization=12000*(s['placed_count']+1)/(s['container']['length_mm']*s['container']['width_mm']*s['container']['max_height_mm']),center_of_mass_offset_mm=0.0)
        pool=[c];b={'version':'jev_candidate_bundle_v13','observation_digest':req['observation_digest'],'candidate_backend':'e2_original_v1',
            'generator_config_digest':digest('CONSTRUCTED_STACK_ONLY'),'physical_candidates':pool,'physical_digest':digest(pool),
            'selectable_candidates':pool,'selectable_digest':digest(pool),'generation_counts':[],'selectable_pool':'physical_feasible',
            'policy_digest':digest(no_policy(req).data),'experiment_protocol':cfg['experiment_protocol'],'business_mode':cfg['business_mode']}
        bundle=CandidateBundle.from_dict(b);policy=no_policy(req)
        ctx=bind_decision(build_context(cfg,req,bundle,policy),job_id,did,config=cfg)
        return req,policy,bundle,ctx
    monkeypatch.setattr(episode,'decision_inputs',inputs)
    ep=run(ex);assert ep['checkpoint']['reason']=='ALL_ITEMS_PLACED'
    placed=ep['final_state']['placed_items'];assert placed[0]['supported_load_kg']==sum(x['mass_kg'] for x in placed[1:])
    from semantic_pallet_planner.jev_select import execution
    monkeypatch.setattr(execution,'commit_physical',lambda *a,**k:pytest.fail('audit committed'))
    monkeypatch.setattr(episode,'decision_inputs',lambda *a,**k:pytest.fail('audit generated'))
    v13.validate_saved_execution(ex['storage_root']);run(ex)
    event=next(e for e in ep['events'] if e['event']=='PLACE' and e['after']['placed_count']==3)
    c=next(c for c in event['bundle']['physical_candidates'] if c['candidate_id']==event['selection']['selected_candidate_id'])
    v13.validate_saved_place(event['before'],event['after'],c)
    bad=copy.deepcopy(event['after']);bad['placed_items'][0]['supported_load_kg']+=1
    with pytest.raises(JevSelectError,match='saved_place_delta_changed'):v13.validate_saved_place(event['before'],bad,c)
    write(tmp_path/'area_load_receipt.json',{'scope':'CONSTRUCTED_MONITOR_STUB','legal_recursive_area_updates':'PASS',
           'old_loads':[p['supported_load_kg'] for p in placed],'wrong_increment':'REFUSED','model_calls':0,'solver_calls':0,
           'saved_validator_commit_or_candidate_dispatch':0})
