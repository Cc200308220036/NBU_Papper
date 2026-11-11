"""Fill-then-plan direct-selection simulator. Checkpoints own durable state."""
from __future__ import annotations
from .packaging_versions import EXACT_VERSION

import copy
import time

from semantic_pallet_planner.o4.buffer.buffer_state import initial, receive, can_wait, invariant
from semantic_pallet_planner.o4.extensions.e2.protocol import observation
from semantic_pallet_planner.o4.extensions.e2.planning import action_for, commit

from .candidates import CandidateProvider, PublicBusinessGuard, decision_route
from .config import generator_config, is_v2, is_v3, business_evaluation_mode, protocol_suffix
from .context import ContextBuilder, resolve_display_id
from .contracts import JevSelectError, digest
from .packaging_driven import is_driven
from .evaluation import feedback, summarize
from .selector import bind_decision, result


def decision_inputs(state, task, config, job_id, decision_id, *, timings=None, memory_snapshot=None, saved_retrieval=None, memory_view=None, memory_driver=None):
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
    try:
        pilot_receipt=None
        if is_driven(config):
            from .packaging_runtime import public_facts
            if memory_driver is None or memory_driver.config!=config or memory_view is not None:
                raise JevSelectError('pilot_missing_or_changed_public_driver')
            _,public_state,public_criteria,_,_=public_facts(config,req,bundle,policy)
            memory_view,pilot_receipt=memory_driver.resolve(public_state,public_criteria)
        context = bind_decision(ContextBuilder(config).build(req, bundle, policy, memories=memory_snapshot, retrieval=saved_retrieval, memory_view=memory_view, retrieval_receipt=pilot_receipt), job_id, decision_id, config=config)
    except JevSelectError as exc:
        if hasattr(exc,'context'):
            exc.context=bind_decision(exc.context,job_id,decision_id)
            exc.observation=req;exc.bundle=bundle
        raise
    if timings is not None:
        timings.update(public_parse_s=parsed-started, physical_generation_s=generated-parsed,
                       facts_context_s=time.perf_counter()-generated,
                       generation_cache_hits=after_cache.hits-before_cache.hits,
                       generation_cache_misses=after_cache.misses-before_cache.misses)
    return req, policy, bundle, context


