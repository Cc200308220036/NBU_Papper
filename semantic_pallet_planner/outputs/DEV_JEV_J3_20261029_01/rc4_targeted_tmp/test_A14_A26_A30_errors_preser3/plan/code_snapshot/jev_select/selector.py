"""Choice validation and same-pool selectors. No reference policy or future stream."""
from __future__ import annotations

import math
from typing import Protocol

from .contracts import DecisionContext, JevSelectError, Snapshot, digest, validate_schema
from .context import validate_context
from .transport import strict_json, validate_transport


class SelectionResult(Snapshot):
    pass


class CandidateSelector(Protocol):
    def select(self, context: DecisionContext, *, decision_id: str) -> SelectionResult: ...


def result(context, *, status, source, label=None, attempt=None, payload=None, error=None):
    value = context.data
    metadata = payload or {}
    answer = metadata.get("answers", {}).get("next_action", {})
    saved = attempt["transport"] if attempt else None
    selection = {"version": "jev_selection_result_v2" if value["version"] == "jev_decision_context_v2" else "jev_selection_result_v1", "status": status,
                 "selected_display_id": label,
                 "selected_candidate_id": None if label is None else value["display_mapping"][label]["candidate_id"],
                 "source": source, "requested_model": value["request_body"]["model"] if value["request_body"] and source in ("jev", "test_double") else None,
                 "served_model": metadata.get("model"), "probabilities": answer.get("probabilities"),
                 "confidence": answer.get("confidence"), "attempt_ids": [attempt["attempt_id"]] if attempt else [],
                 "usage": metadata.get("usage"), "latency_s": saved["latency_s"] if saved else None,
                 "local_binding_digest": digest(value["local_binding"]),
                 "raw_response_digest": saved["raw_sha256"] if saved else None, "error": error}
    validate_schema("selection_result", selection)
    return SelectionResult.from_dict(selection)


def probability_sum_valid(probabilities, config):
    """Accept a unit distribution or v2's declared two-decimal rounding intervals.

    Keep raw probabilities unchanged. A rounded vector is admissible only if
    some unit-sum vector lies inside all clipped half-cent rounding intervals.
    This does not relax the independent selected-option maximum check.
    """
    values = list(probabilities.values())
    tolerance = config["probability_tolerance"]
    if abs(math.fsum(values) - 1.) <= tolerance:
        return True
    if config.get("probability_sum_validation") != "strict_or_2dp_rounding_interval_v1":
        return False
    from decimal import Decimal
    decimals = [Decimal(str(v)) for v in values]
    quantum = Decimal("0.01")
    grid = [v.quantize(quantum) for v in decimals]
    # Decimal-looking provider values can be serialized after binary64 arithmetic,
    # e.g. 0.15000000000000002. Permit at most eight ULPs of representation noise.
    if any(abs(float(v)-float(q)) > 8*math.ulp(float(v)) for v,q in zip(decimals,grid)):
        return False
    decimals = grid
    half = quantum / 2
    lower = sum(max(Decimal(0), v-half) for v in decimals)
    upper = sum(min(Decimal(1), v+half) for v in decimals)
    return lower <= Decimal(1) <= upper


def parse_response(context, attempt, config):
    source = attempt["origin"]
    saved = attempt["transport"]
    raw = validate_transport(saved)
    if saved["status"] != "OK":
        return result(context, status="unknown_in_flight" if saved["status"] == "UNKNOWN_IN_FLIGHT" else "provider_failure",
                      source=source, attempt=attempt, error=saved["error"])
    try:
        if len(raw) > config["response_max_bytes"]:
            raise JevSelectError("response_too_large")
        payload = strict_json(raw)
        if not isinstance(payload, dict) or payload.get("model") != config["model"]:
            raise JevSelectError("wrong_served_model")
        if not isinstance(payload.get("answers"), dict) or set(payload["answers"]) != {"next_action"}:
            raise JevSelectError("wrong_question_keys")
        answer = payload["answers"]["next_action"]
        if not isinstance(answer, dict) or set(answer) != {"type", "choice", "probabilities", "confidence"} or answer["type"] != "choice":
            raise JevSelectError("wrong_choice_type")
        labels = context.data["criteria"]
        choice, probabilities, confidence = answer["choice"], answer["probabilities"], answer["confidence"]
        if not isinstance(choice, str) or choice not in labels:
            raise JevSelectError("unknown_choice")
        if not isinstance(probabilities, dict) or set(probabilities) != set(labels):
            raise JevSelectError("wrong_probability_keys")
        values = [*probabilities.values(), confidence]
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
            raise JevSelectError("invalid_probability_value")
        tolerance = config["probability_tolerance"]
        if not probability_sum_valid(probabilities, config):
            raise JevSelectError("invalid_probability_sum")
        if max(probabilities.values()) - probabilities[choice] > tolerance:
            raise JevSelectError("choice_not_maximum")
        usage = payload.get("usage")
        if usage is not None and (not isinstance(usage, dict) or set(usage) != {"input_tokens", "output_tokens"}
                or any(type(v) is not int or v < 0 for v in usage.values())):
            raise JevSelectError("invalid_usage")
        return result(context, status="selected", source=source, label=choice, attempt=attempt, payload=payload)
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        return result(context, status="invalid_response", source=source, attempt=attempt,
                      error=exc.code if isinstance(exc, JevSelectError) else "INVALID_JSON_OR_STRUCTURE")


