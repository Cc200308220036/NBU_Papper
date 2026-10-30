"""Fill-then-plan direct-selection simulator. Checkpoints own durable state."""
from __future__ import annotations

import copy
import time

from semantic_pallet_planner.o4.buffer.buffer_state import initial, receive, can_wait, invariant
from semantic_pallet_planner.o4.extensions.e2.protocol import observation
from semantic_pallet_planner.o4.extensions.e2.planning import action_for, commit

from .candidates import CandidateProvider, PublicBusinessGuard, decision_route
from .config import generator_config, is_v2
from .context import ContextBuilder, resolve_display_id
from .contracts import JevSelectError, digest
from .evaluation import feedback, summarize
from .selector import bind_decision, result


def decision_inputs(state, task, config, job_id, decision_id, *, timings=None):
    started = time.perf_counter()
    req = observation(state, task["instruction_text"], task["regions"])
    guard = PublicBusinessGuard()
    policy = guard.resolve(req)
    parsed = time.perf_counter()
    from semantic_pallet_planner.o4.extensions.e2.candidates import _cached_generation
    before_cache = _cached_generation.cache_info()
    bundle = CandidateProvider().build(state, req, generator_config(), config=config)
    generated = time.perf_counter()
    after_cache = _cached_generation.cache_info()
    bundle = guard.filter(req, policy, bundle, config)
    context = bind_decision(ContextBuilder(config).build(req, bundle, policy), job_id, decision_id)
    if timings is not None:
        timings.update(public_parse_s=parsed-started, physical_generation_s=generated-parsed,
                       facts_context_s=time.perf_counter()-generated,
                       generation_cache_hits=after_cache.hits-before_cache.hits,
                       generation_cache_misses=after_cache.misses-before_cache.misses)
    return req, policy, bundle, context


def run_episode(task, selector, config, *, job_id, method, resume=None, on_checkpoint=None,
                hook=None, event_limit=None, expected_events=None):
    if is_v2(config):
        return _run_episode_v2(task, selector, config, job_id=job_id, method=method, resume=resume,
                               on_checkpoint=on_checkpoint, hook=hook, event_limit=event_limit,
                               expected_events=expected_events)
    if resume is not None:
        # Rebuild the entire committed prefix using saved answers, never network.
        replay_selector = selector.for_replay() if hasattr(selector, "for_replay") else selector
        checked = run_episode(task, replay_selector, config, job_id=job_id, method=method,
                              event_limit=len(resume["events"]), expected_events=resume["events"])
        if checked["checkpoint"] != resume:
            raise JevSelectError("checkpoint_changed")
        state = copy.deepcopy(resume["state"]); cursor = resume["cursor"]
        decision = resume["decision"]; events = copy.deepcopy(resume["events"])
        reason = resume["reason"]
    else:
        state = initial(task["container"], config["buffer_capacity"])
        cursor = decision = 0; events = []; reason = None

    def checkpoint():
        return {"version": "jev_checkpoint_v1", "job_id": job_id, "method": method,
                "task_digest": digest(task), "config_digest": digest(config), "state": copy.deepcopy(state),
                "cursor": cursor, "decision": decision, "events": copy.deepcopy(events), "reason": reason}

    def save(event):
        events.append(event)
        if expected_events is not None and (len(events) > len(expected_events) or events[-1] != expected_events[len(events)-1]):
            raise JevSelectError("event_reconstruction_mismatch", f"{job_id}: event {len(events)}")
        cp = checkpoint()
        if on_checkpoint: on_checkpoint(cp)
        if hook: hook("after_checkpoint", cp)

    while reason is None and (event_limit is None or len(events) < event_limit):
        invariant(state)
        before = copy.deepcopy(state)
        if can_wait(state):
            if cursor < len(task["items"]):
                obj = task["items"][cursor]
                state = receive(state, obj, task["attributes"][obj["item_id"]]); cursor += 1
                kind = "WAIT_RECEIVE"
            else:
                state = receive(state, eos=True); kind = "EOS"
            save({"event": kind, "before": before, "after": copy.deepcopy(state)})
            continue
        if not state["pending_items"]:
            reason = "ALL_ITEMS_PLACED"
            break
        if decision > len(task["items"]):
            raise JevSelectError("decision_bound_exceeded")
        identifier = f"{job_id}_D{decision:04d}"
        event = {"event": "STOP", "decision_id": identifier, "before": before, "after": before,
                 "route": None, "observation": None, "bundle": None, "context": None,
                 "selection": None, "proposed_action": None, "action": None, "reason": None, "error": None}
        try:
            req, policy, bundle, context = decision_inputs(state, task, config, job_id, identifier)
            route = decision_route(bundle)
            event.update(route=route, observation=req, bundle=bundle.data, context=context.data)
            if hook: hook("decision_ready", event)
            if route.startswith("STOP_"):
                reason = route
            else:
                if route == "SINGLETON_BYPASS":
                    selection = result(context, status="singleton", source="singleton", label="C01")
                else:
                    selection = selector.select(context, decision_id=identifier)
                event["selection"] = selection.data
                if selection.data["local_binding_digest"] != digest(context.data["local_binding"]):
                    raise JevSelectError("stale_selection")
                if selection.data["status"] not in ("selected", "singleton"):
                    reason = selection.data["status"].upper()
                else:
                    chosen = resolve_display_id(context, selection.data["selected_display_id"], req, bundle, config)
                    if chosen["candidate_id"] != selection.data["selected_candidate_id"]:
                        raise JevSelectError("selection_candidate_mismatch")
                    # Rebuild again immediately before commit; no alternate choice is made.
                    fresh = decision_inputs(state, task, config, job_id, identifier)
                    if fresh[3].data != context.data or fresh[2].data != bundle.data:
                        raise JevSelectError("stale_precommit")
                    action = action_for(req, bundle.data["physical_candidates"], chosen)
                    event["proposed_action"] = action
                    if hook: hook("before_commit", event)
                    state = commit(state, task["regions"], req, policy.data["response"], bundle.data["physical_candidates"], action)
                    event.update(event="PLACE", action=action, after=copy.deepcopy(state))
        except (ValueError, KeyError, TypeError) as exc:
            reason = getattr(exc, "code", "DECISION_ERROR")
            event["event"] = "COMMIT_FAILURE" if event["proposed_action"] else "DECISION_FAILURE"
            event["error"] = {"code": reason, "detail": str(exc)}
            if state != before:
                raise JevSelectError("failure_mutated_state") from exc
        event["reason"] = reason
        # Independent private feedback is downstream and never enters the next context.
        event["reference_after"] = feedback(state, task)
        decision += 1
        save(event)
    if reason is None and state["end_of_stream"] and not state["pending_items"]:
        reason = "ALL_ITEMS_PLACED"
    cp = checkpoint()
    summary = summarize(task, config, method, state, events, reason) if reason is not None else None
    return {"job_id": job_id, "events": events, "final_state": state, "summary": summary, "checkpoint": cp}


