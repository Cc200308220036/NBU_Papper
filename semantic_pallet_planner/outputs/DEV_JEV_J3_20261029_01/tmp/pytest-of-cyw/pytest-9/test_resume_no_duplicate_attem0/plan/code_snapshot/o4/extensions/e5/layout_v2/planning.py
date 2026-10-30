"""Independent position ranking and bounded search; original semantics reused."""
import copy
import json
import math
import time
from functools import lru_cache
from ....common import canonical, digest, O4Error
from ....buffer.buffer_state import place, ordered
from ...e2.planning import select_layout as original_select, METHODS, SEARCH
from ...e2.protocol import observation
from .....planner.scoring import geometry_score
from .candidates import generate, key, clear_cache as clear_candidates
from .quality import measure
from .config import validate

PUBLIC_KEYS = ('container', 'buffer_capacity', 'pending_items', 'placed_items', 'arrived_ids',
               'attributes', 'event_index', 'arrival_count', 'placed_count', 'end_of_stream')


def quality_key(q):
    return (-q['side_contact_ratio'], -q['aligned_contact_ratio'],
            round(q['narrow_free_area_fraction'], 12), round(q['extra_free_runs'], 12))


def select_layout(state, req, ast, candidates, config):
    chosen, trace, evaluated = original_select(req, ast, candidates)
    if not config['o4_e5_layout']['ranking'] or chosen is None: return chosen, trace, evaluated
    eligible = [c for c in candidates if c['candidate_id'] in trace['eligible_labels']]
    qualities = {c['candidate_id']: measure(state, c) for c in eligible}
    chosen = min(eligible, key=lambda c: (*quality_key(qualities[c['candidate_id']]), -geometry_score(c), key(c)))
    trace.update(ranking_version='layout_v2_contact_fragment_v1', qualities=qualities,
                 position_quality_evaluations=len(eligible),
                 selected_label=chosen['candidate_id'], rank_order=config['o4_e5_layout']['position_rank'],
                 remaining_capacity_prediction='NOT_IMPLEMENTED', business_support_quality='NOT_IMPLEMENTED')
    chosen_rank = (*quality_key(qualities[chosen['candidate_id']]), -geometry_score(chosen), key(chosen))
    trace['first_differing_rank_component'] = {}
    for c in eligible:
        rank = (*quality_key(qualities[c['candidate_id']]), -geometry_score(c), key(c))
        differing = next((name for name, a, b in zip(trace['rank_order'], chosen_rank, rank) if a != b), 'selected_or_exact_tie')
        trace['first_differing_rank_component'][c['candidate_id']] = differing
    return chosen, trace, evaluated


def pools(state, req, ast, config):
    groups = []; used = 0
    for pending in ordered(state):
        pick = pending['item']['item_id']; candidates, generation = generate(state, pick, req['regions'], config)
        selected, trace, evaluated = select_layout(state, req, ast, candidates, config)
        eligible = [c for c in candidates if c['candidate_id'] in trace['eligible_labels']]
        groups.append({'pick_item_id': pick, 'arrival_index': pending['arrival_index'], 'mass_kg': pending['item']['mass_kg'],
                       'candidates': candidates, 'generation': generation, 'selected': selected,
                       'eligible': eligible, 'trace': trace, 'evaluation': evaluated})
        used += len(candidates)
    return groups, used


