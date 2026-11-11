"""Versioned physical-only commit; public business requirements cannot reject it."""
from __future__ import annotations

from semantic_pallet_planner.o4.buffer.buffer_state import physical, place
from semantic_pallet_planner.o4.extensions.e2.protocol import observation as rebuild_observation
from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate

from .candidates import validate_bundle
from .config import business_evaluation_mode, protocol_suffix
from .context import resolve_display_id, validate_context
from .contracts import JevSelectError, digest, validate_schema


def commit_physical(state, regions, observation, bundle, context, selection, config, *, monitor=None, monitor_event=None):
    validate_schema("config", config)
    if not business_evaluation_mode(config):
        raise JevSelectError("physical_commit_requires_v2")
    if observation != rebuild_observation(state, observation["instruction_text"], regions):
        raise JevSelectError("stale_physical_commit")
    value = validate_bundle(observation, bundle)
    validate_context(context, observation, bundle, config)
    selected = selection.data
    validate_schema("selection_result", selected)
    jm_forced = selected['version'] == 'jev_jm_forced_selection_v1'
    if jm_forced:
        if monitor_event is None or monitor_event['selection'] != selected:
            raise JevSelectError('jm_missing_forced_monitor_event')
    elif selected["version"] != f"jev_selection_result_{protocol_suffix(config)}" or selected["status"] not in ("selected", "singleton"):
        raise JevSelectError("invalid_physical_selection")
    if (context.data["route"] == "SINGLETON_BYPASS") != (selected["status"] == "singleton"):
        raise JevSelectError("selection_route_mismatch")
    if selected["local_binding_digest"] != digest(context.data["local_binding"]):
        raise JevSelectError("stale_selection")
    candidate = resolve_display_id(context, selected["selected_display_id"], observation, bundle, config)
    if candidate["candidate_id"] != selected["selected_candidate_id"]:
        raise JevSelectError("selection_candidate_mismatch")
    if jm_forced:
        from .packaging_jev_forks import validate_forced_selection
        validate_forced_selection(selected, context, candidate, config)
        if monitor is None or monitor['status'] != 'STABLE':
            raise JevSelectError('jm_monitor_commit_not_stable')
    from .stability.monitor import is_monitored, validate_monitor
    if is_monitored(config):
        if monitor is None or monitor_event is None:
            raise JevSelectError('missing_monitor_credential')
        validate_monitor(monitor,state,candidate,monitor_event,config,require_stable=True)
    errors = check_candidate(physical(state, candidate["pick_item_id"]), {"container": state["container"]}, candidate)
    if errors:
        raise JevSelectError("physical_rejection", ",".join(errors))
    # This deliberately does not call E2's business-gated commit or clear any policy.
    return place(state, candidate)