def run_episode(task, selector, config, *, job_id, method, resume=None, on_checkpoint=None,
                hook=None, event_limit=None, expected_events=None, memory_snapshot=None, training_fork=None, memory_view=None, memory_driver=None):
    from .packaging_runtime import is_packaging, DATA_VERSION, METHODS
    if memory_driver is not None and not is_driven(config):
        raise JevSelectError('pilot_driver_protocol_incompatible')
    if config.get('version') in ('jev_packaging_monitored_v5','jev_packaging_remote_v6','jev_packaging_memory_v7','jev_packaging_contrast_v8','jev_packaging_memory_orders_v9','jev_packaging_evaluation_v10','jev_packaging_synthetic_v11', EXACT_VERSION):
        config = copy.deepcopy(config)
    if is_packaging(config):
        if config.get('version') == 'jev_packaging_remote_v6':
            from .packaging_remote import REGISTRY
            METHODS = tuple(REGISTRY)
        if is_driven(config):
            from .packaging_pilot_protocol import METHODS
            if config['version'] in ('jev_packaging_evaluation_v10','jev_packaging_synthetic_v11', EXACT_VERSION):
                from .packaging_evaluation_protocol import METHODS
            if memory_view is not None:raise JevSelectError('pilot_requires_per_decision_driver')
        elif config.get('version') in ('jev_packaging_memory_v7','jev_packaging_contrast_v8'):
            from .packaging_memory_protocol import memory_interface
            interface=memory_interface(config['version'])
            METHODS=(interface.METHOD,)
            if memory_view is not None:interface.validate_view(memory_view,config['memory_snapshot_digest'])
        elif memory_view is not None:
            raise JevSelectError('packaging_memory_protocol_incompatible')
        if (memory_snapshot is not None or task.get('version') not in ((DATA_VERSION,'jev_evaluation_packaging_task_v1') if config['version'] in ('jev_packaging_evaluation_v10','jev_packaging_synthetic_v11', EXACT_VERSION) else (DATA_VERSION,)) or
            task.get('reference_policy') != {'version':DATA_VERSION,'rules':[]} or
            task.get('regions') != [] or method != config['selector'] or method not in METHODS or
            config['runtime_identity']['task_identity'] != digest(task)):
            raise JevSelectError('packaging_episode_binding_or_memory_mismatch')
    if business_evaluation_mode(config):
        return _run_episode_v2(task, selector, config, job_id=job_id, method=method, resume=resume,
                               on_checkpoint=on_checkpoint, hook=hook, event_limit=event_limit,
                               expected_events=expected_events, memory_snapshot=memory_snapshot, training_fork=training_fork, memory_view=memory_view, memory_driver=memory_driver)
    if training_fork is not None:
        raise JevSelectError('training_fork_requires_monitored_packaging')
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
            if is_driven(config) and pending is not None and phase=='DECISION_READY':
                event=copy.deepcopy(pending);times=event['timings']
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
                    on_checkpoint=None, hook=None, event_limit=None, expected_events=None, memory_snapshot=None, training_fork=None, memory_view=None, memory_driver=None):
    from .evaluation import evaluate_committed_state, summarize_v2
    from .execution import commit_physical
    from .selector import SelectionResult
    state = initial(task['container'], config['buffer_capacity'])
    cursor = decision = 0
    events = []; reason = None; pending = None; phase = 'READY'
    replaying = expected_events is not None
    decision_started = None

    from .stability.monitor import is_monitored, preflight, seal_checkpoint, validate_checkpoint
    monitored = is_monitored(config)
    if monitored:
        preflight(config)
    suffix = protocol_suffix(config)
    if is_v3(config):
        from .memory_store import empty_snapshot, validate_snapshot
        memory_snapshot = empty_snapshot() if memory_snapshot is None else memory_snapshot
        validate_snapshot(memory_snapshot, config['memory_snapshot_digest'])
        if config['selector']!=method:raise JevSelectError('episode_method_mismatch')
        from .memory_retrieval import snapshot_index,mode_index
        frozen_index=snapshot_index(memory_snapshot)
        memory_identity={'corpus_digest':memory_snapshot.data['corpus_digest'],'index_digest':digest(frozen_index),
            'mode_index_digest':digest(mode_index(frozen_index,config['memory_mode'])),
            'retrieval_config_digest':frozen_index['config_digest'],'memory_mode':config['memory_mode'],
            'retrieval_version':config['retrieval_version']}

    def checkpoint():
        value = {'version': 'jev_checkpoint_' + suffix, 'job_id': job_id, 'method': method,
                'task_digest': digest(task), 'config_digest': digest(config),
                'state': copy.deepcopy(state), 'cursor': cursor, 'decision': decision,
                'events': copy.deepcopy(events), 'reason': reason, 'phase': phase,
                'pending_event': copy.deepcopy(pending)}
        from .contracts import validate_schema
        from .packaging_runtime import is_packaging
        if is_packaging(config):
            value['runtime_identity'] = copy.deepcopy(config['runtime_identity'])
        if is_v3(config):
            value['memory_snapshot_digest'] = digest(memory_snapshot.data)
            value['memory_identity']=memory_identity
        if monitored:
            seal_checkpoint(value)
        validate_schema('checkpoint_' + suffix,value)
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
        events.append(event); pending = None; phase = 'TERMINATED' if monitored and reason is not None else 'READY'
        cp = persist()
        if hook: hook('after_checkpoint', cp)

    def public_bind(req, policy, bundle):
        if hasattr(selector, 'bind_public'):
            selector.bind_public(req, policy, bundle)

    from .packaging_versions import JM_FORK_PROTOCOLS, JM_CONTINUATION_PROTOCOLS
    jm_continuation = training_fork is not None and training_fork.get('version') in JM_CONTINUATION_PROTOCOLS
    jm_first = training_fork is not None and training_fork.get('version') in JM_FORK_PROTOCOLS
    if training_fork is not None:
        if jm_continuation:
            from .packaging_jev_continuation import validate_route
            from .packaging_jev_forks import bootstrap
            if resume is not None or expected_events is not None or not callable(on_checkpoint):
                raise JevSelectError('jm_A2_resume_not_implemented_A3')
            validate_route(training_fork, task, config, job_id, selector)
            resume = bootstrap(training_fork['binding'], task, config, job_id)
            on_checkpoint(copy.deepcopy(resume))
        elif jm_first:
            from .packaging_jev_forks import bootstrap, UnimplementedContinuation
            if resume is not None:
                raise JevSelectError('jm_resume_not_implemented_A3')
            if not isinstance(selector, UnimplementedContinuation) or not callable(on_checkpoint):
                raise JevSelectError('jm_A1_requires_stop_boundary_and_persistence')
            resume = bootstrap(training_fork, task, config, job_id)
            # Durable forced selection precedes any monitor or commit dispatch.
            on_checkpoint(copy.deepcopy(resume))
        else:
            from .packaging_counterfactual import bootstrap, validate_branch_checkpoint
            seed = bootstrap(training_fork, task, config, job_id)
            if resume is None:
                resume = seed
            validate_branch_checkpoint(resume, task, config, job_id, training_fork)

    if resume is not None:
        from .contracts import validate_schema
        validate_schema('checkpoint_' + suffix,resume)
        from .packaging_runtime import is_packaging
        if is_packaging(config) and resume['runtime_identity'] != config['runtime_identity']:
            raise JevSelectError('packaging_checkpoint_identity_changed')
        if is_v3(config) and resume['memory_snapshot_digest'] != digest(memory_snapshot.data):
            raise JevSelectError('checkpoint_memory_changed')
        if is_v3(config) and resume.get('memory_identity',memory_identity)!=memory_identity:
            raise JevSelectError('checkpoint_memory_identity_changed')
        if resume.get('version') != 'jev_checkpoint_' + suffix or resume['job_id'] != job_id or resume['method'] != method or resume['config_digest'] != digest(config) or resume['task_digest'] != digest(task):
            raise JevSelectError('checkpoint_identity_changed')
        if monitored:
            if training_fork is None:
                validate_checkpoint(resume,task,config,job_id,method)
        else:
            replay_selector = selector.for_replay() if hasattr(selector, 'for_replay') else selector
            prefix = _run_episode_v2(task, replay_selector, config, job_id=job_id, method=method,
                                     event_limit=len(resume['events']), expected_events=resume['events'], memory_snapshot=memory_snapshot)
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
                req, policy, bundle, context = decision_inputs(rebuilt['state'],task,config,job_id,did,memory_snapshot=memory_snapshot,saved_retrieval=event['context'].get('retrieval'))
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
            elif resume['phase']=='DECISION_READY' and is_v3(config):
                event=resume['pending_event'];did=f'{job_id}_D{rebuilt["decision"]:04d}'
                if (resume['cursor']!=rebuilt['cursor'] or resume['decision']!=rebuilt['decision'] or
                    resume['state']!=rebuilt['state'] or semantic_record(resume['events'])!=semantic_record(rebuilt['events']) or
                    event is None or event['event']!='STOP' or event['before']!=rebuilt['state'] or event['after']!=rebuilt['state'] or
                    any(event[k] is not None for k in ('selection','action','proposed_action','reason','error','business_after','reference_after'))):
                    raise JevSelectError('invalid_pending_decision')
                req,policy,bundle,context=decision_inputs(rebuilt['state'],task,config,job_id,did,
                    memory_snapshot=memory_snapshot,saved_retrieval=event['context']['retrieval'])
                if event['decision_id']!=did or event['observation']!=req or event['bundle']!=bundle.data or event['context']!=context.data:
                    raise JevSelectError('pending_decision_changed')
            else:
                raise JevSelectError('invalid_checkpoint_phase')
        state = copy.deepcopy(resume['state']); cursor = resume['cursor']; decision = resume['decision']
        events = copy.deepcopy(resume['events']); reason = resume['reason']
        phase = resume['phase']; pending = copy.deepcopy(resume['pending_event'])
        if pending is not None and (not monitored or phase == 'COMMITTED'):
            reason = None  # Re-evaluate already committed state after a recoverable evaluation failure.

    while (reason is None or pending is not None) and (event_limit is None or len(events) < event_limit):
        invariant(state)
        if pending is not None and phase=='COMMITTED':
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
            if jm_first:
                from .packaging_jev_forks import STOP
                reason = STOP
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
        if monitored:
            event['monitor'] = None
            event['monitor_result_reuses'] = 0
        try:
            saved_context = (pending['context'] if pending is not None and phase=='DECISION_READY' else
                expected_events[len(events)].get('context') if expected_events is not None and len(events)<len(expected_events) else None)
            if monitored and pending is not None and phase in (('DECISION_READY','SELECTED','MONITORED') if is_driven(config) else ('SELECTED','MONITORED')):
                from .contracts import CandidateBundle, DecisionContext
                from .packaging_runtime import no_policy
                req = copy.deepcopy(pending['observation'])
                policy = no_policy(req)
                bundle = CandidateBundle.from_dict(pending['bundle'])
                context = DecisionContext.from_dict(pending['context'])
            else:
                req,policy,bundle,context = decision_inputs(state,task,config,job_id,did,timings=times,memory_snapshot=memory_snapshot,
                    saved_retrieval=saved_context.get('retrieval') if saved_context else None,memory_view=memory_view,memory_driver=memory_driver)
            if is_driven(config) and pending is not None and phase=='DECISION_READY':
                event=copy.deepcopy(pending);times=event['timings']
            route = decision_route(bundle)
            event.update(route=route,observation=req,bundle=bundle.data,context=context.data)
            if is_v3(config) or (is_driven(config) and (pending is None or phase=='DECISION_READY')):
                pending=copy.deepcopy(event);phase='DECISION_READY';persist()
            if hook: hook('decision_ready',event)
            if route == 'STOP_NO_PHYSICAL_CANDIDATE':
                reason = route
            else:
                start = time.perf_counter()
                recovering = monitored and pending is not None and phase in ('SELECTED','MONITORED')
                if recovering:
                    event = copy.deepcopy(pending)
                    times = event['timings']
                    selection = SelectionResult.from_dict(event['selection'])
                elif route == 'SINGLETON_BYPASS':
                    selection = result(context,status='singleton',source='singleton',label='C01')
                else:
                    public_bind(req,policy,bundle)
                    selection = selector.select(context,decision_id=did)
                elapsed = time.perf_counter()-start
                if not recovering:
                    if method == 'shared_business_lexicographic': times['public_business_s'] = elapsed
                    else: times['selection_s'] = elapsed
                event['selection'] = selection.data
                if selection.data['status'] not in ('selected','singleton'):
                    reason = selection.data['status'].upper()
                else:
                    chosen = resolve_display_id(context,selection.data['selected_display_id'],req,bundle,config)
                    action = action_for(req,bundle.data['physical_candidates'],chosen)
                    event['proposed_action'] = action
                    if monitored:
                        from .stability.monitor import monitor_selected_action, validate_monitor, TERMINATIONS
                        if not recovering:
                            pending = copy.deepcopy(event); phase = 'SELECTED'; persist()
                            if hook: hook('after_selected_checkpoint',checkpoint())
                        if event['monitor'] is None:
                            event['monitor'] = monitor_selected_action(state,chosen,event,config)
                            pending = copy.deepcopy(event); phase = 'MONITORED'; persist()
                            if hook: hook('after_monitored_checkpoint',checkpoint())
                        else:
                            validate_monitor(event['monitor'],state,chosen,event,config)
                            event['monitor_result_reuses'] += 1
                        if (jm_first or jm_continuation) and event['monitor']['status'] not in ('STABLE','UNSTABLE','UNASSESSABLE','ERROR'):
                            raise JevSelectError('jm_monitor_status_not_authorized')
                        reason = TERMINATIONS.get(event['monitor']['status'])
                    if reason is None:
                        if hook: hook('before_commit',event)
                        start = time.perf_counter()
                        state = commit_physical(state,task['regions'],req,bundle,context,selection,config,
                            **({'monitor':event['monitor'],'monitor_event':event} if monitored else {}))
                    else:
                        # The selected attempted action remains in the buffer.
                        event['reason'] = reason

                    if reason is None:
                        times['physical_commit_s'] = time.perf_counter()-start
                        event.update(event='PLACE',action=action,after=copy.deepcopy(state))
                        pending = event; phase = 'COMMITTED'
                        start = time.perf_counter(); committed_cp = persist(); times['checkpoint_io_s'] = time.perf_counter()-start
                        if hook: hook('after_commit_checkpoint',committed_cp)
                        continue
        except (ValueError,KeyError,TypeError) as exc:
            # Reconstruction failures are evidence corruption, not a normal experiment outcome.
            if replaying: raise
            reason = getattr(exc,'code','DECISION_ERROR')
            if hasattr(exc,'context'):
                event.update(observation=exc.observation,bundle=exc.bundle.data,context=exc.context.data,route=decision_route(exc.bundle))
                if hook:hook('decision_ready',event)
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
    if monitored and reason is not None:
        phase = 'TERMINATED'
        persist()
    summary = summarize_v2(task,config,method,state,events,reason) if reason is not None else None
    if summary is not None and is_v3(config):
        from .memory_retrieval import memory_statistics
        summary.update(version='jev_order_metrics_v3', memory_snapshot_digest=digest(memory_snapshot.data),memory_statistics=memory_statistics(events))
    return {'job_id':job_id,'events':events,'final_state':state,'summary':summary,'checkpoint':checkpoint()}
