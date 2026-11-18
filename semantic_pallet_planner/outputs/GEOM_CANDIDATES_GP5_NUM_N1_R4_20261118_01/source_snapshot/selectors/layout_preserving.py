"""Versioned ablations: original hard tiers, explicit soft budgets, public facts.

Relaxed variants are NEW soft-objective policies, not exact compliance with the
old lexicographic instruction. Budget comparison is anchored to its original
choice, so the original action always remains admissible.
"""
from ..evaluation.attribute_metrics_v2 import transition
from ..evaluation.layout_preservation import COMPONENTS, layout_features, layout_score
from ..evaluation.policy_v2 import EPS, evaluate, optimal_set
from .policy_executor_v2 import execute_policy

VARIANTS = ('original','strict_layout','relaxed_geometry','relaxed_full',
            'relaxed_wo_floor','relaxed_wo_support','relaxed_wo_capacity',
            'relaxed_wo_height','relaxed_floor_only')
SOFT_BUDGETS = {'heavy_low':.05,'heavy_center':.25}


def select_layout(request, policy, variant, *, allow_business_violation=False):
    if variant not in VARIANTS:
        raise ValueError('unknown layout variant')
    baseline=execute_policy(request,policy,allow_business_violation=allow_business_violation)
    trace={'variant':variant,'baseline_label':baseline,'soft_policy_relaxed':variant.startswith('relaxed_'),
           'budget_version':'layout_soft_budget_v1','soft_budgets':dict(SOFT_BUDGETS)}
    if baseline is None or variant=='original':
        return baseline,trace
    cs=request['candidates']
    values=[evaluate(request,c,policy,request['container']) for c in cs]
    anchor=next(i for i,c in enumerate(cs) if c['display_label']==baseline)
    feasible=optimal_set(values)['feasible_indices']
    if feasible:
        pool=feasible
    else:
        def harm(i):
            e=values[i]
            return (e['new_business_violation_count']+e['worsened_existing_violation_count'],
                    e['post_business_violation_count'])
        best_harm=min(harm(i) for i in range(len(cs)))
        pool=[i for i in range(len(cs)) if harm(i)==best_harm]
    if variant=='strict_layout':
        if feasible:
            eligible=optimal_set(values)['equivalent_indices']
        else:
            # Match the original diagnostic fallback's exact soft ordering.
            def soft(i):
                return tuple(-(q if q is not None else 0.) for q in values[i]['soft_quality'])
            best=min(soft(i) for i in pool)
            eligible=[i for i in pool if soft(i)==best]
    else:
        reference=values[anchor]['soft_quality']
        eligible=[i for i in pool if all(
            best is None or (values[i]['soft_quality'][j] is not None and
                values[i]['soft_quality'][j]>=best-SOFT_BUDGETS[p['metric']]-EPS)
            for j,(best,p) in enumerate(zip(reference,policy['soft_priorities'])))]
        assert anchor in eligible
    trace.update(eligible_labels=[cs[i]['display_label'] for i in eligible],
                 anchor_soft_quality=values[anchor]['soft_quality'],
                 business_feasible_pool=bool(feasible))
    scores={}
    if variant=='relaxed_geometry':
        index=min(eligible,key=lambda i:(-cs[i]['geometry_score'],cs[i]['display_label']))
    elif len(eligible)==1:
        index=eligible[0]
    else:
        parts=COMPONENTS
        if variant=='relaxed_floor_only':
            parts=('floor',)
        elif variant.startswith('relaxed_wo_'):
            parts=tuple(k for k in COMPONENTS if k!=variant.removeprefix('relaxed_wo_'))
        for i in eligible:
            _,after=transition(request,cs[i])
            item=next(x for x in request['available_items'] if x['item_id']==cs[i]['pick_item_id'])
            features=layout_features(request['container'],after,policy,item['mass_kg'])
            scores[cs[i]['display_label']]={'features':features,'score':layout_score(features,parts)}
        index=min(eligible,key=lambda i:(-scores[cs[i]['display_label']]['score'],
                                         -cs[i]['geometry_score'],cs[i]['display_label']))
        trace['components']=list(parts)
    selected=cs[index]['display_label']
    trace.update(selected_soft_quality=values[index]['soft_quality'],
                 soft_loss_from_anchor=[None if a is None or b is None else max(0.,a-b)
                       for a,b in zip(values[anchor]['soft_quality'],values[index]['soft_quality'])],
                 changed_from_original=selected!=baseline,layout_scores=scores)
    return selected,trace
