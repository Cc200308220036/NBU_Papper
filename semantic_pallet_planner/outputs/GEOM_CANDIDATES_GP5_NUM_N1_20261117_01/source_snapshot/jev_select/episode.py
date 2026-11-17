"""Fill-then-plan direct-selection simulator. Checkpoints own durable state."""
from __future__ import annotations
from .packaging_versions import GEOMETRY_ORDER_CONFIGS, GEOMETRY_NATIVE_VERSION
from .packaging_versions import GEOMETRY_CONFIGS, GEOMETRY_RUN_VERSION, GEOMETRY_ORDER_VERSION, GEOMETRY_EXECUTABLE_CONFIGS
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


def decision_inputs(state, task, config, job_id, decision_id, *, timings=None, memory_snapshot=None, saved_retrieval=None, memory_view=None, memory_driver=None, geometry_store=None):
    from .packaging_versions import GEOMETRY_VERSION
    if config.get('version') in GEOMETRY_CONFIGS:
        if any(v is not None for v in (memory_snapshot,saved_retrieval,memory_view,memory_driver)):
            raise JevSelectError('geometry_memory_forbidden')
        return _geometry_decision_inputs(state,task,config,job_id,decision_id,timings=timings,geometry_store=geometry_store)
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
                hook=None, event_limit=None, expected_events=None, memory_snapshot=None, training_fork=None, memory_view=None, memory_driver=None, geometry_store=None):
    from .packaging_versions import reject_geometry_execution
    reject_geometry_execution(config,"run_episode")
    if config.get('version') in GEOMETRY_ORDER_CONFIGS and event_limit is not None:
        raise JevSelectError('geometry_order_no_event_limit')
    if config.get('version') in GEOMETRY_EXECUTABLE_CONFIGS:
        if any(v is not None for v in (expected_events,memory_snapshot,training_fork,memory_view,memory_driver)):
            raise JevSelectError('geometry_run_unsupported_combination')
        from .geometry_execution import validate_run_request
        validate_run_request(task,selector,config,method,geometry_store,on_checkpoint,job_id=job_id)
        return _run_episode_v2(task,selector,config,job_id=job_id,method=method,resume=resume,
            on_checkpoint=on_checkpoint,hook=hook,event_limit=event_limit,geometry_store=geometry_store)
    from .packaging_runtime import is_packaging, DATA_VERSION, METHODS
    if config.get('version')=='jev_packaging_jm_no_memory_v13' and (training_fork is None or training_fork.get('version')!='jev_jm_v13_execution_v1'):
        raise JevSelectError('jm13_explicit_execution_route_required')
    if memory_driver is not None and not is_driven(config):
        raise JevSelectError('pilot_driver_protocol_incompatible')
    if config.get('version') in ('jev_packaging_jm_no_memory_v13','jev_packaging_monitored_v5','jev_packaging_remote_v6','jev_packaging_memory_v7','jev_packaging_contrast_v8','jev_packaging_memory_orders_v9','jev_packaging_evaluation_v10','jev_packaging_synthetic_v11', EXACT_VERSION):
        config = copy.deepcopy(config)
    if is_packaging(config):
        if config.get('version') in ('jev_packaging_remote_v6','jev_packaging_jm_no_memory_v13'):
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
                    on_checkpoint=None, hook=None, event_limit=None, expected_events=None, memory_snapshot=None, training_fork=None, memory_view=None, memory_driver=None, geometry_store=None):
    from .packaging_versions import reject_geometry_execution
    reject_geometry_execution(config,"_run_episode_v2")
    if config.get('version') in GEOMETRY_ORDER_CONFIGS and event_limit is not None:
        raise JevSelectError('geometry_order_no_event_limit')
    from .evaluation import evaluate_committed_state, summarize_v2
    from .execution import commit_physical
    from .selector import SelectionResult
    from .geometry_order_accounting import tick as order_tick
    geometry_run=config.get('version') in GEOMETRY_EXECUTABLE_CONFIGS
    if geometry_run:
        from .geometry_execution import validate_run_request
        if any(v is not None for v in (expected_events,training_fork,memory_snapshot,memory_view,memory_driver)):
            raise JevSelectError('geometry_run_unsupported_combination')
        geometry_execution_binding=validate_run_request(task,selector,config,method,geometry_store,on_checkpoint,job_id=job_id)
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
        if geometry_run:
            value['execution_binding']=copy.deepcopy(geometry_execution_binding)
        if monitored:
            seal_checkpoint(value)
        if jm_recovery:
            value['version'] = 'jev_jm_recovery_checkpoint_v1'
            seal_checkpoint(value)
        validate_schema('jm_recovery_checkpoint_v1' if jm_recovery else 'checkpoint_' + suffix,value)
        return value

    def persist():
        cp = checkpoint()
        if geometry_run:geometry_store.save_checkpoint(cp)
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

    from .packaging_versions import JM_FORK_PROTOCOLS, JM_CONTINUATION_PROTOCOLS, JM_RECOVERY_PROTOCOLS
    jm_v13 = training_fork is not None and training_fork.get('version') == 'jev_jm_v13_execution_v1'
    jm_recovery = training_fork is not None and training_fork.get('version') in JM_RECOVERY_PROTOCOLS
    jm_continuation = training_fork is not None and training_fork.get('version') in JM_CONTINUATION_PROTOCOLS
    jm_first = training_fork is not None and training_fork.get('version') in JM_FORK_PROTOCOLS
    if training_fork is not None:
        if jm_v13:
            from .packaging_jev_v13 import validate_route, validate_saved_checkpoint
            if expected_events is not None or resume is None or not callable(on_checkpoint):
                raise JevSelectError('jm_v13_durable_resume_required')
            validate_route(training_fork,task,config,job_id,selector)
            validate_saved_checkpoint(resume,training_fork)
        elif jm_recovery:
            from .packaging_jev_recovery import validate_route, validate_saved_checkpoint
            if expected_events is not None or resume is None or not callable(on_checkpoint):
                raise JevSelectError('jm_A3_saved_resume_required')
            validate_route(training_fork, task, config, job_id, selector)
            validate_saved_checkpoint(resume, training_fork)
        elif jm_continuation:
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
        validate_schema('jm_recovery_checkpoint_v1' if jm_recovery else 'checkpoint_' + suffix,resume)
        from .packaging_runtime import is_packaging
        if is_packaging(config) and resume['runtime_identity'] != config['runtime_identity']:
            raise JevSelectError('packaging_checkpoint_identity_changed')
        if is_v3(config) and resume['memory_snapshot_digest'] != digest(memory_snapshot.data):
            raise JevSelectError('checkpoint_memory_changed')
        if is_v3(config) and resume.get('memory_identity',memory_identity)!=memory_identity:
            raise JevSelectError('checkpoint_memory_identity_changed')
        if resume.get('version') != ('jev_jm_recovery_checkpoint_v1' if jm_recovery else 'jev_checkpoint_' + suffix) or resume['job_id'] != job_id or resume['method'] != method or resume['config_digest'] != digest(config) or resume['task_digest'] != digest(task):
            raise JevSelectError('checkpoint_identity_changed')
        if monitored:
            if training_fork is None:
                if geometry_run:
                    from .geometry_execution import validate_saved_checkpoint
                    validate_saved_checkpoint(resume,task,config,job_id,method,geometry_store)
                else:validate_checkpoint(resume,task,config,job_id,method)
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
        if geometry_run:
            event['geometry_ref']=None
            geometry_store.input_ref=None
        if monitored:
            event['monitor'] = None
            event['monitor_result_reuses'] = 0
        try:
            saved_context = (pending['context'] if pending is not None and phase=='DECISION_READY' else
                expected_events[len(events)].get('context') if expected_events is not None and len(events)<len(expected_events) else None)
            if monitored and pending is not None and phase in (('DECISION_READY','SELECTED','MONITORED') if is_driven(config) or jm_recovery or jm_v13 or geometry_run else ('SELECTED','MONITORED')):
                from .contracts import CandidateBundle, DecisionContext
                from .packaging_runtime import no_policy
                req = copy.deepcopy(pending['observation'])
                policy = no_policy(req)
                bundle = geometry_store.load_event(pending,config) if geometry_run else CandidateBundle.from_dict(pending['bundle'])
                context = DecisionContext.from_dict(pending['context'])
            else:
                req,policy,bundle,context = decision_inputs(state,task,config,job_id,did,timings=times,memory_snapshot=memory_snapshot,
                    saved_retrieval=saved_context.get('retrieval') if saved_context else None,memory_view=memory_view,memory_driver=memory_driver,geometry_store=geometry_store)
            if is_driven(config) and pending is not None and phase=='DECISION_READY':
                event=copy.deepcopy(pending);times=event['timings']
            if geometry_run:
                event['geometry_ref']=pending['geometry_ref'] if pending is not None else geometry_store.save_event(bundle)
            route = decision_route(bundle)
            event.update(route=route,observation=req,bundle=bundle.data,context=context.data)
            if ((jm_recovery or jm_v13 or geometry_run) and (pending is None or phase=='DECISION_READY')) or is_v3(config) or (is_driven(config) and (pending is None or phase=='DECISION_READY')):
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
                    order_tick(config,'singleton_executions')
                    selection = result(context,status='singleton',source='singleton',label='C01')
                else:
                    public_bind(req,policy,bundle)
                    order_tick(config,'selector_calls')
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
                            order_tick(config,'monitor_entries')
                            event['monitor'] = monitor_selected_action(state,chosen,event,config)
                            pending = copy.deepcopy(event); phase = 'MONITORED'; persist()
                            if hook: hook('after_monitored_checkpoint',checkpoint())
                        else:
                            validate_monitor(event['monitor'],state,chosen,event,config)
                            order_tick(config,'monitor_reuses')
                            event['monitor_result_reuses'] += 1
                        if (jm_first or jm_continuation or jm_recovery or jm_v13) and event['monitor']['status'] not in ('STABLE','UNSTABLE','UNASSESSABLE','ERROR'):
                            raise JevSelectError('jm_monitor_status_not_authorized')
                        reason = ('GEOMETRY_MONITOR_DISABLED' if geometry_run and event['monitor']['status']=='DISABLED'
                                  else TERMINATIONS.get(event['monitor']['status']))
                    if reason is None:
                        if hook: hook('before_commit',event)
                        start = time.perf_counter()
                        order_tick(config,'commit_attempts')
                        state = commit_physical(state,task['regions'],req,bundle,context,selection,config,
                            **({'monitor':event['monitor'],'monitor_event':event} if monitored else {}),
                            **({'geometry_store':geometry_store,'execution_binding':geometry_execution_binding} if geometry_run else {}))
                    else:
                        # The selected attempted action remains in the buffer.
                        event['reason'] = reason

                    if reason is None:
                        order_tick(config,'commit_successes')
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
            if geometry_run and event['event']=='COMMIT_FAILURE' and (event['monitor'] or {}).get('status')=='STABLE':
                # Closed v15 stop category; original exception/code remains in detail.
                from .geometry_execution import COMMIT_TECHNICAL_ERROR
                reason=COMMIT_TECHNICAL_ERROR
            event['error'] = {'code':reason,'detail':str(exc)[:240]}
            if geometry_run and hasattr(exc,'audit'):
                event['geometry_ref']=geometry_store.put_json({'version':'geometry_generation_failure_v1','input':geometry_store.input_ref,'scope':exc.scope,'audit':exc.audit,'error':event['error']})
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


