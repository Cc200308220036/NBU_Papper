"""Exact B poses and coverage, with an independent B0 binding and cache."""
import copy
import json
import time
from functools import lru_cache
from ....common import canonical, digest
from ..layout_v2.candidates import generate as frozen_B_generate
from .config import validate, v2_config


@lru_cache(maxsize=64)
def _cached(serialized):
    state, pick, regions, config = json.loads(serialized)
    candidates, audit = frozen_B_generate(state, pick, regions, v2_config(config))
    for c in candidates:
        c['candidate_fingerprint'] = digest({'pick': pick, 'pose': c['pose'], 'size': c['oriented_size_mm'],
                                             'policy': validate(config)})
        c['candidate_id'] = 'E5B0_'+c['candidate_fingerprint'][:16]
    audit.update(capacity_candidate_policy='frozen_v2_B_retention_v1', binding_version='o4_e5_capacity_b0_v1')
    return candidates, audit


def generate(state, pick, regions, config):
    validate(config); started = time.perf_counter(); hits = _cached.cache_info().hits
    public = {k: state[k] for k in ('container', 'pending_items', 'placed_items', 'event_index')}
    candidates, audit = copy.deepcopy(_cached(canonical([public, pick, regions, config])))
    hit = _cached.cache_info().hits > hits
    audit['elapsed_seconds'] = time.perf_counter()-started
    if hit: audit['generation_seconds'] = {'cache_hit': True, 'full_pool_quality_evaluations_executed': 0}
    return candidates, audit


def clear_cache(): _cached.cache_clear()
