"""Immutable adapter to A/E2 geometry only; no O4 observation or AST is built."""
import copy
from ..o4.extensions.e2.candidates import generate as e2_generate, key
from ..evaluation.geometry_oracle import check_candidate
from .config import geometry_config
from .common import O5Error, digest

ITEM_KEYS = ('item_id', 'dimensions_mm', 'mass_kg', 'stackable', 'top_load_limit_kg_synthetic')
PLACED_KEYS = ITEM_KEYS + ('pose', 'oriented_size_mm', 'supported_load_kg', 'support_fractions')


def physical_item(item, placed=False):
    return {k: copy.deepcopy(item[k]) for k in (PLACED_KEYS if placed else ITEM_KEYS)}


def state_for(container, placed, current, event_index):
    return {'container': copy.deepcopy(container),
            'placed_items': [physical_item(p, True) for p in placed],
            'pending_items': [{'item': physical_item(current), 'arrival_index': len(placed), 'slot': 0}],
            'event_index': event_index}


def case_for(state):
    return {'container': state['container'], 'placed_items': state['placed_items'],
            'available_items': [state['pending_items'][0]['item']]}


def generate(container, placed, current, event_index, config):
    state = state_for(container, placed, current, event_index)
    pool, audit = e2_generate(state, current['item_id'], [], geometry_config(config))
    if len(pool) > 16:
        raise O5Error('CANDIDATE_LIMIT')
    for candidate in pool:
        errors = check_candidate(case_for(state), {'container': container}, candidate)
        if errors:
            raise O5Error('BACKEND_PHYSICAL_REJECTION', ','.join(errors))
    return pool, audit


def pool_fingerprint(pool):
    return digest([{'pose': c['pose'], 'size': c['oriented_size_mm']} for c in sorted(pool, key=key)])