def semantic_record(value):
    """Deterministic state/event data, excluding non-reproducible CPU telemetry."""
    if isinstance(value, dict):
        return {k: semantic_record(v) for k,v in value.items() if not (k == 'timings' and {'event','before','after'} <= set(value))}
    if isinstance(value, list):
        return [semantic_record(v) for v in value]
    return value


def _run_episode_v2(task, selector, config, *, job_id, method, resume=None,
                    on_checkpoint=None, hook=None, event_limit=None, expected_events=None):
    from .evaluation import evaluate_committed_state, summarize_v2
    from .execution import commit_physical
    from .selector import SelectionResult
    state = initial(task['container'], config['buffer_capacity'])
    cursor = decision = 0
    events = []; reason = None; pending = None; phase = 'READY'
    replaying = expected_events is not None
    decision_started = None

    def checkpoint():
        value = {'version': 'jev_checkpoint_v2', 'job_id': job_id, 'method': method,
                'task_digest': digest(task), 'config_digest': digest(config),
                'state': copy.deepcopy(state), 'cursor': cursor, 'decision': decision,
                'events': copy.deepcopy(events), 'reason': reason, 'phase': phase,
                'pending_event': copy.deepcopy(pending)}
        from .contracts import validate_schema
        validate_schema('checkpoint_v2',value)
        return value

    def persist():
        cp = checkpoint()
        if on_checkpoint: on_checkpoint(cp)
        return cp

    def append(event):
        nonlocal pending, phase
        if expected_events is not None:
            if len(events) >= len(expected_events) or semantic_record(event) != semantic_record(expected_events[len(events)]):
                raise JevSelectError('event_reconstruction_mismatch', f'{job_id}: event {len(events)}')
            event['timings'] = copy.deepcopy(expected_events[len(events)]['timings'])
        events.append(event); pending = None; phase = 'READY'
        cp = persist()
        if hook: hook('after_checkpoint', cp)

    def public_bind(req, policy, bundle):
        if hasattr(selector, 'bind_public'):
            selector.bind_public(req, policy, bundle)

    if resume is not None:
        from .contracts import validate_schema
        validate_schema('checkpoint_v2',resume)
        if resume.get('version') != 'jev_checkpoint_v2' or resume['job_id'] != job_id or resume['method'] != method or resume['config_digest'] != digest(config) or resume['task_digest'] != digest(task):
            raise JevSelectError('checkpoint_identity_changed')
        replay_selector = selector.for_replay() if hasattr(selector, 'for_replay') else selector
        prefix = _run_episode_v2(task, replay_selector, config, job_id=job_id, method=method,
                                 event_limit=len(resume['events']), expected_events=resume['events'])
        rebuilt = prefix['checkpoint']
        if resume['phase'] == 'READY':
            normalized = copy.deepcopy(resume)
            if normalized['reason'] is None and rebuilt['reason'] == 'ALL_ITEMS_PLACED' and normalized['state']['end_of_stream'] and not normalized['state']['pending_items']:
                normalized['reason'] = 'ALL_ITEMS_PLACED'
            if semantic_record(rebuilt) != semantic_record(normalized):
                raise JevSelectError('checkpoint_changed')
        elif resume['phase'] == 'COMMITTED':
            event = resume['pending_event']
            if event is None or event['event'] != 'PLACE' or event['before'] != rebuilt['state'] or event['after'] != resume['state'] or event['business_after'] is not None or event['reference_after'] is not None:
                raise JevSelectError('invalid_committed_checkpoint')
            if resume['cursor'] != rebuilt['cursor'] or resume['decision'] != rebuilt['decision'] or resume['events'] != rebuilt['events']:
                raise JevSelectError('committed_prefix_changed')
            did = f'{job_id}_D{rebuilt["decision"]:04d}'
            req, policy, bundle, context = decision_inputs(rebuilt['state'],task,config,job_id,did)
            if event['decision_id'] != did or event['observation'] != req or event['bundle'] != bundle.data or event['context'] != context.data:
                raise JevSelectError('committed_decision_changed')
            if decision_route(bundle) == 'SINGLETON_BYPASS':
                selected = result(context,status='singleton',source='singleton',label='C01')
            else:
                if hasattr(replay_selector,'bind_public'): replay_selector.bind_public(req,policy,bundle)
                selected = replay_selector.select(context,decision_id=did)
            if selected.data != event['selection']:
                raise JevSelectError('committed_selection_changed')
            original = resolve_display_id(context,selected.data['selected_display_id'],req,bundle,config)
            expected_action = action_for(req,bundle.data['physical_candidates'],original)
            if event['action'] != expected_action or event['proposed_action'] != expected_action:
                raise JevSelectError('committed_action_changed')
            # Pure reconstruction on the prefix copy; the durable state below is not submitted again.
            after = commit_physical(rebuilt['state'],task['regions'],req,bundle,context,selected,config)
            if after != resume['state']:
                raise JevSelectError('committed_state_changed')
        else:
            raise JevSelectError('invalid_checkpoint_phase')
        state = copy.deepcopy(resume['state']); cursor = resume['cursor']; decision = resume['decision']
        events = copy.deepcopy(resume['events']); reason = resume['reason']
        phase = resume['phase']; pending = copy.deepcopy(resume['pending_event'])
        if pending is not None:
            reason = None  # Re-evaluate already committed state after a recoverable evaluation failure.

    while (reason is None or pending is not None) and (event_limit is None or len(events) < event_limit):
        invariant(state)
        if pending is not None:
            started = time.perf_counter()
            try:
                business = evaluate_committed_state(state,task['reference_policy'],task['regions'])
            except (ValueError,KeyError,TypeError) as exc:
                reason = 'EVALUATION_ERROR'
                pending['error'] = {'code': 'EVALUATION_ERROR', 'detail': str(exc)[:240]}
                persist()
                if hook: hook('evaluation_failure', checkpoint())
                return {'job_id':job_id,'events':events,'final_state':state,'summary':None,'checkpoint':checkpoint()}
            pending['business_after'] = business
            pending['reference_after'] = business['raw']
            pending['error'] = None
            pending['timings']['independent_evaluation_s'] = time.perf_counter()-started
            pending['timings']['decision_wall_s'] = None if decision_started is None else time.perf_counter()-decision_started
            pending['timings']['decision_segments_s'] = sum(pending['timings'].get(k,0.) for k in (
                'public_parse_s','physical_generation_s','facts_context_s','public_business_s','selection_s','physical_commit_s','independent_evaluation_s','checkpoint_io_s'))
            pending['reason'] = None
            decision += 1
            append(pending)
            continue
        before = copy.deepcopy(state)
        if can_wait(state):
            if cursor < len(task['items']):
                item = task['items'][cursor]
                state = receive(state,item,task['attributes'][item['item_id']]); cursor += 1
                kind = 'WAIT_RECEIVE'
            else:
                state = receive(state,eos=True); kind = 'EOS'
            append({'event':kind,'before':before,'after':copy.deepcopy(state),'timings':{}})
            continue
        if not state['pending_items']:
            reason = 'ALL_ITEMS_PLACED'; break
        if decision >= len(task['items'])+1:
            raise JevSelectError('decision_bound_exceeded')
        decision_started = time.perf_counter()
        did = f'{job_id}_D{decision:04d}'
        times = {'public_business_s':0.,'selection_s':0.,'physical_commit_s':0.,'independent_evaluation_s':0.,'checkpoint_io_s':0.}
        event = {'event':'STOP','decision_id':did,'before':before,'after':before,'route':None,
                 'observation':None,'bundle':None,'context':None,'selection':None,'proposed_action':None,'action':None,
                 'reason':None,'error':None,'reference_after':None,'business_after':None,'timings':times}
        try:
            req,policy,bundle,context = decision_inputs(state,task,config,job_id,did,timings=times)
            route = decision_route(bundle)
            event.update(route=route,observation=req,bundle=bundle.data,context=context.data)
            if hook: hook('decision_ready',event)
            if route == 'STOP_NO_PHYSICAL_CANDIDATE':
                reason = route
            else:
                start = time.perf_counter()
                if route == 'SINGLETON_BYPASS':
                    selection = result(context,status='singleton',source='singleton',label='C01')
                else:
                    public_bind(req,policy,bundle)
                    selection = selector.select(context,decision_id=did)
                elapsed = time.perf_counter()-start
                if method == 'shared_business_lexicographic': times['public_business_s'] = elapsed
                else: times['selection_s'] = elapsed
                event['selection'] = selection.data
                if selection.data['status'] not in ('selected','singleton'):
                    reason = selection.data['status'].upper()
                else:
                    chosen = resolve_display_id(context,selection.data['selected_display_id'],req,bundle,config)
                    action = action_for(req,bundle.data['physical_candidates'],chosen)
                    event['proposed_action'] = action
                    if hook: hook('before_commit',event)
                    start = time.perf_counter()
                    state = commit_physical(state,task['regions'],req,bundle,context,selection,config)
                    times['physical_commit_s'] = time.perf_counter()-start
                    event.update(event='PLACE',action=action,after=copy.deepcopy(state))
                    pending = event; phase = 'COMMITTED'
                    start = time.perf_counter(); persist(); times['checkpoint_io_s'] = time.perf_counter()-start
                    if hook: hook('after_commit_checkpoint',checkpoint())
                    continue
        except (ValueError,KeyError,TypeError) as exc:
            # Reconstruction failures are evidence corruption, not a normal experiment outcome.
            if replaying: raise
            reason = getattr(exc,'code','DECISION_ERROR')
            event['event'] = 'COMMIT_FAILURE' if event['proposed_action'] else 'DECISION_FAILURE'
            event['error'] = {'code':reason,'detail':str(exc)[:240]}
            if state != before:
                raise JevSelectError('failure_mutated_state') from exc
        event['reason'] = reason
        started = time.perf_counter()
        business = evaluate_committed_state(state,task['reference_policy'],task['regions'])
        event['business_after'] = business; event['reference_after'] = business['raw']
        times['independent_evaluation_s'] = time.perf_counter()-started
        times['decision_wall_s'] = time.perf_counter()-decision_started
        times['decision_segments_s'] = sum(times.get(k,0.) for k in ('public_parse_s','physical_generation_s','facts_context_s','public_business_s','selection_s','physical_commit_s','independent_evaluation_s','checkpoint_io_s'))
        decision += 1; append(event)
    if reason is None and state['end_of_stream'] and not state['pending_items']:
        reason = 'ALL_ITEMS_PLACED'
    summary = summarize_v2(task,config,method,state,events,reason) if reason is not None else None
    return {'job_id':job_id,'events':events,'final_state':state,'summary':summary,'checkpoint':checkpoint()}
