"""E2 single/buffer episodes; downstream reference audits never select actions."""
import copy
import math
from ...common import digest, O4Error
from ...buffer.buffer_state import initial, receive, can_wait, invariant
from .protocol import observation, response_for
from .compiler import compile_policy
from .planning import choose, action_for, commit, METHODS
from .reference import audit, state as reference_state, compare


def stable(value):
    """Execution times are measured, not treated as deterministic state."""
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k not in ('elapsed_seconds',)}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value


def episode(task, backend, method, config, *, resume=None, fault=None):
    if backend not in ('public_parser', 'oracle_ast') or method not in METHODS:
        raise O4Error('unsupported_backend_or_planner')
    capacity = 1 if method == 'single' else 3
    s = initial(task['container'], capacity) if resume is None else copy.deepcopy(resume['state'])
    cursor = 0 if resume is None else resume['cursor']
    events = [] if resume is None else copy.deepcopy(resume['events'])
    if s['buffer_capacity'] != capacity:
        raise O4Error('invalid_restore_capacity')
    checkpoints = []
    planned_ids = [o['item_id'] for o in task['items']]
    if s['arrived_ids'] != planned_ids[:cursor]:
        raise O4Error('invalid_restore_cursor')
    if resume is not None:
        verify_episode({'summary':{'capacity':capacity,'planner':method},'events':events,'final_state':s},task,config)
    terminal=bool(events and events[-1]['event']=='STOP')
    reason=events[-1]['reason'] if terminal else None
    while not terminal:
        invariant(s)
        if can_wait(s):
            before = copy.deepcopy(s)
            if cursor < len(task['items']):
                obj = task['items'][cursor]
                s = receive(s, obj, task['attributes'][obj['item_id']]); cursor += 1
                kind = 'WAIT_RECEIVE'
            else:
                s = receive(s, eos=True); kind = 'EOS'
            events.append({'event': kind, 'before': before, 'after': copy.deepcopy(s)})
            checkpoints.append({'state': copy.deepcopy(s), 'cursor': cursor, 'events': copy.deepcopy(events)})
            continue
        if not s['pending_items']:
            reason = 'all_items_placed' if cursor == len(task['items']) else 'unexpected_empty_buffer'
            break
        req = observation(s, task['instruction_text'], task['regions'])
        # Oracle is an explicitly privileged backend; parser only receives req.
        response = compile_policy(req) if backend == 'public_parser' else response_for(req, task['reference_policy'])
        if fault == 'drop_rules':
            response = response_for(req, {'schema_version': 'o4_e2_policy_v1', 'rules': []})
        elif fault=='invert_relation':
            wrong=copy.deepcopy(response['policy_ast'])
            for r in wrong['rules']:
                if r['type']=='relative_position':
                    r['relation']={'left_of':'right_of','right_of':'left_of','front_of':'behind','behind':'front_of'}[r['relation']]
            response=response_for(req,wrong)
        chosen, groups, search_trace, reason = choose(s, req, response['policy_ast'], config, method)
        candidates = [c for g in groups for c in g['candidates']]
        before = copy.deepcopy(s)
        action = action_for(req, candidates, chosen) if chosen is not None else None
        if action:
            s = commit(s, task['regions'], req, response, candidates, action)
        # Reference is evaluated after proposal/commit; it cannot reject it.
        reference = audit(req, task['reference_policy'], candidates)
        after_req = observation(s, task['instruction_text'], task['regions'])
        evaluated = reference_state(after_req['placed_objects'], task['reference_policy'], task['regions'],
                                    pending_objects=after_req['available_objects'],end_of_stream=after_req['buffer_context']['end_of_stream'])
        metrics = compare(response['policy_ast'], task['reference_policy'], req['placed_objects']+req['available_objects'])
        metrics['allowed_set_equal'] = sorted(c['candidate_id'] for g in groups for c in g['candidates'] if c['candidate_id'] in g['evaluation']['allowed_ids']) == reference['allowed_ids']
        actual_allowed={i for g in groups for i in g['evaluation']['allowed_ids']};expected_allowed=set(reference['allowed_ids'])
        metrics['false_allow_ids']=sorted(actual_allowed-expected_allowed);metrics['false_reject_ids']=sorted(expected_allowed-actual_allowed)
        events.append({'event': 'PLACE' if chosen is not None else 'STOP', 'before': before, 'after': copy.deepcopy(s),
                       'request': req, 'response': response, 'groups': groups, 'search_trace': search_trace,
                       'candidates': candidates, 'action': action, 'reference_evaluation': reference,
                       'reference_after': evaluated, 'compilation_metrics': metrics, 'reason': reason})
        checkpoints.append({'state': copy.deepcopy(s), 'cursor': cursor, 'events': copy.deepcopy(events)})
        if chosen is None:
            break
    final_req = observation(s, task['instruction_text'], task['regions'])
    final_ref = reference_state(final_req['placed_objects'], task['reference_policy'], task['regions'],
                               pending_objects=final_req['available_objects'],end_of_stream=final_req['buffer_context']['end_of_stream'])
    total = len(task['items']); complete = s['placed_count'] == total
    summary = {'task_id': task['task_id'], 'source_order_key': task['source_order_key'], 'backend': backend,
               'planner': method, 'capacity': capacity, 'planned_items': total, 'placed_items': s['placed_count'],
               'arrived_items': s['arrival_count'], 'pending_ids': [p['item']['item_id'] for p in s['pending_items']],
               'unarrived_ids': planned_ids[cursor:], 'completed': complete,
               'clean_completed': complete and not final_ref['violations'], 'termination_reason': reason,
               'final_business_violations': final_ref['violations'], 'relation_status':final_ref['relation_status'],
               'deferred_relations':final_ref['deferred_relations'], 'new_api_attempts': 0,
               'violating_steps': sum(bool(e.get('action')) and bool(e['reference_after']['violations']) for e in events),
               'placed_item_ratio': s['placed_count']/total,
               'placed_volume_ratio': sum(math.prod(o['oriented_size_mm']) for o in s['placed_items'])/sum(math.prod(list(o['dimensions_mm'].values())) for o in task['items'])}
    return {'summary': summary, 'events': events, 'final_state': s, 'checkpoints': checkpoints}