def _geometry_decision_inputs(state,task,config,job_id,decision_id,*,timings=None,geometry_store=None):
    """Shared geometry F0 construction; v15 first persists current input bytes."""
    from .config import generator_config_for
    started=time.perf_counter()
    req=observation(state,task['instruction_text'],task['regions'])
    guard=PublicBusinessGuard();policy=guard.resolve(req)
    parsed=time.perf_counter()
    common=None
    if config['version'] in GEOMETRY_EXECUTABLE_CONFIGS:
        if geometry_store is None:raise JevSelectError('geometry_durable_store_required')
        from .candidate_backends import capture_common_input
        common=capture_common_input(state,req,config)
        geometry_store.save_input(common)
    bundle=CandidateProvider().build(state,req,generator_config_for(config),config=config,common_input=common)
    generated=time.perf_counter()
    bundle=guard.filter(req,policy,bundle,config)
    context=bind_decision(ContextBuilder(config).build(req,bundle,policy),job_id,decision_id,config=config)
    if timings is not None:
        stats=bundle.telemetry
        timings.update(public_parse_s=parsed-started,physical_generation_s=generated-parsed,
            facts_context_s=time.perf_counter()-generated,generation_backend=stats['backend'],
            generation_cache_supported=stats['cache_supported'],generation_cache_hits=stats['cache_hits'],
            generation_cache_misses=stats['cache_misses'])
    return req,policy,bundle,context
