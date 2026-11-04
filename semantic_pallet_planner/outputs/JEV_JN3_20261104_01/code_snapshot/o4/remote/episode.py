"""O4-D rolling execution using frozen C/F planning and physical transitions.

Only the environment reads the arrival stream. Compilation receives public facts
before any reference evaluation. Single mode uses the original single schema;
buffer mode uses the full F state (including slots and EOS).
"""
from __future__ import annotations

import copy
import math
import time
from collections.abc import Callable

from ..buffer.buffer_baselines import choose
from ..buffer.buffer_candidates import pools, public_candidates
from ..buffer.buffer_evaluation import submit
from ..buffer.buffer_protocol import action, validate_action
from ..buffer.buffer_search import search
from ..buffer.buffer_state import (
    can_wait, initial, observation, physical, public_state, receive,
)
from ..common import O4Error
from ..compiler import parse_instruction, response_for
from ..evaluator import reference_state
from ..observation import build_observation
from ..visual.facts import unpack
from .evaluation import compilation_metrics
from .protocol import validate_response


BACKENDS = ("public_parser", "remote_text", "remote_image", "oracle_ast")
PLANNERS = ("single_greedy", "buffer_fifo", "buffer_heuristic", "buffer_search")


def compile_source(source: dict, backend: str, compiler=None,
                   oracle_policy: dict | None = None) -> tuple[dict | None, str, str | None]:
    """Remote branches never pass reference policies to the compiler."""
    obs, buffer = unpack(source)
    if backend in ("remote_text", "remote_image"):
        record = compiler.compile(source, "image" if backend == "remote_image" else "text")
        return record["response"], record["status"], record["compilation_id"]
    if backend == "public_parser":
        ast = parse_instruction(obs["instruction_text"])
    elif backend == "oracle_ast":
        ast = copy.deepcopy(oracle_policy)
    else:
        raise ValueError("unknown compilation backend")
    response = response_for(obs, ast)
    if buffer is not None:
        response.update(schema_version="o4_buffer_response_v1",
                        buffer_state_hash=buffer["buffer_state_hash"],
                        event_index=buffer["event_index"])
    validate_response(response, source)
    return response, "valid", None


