"""E2 fixed ranking, bounded buffer planning, bound commits, no reference AST."""
import copy
import math
from ...common import O4Error, digest
from ...online.planner_adapter import soft_quality
from ....planner.scoring import geometry_score
from ...buffer.buffer_state import place, ordered
from .protocol import observation, validate_response, validate_candidates, BINDINGS
from .runtime import evaluate_candidates
from .candidates import generate, key

METHODS = ('single', 'buffer_fifo', 'buffer_heuristic', 'buffer_search')
SEARCH = {'search_depth': 3, 'beam_width': 8, 'max_successor_evaluations': 256}


def select_layout(req, ast, candidates):
    evaluated = evaluate_candidates(req, ast, candidates)
    feasible = [c for c in candidates if c['candidate_id'] in evaluated['allowed_ids']]
    trace = {'hard_feasible_labels': evaluated['allowed_ids'], 'soft_order': ['heavy_low', 'heavy_center'],
             'soft_budgets': [.05, .25], 'eligible_labels': [], 'anchor_label': None}
    if not feasible:
        return None, trace, evaluated
    quality = {c['candidate_id']: soft_quality(req, c) for c in feasible}
    strict = feasible
    for tier in (0, 1):
        values = [quality[c['candidate_id']][tier] for c in strict if quality[c['candidate_id']][tier] is not None]
        if values:
            best = max(values)
            strict = [c for c in strict if quality[c['candidate_id']][tier] is not None and quality[c['candidate_id']][tier] >= best-1e-6]
    # Stable public pose labels, independent of item-ID hash tie breaks.
    anchor = min(strict, key=lambda c: (-geometry_score(c), key(c)))
    a = quality[anchor['candidate_id']]
    eligible = [c for c in feasible if all(v is None or (q is not None and q >= v-b-1e-6)
                for v, q, b in zip(a, quality[c['candidate_id']], (.05, .25)))]
    maximum = max(geometry_score(c) for c in eligible)
    chosen = min((c for c in eligible if geometry_score(c) >= maximum-1e-12), key=key)
    trace.update(anchor_label=anchor['candidate_id'], eligible_labels=[c['candidate_id'] for c in eligible], soft_values=quality)
    return chosen, trace, evaluated


def pools(state, req, ast, config):
    groups, evaluations = [], 0
    for p in ordered(state):
        pick = p['item']['item_id']
        candidates, generation = generate(state, pick, req['regions'], config)
        selected, trace, evaluated = select_layout(req, ast, candidates)
        eligible = [c for c in candidates if c['candidate_id'] in trace['eligible_labels']]
        evaluations += len(candidates)
        groups.append({'pick_item_id': pick, 'arrival_index': p['arrival_index'], 'mass_kg': p['item']['mass_kg'],
                       'candidates': candidates, 'generation': generation, 'selected': selected,
                       'eligible': eligible, 'trace': trace, 'evaluation': evaluated})
    return groups, evaluations


