"""Build an offline TypeSafe Choice request from public facts only."""
from __future__ import annotations

import copy
import random
import re

from semantic_pallet_planner.o4.extensions.e2.protocol import BINDINGS, validate_observation
from semantic_pallet_planner.o4.online.planner_adapter import soft_quality
from semantic_pallet_planner.planner.scoring import geometry_score

from .candidates import PublicBusinessGuard, decision_route, validate_bundle
from .config import is_v2
from semantic_pallet_planner.o4.executor import reconstruct, transition
from .contracts import (CandidateBundle, DecisionContext, JevSelectError, MemorySnapshot,
                        PublicPolicyContext, canonical, digest, validate_schema)


PROMPT = "jev_direct_en_v1"
OBJECTIVE = ("Prioritize completing the order without business violations. Compare the future "
             "usefulness of remaining space using only observed facts. Prefer low and central "
             "heavy-box placement when it does not undermine completion. No future arrivals are known.")
QUESTION = ("Choose one complete box-and-placement action from criteria, using the public state "
            "and applicable memories. All options passed current physical and business checks. "
            "Do not assume unobserved boxes or invent future dimensions.")


PROMPT_V2 = "jev_business_eval_en_v2"
QUESTION_V2 = ("Select one complete box-and-placement action. Every option is physically feasible "
               "under the declared simulator checks, but some may violate business requirements. "
               "Aim to place the entire order, avoid business violations, and preserve useful space "
               "using only observed facts. Business violations are recorded and do not end the episode. "
               "Do not assume unseen arrivals.")
OBJECTIVE_V2 = ("Aim to place the entire order while avoiding business violations and preserving useful "
                "space. Business requirements remain goals, but violations do not block execution or end "
                "the episode. Physical checks remain mandatory. Only currently observed boxes are known.")


def _selector_text(selector: dict, aliases: dict) -> str:
    key, value = next(iter(selector.items()))
    if key == "all":
        return "all boxes"
    if key == "object_ids":
        return "boxes " + ", ".join(aliases[i] for i in value)
    if key in ("and", "or"):
        return "(" + f" {key.upper()} ".join(_selector_text(s, aliases) for s in value) + ")"
    if key == "not":
        return "NOT (" + _selector_text(value, aliases) + ")"
    return f"{value['field']} {key} {canonical(value['value'])}"


def business_text(ast: dict, aliases: dict) -> list[str]:
    """Deterministic descriptions, not an LLM translation or a model AST."""
    rule_names = {r["rule_id"]: f"R{i:02d}" for i, r in enumerate(ast["rules"], 1)}
    sentences = []
    for r in ast["rules"]:
        kind = r["type"]
        if kind == "forbidden_contact":
            text = f"No direct face contact between {_selector_text(r['left'], aliases)} and {_selector_text(r['right'], aliases)}."
        elif kind == "inside_region":
            text = f"The entire footprint of {_selector_text(r['target'], aliases)} must be inside public region {r['region_id']}."
        elif kind == "relative_position":
            text = (f"Every distinct pair of {_selector_text(r['subject'], aliases)} and "
                    f"{_selector_text(r['reference'], aliases)} must satisfy {r['relation']} "
                    f"with boundary clearance at least {r['min_gap_mm']} mm; pending relations are deferred until both boxes are placed.")
        elif kind == "no_top_load":
            text = f"No top load on {_selector_text(r['target'], aliases)}."
        else:
            limit = r["limit"].get("constant_kg")
            limit_text = f"{limit} kg" if limit is not None else "each box's labels.max_top_load_kg"
            text = f"Cumulative top load on {_selector_text(r['target'], aliases)} must not exceed {limit_text}."
        overrides = ",".join(rule_names[name] for name in r["overrides"]) or "none"
        sentences.append(f"{rule_names[r['rule_id']]}: {text} Priority={r['priority']}; explicitly overrides={overrides} on matching objects.")
    return sentences