def episode(scenario: dict, attributes: dict, task: dict, backend: str,
            planner: str, generator_config: dict, compiler=None,
            on_event: Callable[[dict], None] | None = None) -> tuple[dict, list[dict]]:
    if backend not in BACKENDS or planner not in PLANNERS:
        raise ValueError("unsupported backend/planner")
    capacity = 1 if planner == "single_greedy" else 3
    state = initial(scenario["container"], capacity)
    by_id = {item["item_id"]: item for item in scenario["items"]}
    cursor = 0
    events = []
    text = task["instruction_text"]
    while True:
        before = copy.deepcopy(state)
        public = public_state(state, text)
        event = {"event_index": state["event_index"], "before_public_state": public,
                 "response": None, "compilation_id": None, "compilation_metrics": None,
                 "action": None, "search_trace": None, "physical_errors": []}
        if can_wait(state):
            value = action(public, "WAIT_NEXT")
            validate_action(public, value)
            # Only this environment boundary reads the next actual arrival.
            identifier = scenario["arrival_order"][cursor] if cursor < len(scenario["arrival_order"]) else None
            state = receive(state, by_id[identifier] if identifier else None,
                            attributes[identifier] if identifier else None,
                            eos=identifier is None)
            cursor += int(identifier is not None)
            event.update(kind="WAIT_NEXT", status="received" if identifier else "eos",
                         action=value, received_id=identifier, received_eos=identifier is None)
        elif not state["pending_items"]:
            event.update(kind="STOP", status="all_items_placed")
        else:
            source = (build_observation(physical(state), state["attributes"], text)
                      if capacity == 1 else public)
            started = time.perf_counter()
            try:
                response, status, compilation_id = compile_source(
                    source, backend, compiler,
                    task["reference_policy"] if backend == "oracle_ast" else None,
                )
            except O4Error as exc:
                response, status, compilation_id = None, exc.code, None
            event.update(source=source, response=response, compilation_id=compilation_id)
            # No reference data can affect the chosen action or committed state.
            if response is None:
                event.update(kind="STOP", status=status)
                groups = None
                candidates = []
            else:
                ast = response["policy_ast"]
                groups, audit = pools(state, text, ast, generator_config)
                candidates = public_candidates(groups, public["buffer_state_hash"])
                if planner == "buffer_search":
                    chosen, reason, trace = search(state, text, ast, generator_config, groups, audit)
                else:
                    chosen, reason = choose(groups, planner)
                    trace = None
                event.update(root_pools=groups, root_audit=audit, candidates=candidates,
                             search_trace=trace)
                if chosen is None:
                    event.update(kind="STOP", status=reason)
                else:
                    value = action(public, "PLACE", pick=chosen["pick_item_id"],
                                   label=chosen["candidate_id"], candidates=candidates)
                    # submit independently validates raw/public pose mapping and physics.
                    state = submit(state, text, ast, chosen, value, candidates)
                    event.update(kind="PLACE", status="placed", action=value,
                                 chosen_candidate=chosen)
            event["planning_seconds"] = time.perf_counter() - started
            # On compilation failure still evaluate the same physical candidate
            # opportunity; this is audit-only and cannot manufacture a method AST.
            if groups is None:
                groups, audit = pools(before, text, {"schema_version": "o4_policy_v1", "rules": []},
                                      generator_config)
                candidates = public_candidates(groups, public["buffer_state_hash"])
                event.update(candidates=candidates, failure_audit_only=True)
            obs, _ = unpack(source)
            event["compilation_metrics"] = compilation_metrics(
                obs, response, task["reference_policy"], candidates,
            )
        event["after_public_state"] = public_state(state, text)
        event["reference_after"] = reference_state(
            observation(state, text)["placed_objects"], task["reference_policy"],
        )
        events.append(event)
        if on_event:
            on_event(event)
        if event["kind"] == "STOP":
            break
    planned = len(scenario["arrival_order"])
    total_volume = math.fsum(math.prod(list(item["dimensions_mm"].values())) for item in scenario["items"])
    final_violations = events[-1]["reference_after"]["violations"]
    placed = len(state["placed_items"])
    order = [item["item_id"] for item in state["placed_items"]]
    arrival_rank = {identifier: index for index, identifier in enumerate(scenario["arrival_order"])}
    summary = {
        "task_id": task["task_id"], "source_order_key": task["source_order_key"],
        "configuration": task["configuration"], "backend": backend, "planner": planner,
        "capacity": capacity, "planned_items": planned, "placed_items": placed,
        "completed": placed == planned,
        "clean_completed": placed == planned and not final_violations,
        "placed_item_ratio": placed / planned,
        "placed_volume_ratio": math.fsum(math.prod(item["oriented_size_mm"]) for item in state["placed_items"]) / total_volume,
        "termination_reason": events[-1]["status"], "placed_sequence": order,
        "pending_ids": [item["item"]["item_id"] for item in state["pending_items"]],
        "not_arrived_ids": scenario["arrival_order"][cursor:],
        "wait_requests": sum(event["kind"] == "WAIT_NEXT" for event in events),
        "successful_receives": cursor, "place_events": placed,
        "inversions": sum(arrival_rank[a] > arrival_rank[b] for index, a in enumerate(order) for b in order[index + 1:]),
        "physical_violations": sum(bool(event["physical_errors"]) for event in events),
        "final_business_violation_count": len(final_violations),
        "reference_violating_commits": sum(event["kind"] == "PLACE" and bool(event["reference_after"]["violations"]) for event in events),
        "compilation_opportunities": sum(event["compilation_metrics"] is not None for event in events),
        "search_evaluations": [event["search_trace"]["evaluations"] for event in events if event["search_trace"]],
        "search_truncated_count": sum(bool(event["search_trace"] and event["search_trace"]["search_truncated"]) for event in events),
    }
    return summary, events
