"""Post-decision coverage diagnostics. Never imported by selection/planning."""
import copy
import json
from functools import lru_cache
from ...common import canonical
from ..e2.reference import audit
from ..e2.runtime import evaluate_candidates


def _compute(req,ast,reference_policy,groups,trace,reason):
    rows=[]
    for g in groups:
        samples=g['generation']['public_enumerated_candidates']
        method=audit(req,ast,samples)['allowed_ids'];reference=audit(req,reference_policy,samples)['allowed_ids']
        reference_top=audit(req,reference_policy,g['candidates'])['allowed_ids']
        base=evaluate_candidates(req,ast,g['generation']['baseline_candidates'])['allowed_ids']
        rows.append({'pick_item_id':g['pick_item_id'],'returned_candidates':len(g['candidates']),
                     'sampled_physical_candidates':len(samples),'topk_truncated':g['generation']['topk_truncated'],
                     'method_topk_allowed':len(g['evaluation']['allowed_ids']),'reference_topk_allowed':len(reference_top),
                     'method_sampled_allowed':len(method),'reference_sampled_allowed':len(reference),
                     'topk_coverage_limited':not g['evaluation']['allowed_ids'] and bool(method),
                     'baseline_allowed':len(base),'public_enumeration_attempts':g['generation']['public_enumeration_attempts'],
                     'generation_seconds':g['generation'].get('elapsed_seconds',0.),
                     'scope':'public_sampled_pool_not_continuous_feasibility'})
    return {'termination_reason':reason,'groups':rows,'search_truncated':trace.get('search_truncated',False),
            'fifo_head_blocked':reason=='fifo_head_blocked',
            'sampled_physical_empty':not any(r['sampled_physical_candidates'] for r in rows),
            'method_topk_empty':not any(r['method_topk_allowed'] for r in rows),
            'reference_topk_empty':not any(r['reference_topk_allowed'] for r in rows),
            'topk_coverage_limited':any(r['topk_coverage_limited'] for r in rows),
            'global_infeasibility':'NOT_PROVEN'}


def _stable(value):
    if isinstance(value,dict):return {k:_stable(v) for k,v in value.items() if k not in ('elapsed_seconds','generation_seconds')}
    if isinstance(value,list):return [_stable(v) for v in value]
    return value


@lru_cache(maxsize=64)
def _cached(serialized):return _compute(*json.loads(serialized))


def diagnose(req,ast,reference_policy,groups,trace,reason):
    # Private reference is used exclusively by this downstream audit; selection
    # has its own cache/module and never imports or consumes this result.
    key=canonical(_stable([req,ast,reference_policy,groups,trace,reason]))
    result=copy.deepcopy(_cached(key))
    for row,group in zip(result['groups'],groups):row['generation_seconds']=group['generation']['elapsed_seconds']
    return result
