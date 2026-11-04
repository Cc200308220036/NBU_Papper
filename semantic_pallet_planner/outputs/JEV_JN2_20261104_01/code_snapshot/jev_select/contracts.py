"""J0 value snapshots and closed, package-local JSON contracts. No model calls."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from importlib.resources import files
import json

from jsonschema import Draft202012Validator


class JevSelectError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(code + (f": {detail}" if detail else ""))


def canonical(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise JevSelectError("invalid_json", str(exc)) from exc


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


@lru_cache(maxsize=64)
def schema_validator(name: str) -> Draft202012Validator:
    if name not in {"packaging_fork_snapshot_v1", "packaging_fork_binding_v1", "packaging_fork_plan_v1", "packaging_branch_receipt_v1", "packaging_full_order_decision_v1", "packaging_full_order_plan_v2", "packaging_full_order_run_v2", "config_v6", "candidate_bundle_v6", "decision_context_v6", "selection_result_v6", "checkpoint_v6", "remote_order_metrics_v1", "packaging_full_order_plan_v1", "monitored_order_metrics_v1", "config_v5", "candidate_bundle_v5", "decision_context_v5", "selection_result_v5", "checkpoint_v5", "config_v4", "candidate_bundle_v4", "decision_context_v4", "selection_result_v4", "checkpoint_v4", "packaging_order_metrics_v1", "packaging_load_config_v1", "packaging_load_task_v1", "business_spec_v2", "config", "candidate_bundle", "decision_context", "selection_result", "transport_result", "config_v2", "candidate_bundle_v2", "decision_context_v2", "selection_result_v2", "business_state", "plan_v2", "checkpoint_v2", "order_metrics_v2", "metrics_v2",
                    "config_v3", "candidate_bundle_v3", "decision_context_v3", "selection_result_v3", "plan_v3", "checkpoint_v3", "order_metrics_v3", "metrics_v3", "memory_card", "memory_snapshot", "memory_episode_export", "memory_query", "memory_index", "memory_retrieval", "memory_generation_result", "memory_review", "memory_generator_config", "memory_review_authorization"}:
        raise JevSelectError("unknown_schema", name)
    resource = files("semantic_pallet_planner.jev_select").joinpath("schemas", f"{name}.schema.json")
    schema = json.loads(resource.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_schema(name: str, value: dict) -> None:
    canonical(value)
    if name in {"config", "candidate_bundle", "decision_context", "selection_result"}:
        for suffix in ("_v2", "_v3", "_v4", "_v5", "_v6"):
            if str(value.get("version", "")).endswith(suffix):
                name += suffix
                break
    errors = sorted(schema_validator(name).iter_errors(value), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        raise JevSelectError(f"invalid_{name}", f"/{'/'.join(map(str, error.path))}: {(error.message[:240] if error.validator not in ("anyOf", "oneOf") else "value does not match the versioned contract")}")


@dataclass(frozen=True)
class Snapshot:
    """A JSON-backed value: every read is independent of caller mutation."""
    _json: str

    @classmethod
    def from_dict(cls, value: dict):
        return cls(canonical(value))

    @property
    def data(self) -> dict:
        return json.loads(self._json)


class CandidateBundle(Snapshot):
    pass


class PublicPolicyContext(Snapshot):
    pass


class BusinessEvaluation(Snapshot):
    pass


class DecisionContext(Snapshot):
    pass


class MemorySnapshot(Snapshot):
    @classmethod
    def empty(cls):
        return cls.from_dict({"version": "memory_none_v1", "cards": []})


class MemoryQuery(Snapshot):
    pass


class RetrievalResult(Snapshot):
    pass
