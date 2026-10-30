"""Independent reference feedback and whole-order metrics, downstream of choice."""
from __future__ import annotations

import math
from collections import Counter

from semantic_pallet_planner.o4.extensions.e2.protocol import observation
from semantic_pallet_planner.o4.extensions.e2.reference import state as reference_state


def feedback(state, task):
    req = observation(state, task["instruction_text"], task["regions"])
    return reference_state(req["placed_objects"], task["reference_policy"], task["regions"],
                           pending_objects=req["available_objects"], end_of_stream=state["end_of_stream"])


def summarize(task, config, method, state, events, reason):
    final = feedback(state, task)
    placed = len(state["placed_items"]); total = len(task["items"])
    volume = sum(math.prod(o["oriented_size_mm"]) for o in state["placed_items"])
    planned_volume = sum(math.prod(o["dimensions_mm"].values()) for o in task["items"])
    decisions = [e for e in events if e["event"] not in ("WAIT_RECEIVE", "EOS")]
    violating = sum(e["event"] == "PLACE" and bool(e["reference_after"]["violations"]) for e in decisions)
    return {"task_id": task["task_id"], "source_order_key": task["source_order_key"],
            "source_kind": task["source_kind"], "negative": task.get("negative", False),
            "selector_backend": method, "candidate_backend": config["candidate_backend"],
            "selectable_pool": config["selectable_pool"], "policy_source": config["policy_source"],
            "feature_version": config["feature_version"], "memory_mode": config["memory_mode"],
            "planned_items": total, "arrived_items": state["arrival_count"], "placed_items": placed,
            "pending_ids": [p["item"]["item_id"] for p in state["pending_items"]],
            "unarrived_ids": [o["item_id"] for o in task["items"] if o["item_id"] not in state["arrived_ids"]],
            "completed": placed == total, "clean_completed": placed == total and not final["violations"] and violating == 0,
            "termination_reason": reason, "final_business_violations": final["violations"],
            "relation_status": final["relation_status"], "violating_steps": violating,
            "placed_item_ratio": placed / total, "placed_volume_ratio": volume / planned_volume,
            "volume_utilization": volume / (state["container"]["length_mm"] * state["container"]["width_mm"] * state["container"]["max_height_mm"]),
            "max_height_mm": max((o["pose"]["z_base_mm"] + o["oriented_size_mm"][2] for o in state["placed_items"]), default=0),
            "decision_records": len(decisions), "singleton_steps": sum(e.get("route") == "SINGLETON_BYPASS" for e in decisions),
            "choice_steps": sum(e.get("route") == "CHOICE_REQUIRED" for e in decisions),
            "physical_check_failures": sum(e.get("reason") == "physical_rejection" for e in decisions)}


def aggregate(rows, attempts, *, mode="offline", pricing=None):
    groups = []
    for method in sorted({r["selector_backend"] for r in rows}):
        for negative in (False, True):
            selected = [r for r in rows if r["selector_backend"] == method and r["negative"] == negative]
            if selected:
                groups.append({"selector_backend": method, "stratum": "contradictory_constructed" if negative else "positive_or_development",
                               "planned_orders": len(selected), "clean_completed": sum(r["clean_completed"] for r in selected),
                               "termination_reasons": dict(Counter(r["termination_reason"] for r in selected))})
    real = [r for r in attempts if r["origin"] == "jev"]
    measured = [r for r in real if r["transport"] and r["transport"]["network_attempted"] is True]
    unknown_send = sum(r["transport"]["network_attempted"] is None for r in real)
    from .transport import strict_json, validate_transport
    usages = []; served = []; latencies = []
    for row in measured:
        saved = row["transport"]; latencies.append(saved["latency_s"])
        try:
            payload = strict_json(validate_transport(saved))
            usage = payload.get("usage")
            if isinstance(payload.get("model"), str): served.append(payload["model"])
            if isinstance(usage, dict) and set(usage) == {"input_tokens", "output_tokens"} and all(type(v) is int and v >= 0 for v in usage.values()):
                usages.append(usage)
        except (ValueError, TypeError, UnicodeError, AttributeError):
            pass
    usage_complete = bool(measured) and len(usages) == len(measured) and unknown_send == 0
    known_input = sum(u["input_tokens"] for u in usages); known_output = sum(u["output_tokens"] for u in usages)
    pricing = pricing or {"input_per_million": 0.042, "output_per_million": 0.}
    known_cost = (known_input * pricing["input_per_million"] + known_output * pricing["output_per_million"]) / 1_000_000
    def percentile(values, fraction):
        if not values: return None
        values = sorted(values); position = (len(values)-1) * fraction
        lo = int(position); hi = min(lo+1, len(values)-1)
        return values[lo] + (values[hi]-values[lo]) * (position-lo)
    return {"version": "jev_metrics_v1", "mode": mode, "planned_jobs": len(rows),
            "source_orders": len({r["source_order_key"] for r in rows}), "groups": groups,
            "model_api_calls": len(measured), "unknown_send_attempts": unknown_send, "remote_reserved_attempts": len(real),
            "offline_attempts": len(attempts) - len(real),
            "estimated_model_cost_usd": 0. if mode == "offline" else known_cost if usage_complete else None,
            "known_usage_cost_usd": known_cost if mode == "remote" else 0., "usage_complete": usage_complete,
            "known_input_tokens": known_input if mode == "remote" else None,
            "known_output_tokens": known_output if mode == "remote" else None,
            "model_usage": {"input_tokens": known_input, "output_tokens": known_output} if usage_complete else None,
            "served_models": sorted(set(served)),
            "model_latency_p50_s": percentile(latencies, .5), "model_latency_p95_s": percentile(latencies, .95),
            "model_quality": "NOT_MEASURED" if mode == "offline" else "SMOKE_ONLY_NOT_BENCHMARKED",
            "memory_maintenance_cost_usd": 0.}
