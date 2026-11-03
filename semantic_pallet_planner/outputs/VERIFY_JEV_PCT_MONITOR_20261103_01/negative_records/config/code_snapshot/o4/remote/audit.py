"""Independent checks of committed events and resource accounting.

These checks read saved public states and private references after execution;
they neither call the planner nor repair decisions.
"""
from __future__ import annotations

import copy

from ...evaluation.geometry_oracle import check_candidate
from ..common import O4Error
from ..evaluator import reference_state
from ..buffer.buffer_protocol import validate_state


def raw_physical_state(public: dict, item_catalog: dict, pick: str) -> dict:
    observation = public["observation"]
    placed = []
    for obj in observation["placed_objects"]:
        item = copy.deepcopy(item_catalog[obj["object_id"]])
        item.update(pose=obj["pose"], oriented_size_mm=obj["oriented_size_mm"])
        placed.append(item)
    # Public facts intentionally omit the physics engine's cached loads/edges.
    # Reconstruct them with the independent reference interpreter, rather than
    # copying stale per-item values from the original (unplaced) item catalog.
    physics = reference_state(observation["placed_objects"], {"rules": []})
    for item in placed:
        identifier = item["item_id"]
        item["supported_load_kg"] = physics["loads_kg"][identifier]
        item["support_fractions"] = [
            {"item_id": lower, "fraction": fraction}
            for lower, fraction in physics["support_edges"][identifier]
        ]
    return {"request_id": observation["request_id"], "container": observation["container"],
            "placed_items": placed, "available_items": [item_catalog[pick]]}


def audit_episode(events: list[dict], scenario: dict, reference_policy: dict) -> dict:
    arrived = []
    commits = []
    counts = {"events": 0, "physical_checks": 0, "reference_checks": 0,
              "search_evaluations": 0, "capacity_violations": 0, "leakage": 0}
    by_id = {item["item_id"]: item for item in scenario["items"]}
    previous = None
    for event in events:
        before, after = event["before_public_state"], event["after_public_state"]
        validate_state(before)
        validate_state(after)
        counts["events"] += 1
        if previous is not None and previous != before:
            raise O4Error("event_audit", "broken state chain")
        previous = after
        if event["kind"] == "WAIT_NEXT":
            if before["end_of_stream"] or len(before["pending_items"]) >= before["buffer_capacity"]:
                raise O4Error("event_audit", "illegal WAIT")
            identifier = event["received_id"]
            if identifier is not None:
                if identifier != scenario["arrival_order"][len(arrived)]:
                    raise O4Error("event_audit", "arrival order changed")
                arrived.append(identifier)
            if before["observation"]["placed_objects"] != after["observation"]["placed_objects"]:
                raise O4Error("event_audit", "WAIT changed pallet")
        elif event["kind"] == "PLACE":
            candidate = event["chosen_candidate"]
            pick = candidate["pick_item_id"]
            if pick not in {entry["object_id"] for entry in before["pending_items"]} or pick in commits:
                raise O4Error("event_audit", "invalid/duplicate pick")
            raw = raw_physical_state(before, by_id, pick)
            errors = check_candidate(raw, {"container": raw["container"]}, candidate["raw"])
            counts["physical_checks"] += 1
            if errors:
                raise O4Error("event_audit", "physical violation")
            commits.append(pick)
            actual = after["observation"]["placed_objects"][-1]
            if actual["object_id"] != pick or actual["pose"] != candidate["pose"]:
                raise O4Error("event_audit", "committed pose mismatch")
        elif event["kind"] != "STOP":
            raise O4Error("event_audit", "unknown event kind")
        placed = [obj["object_id"] for obj in after["observation"]["placed_objects"]]
        pending = [obj["object_id"] for obj in after["pending_items"]]
        if placed != commits or set(placed) & set(pending) or sorted(placed + pending) != sorted(arrived):
            raise O4Error("event_audit", "object conservation")
        if after["arrival_count"] != len(arrived) or after["placed_count"] != len(commits):
            raise O4Error("event_audit", "event accounting")
        actual_reference = reference_state(after["observation"]["placed_objects"], reference_policy)
        counts["reference_checks"] += 1
        if actual_reference != event["reference_after"]:
            raise O4Error("event_audit", "reference violation concealed")
        trace = event["search_trace"]
        if trace:
            evaluations = sum(node["audit"]["evaluations"] for node in trace["nodes"])
            if evaluations != trace["evaluations"] or evaluations > 256 or trace["max_depth"] > 3 or trace["max_beam"] > 8:
                raise O4Error("event_audit", "search accounting")
            counts["search_evaluations"] += evaluations
    if not events or events[-1]["kind"] != "STOP":
        raise O4Error("event_audit", "missing terminal event")
    return {"status": "PASS", **counts}
