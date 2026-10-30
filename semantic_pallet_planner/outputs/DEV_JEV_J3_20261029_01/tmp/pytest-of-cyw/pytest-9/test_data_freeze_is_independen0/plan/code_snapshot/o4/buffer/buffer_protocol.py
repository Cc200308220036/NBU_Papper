"""Closed, public-only buffer protocol with full-state action bindings."""
import copy
from ..common import O4Error,digest,validate
from ..normalize import validate_policy
from ..compiler import parse_instruction,response_for


def validate_observation(req):
    validate('buffer_observation',req,'invalid_observation')
    ids=[o['object_id'] for k in ('placed_objects','available_objects') for o in req[k]]
    if len(ids)!=len(set(ids)):raise O4Error('invalid_observation')
    for obj in req['placed_objects']:
        dims=[obj['dimensions_mm'][k] for k in ('length','width','height')]
        if obj['pose']['yaw_deg']==90:dims[0],dims[1]=dims[1],dims[0]
        if dims!=obj['oriented_size_mm']:raise O4Error('invalid_observation','orientation mismatch')
    if (req['state_hash']!=digest({k:req[k] for k in ('container','placed_objects','available_objects')})
        or req['instruction_digest']!=digest(req['instruction_text'])
        or req['observation_digest']!=digest({k:v for k,v in req.items() if k not in ('request_id','observation_digest')})):
        raise O4Error('invalid_binding')
    return req


def compile_backend(req,backend,oracle_policy=None,fault=None,*,public=None):
    validate_observation(req)
    if backend=='public_parser':ast=parse_instruction(req['instruction_text'])
    elif backend=='oracle_ast':ast=copy.deepcopy(oracle_policy)
    else:raise O4Error('invalid_method')
    if fault=='drop_rules':ast={'schema_version':'o4_policy_v1','rules':[]}
    response=response_for(req,ast)
    validate('response',response);validate_policy(ast,req)
    if public is None:raise O4Error('invalid_binding','full buffer state required')
    validate_state(public)
    if public['observation']!=req:raise O4Error('invalid_binding')
    response.update(schema_version='o4_buffer_response_v1',buffer_state_hash=public['buffer_state_hash'],event_index=public['event_index'])
    validate('buffer_response',response)
    return response


def validate_state(public):
    validate('buffer_state',public,'invalid_buffer_state')
    obs=validate_observation(public['observation'])
    if public['buffer_state_hash']!=digest({k:v for k,v in public.items() if k!='buffer_state_hash'}):
        raise O4Error('invalid_binding')
    pending=public['pending_items'];ids=[x['object_id'] for x in pending]
    if (public['mode']!=('single' if public['buffer_capacity']==1 else 'buffer') or len(ids)!=len(set(ids)) or len(pending)>public['buffer_capacity']
        or [x['facts'] for x in pending]!=obs['available_objects']
        or any(x['facts']['object_id']!=x['object_id'] for x in pending)
        or public['placed_count']!=len(obs['placed_objects'])
        or public['arrival_count']!=public['placed_count']+len(pending)
        or public['instruction_digest']!=obs['instruction_digest']
        or len({x['slot'] for x in pending})!=len(pending)
        or any(x['slot']>=public['buffer_capacity'] for x in pending)
        or any(x['arrival_index']>=public['arrival_count'] for x in pending)
        or len({x['arrival_index'] for x in pending})!=len(pending)):
        raise O4Error('invalid_buffer_state')
    return public


def action(public,kind,*,pick=None,label=None,candidates=()):
    validate_state(public)
    return {'schema_version':'o4_buffer_action_v1','kind':kind,
            'buffer_state_hash':public['buffer_state_hash'],'instruction_digest':public['instruction_digest'],
            'event_index':public['event_index'],'pick_item_id':pick,'candidate_label':label,
            'candidate_set_digest':digest(list(candidates))}


def validate_action(public,value,candidates=()):
    validate_state(public);validate('buffer_action',value,'invalid_buffer_action')
    for k in ('buffer_state_hash','instruction_digest','event_index'):
        if public[k]!=value[k]:raise O4Error('invalid_binding')
    if value['candidate_set_digest']!=digest(list(candidates)):raise O4Error('invalid_binding')
    if value['kind']=='WAIT_NEXT':
        if (public['end_of_stream'] or len(public['pending_items'])>=public['buffer_capacity']
            or value['pick_item_id'] is not None or value['candidate_label'] is not None):raise O4Error('invalid_wait')
    else:
        ids={p['object_id'] for p in public['pending_items']}
        selected=[c for c in candidates if c['candidate_id']==value['candidate_label']]
        if value['pick_item_id'] not in ids or len(selected)!=1 or selected[0]['pick_item_id']!=value['pick_item_id']:
            raise O4Error('invalid_pick')
    return value