def _public_object(obj: dict, aliases: dict) -> dict:
    keys = ("mass_kg", "dimensions_mm", "stackable", "fragile", "weight_class", "cargo_category",
            "packaging", "labels", "physical_top_load_limit_kg", "pose", "oriented_size_mm")
    result = {k: copy.deepcopy(obj[k]) for k in keys if k in obj}
    return {"object_id": aliases[obj["object_id"]], **result}


class ContextBuilder:
    def __init__(self, config: dict):
        validate_schema("config", config)
        self.config = copy.deepcopy(config)

    def build(self, observation: dict, bundle: CandidateBundle,
              public_policy: PublicPolicyContext,
              memories: MemorySnapshot | None = None) -> DecisionContext:
        validate_observation(observation)
        value = validate_bundle(observation, bundle)
        guard = PublicBusinessGuard()
        if value != guard.filter(observation, public_policy, bundle, self.config).data:
            raise JevSelectError("candidate_filter_mismatch")
        memory = MemorySnapshot.empty() if memories is None else memories
        if memory.data != MemorySnapshot.empty().data:
            raise JevSelectError("memory_not_implemented", "J0 accepts only the frozen empty memory")
        if observation["buffer_context"]["capacity"] != self.config["buffer_capacity"]:
            raise JevSelectError("config_capacity_mismatch")
        objects = observation["placed_objects"] + observation["available_objects"]
        aliases = {o["object_id"]: f"B{i:03d}" for i, o in enumerate(objects, 1)}
        ordered = sorted(value["selectable_candidates"], key=lambda c: (
            c["pose"]["x_mm"], c["pose"]["y_mm"], c["pose"]["z_base_mm"],
            c["pose"]["yaw_deg"], aliases[c["pick_item_id"]]))
        # Identity and state, not private order provenance, drive deterministic display order.
        seed = digest([self.config["display_order_seed"], observation["request_id"], observation["state_hash"]])
        random.Random(int(seed[:16], 16)).shuffle(ordered)
        version_two = is_v2(self.config)
        if version_two:
            before_loads = reconstruct(observation["placed_objects"])[0]
            evaluations = {}
        else:
            evaluation = guard.evaluate(observation, public_policy, value["physical_candidates"]).data
            evaluations = {row["candidate_id"]: row for row in evaluation["evaluations"]}
        criteria, mapping = {}, {}
        for index, c in enumerate(ordered, 1):
            label = f"C{index:02d}"
            if version_two:
                after_loads = reconstruct(transition(observation, c))[0]
                row = {"before": {"loads_kg": before_loads}, "after": {"loads_kg": after_loads, "limits_kg": {}}}
            else:
                row = evaluations[c["candidate_id"]]
            heavy = soft_quality(observation, c)
            changed = []
            for obj in observation["placed_objects"]:
                identifier = obj["object_id"]
                before = row["before"]["loads_kg"][identifier]
                after = row["after"]["loads_kg"][identifier]
                if after <= before:
                    continue
                limit = row["after"]["limits_kg"].get(identifier)
                changed.append({"object_id": aliases[identifier], "before_top_load_kg": before,
                                "after_top_load_kg": after, "effective_business_limit_kg": limit,
                                "remaining_business_limit_kg": None if limit is None else limit-after})
            criteria[label] = {
                "pick_object": aliases[c["pick_item_id"]], "pose": copy.deepcopy(c["pose"]),
                "oriented_size_mm": list(c["oriented_size_mm"]),
                "features": {"geometry_score": geometry_score(c),
                             "geometry_components": copy.deepcopy(c["geometry_score_components"]),
                             "support_ratio": c["support"]["support_ratio"],
                             "com_margin_mm": c["support"]["com_margin_mm"],
                             "supported_by": [aliases[i] for i in c["support"]["support_item_ids"]],
                             "resulting_max_height_mm": c["resulting_geometry"]["max_height_mm"],
                             "resulting_volume_utilization": c["resulting_geometry"]["volume_utilization"],
                             "heavy_low_quality": heavy[0], "heavy_center_quality": heavy[1],
                             "current_business_allowed": True},
                "load_changes": changed,
            }
            if version_two:
                criteria[label]["features"].pop("current_business_allowed")
                for change in changed:
                    change.pop("effective_business_limit_kg")
                    change.pop("remaining_business_limit_kg")
            mapping[label] = {"candidate_id": c["candidate_id"], "pick_item_id": c["pick_item_id"],
                              "candidate_digest": digest(c)}
        instruction = re.sub(r"对象（([^）]+)）", lambda m: "对象（" + ",".join(
            aliases[i] for i in m[1].split(",")) + "）", observation["instruction_text"])
        buffer = observation["buffer_context"]
        state = {
            "units": {"length": "mm", "mass": "kg"},
            "coordinate_convention": observation["coordinate_convention"],
            "container": {k: observation["container"][k] for k in (
                "length_mm", "width_mm", "max_height_mm", "max_payload_kg")},
            "placed_objects": [_public_object(o, aliases) for o in observation["placed_objects"]],
            "available_objects": [_public_object(o, aliases) for o in observation["available_objects"]],
            "regions": copy.deepcopy(observation["regions"]),
            "buffer": {"capacity": buffer["capacity"], "end_of_stream": buffer["end_of_stream"],
                       "pending": [{**p, "object_id": aliases[p["object_id"]]} for p in buffer["pending"]]},
            "business_requirements": {"original_text": instruction,
                                      "english_descriptions": business_text(public_policy.data["response"]["policy_ast"], aliases)},
            "objective": OBJECTIVE_V2 if version_two else OBJECTIVE, "memories": [],
        }
        if version_two:
            state["business_attribute_source"] = self.config["business_attribute_source"]
            for obj in state["placed_objects"]:
                original = next(k for k, alias in aliases.items() if alias == obj["object_id"])
                obj["current_top_load_kg"] = before_loads[original]
        route = decision_route(bundle)
        body = None if route != "CHOICE_REQUIRED" else {
            "model": self.config["model"], "state": state,
            "questions": {"next_action": {"type": "choice", "instructions": QUESTION_V2 if version_two else QUESTION, "criteria": criteria}}}
        if body is not None and len(canonical(body).encode("utf-8")) > self.config["max_request_bytes"]:
            raise JevSelectError("request_too_large", "No candidate or fact was silently dropped")
        binding = {**{k: observation[k] for k in BINDINGS}, "event_index": buffer["event_index"],
                   "physical_digest": value["physical_digest"], "selectable_digest": value["selectable_digest"],
                   "mapping_digest": digest(mapping), "memory_digest": digest(memory.data),
                   "policy_digest": digest(public_policy.data), "config_digest": digest(self.config),
                   "generator_config_digest": value["generator_config_digest"],
                   "prompt_version": self.config["prompt_version"], "feature_version": self.config["feature_version"],
                   "model_state_digest": digest(state), "criteria_digest": digest(criteria),
                   "request_body_digest": digest(body)}
        if version_two:
            binding.update({k: self.config[k] for k in ("experiment_protocol", "business_mode", "execution_version", "evaluation_version")})
            binding["public_spec_digest"] = digest(public_policy.data["response"]["policy_ast"])
        result = DecisionContext.from_dict({"version": "jev_decision_context_v2" if version_two else "jev_decision_context_v1", "route": route,
                                            "model_state": state, "criteria": criteria,
                                            "request_body": body, "display_mapping": mapping,
                                            "local_binding": binding})
        validate_context(result, observation, bundle, self.config)
        return result


