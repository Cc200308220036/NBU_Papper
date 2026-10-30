"""B0 changes candidate retention only; legacy selection and search order stay fixed."""
import copy
import json
import math
import time
from functools import lru_cache
from ....common import canonical, digest, O4Error
from ....buffer.buffer_state import place, ordered
from ...e2.planning import select_layout, METHODS, SEARCH
from ...e2.candidates import key
from ...e2.protocol import observation
from ..layout_v2.planning import PUBLIC_KEYS
from .config import validate
from .candidates import generate, clear_cache as clear_candidates


def pools(state, req, ast, config):
    groups = []; used = 0
    for p in ordered(state):
        candidates, generation = generate(state, p['item']['item_id'], req['regions'], config)
        selected, trace, evaluated = select_layout(req, ast, candidates)
        groups.append({'pick_item_id': p['item']['item_id'], 'arrival_index': p['arrival_index'], 'mass_kg': p['item']['mass_kg'],
                       'candidates': candidates, 'generation': generation, 'selected': selected,
                       'eligible': [c for c in candidates if c['candidate_id'] in trace['eligible_labels']],
                       'trace': trace, 'evaluation': evaluated})
        used += len(candidates)
    return groups, used


def search(state, req, ast, config, root_groups, root_used):
    before = digest(state); used = root_used; truncated = False
    def path_key(n):
        return [(state['arrived_ids'].index(c['pick_item_id']), key(c)[:-1]) for c in n['path']]
    beam = [{'state': state, 'path': [], 'volume': 0.}]; leaves = []; nodes = []; budget_refusals = []
    peak = 1; layers = []
    for depth in range(min(3, len(state['pending_items']))):
        children = []; expanded = 0
        for n in beam:
            reserve = 16*len(n['state']['pending_items'])
            spent_before = used
            if not depth: groups = root_groups
            else:
                if used+reserve > 256:
                    truncated = True; leaves.append(n)
                    budget_refusals.append({'depth': depth, 'path': path_key(n), 'spent': used, 'remaining': 256-used, 'required': reserve})
                    continue
                subreq = observation(n['state'], req['instruction_text'], req['regions'])
                groups, cost = pools(n['state'], subreq, ast, config); used += cost
            expanded += 1
            viable = [c for g in groups for c in g['eligible']]
            nodes.append({'depth': depth, 'state_digest': digest(n['state']), 'path': path_key(n),
                          'candidate_count': sum(len(g['candidates']) for g in groups), 'spent_before': spent_before if depth else 0,
                          'spent_after': used, 'remaining': 256-used, 'required': reserve,
                          'reason': 'expanded' if viable else 'terminal_no_action'})
            if not viable: leaves.append(n)
            for c in sorted(viable, key=lambda c: (next(g['arrival_index'] for g in groups if g['pick_item_id'] == c['pick_item_id']), key(c))):
                children.append({'state': place(n['state'], c), 'path': n['path']+[c],
                                 'volume': n['volume']+math.prod(c['oriented_size_mm'])})
        if not children: break
        def rank(n):
            return (-len(n['path']), -n['volume'], max((p['pose']['z_base_mm']+p['oriented_size_mm'][2] for p in n['state']['placed_items']), default=0), path_key(n))
        beam = sorted(children, key=rank)[:8]; peak = max(peak, len(beam))
        layers.append({'depth': depth, 'generated': len(children), 'survived': len(beam), 'expanded': expanded, 'spent': used})
    leaves.extend(beam)
    best = min(leaves, key=lambda n: (-len(n['path']), -n['volume'], path_key(n)))
    if digest(state) != before or used > 256: raise O4Error('capacity_search_invariant')
    return (best['path'][0] if best['path'] else None), {'config': SEARCH, 'evaluations': used,
        'search_truncated': truncated, 'nodes': nodes, 'layers': layers, 'budget_refusals': budget_refusals,
        'chosen_path': [c['candidate_id'] for c in best['path']], 'chosen_pose_path': path_key(best),
        'max_depth': max(len(n['path']) for n in leaves), 'max_beam': peak, 'max_beam_observed': peak,
        'before_real_state': before, 'after_real_state': digest(state), 'ranking_version': 'e2_count_volume_stable_v1',
        'capacity_version': 'o4_e5_capacity_b0_v1'}


def _choose(state, req, ast, config, method):
    validate(config)
    if method not in METHODS or (method == 'single') != (state['buffer_capacity'] == 1): raise O4Error('invalid_planner_capacity')
    groups, used = pools(state, req, ast, config)
    trace = {'evaluations': used, 'search_truncated': False}
    if method == 'buffer_search': selected, trace = search(state, req, ast, config, groups, used)
    elif method in ('single', 'buffer_fifo'): selected = groups[0]['selected'] if groups else None
    else:
        available = sorted((g for g in groups if g['selected'] is not None), key=lambda g: (len(g['evaluation']['allowed_ids']), -g['mass_kg'], g['arrival_index']))
        selected = available[0]['selected'] if available else None
    reason = None
    if selected is None:
        reason = 'fifo_head_blocked' if method == 'buffer_fifo' and any(g['selected'] for g in groups[1:]) else 'no_physical_candidate' if not any(g['candidates'] for g in groups) else 'no_compiled_business_candidate'
    return selected, groups, trace, reason


@lru_cache(maxsize=64)
def _cached(serialized): return _choose(*json.loads(serialized))


def choose(state, req, ast, config, method):
    validate(config); started = time.perf_counter(); hits = _cached.cache_info().hits
    public = {k: state[k] for k in PUBLIC_KEYS}
    result = copy.deepcopy(_cached(canonical([public, req, ast, config, method])))
    selected, groups, trace, reason = result; hit = _cached.cache_info().hits > hits
    if hit:
        for g in groups:
            g['generation']['elapsed_seconds'] = 0.
            g['generation']['generation_seconds'] = {'cache_hit': True, 'full_pool_quality_evaluations_executed': 0}
    trace.update(elapsed_seconds=time.perf_counter()-started, memoization_scope='capacity_b0_exact_public_request_ast_config_method_deepcopy',
                 generation_seconds={'cache_hit': hit})
    return result


def clear_cache(): _cached.cache_clear(); clear_candidates()
