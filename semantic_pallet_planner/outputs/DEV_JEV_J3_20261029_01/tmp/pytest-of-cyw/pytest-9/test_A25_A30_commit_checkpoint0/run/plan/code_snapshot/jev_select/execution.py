"""Versioned physical-only commit; public business requirements cannot reject it."""
from __future__ import annotations

from semantic_pallet_planner.o4.buffer.buffer_state import physical, place
from semantic_pallet_planner.o4.extensions.e2.protocol import observation as rebuild_observation
from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate

from .candidates import validate_bundle
from .config import is_v2
from .context import resolve_display_id, validate_context
from .contracts import JevSelectError, digest, validate_schema


def commit_physical(state, regions, observation, bundle, context, selection, config):
    validate_schema("config", config)
    if not is_v2(config):
        raise JevSelectError("physical_commit_requires_v2")
    if observation != rebuild_observation(state, observation["instruction_text"], regions):
        raise JevSelectError("stale_physical_commit")
    value = validate_bundle(observation, bundle)
    validate_context(context, observation, bundle, config)
    selected = selection.data
    validate_schema("selection_result", selected)
    if selected["version"] != "jev_selection_result_v2" or selected["status"] not in ("selected", "singleton"):
        raise JevSelectError("invalid_physical_selection")
    if (context.data["route"] == "SINGLETON_BYPASS") != (selected["status"] == "singleton"):
        raise JevSelectError("selection_route_mismatch")
    if selected["local_binding_digest"] != digest(context.data["local_binding"]):
        raise JevSelectError("stale_selection")
    candidate = resolve_display_id(context, selected["selected_display_id"], observation, bundle, config)
    if candidate["candidate_id"] != selected["selected_candidate_id"]:
        raise JevSelectError("selection_candidate_mismatch")
    errors = check_candidate(physical(state, candidate["pick_item_id"]), {"container": state["container"]}, candidate)
    if errors:
        raise JevSelectError("physical_rejection", ",".join(errors))
    # This deliberately does not call E2's business-gated commit or clear any policy.
    return place(state, candidate)