def validate_context(context: DecisionContext, observation: dict | None = None,
                     bundle: CandidateBundle | None = None, config: dict | None = None) -> dict:
    value = context.data
    validate_schema("decision_context", value)
    state, criteria, binding = value["model_state"], value["criteria"], value["local_binding"]
    labels = list(value["display_mapping"])
    if set(labels) != set(criteria) or sorted(labels) != [f"C{i:02d}" for i in range(1, len(labels)+1)]:
        raise JevSelectError("invalid_display_mapping")
    expected = {"mapping_digest": digest(value["display_mapping"]), "model_state_digest": digest(state),
                "criteria_digest": digest(criteria), "request_body_digest": digest(value["request_body"]),
                "memory_digest": digest(MemorySnapshot.empty().data)}
    if any(binding[k] != v for k, v in expected.items()):
        raise JevSelectError("context_digest_mismatch")
    body = value["request_body"]
    if value["route"] == "CHOICE_REQUIRED":
        if len(labels) < 2 or body is None or body["state"] != state or body["questions"]["next_action"] != {
                "type": "choice", "instructions": QUESTION_V2 if value["version"] == "jev_decision_context_v2" else QUESTION, "criteria": criteria}:
            raise JevSelectError("request_context_mismatch")
    elif body is not None or (value["route"] == "SINGLETON_BYPASS") != (len(labels) == 1):
        raise JevSelectError("invalid_decision_route")
    if config is not None:
        validate_schema("config", config)
        if (value["version"] == "jev_decision_context_v2") != is_v2(config):
            raise JevSelectError("context_protocol_mismatch")
        if binding["config_digest"] != digest(config) or (body is not None and body["model"] != config["model"]):
            raise JevSelectError("config_binding_mismatch")
    if observation is not None:
        validate_observation(observation)
        if any(binding[k] != observation[k] for k in BINDINGS) or binding["event_index"] != observation["buffer_context"]["event_index"]:
            raise JevSelectError("stale_decision_context")
    if bundle is not None:
        if observation is None:
            raise JevSelectError("missing_observation")
        b = validate_bundle(observation, bundle)
        by_id = {c["candidate_id"]: c for c in b["selectable_candidates"]}
        if binding["physical_digest"] != b["physical_digest"] or binding["selectable_digest"] != b["selectable_digest"] or value["route"] != decision_route(bundle):
            raise JevSelectError("stale_candidate_mapping")
        if set(by_id) != {m["candidate_id"] for m in value["display_mapping"].values()}:
            raise JevSelectError("incomplete_candidate_mapping")
        for label, entry in value["display_mapping"].items():
            c = by_id[entry["candidate_id"]]
            aliases = {o["object_id"]: f"B{i:03d}" for i, o in enumerate(
                observation["placed_objects"] + observation["available_objects"], 1)}
            if entry["candidate_digest"] != digest(c) or entry["pick_item_id"] != c["pick_item_id"] or criteria[label]["pose"] != c["pose"] or criteria[label]["oriented_size_mm"] != c["oriented_size_mm"] or criteria[label]["pick_object"] != aliases[c["pick_item_id"]]:
                raise JevSelectError("changed_candidate_mapping")
        if value["version"] == "jev_decision_context_v2":
            public_policy = PublicBusinessGuard().resolve(observation)
            if binding["public_spec_digest"] != digest(public_policy.data["response"]["policy_ast"]):
                raise JevSelectError("public_spec_mismatch")
        if binding["policy_digest"] != b["policy_digest"] or binding["generator_config_digest"] != b["generator_config_digest"]:
            raise JevSelectError("candidate_provenance_mismatch")
    return value


def resolve_display_id(context: DecisionContext, display_id: str,
                       observation: dict, bundle: CandidateBundle, config: dict) -> dict:
    value = validate_context(context, observation, bundle, config)
    if display_id not in value["display_mapping"]:
        raise JevSelectError("unknown_display_id")
    identifier = value["display_mapping"][display_id]["candidate_id"]
    return next(c for c in bundle.data["selectable_candidates"] if c["candidate_id"] == identifier)
