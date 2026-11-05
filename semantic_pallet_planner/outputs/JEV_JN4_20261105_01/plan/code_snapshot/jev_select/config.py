"""Versioned Jev/J0 settings and geometry resources, independent of cwd."""
from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path

from .contracts import JevSelectError, validate_schema, digest


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


def is_v3(config: dict) -> bool:
    return config.get("version") == "jev_direct_choice_v3"


def business_evaluation_mode(config: dict) -> bool:
    from .packaging_runtime import is_packaging
    return is_v2(config) or is_v3(config) or is_packaging(config)


def protocol_suffix(config: dict) -> str:
    validate_schema("config", config)
    from .packaging_runtime import is_packaging
    return "v9" if config.get("version") == "jev_packaging_memory_orders_v9" else "v8" if config.get("version") == "jev_packaging_contrast_v8" else "v7" if config.get("version") == "jev_packaging_memory_v7" else "v6" if config.get("version") == "jev_packaging_remote_v6" else "v5" if config.get("version") == "jev_packaging_monitored_v5" else "v4" if is_packaging(config) else "v3" if is_v3(config) else "v2" if is_v2(config) else "v1"


def load_v3_config() -> dict:
    resource = files("semantic_pallet_planner.jev_select").joinpath("configs", "jev_public_memory_v3.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    validate_schema("config", value)
    return value


def load_v2_config() -> dict:
    resource = files("semantic_pallet_planner.jev_select").joinpath("configs", "jev_orders_business_eval_v2.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    validate_schema("config", value)
    return value


def memory_retrieval_limits(config: dict) -> dict:
    """Explicit offline/B1-B adapter; no change to the B0 runtime route."""
    validate_schema('config', config)
    if not is_v3(config):
        raise JevSelectError('memory_retrieval_requires_v3')
    return {'top_k': config['memory_top_k'],
            'item_max_utf8_bytes': config['memory_item_max_utf8_bytes'],
            'total_max_utf8_bytes': config['memory_total_max_utf8_bytes']}


def memory_mode_for_method(method):
    modes={'shared_geometry':'none','shared_business_lexicographic':'none','jev_no_memory':'none',
           'jev_raw_history':'raw_history','jev_memory_cards':'cards'}
    if method not in modes: raise JevSelectError('invalid_j4_method')
    return modes[method]


def config_for_memory(config, method, snapshot):
    return dict(config,selector=method,memory_mode=memory_mode_for_method(method),
                memory_snapshot_digest=digest(snapshot.data),
                memory_corpus_digest=snapshot.data['corpus_digest'])
