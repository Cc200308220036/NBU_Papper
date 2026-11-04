"""One state machine for local/remote backends; reference is downstream only."""
import copy
import math
from ...common import O4Error,digest
from ...buffer.buffer_state import initial,receive,can_wait,invariant,physical
from ....evaluation.geometry_oracle import check_candidate
from ..e2.protocol import observation,validate_response
from ..e2.planning import action_for,commit,METHODS
from .planning import choose
from ..e2.reference import audit,state as reference_state,compare
from .diagnostics import diagnose
from .activity import task_presence,activity


def stable(value):
    if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in ('elapsed_seconds','generation_seconds')}
    if isinstance(value,list):return [stable(v) for v in value]
    return value


def final_reference(s,task):
    q=observation(s,task['instruction_text'],task['regions'])
    return reference_state(q['placed_objects'],task['reference_policy'],task['regions'],pending_objects=q['available_objects'],end_of_stream=q['buffer_context']['end_of_stream'])


def metrics_for(req,response,task,groups):
    m=compare(response['policy_ast'],task['reference_policy'],req['placed_objects']+req['available_objects'])
    candidates=[c for g in groups for c in g['candidates']]
    expected=audit(req,task['reference_policy'],candidates)
    actual={i for g in groups for i in g['evaluation']['allowed_ids']};allowed=set(expected['allowed_ids'])
    m.update(valid_ast=True,allowed_set_equal=actual==allowed,false_allow_ids=sorted(actual-allowed),false_reject_ids=sorted(allowed-actual))
    return m,expected


def summarize(task,backend,method,s,events,reason):
    total=len(task['items']);placed=[o['item_id'] for o in s['placed_items']];pending=[p['item']['item_id'] for p in s['pending_items']]
    final=final_reference(s,task);complete=len(placed)==total
    violating_steps=sum(bool(e.get('action')) and bool(e['reference_after']['violations']) for e in events)
    status='PASS' if reason in ('all_items_placed','fifo_head_blocked','no_physical_candidate','no_compiled_business_candidate') else 'PARTIAL' if reason=='budget_exhausted' else 'FAIL'
    return {'task_id':task['task_id'],'source_order_key':task['source_order_key'],'source_kind':task['source_kind'],
            'configuration':task['configuration'],'backend':backend,'planner':method,'capacity':s['buffer_capacity'],
            'task_rule_presence':task_presence(task),'execution_status':status,'planned_items':total,'arrived_items':len(s['arrived_ids']),'placed_items':len(placed),
            'pending_ids':pending,'unarrived_ids':[o['item_id'] for o in task['items'] if o['item_id'] not in s['arrived_ids']],
            'completed':complete,'clean_completed':complete and not final['violations'] and violating_steps==0,
            'termination_reason':reason,'final_business_violations':final['violations'],'relation_status':final['relation_status'],
            'violating_steps':violating_steps,
            'business_violation_step_rate':violating_steps/len(placed) if placed else None,
            'placed_item_ratio':len(placed)/total,
            'placed_volume_ratio':sum(math.prod(o['oriented_size_mm']) for o in s['placed_items'])/sum(math.prod(list(o['dimensions_mm'].values())) for o in task['items']),
            'decision_records':sum(e['event'] in ('PLACE','STOP','COMPILE_FAILURE','COMMIT_FAILURE') for e in events)}