def search(state, req, ast, config, root_groups, root_used):
    cfg = validate(config['o4_e5_layout']); before = digest(state); used = root_used
    truncated = False; beam = [{'state': state, 'path': [], 'volume': 0., 'last_quality': (0, 0, 0, 0), 'geometry': 0.}]
    leaves = []; nodes = []; generated = pruned = 0; full_quality_work = 0; generation_seconds = 0.
    full_quality_executed = position_quality_work = 0
    def path_key(node):
        return [(state['arrived_ids'].index(c['pick_item_id']), key(c)[:-1]) for c in node['path']]
    def rank(node, final=False):
        base = (-len(node['path']), -node['volume'])
        height = max((o['pose']['z_base_mm']+o['oriented_size_mm'][2] for o in node['state']['placed_items']), default=0)
        if cfg['ranking']:
            return (*base, *node['last_quality'], height, -node['geometry'], path_key(node))
        return (*base, path_key(node)) if final else (*base, height, path_key(node))
    for depth in range(min(3, len(state['pending_items']))):
        children = []
        for node in beam:
            if not depth: groups = root_groups
            else:
                if used+16*len(node['state']['pending_items']) > 256:
                    truncated = True; leaves.append(node); continue
                subreq = observation(node['state'], req['instruction_text'], req['regions'])
                groups, cost = pools(node['state'], subreq, ast, config); used += cost
            full_quality_work += sum(g['generation'].get('full_pool_quality_evaluations', 0) for g in groups)
            full_quality_executed += sum(g['generation'].get('generation_seconds', {}).get('full_pool_quality_evaluations_executed', 0) for g in groups)
            position_quality_work += sum(g['trace'].get('position_quality_evaluations', 0) for g in groups)
            generation_seconds += sum(g['generation']['elapsed_seconds'] for g in groups)
            viable = [c for g in groups for c in g['eligible']]
            nodes.append({'depth': depth, 'state_digest': digest(node['state']), 'candidate_count': sum(len(g['candidates']) for g in groups)})
            if not viable: leaves.append(node)
            for c in sorted(viable, key=lambda c: (next(g['arrival_index'] for g in groups if g['pick_item_id'] == c['pick_item_id']), key(c))):
                q = measure(node['state'], c) if cfg['ranking'] else None
                children.append({'state': place(node['state'], c), 'path': node['path']+[c],
                                 'volume': node['volume']+math.prod(c['oriented_size_mm']),
                                 'last_quality': quality_key(q) if q else (0, 0, 0, 0), 'geometry': geometry_score(c)})
        if not children: break
        generated += len(children); pruned += max(0, len(children)-8)
        beam = sorted(children, key=rank)[:8]
    leaves.extend(beam); best = min(leaves, key=lambda n: rank(n, final=True))
    if used > 256 or digest(state) != before: raise O4Error('layout_search_invariant')
    return (best['path'][0] if best['path'] else None), {
        'config': SEARCH, 'evaluations': used, 'search_truncated': truncated, 'nodes': nodes,
        'chosen_path': [c['candidate_id'] for c in best['path']], 'max_depth': max(len(n['path']) for n in leaves),
        'max_beam': min(8, len(beam)), 'before_real_state': before, 'after_real_state': digest(state),
        'ranking_version': 'layout_v2_unified_path_v1' if cfg['ranking'] else 'e2_count_volume_stable_v1',
        'beam_and_final_rank_identical': cfg['ranking'], 'generated_children': generated, 'pruned_children': pruned,
        'full_pool_quality_evaluations_logical': full_quality_work,
        'position_quality_evaluations_logical': position_quality_work,
        'path_quality_evaluations_logical': generated if cfg['ranking'] else 0,
        'generation_seconds': {'sampling_seconds': generation_seconds,
                               'full_pool_quality_evaluations_executed': full_quality_executed}}


def _choose(state, req, ast, config, method):
    validate(config['o4_e5_layout'])
    if method not in METHODS or (method == 'single') != (state['buffer_capacity'] == 1): raise O4Error('invalid_planner_capacity')
    groups, used = pools(state, req, ast, config); trace = {'evaluations': used, 'search_truncated': False}
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
    started = time.perf_counter(); public = {k: state[k] for k in PUBLIC_KEYS}; hits = _cached.cache_info().hits
    selected, groups, trace, reason = copy.deepcopy(_cached(canonical([public, req, ast, config, method])))
    hit = _cached.cache_info().hits > hits
    if hit:
        for g in groups:
            g['generation']['elapsed_seconds'] = 0.
            g['generation']['generation_seconds'] = {'cache_hit': True, 'full_pool_quality_evaluations_executed': 0}
    runtime = trace.get('generation_seconds', {})
    trace['generation_seconds'] = {'cache_hit': hit, 'sampling_seconds': 0. if hit else runtime.get('sampling_seconds', 0.),
                                  'full_pool_quality_evaluations_executed': 0 if hit else runtime.get('full_pool_quality_evaluations_executed',
                                  sum(g['generation'].get('generation_seconds', {}).get('full_pool_quality_evaluations_executed', 0) for g in groups))}
    trace.update(elapsed_seconds=time.perf_counter()-started,
                 memoization_scope='layout_v2_exact_public_request_ast_config_method_deepcopy')
    return selected, groups, trace, reason


def clear_cache():
    _cached.cache_clear(); clear_candidates()