def bind_decision(context, job_id, decision_id):
    value = context.data
    value["local_binding"].update(job_id=job_id, decision_id=decision_id)
    bound = DecisionContext.from_dict(value)
    validate_context(bound)
    return bound


def baseline_label(context, method):
    value = context.data; criteria = value["criteria"]
    def pose_key(label):
        c = criteria[label]; p = c["pose"]
        return (-c["features"]["geometry_score"], p["x_mm"], p["y_mm"], p["z_base_mm"], p["yaw_deg"], c["pick_object"])
    labels = list(criteria)
    if method == "shared_constrained_first":
        objects = {o["object_id"]: o for o in value["model_state"]["available_objects"]}
        pending = value["model_state"]["buffer"]["pending"]
        count = {o: sum(c["pick_object"] == o for c in criteria.values()) for o in objects}
        arrival = {o["object_id"]: o["arrival_index"] for o in pending}
        pick = min((o for o in objects if count[o]), key=lambda o: (count[o], -objects[o]["mass_kg"], arrival[o]))
        labels = [l for l in labels if criteria[l]["pick_object"] == pick]
    elif method != "shared_geometry":
        raise JevSelectError("unknown_baseline")
    return min(labels, key=pose_key)


class LocalSelector:
    def __init__(self, method):
        self.method = method

    def bind_public(self, observation, public_policy, bundle):
        self.public_inputs = (observation, public_policy, bundle)

    def select(self, context, *, decision_id):
        validate_context(context)
        if self.method == "shared_business_lexicographic":
            observation, policy, bundle = self.public_inputs
            costs = PublicBusinessScorer().score(observation, policy, bundle)
            value = context.data
            labels = list(value["criteria"])
            def key(label):
                entry = value["display_mapping"][label]
                c = value["criteria"][label]; p = c["pose"]
                return (*costs[entry["candidate_id"]], -c["features"]["geometry_score"],
                        p["x_mm"], p["y_mm"], p["z_base_mm"], p["yaw_deg"], c["pick_object"])
            label = min(labels, key=key)
            # Reject stale or substituted public scoring inputs before returning.
            # Context may use a non-default display seed/config: validate explicit bindings directly.
            if value["local_binding"]["observation_digest"] != observation["observation_digest"] or value["local_binding"]["selectable_digest"] != bundle.data["selectable_digest"]:
                raise JevSelectError("stale_public_scorer")
            return result(context, status="selected", source="local_baseline", label=label)
        return result(context, status="selected", source="local_baseline", label=baseline_label(context, self.method))


class JevSelector:
    def __init__(self, config, ledger, job_id, transport=None):
        self.config, self.ledger, self.job_id, self.transport = config, ledger, job_id, transport

    def for_replay(self):
        return JevSelector(self.config, self.ledger, self.job_id)

    def select(self, context, *, decision_id):
        validate_context(context, config=self.config)
        if context.data["local_binding"].get("decision_id") != decision_id or context.data["local_binding"].get("job_id") != self.job_id:
            raise JevSelectError("selector_identity_mismatch")
        attempt = self.ledger.request(context, self.job_id, decision_id, self.transport)
        if attempt is None:
            return result(context, status="budget_exhausted", source=self.ledger.origin if self.transport is None else self.transport.origin,
                          error="ATTEMPT_BUDGET_EXHAUSTED")
        return parse_response(context, attempt, self.config)



class PublicBusinessScorer:
    """Costs derived solely from the current public instruction and observation."""
    def score(self, observation, public_policy, bundle):
        from .candidates import PublicBusinessGuard, validate_bundle
        value = validate_bundle(observation, bundle)
        rows = PublicBusinessGuard().evaluate(observation, public_policy, value["physical_candidates"]).data["evaluations"]
        return {r["candidate_id"]: (len(r["new_violations"]), len(r["after"]["violations"])) for r in rows}