def verify_episode(result, task, config):
    """Recompute each transition, independent physics and reference judgments."""
    from ...buffer.buffer_state import place, physical
    from ....evaluation.geometry_oracle import check_candidate
    previous = initial(task['container'], result['summary']['capacity'])
    for event in result['events']:
        if previous != event['before']:
            raise O4Error('invalid_event_chain')
        if event['event'] == 'WAIT_RECEIVE':
            index = previous['arrival_count']; obj = task['items'][index]
            expected = receive(previous, obj, task['attributes'][obj['item_id']])
        elif event['event'] == 'EOS':
            expected = receive(previous, eos=True)
        else:
            req = observation(previous, task['instruction_text'], task['regions'])
            if req != event['request']:
                raise O4Error('invalid_event_observation')
            selected, groups, trace, reason = choose(previous, req, event['response']['policy_ast'], config, result['summary']['planner'])
            if stable(groups) != stable(event['groups']) or stable(trace) != stable(event['search_trace']) or reason != event['reason']:
                raise O4Error('invalid_event_planning')
            regenerated=[c for g in groups for c in g['candidates']]
            if regenerated!=event['candidates']:
                raise O4Error('invalid_event_candidate_pool')
            if event['action']:
                if selected is None or selected['candidate_id'] != event['action']['candidate_id']:
                    raise O4Error('invalid_event_action')
                if event['action']!=action_for(req,regenerated,selected):
                    raise O4Error('invalid_event_action_binding')
                errors = check_candidate(physical(previous, selected['pick_item_id']), {'container': task['container']}, selected)
                if errors:
                    raise O4Error('physical_violation', str(errors))
                expected = commit(previous, task['regions'], req, event['response'], event['candidates'], event['action'])
            else:
                if selected is not None or event['event'] != 'STOP':
                    raise O4Error('invalid_event_stop')
                expected = previous
            reference = audit(req, task['reference_policy'], event['candidates'])
            if reference != event['reference_evaluation']:
                raise O4Error('invalid_reference_audit')
            after_req = observation(expected, task['instruction_text'], task['regions'])
            if reference_state(after_req['placed_objects'], task['reference_policy'], task['regions'],
                               pending_objects=after_req['available_objects'],end_of_stream=after_req['buffer_context']['end_of_stream']) != event['reference_after']:
                raise O4Error('invalid_reference_state')
        if expected != event['after']:
            raise O4Error('invalid_event_transition')
        invariant(expected); previous = expected
    if previous != result['final_state']:
        raise O4Error('invalid_final_state')
    return {'event_chain': True, 'conservation': True, 'independent_physics': True,
            'reference_recomputed': True, 'planning_recomputed': True, 'event_count': len(result['events'])}
