"""Fill-then-plan direct-selection simulator. Checkpoints own durable state."""
from __future__ import annotations

import copy

from semantic_pallet_planner.o4.buffer.buffer_state import initial, receive, can_wait, invariant
from semantic_pallet_planner.o4.extensions.e2.protocol import observation
from semantic_pallet_planner.o4.extensions.e2.planning import action_for, commit

from .candidates import CandidateProvider, PublicBusinessGuard, decision_route
from .config import generator_config
from .context import ContextBuilder, resolve_display_id
from .contracts import JevSelectError, digest
from .evaluation import feedback, summarize
from .selector import bind_decision, result


def decision_inputs(state, task, config, job_id, decision_id):
    req = observation(state, task["instruction_text"], task["regions"])
    guard = PublicBusinessGuard()
    policy = guard.resolve(req)
    bundle = guard.filter(req, policy, CandidateProvider().build(state, req, generator_config()), config)
    context = bind_decision(ContextBuilder(config).build(req, bundle, policy), job_id, decision_id)
    return req, policy, bundle, context


def run_episode(task, selector, config, *, job_id, method, resume=None, on_checkpoint=None,
                hook=None, event_limit=None, expected_events=None):
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
