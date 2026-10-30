"""Arrived-only episode driver and downstream independent reference/event audit."""
import copy
import math
import time
from ..common import digest,O4Error
from .buffer_protocol import compile_backend
from ..executor import evaluate_candidates
from ..evaluator import audit_reference,reference_state
from ...evaluation.geometry_oracle import check_candidate
from ...evaluation.state import state_metrics
from .buffer_state import initial,receive,place,can_wait,public_state,observation,physical,invariant,ordered
from .buffer_protocol import action,validate_action
from .buffer_candidates import pools,public_candidates
from .buffer_baselines import choose
from .buffer_search import search,surface

METHODS=('single_greedy','buffer_fifo','buffer_heuristic','buffer_search')


def stable(value):
    """Timing is measurement, excluded only from deterministic replay comparisons."""
    if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in ('elapsed_seconds','planning_seconds')}
    if isinstance(value,list):return [stable(v) for v in value]
    return value


def submit(s,text,ast,candidate,value,candidates):
    pub=public_state(s,text);validate_action(pub,value,candidates)
    if value['kind']!='PLACE':raise O4Error('invalid_buffer_action')
    if candidate['candidate_id']!=value['candidate_label'] or candidate['pick_item_id']!=value['pick_item_id']:
        raise O4Error('invalid_pick')
    public_match=next((c for c in candidates if c['candidate_id']==candidate['candidate_id']),None)
    expected_fingerprint=digest({'pick':candidate['raw']['pick_item_id'],'pose':candidate['raw']['pose'],'size':candidate['raw']['oriented_size_mm']})
    if (public_match is None or public_match['buffer_state_hash']!=pub['buffer_state_hash']
        or any(candidate[k]!=candidate['raw'][k] for k in ('pick_item_id','pose','oriented_size_mm'))
        or any(candidate[k]!=public_match[k] for k in ('pick_item_id','pose','oriented_size_mm','candidate_fingerprint'))
        or expected_fingerprint!=candidate['candidate_fingerprint']):raise O4Error('invalid_binding','candidate mapping changed')
    req=observation(s,text)
    if candidate['candidate_id'] not in evaluate_candidates(req,ast,[candidate])['allowed_ids']:
        raise O4Error('business_rejection')
    return place(s,candidate['raw'])