def search(state, req, ast, config, root_groups, root_used, search_config=None):
    cfg = dict(SEARCH if search_config is None else search_config)
    if (set(cfg) != set(SEARCH) or any(type(v) is not int for v in cfg.values())
            or not 1 <= cfg['search_depth'] <= 3 or not 1 <= cfg['beam_width'] <= 8
            or not 16*state['buffer_capacity'] <= cfg['max_successor_evaluations'] <= 256):
        raise O4Error('invalid_search_config')
    before = digest(state); used = root_used; truncated = False
    def path_key(node):
        return [(state['arrived_ids'].index(c['pick_item_id']),key(c)[:-1]) for c in node['path']]
    beam = [{'state': state, 'path': [], 'volume': 0.}]; leaves = []; nodes = []
    for depth in range(min(cfg['search_depth'], len(state['pending_items']))):
        children = []
        for n in beam:
            if not depth:
                groups = root_groups
            else:
                reserve = 16*len(n['state']['pending_items'])
                if used+reserve > cfg['max_successor_evaluations']:
                    truncated = True; leaves.append(n); continue
                subreq = observation(n['state'], req['instruction_text'], req['regions'])
                groups, cost = pools(n['state'], subreq, ast, config); used += cost
            viable = [c for g in groups for c in g['eligible']]
            nodes.append({'depth': depth, 'state_digest': digest(n['state']), 'candidate_count': sum(len(g['candidates']) for g in groups)})
            if not viable:
                leaves.append(n)
            for c in sorted(viable, key=lambda c: (next(g['arrival_index'] for g in groups if g['pick_item_id']==c['pick_item_id']), key(c))):
                after = place(n['state'], c)
                children.append({'state': after, 'path': n['path']+[c], 'volume': n['volume']+math.prod(c['oriented_size_mm'])})
        if not children:
            break
        def rank(n):
            return (-len(n['path']), -n['volume'], max((p['pose']['z_base_mm']+p['oriented_size_mm'][2] for p in n['state']['placed_items']), default=0),
                    path_key(n))
        beam = sorted(children, key=rank)[:cfg['beam_width']]
    leaves.extend(beam)
    best = min(leaves, key=lambda n: (-len(n['path']), -n['volume'], path_key(n)))
    if digest(state) != before or used > cfg['max_successor_evaluations']:
        raise O4Error('search_invariant')
    return (best['path'][0] if best['path'] else None), {'config': cfg, 'evaluations': used,
        'search_truncated': truncated, 'nodes': nodes, 'chosen_path': [c['candidate_id'] for c in best['path']],
        'max_depth': max((len(n['path']) for n in leaves), default=0), 'max_beam': min(cfg['beam_width'], len(beam)),
        'before_real_state': before, 'after_real_state': digest(state), 'ranking_version': 'e2_count_volume_stable_v1'}


def choose(state, req, ast, config, method):
    if method not in METHODS or (method == 'single') != (state['buffer_capacity'] == 1):
        raise O4Error('invalid_planner_capacity')
    groups, used = pools(state, req, ast, config)
    trace = {'evaluations': used, 'search_truncated': False}
    if method == 'buffer_search':
        selected, trace = search(state, req, ast, config, groups, used)
    elif method in ('single', 'buffer_fifo'):
        selected = groups[0]['selected'] if groups else None
    else:
        available = sorted((g for g in groups if g['selected'] is not None),
                           key=lambda g: (len(g['evaluation']['allowed_ids']), -g['mass_kg'], g['arrival_index']))
        selected = available[0]['selected'] if available else None
    reason = None
    if selected is None:
        if method == 'buffer_fifo' and any(g['selected'] for g in groups[1:]):
            reason = 'fifo_head_blocked'
        elif not any(g['candidates'] for g in groups):
            reason = 'no_physical_candidate'
        else:
            reason = 'no_compiled_business_candidate'
    return selected, groups, trace, reason


def action_for(req, candidates, selected):
    return {**{k: req[k] for k in BINDINGS}, 'candidate_set_digest': digest(candidates),
            'candidate_id': selected['candidate_id']}


def commit(state, regions, req, response, candidates, action):
    rebuilt = observation(state, req['instruction_text'], regions, req['images'])
    if rebuilt != req:
        raise O4Error('invalid_binding', 'current public state differs')
    validate_response(response, req)
    validate_candidates(req,candidates)
    if any(action.get(k) != req[k] for k in BINDINGS) or action.get('candidate_set_digest') != digest(candidates):
        raise O4Error('invalid_binding', 'stale action/candidate pool')
    found = [c for c in candidates if c['candidate_id'] == action.get('candidate_id')]
    if len(found) != 1:
        raise O4Error('invalid_candidate')
    allowed = evaluate_candidates(req, response['policy_ast'], found)['allowed_ids']
    if not allowed:
        raise O4Error('business_rejection')
    return place(state, found[0])
