"""Actual negative executions, recorded separately from primary experiment."""
import copy
import ast
from pathlib import Path
from ...common import O4Error, digest
from ...buffer.buffer_state import initial, receive
from .protocol import observation, rebind, validate_response, response_for
from .compiler import compile_policy
from .planning import choose, search, action_for, commit, pools
from .episode import episode, verify_episode, stable


def run_faults(data, config, root):
    rows=[];task=data['constructs'][0]
    state=initial(task['container'],3)
    for obj in task['items'][:3]:state=receive(state,obj,task['attributes'][obj['item_id']])
    req=observation(state,task['instruction_text'],task['regions']);response=compile_policy(req)
    def reject(purpose,fn):
        try:fn()
        except O4Error as exc:rows.append({'purpose':purpose,'passed':True,'error':str(exc)})
        else:rows.append({'purpose':purpose,'passed':False,'error':None})
    for field in ('regions','instruction_text','buffer_context','request_id'):
        changed=copy.deepcopy(req)
        if field=='regions':changed['regions'][0]['x_min_mm']-=1
        elif field=='instruction_text':changed[field]+=' '
        elif field=='buffer_context':changed[field]['end_of_stream']=True
        else:changed[field]+='_new'
        changed=rebind(changed)
        reject('stale_response_'+field,lambda q=changed:validate_response(response,q))
    for field,value in (('placement_convention','label_pos_x'),('capability_version','o4_e3_v1'),('coordinate_convention','screen_xy'),('spatial_eps_mm',.1)):
        changed=copy.deepcopy(req);changed[field]=value
        reject('unsupported_'+field,lambda q=changed:rebind(q))
    chosen,groups,trace,reason=choose(state,req,response['policy_ast'],config,'buffer_search')
    candidates=[c for g in groups for c in g['candidates']];action=action_for(req,candidates,chosen)
    reject('changed_candidate_order',lambda:commit(state,task['regions'],req,response,list(reversed(candidates)),action))
    altered=copy.deepcopy(candidates);altered[0]['pose']['yaw_deg']=90-altered[0]['pose']['yaw_deg']
    reject('changed_candidate_yaw',lambda:commit(state,task['regions'],req,response,altered,action))
    altered=copy.deepcopy(candidates);altered[0]['pose']['roll_deg']=180
    reject('tilted_candidate',lambda:commit(state,task['regions'],req,response,altered,action))
    modified=copy.deepcopy(state);modified['end_of_stream']=True
    reject('changed_eos_action',lambda:commit(modified,task['regions'],req,response,candidates,action))
    modified=copy.deepcopy(state);modified['pending_items'][0]['slot'],modified['pending_items'][1]['slot']=modified['pending_items'][1]['slot'],modified['pending_items'][0]['slot']
    reject('changed_slot_action',lambda:commit(modified,task['regions'],req,response,candidates,action))
    bad=copy.deepcopy(response['policy_ast']);bad['rules'][0]['subject']={'object_ids':['future_box']}
    reject('future_object_reference',lambda:response_for(req,bad))
    bad=copy.deepcopy(response['policy_ast']);bad['rules'].append({'rule_id':'load','type':'max_top_load','target':{'all':True},'priority':0,'overrides':['rel'],'limit':{'constant_kg':2.}})
    reject('cross_family_override',lambda:response_for(req,bad))
    reject('search_budget_too_small',lambda:search(state,req,response['policy_ast'],config,groups,48,{'search_depth':3,'beam_width':8,'max_successor_evaluations':47}))
    rows.append({'purpose':'search_clone_and_budget','passed':trace['before_real_state']==trace['after_real_state']==digest(state)
                 and trace['evaluations']<=256 and trace['max_depth']<=3 and trace['max_beam']<=8})
    # The planner receives only arrived state; future modifications must not
    # affect its request or complete search trace.
    altered_task=copy.deepcopy(task);altered_task['items'][3]['mass_kg']=99.
    original_run=episode(task,'public_parser','buffer_search',config)
    altered_run=episode(altered_task,'public_parser','buffer_search',config)
    first_original=next(e for e in original_run['events'] if 'request' in e)
    first_altered=next(e for e in altered_run['events'] if 'request' in e)
    rows.append({'purpose':'hidden_future_invariance','passed':stable(first_original)==stable(first_altered),
                 'public_request_has_future':any(o['object_id']==task['items'][3]['item_id'] for o in req['available_objects'])})
    wrong=episode(data['constructs'][4],'public_parser','single',config,fault='drop_rules')
    rows.append({'purpose':'wrong_ast_visible','passed':wrong['summary']['completed'] and bool(wrong['summary']['final_business_violations']),
                 'summary':wrong['summary']})
    wrong_direction=episode(task,'public_parser','single',config,fault='invert_relation')
    rows.append({'purpose':'wrong_direction_visible','passed':wrong_direction['summary']['completed'] and bool(wrong_direction['summary']['final_business_violations']),
                 'summary':wrong_direction['summary']})
    from .candidates import generate
    c1,a1=generate(state,state['pending_items'][0]['item']['item_id'],req['regions'],config)
    no_private=copy.deepcopy(state);no_private['future_items']=[{'item_id':'unarrived','mass_kg':999999}]
    c2,a2=generate(no_private,state['pending_items'][0]['item']['item_id'],req['regions'],config)
    rows.append({'purpose':'candidate_public_input_only','passed':c1==c2 and stable(a1)==stable(a2),
                 'scope':'sampler signature has no AST/relation/private gap and ignores unexposed extra state fields'})
    good=episode(task,'oracle_ast','single',config)
    corrupted=copy.deepcopy(good);corrupted['events'][0]['after']['end_of_stream']=True
    reject('tampered_event',lambda:verify_episode(corrupted,task,config))
    from . import reference
    tree=ast.parse(Path(reference.__file__).read_text())
    imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    rows.append({'purpose':'reference_dependency_boundary','passed':not any(any(x in m.split('.') for x in ('runtime','normalize','compiler','planning','candidates')) for m in imports),'imports':imports})
    return rows