def summary(scenario,task,method,backend,events,s):
    n=len(scenario['arrival_order']);placed=s['placed_items']
    volumes={i['item_id']:math.prod(list(i['dimensions_mm'].values())) for i in scenario['items']}
    order={i:j for j,i in enumerate(scenario['arrival_order'])};sequence=[p['item_id'] for p in placed]
    inversions=sum(order[a]>order[b] for i,a in enumerate(sequence) for b in sequence[i+1:])
    waits=[e for e in events if e['kind']=='WAIT_NEXT'];commits=[e for e in events if e['kind']=='PLACE']
    after_arrival=[len(e['after_state']['pending_items']) for e in waits if e['received_id'] is not None]
    after_place=[len(e['after_state']['pending_items']) for e in commits]
    audits=[e['search_trace'] for e in events if e.get('search_trace')]
    final=reference_state(observation(s,task['instruction_text'])['placed_objects'],task['reference_policy'])
    def spans(identifier):
        start=next(e['event_index'] for e in waits if e['received_id']==identifier)
        end=next((e['event_index'] for e in commits if e['action']['pick_item_id']==identifier),math.inf)
        return sum(start<e['event_index']<end for e in commits)
    area,height=surface(s,task['reference_policy'])
    return {'task_id':task['task_id'],'scenario_id':task['scenario_id'],'source_order_key':task['source_order_key'],
        'configuration':task['configuration'],'method':method,'backend':backend,'planned_items':n,'placed_items':len(placed),
        'completed':len(placed)==n,'clean_completed':len(placed)==n and not final['violations'],
        'placed_item_ratio':len(placed)/n,'placed_volume_ratio':sum(volumes[i] for i in sequence)/sum(volumes.values()),
        'final_business_violation_count':len(final['violations']),'final_violation_ids':final['violations'],
        'physical_violations':sum(bool(e.get('committed_physical_errors')) for e in commits),
        'reference_violating_commits':sum(bool(e.get('reference_after',{}).get('violations')) for e in commits),
        'termination_reason':events[-1]['status'],'arrived_ids':s['arrived_ids'],'placed_sequence':sequence,
        'pending_ids':[p['item']['item_id'] for p in ordered(s)],'not_arrived_ids':scenario['arrival_order'][s['arrival_count']:],
        'arrival_count':s['arrival_count'],'wait_requests':len(waits),'successful_receives':sum(e['received_id'] is not None for e in waits),
        'eos_events':sum(e['received_eos'] for e in waits),'place_events':len(commits),
        'max_pending':max((len(e['after_state']['pending_items']) for e in events),default=0),
        'mean_pending_after_receive':sum(after_arrival)/len(after_arrival) if after_arrival else None,
        'mean_pending_after_place':sum(after_place)/len(after_place) if after_place else None,
        'non_head_commits':sum(e['action']['pick_item_id']!=ordered(e['before_state'])[0]['item']['item_id'] for e in commits),
        'non_head_fraction':sum(e['action']['pick_item_id']!=ordered(e['before_state'])[0]['item']['item_id'] for e in commits)/len(commits) if commits else 0.,
        'inversions':inversions,'defer_spans':{i:spans(i) for i in sequence},
        'unplaced_defer_spans':{p['item']['item_id']:spans(p['item']['item_id']) for p in s['pending_items']},
        'search_evaluations':[a['evaluations'] for a in audits],'search_truncated_count':sum(a['search_truncated'] for a in audits),
        'planning_count':sum(e['kind']!='WAIT_NEXT' for e in events),'event_records':len(events),
        'geometry':state_metrics(s['container'],placed),'exposed_stackable_area_ratio':area,'height_ratio':height,
        'same_count_geometry':[{'exposed_stackable_area_ratio':surface(e['after_state'],task['reference_policy'])[0],'placed_count':e['after_state']['placed_count'],**state_metrics(s['container'],e['after_state']['placed_items'])} for e in commits],
        'full_buffer_blocked':events[-1]['kind']=='STOP' and len(s['pending_items'])==s['buffer_capacity'],
        'eos_remaining':len(s['pending_items']) if s['end_of_stream'] else 0,'remote_calls':0}


