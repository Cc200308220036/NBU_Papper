"""Versioned Jev/J0 settings and geometry resources, independent of cwd."""
from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path

from .contracts import JevSelectError, validate_schema


def load_config(path: str | Path | None = None) -> dict:
    text = (Path(path).read_text(encoding="utf-8") if path is not None else
            files("semantic_pallet_planner.jev_select").joinpath("configs", "jev_direct_v1.json").read_text(encoding="utf-8"))
    value = json.loads(text)
    validate_schema("config", value)
    return value


def generator_config() -> dict:
    """A small, provenance-checked copy of the existing V1 geometry settings."""
    resource = files("semantic_pallet_planner.jev_select").joinpath("configs", "generator_v1.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    if value["candidate_generator"]["top_k"] != 16 or value["candidate_generator"]["yaw_degrees"] != [0, 90]:
        raise JevSelectError("invalid_generator_config")
    return value



def is_v2(config: dict) -> bool:
    return config.get("version") == "jev_direct_choice_v2"


def load_v2_config() -> dict:
    resource = files("semantic_pallet_planner.jev_select").joinpath("configs", "jev_orders_business_eval_v2.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    validate_schema("config", value)
    return value
