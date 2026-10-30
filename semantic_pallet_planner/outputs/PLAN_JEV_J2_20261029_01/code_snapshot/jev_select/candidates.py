"""Public-only candidate generation and business filtering; no selection policy."""
from __future__ import annotations

import copy

from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate
from semantic_pallet_planner.o4.buffer.buffer_state import invariant, ordered, physical
from semantic_pallet_planner.o4.extensions.e2.candidates import generate
from semantic_pallet_planner.o4.extensions.e2.compiler import compile_policy
from semantic_pallet_planner.o4.extensions.e2.planning import select_layout
from semantic_pallet_planner.o4.extensions.e2.protocol import (
    observation as public_observation, validate_candidates, validate_observation,
)
from semantic_pallet_planner.o4.extensions.e2.runtime import evaluate_candidates

from .contracts import (
    BusinessEvaluation, CandidateBundle, JevSelectError, PublicPolicyContext,
    digest, validate_schema,
)


STATE_KEYS = ("container", "buffer_capacity", "pending_items", "placed_items", "arrived_ids",
              "attributes", "event_index", "arrival_count", "placed_count", "end_of_stream")
ITEM_KEYS = ("item_id", "mass_kg", "dimensions_mm", "stackable", "fragile", "weight_class",
             "top_load_limit_kg_synthetic", "product_category", "pose", "oriented_size_mm",
             "supported_load_kg", "support_fractions")


def current_state(state: dict, req: dict) -> dict:
    """Discard extra environment metadata; require current public facts to match."""
    validate_observation(req)
    if req["images"]:
        raise JevSelectError("unsupported_images")
    clean = {k: copy.deepcopy(state[k]) for k in STATE_KEYS}
    for obj in clean["placed_items"]:
        for k in list(obj):
            if k not in ITEM_KEYS:
                del obj[k]
    for pending in clean["pending_items"]:
        pending["item"] = {k: v for k, v in pending["item"].items() if k in ITEM_KEYS}
    invariant(clean)
    if public_observation(clean, req["instruction_text"], req["regions"]) != req:
        raise JevSelectError("stale_observation")
    return clean


def validate_bundle(req: dict, bundle: CandidateBundle) -> dict:
    value = bundle.data
    validate_schema("candidate_bundle", value)
    if value["observation_digest"] != req["observation_digest"]:
        raise JevSelectError("stale_candidate_bundle")
    candidates = value["physical_candidates"]
    validate_candidates(req, candidates)
    if digest(candidates) != value["physical_digest"]:
        raise JevSelectError("candidate_digest_mismatch")
    if digest(value["selectable_candidates"]) != value["selectable_digest"]:
        raise JevSelectError("selectable_digest_mismatch")
    original = {c["candidate_id"]: c for c in candidates}
    selected = value["selectable_candidates"]
    if len({c["candidate_id"] for c in selected}) != len(selected) or any(original.get(c["candidate_id"]) != c for c in selected):
        raise JevSelectError("invalid_candidate_subset")
    return value


class CandidateProvider:
    def build(self, state: dict, observation: dict, generator_config: dict) -> CandidateBundle:
        clean = current_state(state, observation)
        if clean["buffer_capacity"] > 3:
            raise JevSelectError("invalid_capacity")
        candidates = []
        counts = []
        for pending in ordered(clean):
            pick = pending["item"]["item_id"]
            generated, audit = generate(clean, pick, observation["regions"], copy.deepcopy(generator_config))
            for c in generated:
                errors = check_candidate(physical(clean, pick), {"container": clean["container"]}, c)
                if errors:
                    raise JevSelectError("physical_candidate_error", str(errors))
            candidates.extend(generated)
            counts.append({"pick_item_id": pick, "returned": len(generated),
                           "sampled_physical": audit["public_enriched_physical_count"]})
        validate_candidates(observation, candidates)
        result = CandidateBundle.from_dict({
            "version": "jev_candidate_bundle_v1", "observation_digest": observation["observation_digest"],
            "candidate_backend": "e2_original_v1", "generator_config_digest": digest(generator_config),
            "physical_candidates": candidates, "physical_digest": digest(candidates),
            "generation_counts": counts, "selectable_pool": "unfiltered",
            "selectable_candidates": [], "selectable_digest": digest([]), "policy_digest": None,
        })
        validate_bundle(observation, result)
        return result


class PublicBusinessGuard:
    def resolve(self, observation: dict) -> PublicPolicyContext:
        validate_observation(observation)
        response = compile_policy(copy.deepcopy(observation))
        return PublicPolicyContext.from_dict({"source": "public_parser",
                                             "observation_digest": observation["observation_digest"],
                                             "response": response})

    def validate_policy_context(self, req: dict, policy: PublicPolicyContext) -> dict:
        # Do not accept a user-supplied private/reference policy as a public one.
        if policy.data != self.resolve(req).data:
            raise JevSelectError("invalid_public_policy")
        return policy.data["response"]["policy_ast"]

    def evaluate(self, observation: dict, policy: PublicPolicyContext,
                 candidates: list[dict]) -> BusinessEvaluation:
        ast = self.validate_policy_context(observation, policy)
        evaluated = evaluate_candidates(observation, ast, copy.deepcopy(candidates))
        return BusinessEvaluation.from_dict({"candidate_digest": digest(candidates),
                                             "policy_digest": digest(policy.data), **evaluated})

    def filter(self, req: dict, policy: PublicPolicyContext, bundle: CandidateBundle,
               config: dict) -> CandidateBundle:
        validate_schema("config", config)
        value = validate_bundle(req, bundle)
        candidates = value["physical_candidates"]
        evaluation = self.evaluate(req, policy, candidates).data
        allowed = set(evaluation["allowed_ids"])
        if config["selectable_pool"] == "legacy_soft_eligible":
            allowed = set()
            ast = self.validate_policy_context(req, policy)
            for pick in dict.fromkeys(c["pick_item_id"] for c in candidates):
                group = [c for c in candidates if c["pick_item_id"] == pick]
                _, trace, _ = select_layout(req, ast, group)
                allowed.update(trace["eligible_labels"])
        value.update(selectable_pool=config["selectable_pool"],
                     selectable_candidates=[c for c in candidates if c["candidate_id"] in allowed],
                     policy_digest=digest(policy.data))
        value["selectable_digest"] = digest(value["selectable_candidates"])
        result = CandidateBundle.from_dict(value)
        validate_bundle(req, result)
        return result


def decision_route(bundle: CandidateBundle) -> str:
    value = bundle.data
    if value["selectable_pool"] == "unfiltered":
        raise JevSelectError("unfiltered_candidates")
    if not value["physical_candidates"]:
        return "STOP_NO_PHYSICAL_CANDIDATE"
    n = len(value["selectable_candidates"])
    if not n:
        return "STOP_NO_BUSINESS_CANDIDATE"
    return "SINGLETON_BYPASS" if n == 1 else "CHOICE_REQUIRED"
