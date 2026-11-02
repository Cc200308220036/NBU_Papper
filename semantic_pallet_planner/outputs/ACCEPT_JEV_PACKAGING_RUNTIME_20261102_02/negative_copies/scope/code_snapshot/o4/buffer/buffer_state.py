"""The sole owner of real pending-set mutations. No future stream lives here."""
import copy
from ..common import O4Error,digest
from ..observation import public_object
from ...protocol import state_hash
from ...evaluation.geometry_oracle import check_candidate
from ...evaluation.state import apply_candidate


def initial(container,capacity=3):
    if type(capacity) is not int or capacity not in (1,2,3):
        raise O4Error('invalid_capacity')
    return {'container':copy.deepcopy(container),'buffer_capacity':capacity,'pending_items':[],
            'placed_items':[],'arrived_ids':[],'attributes':{},'event_index':0,
            'arrival_count':0,'placed_count':0,'end_of_stream':False}


def invariant(s):
    a=s['arrived_ids'];p=[x['item_id'] for x in s['placed_items']]
    q=[x['item']['item_id'] for x in s['pending_items']];slots=[x['slot'] for x in s['pending_items']]
    if (len(set(a))!=len(a) or len(set(p+q))!=len(p+q) or set(a)!=set(p+q)
        or len(q)>s['buffer_capacity'] or len(slots)!=len(set(slots))
        or any(type(i) is not int or not 0<=i<s['buffer_capacity'] for i in slots)
        or s['arrival_count']!=len(a) or s['placed_count']!=len(p)
        or set(s['attributes'])!=set(a)
        or any(x['arrival_index']!=a.index(x['item']['item_id']) for x in s['pending_items'])):
        raise O4Error('buffer_invariant')
    return True


def ordered(s):return sorted(s['pending_items'],key=lambda x:x['arrival_index'])


def physical(s,pick=None):
    return {'request_id':f"O4F_E{s['event_index']:04d}",'container':copy.deepcopy(s['container']),
            'placed_items':copy.deepcopy(s['placed_items']),
            'available_items':[copy.deepcopy(x['item']) for x in ordered(s) if pick is None or x['item']['item_id']==pick]}


def observation(s,text):
    invariant(s)
    case=physical(s)
    req={'schema_version':'o4_buffer_observation_v1','request_id':case['request_id'],
         'units':{'length':'mm','mass':'kg'},'container':copy.deepcopy(s['container']),
         'placed_objects':[public_object(i,s['attributes'][i['item_id']],True) for i in case['placed_items']],
         'available_objects':[public_object(i,s['attributes'][i['item_id']]) for i in case['available_items']],
         'instruction_text':text,'images':[]}
    req['state_hash']=digest({k:req[k] for k in ('container','placed_objects','available_objects')})
    req['instruction_digest']=digest(text)
    req['observation_digest']=digest({k:v for k,v in req.items() if k!='request_id'})
    from .buffer_protocol import validate_observation
    return validate_observation(req)


def public_state(s,text):
    from .buffer_protocol import validate_state
    obs=observation(s,text)
    obj={x['object_id']:x for x in obs['available_objects']}
    result={'schema_version':'o4_buffer_state_v1','mode':'single' if s['buffer_capacity']==1 else 'buffer',
            'buffer_capacity':s['buffer_capacity'],'event_index':s['event_index'],
            'arrival_count':s['arrival_count'],'placed_count':s['placed_count'],'end_of_stream':s['end_of_stream'],
            'physical_state_hash':state_hash(s['container'],physical(s)),
            'pending_items':[{'object_id':x['item']['item_id'],'facts':obj[x['item']['item_id']],
                              'slot':x['slot'],'arrival_index':x['arrival_index']} for x in ordered(s)],
            'observation':obs,'instruction_digest':obs['instruction_digest']}
    result['buffer_state_hash']=digest(result)
    return validate_state(result)


def can_wait(s):return not s['end_of_stream'] and len(s['pending_items'])<s['buffer_capacity']


def receive(s,item=None,attributes=None,*,eos=False):
    invariant(s)
    if not can_wait(s):raise O4Error('invalid_wait')
    if item is None and not eos:raise O4Error('invalid_arrival')
    new=copy.deepcopy(s)
    if item is not None:
        identifier=item['item_id']
        if identifier in new['arrived_ids']:raise O4Error('duplicate_arrival')
        if attributes is None or attributes['object_id']!=identifier:raise O4Error('invalid_arrival')
        slot=min(set(range(s['buffer_capacity']))-{x['slot'] for x in s['pending_items']})
        new['pending_items'].append({'item':copy.deepcopy(item),'slot':slot,'arrival_index':new['arrival_count']})
        new['attributes'][identifier]=copy.deepcopy(attributes)
        new['arrived_ids'].append(identifier);new['arrival_count']+=1
    new['end_of_stream']=bool(eos);new['event_index']+=1
    invariant(new)
    return new


def place(s,candidate):
    invariant(s)
    if candidate.get('pick_item_id') not in {x['item']['item_id'] for x in s['pending_items']}:
        raise O4Error('invalid_pick')
    case=physical(s,candidate['pick_item_id'])
    try:errors=check_candidate(case,{'container':s['container']},candidate)
    except (KeyError,TypeError,ValueError) as exc:raise O4Error('invalid_candidate',str(exc)) from exc
    if errors:raise O4Error('physical_rejection',','.join(errors))
    new=copy.deepcopy(s);new['placed_items']=apply_candidate(case,candidate)
    new['pending_items']=[x for x in new['pending_items'] if x['item']['item_id']!=candidate['pick_item_id']]
    new['placed_count']+=1;new['event_index']+=1
    invariant(new)
    return new
