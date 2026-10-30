"""Faithful bounded-search instrumentation for the predeclared T0 experiment.

No reference answers, arrival stream or source identifiers enter this module.
The historical comparator variants are diagnostic policies, not production defaults.
"""
import math
from collections import Counter, defaultdict

from ....common import digest, O4Error
from ....buffer.buffer_state import place
from ...e2 import planning as legacy
from ...e2.candidates import key
from ...e2.protocol import observation
from .....planner.scoring import geometry_score
from ..layout_v2 import planning as v2
from ..layout_v2.quality import measure


def pose(c):
    return [c['pick_item_id'], list(key(c)[:-1])]


def search(state, req, ast, config, candidate_policy, beam_policy, leaf_policy):
    """One logical search, <=256 evaluations; all diagnostic work is read only."""
    if candidate_policy not in ('legacy', 'B') or any(p not in ('legacy', 'v2') for p in (beam_policy, leaf_policy)):
        raise O4Error('invalid_diagnostic_policy')
    pools = legacy.pools if candidate_policy == 'legacy' else v2.pools
    before = digest(state)
    groups, used = pools(state, req, ast, config)
    root_groups = groups
    beam = [{'state': state, 'path': [], 'volume': 0., 'q': (0, 0, 0, 0), 'g': 0.}]
    leaves = []; nodes = []; levels = []; refusals = []; max_beam = 1
    exposures = defaultdict(lambda: {'evaluations': 0, 'expanded_depths': [], 'budget_not_expanded': 0})

    def path_key(n):
        return [(state['arrived_ids'].index(c['pick_item_id']), key(c)[:-1]) for c in n['path']]

    def rank(n, policy, final=False):
        base = (-len(n['path']), -n['volume'])
        height = max((p['pose']['z_base_mm']+p['oriented_size_mm'][2] for p in n['state']['placed_items']), default=0)
        if policy == 'v2': return (*base, *n['q'], height, -n['g'], path_key(n))
        return (*base, path_key(n)) if final else (*base, height, path_key(n))

    def record(n):
        path = [pose(c) for c in n['path']]
        return {'path': path, 'path_digest': digest(path), 'parent_path_digest': digest(path[:-1]) if path else None,
                'state_digest': digest(n['state']), 'root_action': path[0] if path else None,
                'depth': len(path), 'volume': n['volume'], 'height': max((p['pose']['z_base_mm']+p['oriented_size_mm'][2] for p in n['state']['placed_items']), default=0),
                'last_quality': n['q'], 'geometry': n['g'], 'beam_rank': rank(n, beam_policy),
                'leaf_rank': rank(n, leaf_policy, True)}

    for depth in range(min(3, len(state['pending_items']))):
        children = []; expanded = 0
        for n in beam:
            root = digest(pose(n['path'][0])) if n['path'] else 'ROOT'
            reserve = 16*len(n['state']['pending_items'])
            spent_before = used
            if depth:
                if used+reserve > 256:
                    refusals.append({**record(n), 'reason': 'budget_not_expanded', 'spent': used, 'remaining': 256-used, 'required_upper_bound': reserve})
                    exposures[root]['budget_not_expanded'] += 1
                    leaves.append(n); continue
                subreq = observation(n['state'], req['instruction_text'], req['regions'])
                groups, cost = pools(n['state'], subreq, ast, config); used += cost
            else: groups = root_groups; cost = used
            expanded += 1
            exposures[root]['evaluations'] += cost
            exposures[root]['expanded_depths'].append(depth)
            group_records = []
            for g in groups:
                allowed = set(g['evaluation']['allowed_ids']); eligible = set(g['trace']['eligible_labels'])
                group_records.append({'pick': g['pick_item_id'], 'generation': g['generation'],
                    'soft_budgets': g['trace']['soft_budgets'], 'candidates': [
                        {'candidate': c, 'pose': pose(c), 'status': 'hard_rejected' if c['candidate_id'] not in allowed else 'soft_ineligible' if c['candidate_id'] not in eligible else 'eligible'} for c in g['candidates']]})
            viable = [c for g in groups for c in g['eligible']]
            nodes.append({**record(n), 'groups': group_records, 'candidate_count': cost,
                          'spent_before': spent_before if depth else 0, 'spent_after': used,
                          'required_upper_bound': reserve, 'remaining': 256-used,
                          'reason': 'expanded' if viable else 'terminal_no_action'})
            if not viable: leaves.append(n)
            for c in sorted(viable, key=lambda c: (next(g['arrival_index'] for g in groups if g['pick_item_id'] == c['pick_item_id']), key(c))):
                # Measure even for legacy rank so saved vectors can be compared. It
                # has no AST evaluation, random state or mutation and never enters
                # a legacy key. No further search or trial placement is performed.
                q = v2.quality_key(measure(n['state'], c))
                children.append({'state': place(n['state'], c), 'path': n['path']+[c],
                                 'volume': n['volume']+math.prod(c['oriented_size_mm']), 'q': q, 'g': geometry_score(c)})
        if not children: break
        ordered = sorted(children, key=lambda n: rank(n, beam_policy))
        beam = ordered[:8]; max_beam = max(max_beam, len(beam))
        boundary = rank(beam[-1], beam_policy)
        names = ['count', 'volume', 'side_contact', 'aligned_contact', 'narrow_area', 'free_runs', 'height', 'geometry', 'stable_path'] if beam_policy == 'v2' else ['count', 'volume', 'height', 'stable_path']
        rows = []
        for i, n in enumerate(ordered):
            r = rank(n, beam_policy)
            first = next((k for k, a, b in zip(names, boundary, r) if a != b), 'exact_tie')
            rows.append({**record(n), 'status': 'survived' if i < 8 else 'beam_pruned', 'first_difference_from_boundary': first})
        levels.append({'depth': depth, 'generated': len(children), 'expanded': expanded,
                       'spent': used, 'remaining': 256-used, 'children': rows})
    leaves.extend(beam)
    best = min(leaves, key=lambda n: rank(n, leaf_policy, True))
    if used > 256 or digest(state) != before: raise O4Error('diagnostic_search_invariant')
    tree = {'nodes': [(n['path'], [[c['pose'], c['status']] for g in n['groups'] for c in g['candidates']], n['spent_after']) for n in nodes],
            'survivors': [[c['path'] for c in l['children'] if c['status'] == 'survived'] for l in levels],
            'refusals': [r['path'] for r in refusals]}
    return {'candidate_policy': candidate_policy, 'beam_policy': beam_policy, 'leaf_policy': leaf_policy,
            'selected': pose(best['path'][0]) if best['path'] else None, 'chosen_path': [pose(c) for c in best['path']],
            'evaluations': used, 'nodes': nodes, 'levels': levels, 'budget_refusals': refusals,
            'leaves': [{**record(n), 'reason': 'depth_limit' if len(n['path']) == min(3, len(state['pending_items'])) else 'see_node_or_budget_refusal'} for n in leaves],
            'root_exposure': dict(exposures), 'max_beam_observed': max_beam,
            'expanded_depth_distribution': dict(Counter(n['depth'] for n in nodes)),
            'tree_digest': digest(tree), 'root_unchanged': digest(state) == before,
            'new_api_attempts': 0}
