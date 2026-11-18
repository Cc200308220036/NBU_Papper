"""Numerically stable layout ranking, isolated from all frozen v1 experiments.

The original control and anchor remain the frozen executor. Only relaxed ranking
changes: fsum mean, max-anchored 1e-12 ties at layout AND geometry tiers, then Cxx.
This tolerance never changes hard feasibility or the original soft budget test.
"""
from math import fsum, isfinite

from ..evaluation.attribute_metrics_v2 import transition
from ..evaluation.layout_preservation import layout_features
from ..evaluation.policy_v2 import EPS, evaluate, optimal_set
from .layout_preserving import SOFT_BUDGETS
from .policy_executor_v2 import execute_policy

VERSION = 'layout_preserving_v2_fsum_max_anchor_1e-12'
RANKING_EPS = 1e-12
VARIANTS = ('original', 'relaxed_geometry', 'relaxed_wo_floor')
COMPONENTS = ('support', 'capacity', 'height')


def stable_best(indices, score, epsilon=RANKING_EPS):
    """Anchor every comparison to the same maximum; no non-transitive comparator."""
    if epsilon < 0 or not isfinite(epsilon):
        raise ValueError('invalid ranking epsilon')
    indices = list(indices)
    values = {i: float(score(i)) for i in indices}
    if not values or not all(isfinite(v) for v in values.values()):
        raise ValueError('empty or non-finite ranking')
    best = max(values.values())
    return [i for i in indices if values[i] >= best-epsilon]


def layout_score(features):
    values = [float(features[k]) for k in COMPONENTS]
    if not all(isfinite(v) for v in values):
        raise ValueError('non-finite layout feature')
    return fsum(values)/len(values)


def select_layout(request, policy, variant, *, allow_business_violation=False):
    if variant not in VARIANTS:
        raise ValueError('unknown stable layout variant')
    baseline = execute_policy(request, policy, allow_business_violation=allow_business_violation)
    trace = {'variant': variant, 'baseline_label': baseline, 'soft_policy_relaxed': variant.startswith('relaxed_'),
        'budget_version': 'layout_soft_budget_v1', 'soft_budgets': dict(SOFT_BUDGETS),
        'ranking_version': VERSION, 'ranking_epsilon': RANKING_EPS,
        'anchor_executor': 'frozen_policy_executor_v2'}
    if baseline is None or variant == 'original':
        return baseline, trace
    candidates = request['candidates']
    values = [evaluate(request, c, policy, request['container']) for c in candidates]
    anchor = next(i for i, c in enumerate(candidates) if c['display_label'] == baseline)
    feasible = optimal_set(values)['feasible_indices']
    if feasible:
        pool = feasible
    else:
        def harm(i):
            v = values[i]
            return (v['new_business_violation_count']+v['worsened_existing_violation_count'],
                    v['post_business_violation_count'])
        best_harm = min(harm(i) for i in range(len(candidates)))
        pool = [i for i in range(len(candidates)) if harm(i) == best_harm]
    reference = values[anchor]['soft_quality']
    eligible = [i for i in pool if all(best is None or (
        values[i]['soft_quality'][j] is not None and
        values[i]['soft_quality'][j] >= best-SOFT_BUDGETS[p['metric']]-EPS)
        for j, (best, p) in enumerate(zip(reference, policy['soft_priorities'])))]
    if anchor not in eligible:
        raise ValueError('frozen anchor escaped original admissible pool')
    trace.update(eligible_labels=[candidates[i]['display_label'] for i in eligible],
        anchor_soft_quality=reference, business_feasible_pool=bool(feasible))
    scores = {}
    best = eligible
    if variant == 'relaxed_wo_floor':
        for i in eligible:
            _, after = transition(request, candidates[i])
            item = next(x for x in request['available_items'] if x['item_id'] == candidates[i]['pick_item_id'])
            features = layout_features(request['container'], after, policy, item['mass_kg'])
            scores[candidates[i]['display_label']] = {'features': features, 'score': layout_score(features)}
        best = stable_best(eligible, lambda i: scores[candidates[i]['display_label']]['score'])
        trace.update(components=list(COMPONENTS), layout_tie_labels=[candidates[i]['display_label'] for i in best])
    geometry = stable_best(best, lambda i: candidates[i]['geometry_score'])
    selected_index = min(geometry, key=lambda i: candidates[i]['display_label'])
    selected = candidates[selected_index]['display_label']
    trace.update(geometry_tie_labels=[candidates[i]['display_label'] for i in geometry],
        selected_soft_quality=values[selected_index]['soft_quality'],
        soft_loss_from_anchor=[None if a is None or b is None else max(0., a-b)
            for a, b in zip(reference, values[selected_index]['soft_quality'])],
        changed_from_original=selected != baseline, layout_scores=scores)
    return selected, trace