def episode(task,backend,method,config,compiler,job_id,*,resume=None,on_checkpoint=None):
    if backend not in ('public_parser','oracle_ast','remote_text','remote_image') or method not in METHODS:raise O4Error('unsupported_backend_or_planner')
    capacity=1 if method=='single' else 3
    if resume is None:s=initial(task['container'],capacity);cursor=decision=0;events=[]
    else:
        if resume['job_id']!=job_id or resume['backend']!=backend or resume['planner']!=method:raise O4Error('checkpoint_identity_changed')
        s=copy.deepcopy(resume['state']);cursor=resume['cursor'];decision=resume['decision'];events=copy.deepcopy(resume['events'])
        verify_prefix(task,backend,method,config,s,events)
        if cursor!=s['arrival_count'] or decision!=sum(e['event'] in ('PLACE','STOP','COMPILE_FAILURE','COMMIT_FAILURE') for e in events):raise O4Error('checkpoint_cursor_changed')
    if s['buffer_capacity']!=capacity:raise O4Error('checkpoint_capacity_changed')
    checkpoints=[]
    def save(phase):
        cp={'job_id':job_id,'backend':backend,'planner':method,'state':copy.deepcopy(s),'cursor':cursor,'decision':decision,'events':copy.deepcopy(events)}
        if not checkpoints or (len(checkpoints)<2 and phase=='after_decision'):checkpoints.append(cp)
        if on_checkpoint:on_checkpoint(cp,phase)
    reason=events[-1]['reason'] if events and events[-1]['event'] in ('STOP','COMPILE_FAILURE','COMMIT_FAILURE') else None
    while reason is None:
        invariant(s)
        if can_wait(s):
            before=copy.deepcopy(s)
            if cursor<len(task['items']):
                obj=task['items'][cursor];s=receive(s,obj,task['attributes'][obj['item_id']]);cursor+=1;kind='WAIT_RECEIVE'
            else:s=receive(s,eos=True);kind='EOS'
            events.append({'event':kind,'before':before,'after':copy.deepcopy(s)});save('after_receive');continue
        if not s['pending_items']:
            reason='all_items_placed';break
        if decision>len(task['items']):raise O4Error('decision_bound_exceeded')
        source=observation(s,task['instruction_text'],task['regions']);save('before_compile')
        try:compilation=compiler.compile(source,job_id,decision)
        except O4Error as exc:
            compilation={'compiled_request':source,'response':None,'status':exc.code,'error':str(exc),
                         'compilation_id':f'{job_id}_D{decision:04d}','backend':backend,'source_digest':digest(source),
                         'first_valid':False,'repaired_valid':False,'attempt_ids':[],'test_double':False}
        req=compilation['compiled_request'];response=compilation['response']
        if response is None:
            reason=compilation['status'];events.append({'event':'COMPILE_FAILURE','before':copy.deepcopy(s),'after':copy.deepcopy(s),
                  'source_request':source,'request':req,'compilation':compilation,'reason':reason,'action':None})
            decision+=1;save('after_failure');break
        # Actual bound request (including image attachment), never a rebinding
        # of an incoming response. It must describe the current physical state.
        if req!=observation(s,task['instruction_text'],task['regions'],req['images']):raise O4Error('backend_changed_public_state')
        validate_response(response,req)
        if compilation['status']!='valid':raise O4Error('backend_status_mismatch')
        save('before_commit')
        chosen,groups,trace,stop=choose(s,req,response['policy_ast'],config,method)
        candidates=[c for g in groups for c in g['candidates']];before=copy.deepcopy(s)
        proposed=action_for(req,candidates,chosen) if chosen is not None else None
        action=proposed;commit_error=None
        if action:
            try:s=commit(s,task['regions'],req,response,candidates,action)
            except O4Error as exc:
                commit_error={'code':exc.code,'detail':str(exc)};action=None
        # Audit has no influence on proposal, selection, or commit.
        m,reference=metrics_for(req,response,task,groups)
        terminal_reason=commit_error['code'] if commit_error else stop
        event={'event':'COMMIT_FAILURE' if commit_error else 'PLACE' if action else 'STOP','before':before,'after':copy.deepcopy(s),
               'source_request':source,'request':req,'response':response,'compilation':compilation,
               'groups':groups,'candidates':candidates,'search_trace':trace,'action':action,'proposed_action':proposed,'commit_error':commit_error,'planning_reason':stop,
               'reference_evaluation':reference,'reference_after':final_reference(s,task),
               'compilation_metrics':m,'diagnostics':diagnose(req,response['policy_ast'],task['reference_policy'],groups,trace,terminal_reason),'reason':terminal_reason}
        event['rule_activity']=activity(task['reference_policy'],event['reference_after'])
        events.append(event);decision+=1;save('after_decision')
        if not action:reason=terminal_reason
    return {'job_id':job_id,'summary':summarize(task,backend,method,s,events,reason),'events':events,'final_state':s,'checkpoints':checkpoints}