def episode(scenario,attributes,task,method,backend,config,*,search_config=None,fault=None,
            eos_mode='empty_read',checkpoint=None,pause_after=None,capacity=None):
    if method not in METHODS or backend not in ('oracle_ast','public_parser'):raise O4Error('invalid_method')
    if eos_mode not in ('empty_read','last_arrival'):raise O4Error('invalid_eos_mode')
    capacity=(1 if method=='single_greedy' else 3) if capacity is None else capacity
    if capacity not in (1,2,3) or (method=='single_greedy' and capacity!=1):raise O4Error('invalid_capacity')
    binding=digest([scenario,attributes,task,method,backend,config,search_config,fault,eos_mode,capacity])
    if checkpoint:
        if checkpoint['binding']!=binding or checkpoint['digest']!=digest({k:v for k,v in checkpoint.items() if k!='digest'}):raise O4Error('invalid_checkpoint')
        s=copy.deepcopy(checkpoint['state']);events=copy.deepcopy(checkpoint['events']);cursor=checkpoint['cursor']
        invariant(s)
        if s['arrived_ids']!=scenario['arrival_order'][:cursor] or cursor!=s['arrival_count']:raise O4Error('invalid_checkpoint')
    else:s=initial(scenario['container'],capacity);events=[];cursor=0
    by_id={i['item_id']:i for i in scenario['items']}
    while True:
        before=copy.deepcopy(s);pub=public_state(s,task['instruction_text'])
        event={'event_index':s['event_index'],'before_state':before,'public_state':pub,
               'search_trace':None,'reference_after':None}
        if can_wait(s):
            value=action(pub,'WAIT_NEXT');validate_action(pub,value)
            # Environment owns source stream; only receive() result crosses into planning state.
            identifier=scenario['arrival_order'][cursor] if cursor<len(scenario['arrival_order']) else None
            ended=identifier is None or (eos_mode=='last_arrival' and cursor+1==len(scenario['arrival_order']))
            s=receive(s,by_id[identifier] if identifier else None,attributes[identifier] if identifier else None,eos=ended)
            if identifier:cursor+=1
            event.update(kind='WAIT_NEXT',action=value,received_id=identifier,received_eos=ended,status='received' if identifier else 'eos')
        elif not s['pending_items']:
            event.update(kind='STOP',status='all_items_placed',action=None)
        else:
            start=time.perf_counter();req=observation(s,task['instruction_text'])
            response=compile_backend(req,backend,task['reference_policy'] if backend=='oracle_ast' else None,fault,public=pub)
            ast=response['policy_ast'];groups,audit=pools(s,task['instruction_text'],ast,config)
            candidates=public_candidates(groups,pub['buffer_state_hash'])
            if method=='buffer_search':
                chosen,reason,trace=search(s,task['instruction_text'],ast,config,groups,audit,search_config)
            else:
                chosen,reason=choose(groups,method);trace=None
            event.update(response=response,root_pools=groups,root_audit=audit,public_candidates=candidates,
                         search_trace=trace,planning_seconds=time.perf_counter()-start)
            if chosen:
                value=action(pub,'PLACE',pick=chosen['pick_item_id'],label=chosen['candidate_id'],candidates=candidates)
                s=submit(s,task['instruction_text'],ast,chosen,value,candidates)
                event.update(kind='PLACE',action=value,status='placed',chosen_candidate=chosen,
                             committed_physical_errors=check_candidate(physical(before,chosen['pick_item_id']),{'container':s['container']},chosen['raw']))
            else:event.update(kind='STOP',status=reason,action=None)
            # Privileged evaluation starts after the chosen action and actual commit are fixed.
            event['reference_root']=audit_reference(req,task['reference_policy'],candidates)
            event['reference_after']=reference_state(observation(s,task['instruction_text'])['placed_objects'],task['reference_policy'])
        invariant(s);event['after_state']=copy.deepcopy(s)
        event['after_public_state']=public_state(s,task['instruction_text']);events.append(event)
        if event['kind']=='STOP':return summary(scenario,task,method,backend,events,s),events,None
        if pause_after is not None and len(events)>=pause_after:
            cp={'binding':binding,'state':s,'events':events,'cursor':cursor};cp['digest']=digest(cp)
            return None,events,cp


def audit_events(events):
    """Recompute conservation and event accounting without state mutation helpers."""
    errors=[];placed_count=0;arrived=[];checks=0
    for e in events:
        a=e['after_state'];before=e['before_state'];checks+=1
        p=[i['item_id'] for i in a['placed_items']];q=[i['item']['item_id'] for i in a['pending_items']]
        if len(set(p+q))!=len(p+q) or set(p+q)!=set(a['arrived_ids']) or len(q)>a['buffer_capacity']:errors.append('conservation')
        if e['kind']=='WAIT_NEXT':
            if before['end_of_stream'] or len(before['pending_items'])>=before['buffer_capacity']:errors.append('illegal_wait')
            if before['placed_items']!=a['placed_items']:errors.append('wait_changed_pallet')
            if e['received_id'] is not None:arrived.append(e['received_id'])
        elif e['kind']=='PLACE':
            placed_count+=1
            if before['arrived_ids']!=a['arrived_ids'] or len(p)!=len(before['placed_items'])+1:errors.append('place_account')
            errors.extend(check_candidate(physical(before,e['action']['pick_item_id']),{'container':before['container']},e['chosen_candidate']['raw']))
            expected=reference_state(e['after_public_state']['observation']['placed_objects'],e['response']['policy_ast'])
            # This is an independent business check of what actually happened, not action correction.
            if expected['violations']:errors.append('method_business_violation')
        if a['arrival_count']!=len(arrived) or a['placed_count']!=placed_count:errors.append('counts')
        trace=e.get('search_trace')
        if trace:
            counted=sum(n['audit']['evaluations'] for n in trace['nodes'])
            if counted!=trace['evaluations'] or counted>256 or trace['max_depth']>3 or trace['max_beam']>8:errors.append('search_budget')
        for pool in e.get('root_pools',[]):
            if len(pool['joint'])>16:errors.append('top_k')
        if sum(len(g['joint']) for g in e.get('root_pools',[]))>48:errors.append('joint_top_k')
    return {'status':'PASS' if not errors else 'FAIL','event_checks':checks,'errors':errors}
