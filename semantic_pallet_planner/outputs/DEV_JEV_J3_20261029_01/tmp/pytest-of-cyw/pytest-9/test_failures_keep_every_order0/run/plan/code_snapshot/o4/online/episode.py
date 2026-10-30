"""One-box O4 online rollout. Reference evaluation is downstream of selection."""
import copy
import math
from ...domain import PalletState
from ...planner.generator import ExtremePointGenerator
from ...protocol import state_hash
from ...evaluation.state import state_metrics
from ...evaluation.geometry_oracle import check_candidate
from ..common import O4Error,digest
from ..observation import build_observation
from ..compiler import compile_policy,response_for,validate_response
from ..evaluator import audit_reference,reference_state
from .planner_adapter import labeled_candidates,select_and_commit


def state_for(scenario,placed,index,request_id,available=True):
    items={i['item_id']:i for i in scenario['items']}
    current=[copy.deepcopy(items[scenario['arrival_order'][index]])] if available and index<len(scenario['arrival_order']) else []
    return {'request_id':request_id,'container':copy.deepcopy(scenario['container']),
            'placed_items':copy.deepcopy(placed),'available_items':current}


def compile_backend(req,backend,oracle_policy=None,fault=None):
    if backend=='public_parser':response=compile_policy(req)
    elif backend=='oracle_ast':response=response_for(req,copy.deepcopy(oracle_policy))
    else:raise O4Error('unsupported_construct','offline backend only')
    if fault=='drop_rules':response['policy_ast']={'schema_version':'o4_policy_v1','rules':[]}
    elif fault=='invalid_ast':response['policy_ast']={'schema_version':'unsupported','rules':[]}
    elif fault=='invalid_binding':response['observation_digest']='0'*64
    elif fault=='provider_error':raise O4Error('provider_error','injected offline failure')
    validate_response(response,req)
    return response


def enumerate_physical(state,config):
    # Audit only, after selection; never changes the planner's Top-K pool.
    from ...domain import internal_item,restore_placed
    from ...planner.constraints import candidate_points,evaluate_pose
    item=internal_item(state['available_items'][0]);placed=restore_placed(state['placed_items'])
    settings=copy.deepcopy(config);settings['container']=state['container'];out=[]
    for yaw in settings['candidate_generator']['yaw_degrees']:
        l,w=item['dimensions'][:2] if yaw==0 else item['dimensions'][:2][::-1]
        for x,y,z in candidate_points(placed,l,w,settings['container']):
            candidate,_=evaluate_pose(item,placed,x,y,z,l,w,yaw,settings)
            if candidate is not None:out.append(candidate['visible'])
    return out


def summarize(scenario,task,backend,events):
    last=events[-1]
    placed=last['after_placed_items'];planned=len(scenario['arrival_order'])
    final=last['reference_after']['violations']
    violating=0
    for e in events:
        if not e['committed_label']:continue
        selected=next(v for v in e['reference_evaluation']['evaluations'] if v['candidate_id']==e['proposed_label'])
        before,after=selected['before'],selected['after']
        worsened=any(after['loads_kg'].get(i,0)-limit > max(0.,before['loads_kg'].get(i,0)-limit)+1e-6
                     for i,limit in after['limits_kg'].items() if f'load:{i}' in before['violations'])
        violating+=bool(selected['new_violations'] or worsened)
    total_volume=math.fsum(math.prod(list(o['dimensions_mm'].values())) for o in scenario['items'])
    return {'task_id':task['task_id'],'scenario_id':task['scenario_id'],
            'source_order_key':task['source_order_key'],'configuration':task['configuration'], 'method':backend,
            'planned_items':planned,'placed_items':len(placed),'completed':len(placed)==planned,
            'clean_completed':len(placed)==planned and not final,
            'placed_item_ratio':len(placed)/planned,
            'placed_volume_ratio':math.fsum(math.prod(p['oriented_size_mm']) for p in placed)/total_volume,
            'final_business_violation_count':len(final),'final_violation_ids':final,
            'violating_steps':violating,'business_violation_step_rate':violating/len(placed) if placed else None,
            'ever_violating':any(e['reference_after']['violations'] for e in events),
            'physical_violations':sum(bool(e['committed_label']) and bool(e['physical_errors']) for e in events),
            'physical_rejections':sum(e['status']=='physical_rejection' for e in events),
            'termination_reason':last['status'],'decision_records':len(events),'remote_calls':0,
            'geometry':state_metrics(scenario['container'],placed)}


def episode(scenario,attributes,task,backend,generator_config,*,fault=None):
    generator=ExtremePointGenerator(generator_config)
    placed=[];events=[]
    for index in range(len(scenario['arrival_order'])):
        request_id=f"{task['task_id']}_S{index:03d}"
        state=state_for(scenario,placed,index,request_id)
        generation=generator.generate(PalletState.from_dict(state))
        raw_candidates=generation.candidate_set.data['candidates']
        if generation.candidate_set.data['physical_state_hash'] != state_hash(state['container'],state):
            raise O4Error('invalid_binding','generator returned stale candidates')
        req=build_observation(state,attributes,task['instruction_text'])
        public,mapping=labeled_candidates(raw_candidates)
        response=None
        if not raw_candidates:
            result={'status':'no_physical_candidate','proposed_label':None,'committed_label':None,
                    'action':None,'trace':{},'method_evaluation':None,'physical_errors':[]}
        else:
            try:
                response=compile_backend(req,backend,task['reference_policy'] if backend=='oracle_ast' else None,fault)
                result,new_placed=select_and_commit(state,attributes,req,raw_candidates,response)
                if result['committed_label']:placed=new_placed
            except O4Error as exc:
                result={'status':exc.code,'proposed_label':None,'committed_label':None,
                        'action':None,'trace':{},'method_evaluation':None,'physical_errors':[]}
        # The hidden reference is consulted only after the proposal/commit is fixed.
        reference=audit_reference(req,task['reference_policy'],public)
        after_state=state_for(scenario,placed,index+1,request_id+'_AFTER',available=False)
        after_observation=build_observation(after_state,attributes,task['instruction_text'])
        reference_after=reference_state(after_observation['placed_objects'],task['reference_policy'])
        full=None
        if result['status']=='no_compiled_business_candidate' or (raw_candidates and not reference['allowed_ids']):
            all_candidates=enumerate_physical(state,generator_config)
            audit=audit_reference(req,task['reference_policy'],all_candidates)
            full={'physical_count':len(all_candidates),'reference_business_feasible_count':len(audit['allowed_ids']),
                  'scope':'frozen_enumerated_space_not_continuous_global_feasibility'}
        if result['committed_label'] and index+1==len(scenario['arrival_order']):result['status']='all_items_placed'
        # Recheck actual submission independently, including stored candidate metadata.
        committed_errors=check_candidate(state,{'container':state['container']},mapping[result['committed_label']]) if result['committed_label'] else []
        if committed_errors:raise O4Error('physical_invariant','committed invalid pose')
        events.append({**result,'step_index':index,'request':req,'response':response,
                       'before_physical_state_hash':state_hash(state['container'],state),
                       'after_physical_state_hash':state_hash(after_state['container'],after_state),
                       'before_state':state,'raw_candidates':raw_candidates,'candidate_mapping':mapping,
                       'public_candidates':public,'candidate_set_digest':digest(public),
                       'generation_audit':generation.audit.data,
                       'after_placed_items':copy.deepcopy(placed),'reference_evaluation':reference,
                       'reference_after':reference_after,'full_enumeration_audit':full})
        if not result['committed_label'] or result['status']=='all_items_placed':break
    return summarize(scenario,task,backend,events),events