def verify_prefix(task,backend,method,config,final,events):
    previous=initial(task['container'],1 if method=='single' else 3);terminal=False
    for e in events:
        if terminal or previous!=e['before']:raise O4Error('invalid_event_chain')
        if e['event']=='WAIT_RECEIVE':
            obj=task['items'][previous['arrival_count']];expected=receive(previous,obj,task['attributes'][obj['item_id']])
        elif e['event']=='EOS':
            if previous['arrival_count']!=len(task['items']):raise O4Error('premature_eos')
            expected=receive(previous,eos=True)
        else:
            if e['event'] not in ('PLACE','STOP','COMPILE_FAILURE','COMMIT_FAILURE') or can_wait(previous):raise O4Error('invalid_event_phase')
            source=observation(previous,task['instruction_text'],task['regions']);req=e['request'];comp=e['compilation']
            if source!=e['source_request'] or comp['source_digest']!=digest(source) or req!=observation(previous,task['instruction_text'],task['regions'],req['images']):raise O4Error('invalid_event_observation')
            if comp['compiled_request']!=req or comp['backend']!=backend:raise O4Error('invalid_compilation_binding')
            if e['event']=='COMPILE_FAILURE':
                if comp['response'] is not None or comp['status']=='valid' or e['reason']!=comp['status']:raise O4Error('invalid_failure_event')
                expected=previous;terminal=True
            else:
                response=e['response'];validate_response(response,req)
                if comp['response']!=response:raise O4Error('changed_saved_response')
                chosen,groups,trace,reason=choose(previous,req,response['policy_ast'],config,method)
                candidates=[c for g in groups for c in g['candidates']]
                if stable(groups)!=stable(e['groups']) or stable(trace)!=stable(e['search_trace']) or candidates!=e['candidates'] or reason!=e['planning_reason']:raise O4Error('invalid_event_planning')
                if e['proposed_action']!=(action_for(req,candidates,chosen) if chosen is not None else None):raise O4Error('invalid_proposed_action')
                if e['event']=='COMMIT_FAILURE':
                    if chosen is None or e['action'] is not None or e['proposed_action']!=action_for(req,candidates,chosen):raise O4Error('invalid_commit_failure')
                    try:commit(previous,task['regions'],req,response,candidates,e['proposed_action'])
                    except O4Error as exc:
                        if e['commit_error']!={'code':exc.code,'detail':str(exc)} or e['reason']!=exc.code:raise O4Error('invalid_commit_error')
                    else:raise O4Error('unreproduced_commit_failure')
                    expected=previous;terminal=True
                elif e['action']:
                    if chosen is None or e['event']!='PLACE' or action_for(req,candidates,chosen)!=e['action']:raise O4Error('invalid_event_action')
                    errors=check_candidate(physical(previous,chosen['pick_item_id']),{'container':task['container']},chosen)
                    if errors:raise O4Error('physical_violation',str(errors))
                    expected=commit(previous,task['regions'],req,response,candidates,e['action'])
                else:
                    if chosen is not None or e['event']!='STOP':raise O4Error('invalid_event_stop')
                    expected=previous;terminal=True
                m,reference=metrics_for(req,response,task,groups)
                if m!=e['compilation_metrics'] or reference!=e['reference_evaluation'] or final_reference(expected,task)!=e['reference_after']:raise O4Error('invalid_reference_metrics')
                if activity(task['reference_policy'],e['reference_after'])!=e['rule_activity']:raise O4Error('invalid_rule_activity')
                if stable(diagnose(req,response['policy_ast'],task['reference_policy'],groups,trace,e['reason']))!=stable(e['diagnostics']):raise O4Error('invalid_diagnostics')
        if expected!=e['after']:raise O4Error('invalid_event_transition')
        invariant(expected);previous=expected
    if previous!=final:raise O4Error('invalid_final_state')
    return {'event_chain':True,'conservation':True,'independent_physics':True,'reference_recomputed':True,'planning_recomputed':True}


def verify_episode(result,task,config):
    summary=result['summary'];backend=summary['backend'];method=summary['planner']
    checked=verify_prefix(task,backend,method,config,result['final_state'],result['events'])
    if summary!=summarize(task,backend,method,result['final_state'],result['events'],summary['termination_reason']):raise O4Error('invalid_summary')
    if result['events'] and result['events'][-1]['event'] in ('STOP','COMPILE_FAILURE','COMMIT_FAILURE'):
        if summary['termination_reason']!=result['events'][-1]['reason']:raise O4Error('invalid_termination')
    elif not summary['completed'] or not result['final_state']['end_of_stream'] or summary['termination_reason']!='all_items_placed':raise O4Error('premature_success')
    return {**checked,'summary_recomputed':True}
