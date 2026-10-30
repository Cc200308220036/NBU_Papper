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


@lru_cache(maxsize=8)
def schema_validator(name: str) -> Draft202012Validator:
    if name not in {"config", "candidate_bundle", "decision_context", "selection_result", "transport_result"}:
        raise JevSelectError("unknown_schema", name)
    resource = files("semantic_pallet_planner.jev_select").joinpath("schemas", f"{name}.schema.json")
    schema = json.loads(resource.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_schema(name: str, value: dict) -> None:
    canonical(value)
    errors = sorted(schema_validator(name).iter_errors(value), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        raise JevSelectError(f"invalid_{name}", f"/{'/'.join(map(str, error.path))}: {error.message}")


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
