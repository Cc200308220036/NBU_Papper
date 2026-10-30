import math
import statistics
from collections import defaultdict
import numpy as np
from .geometry_oracle import check_candidate
from .state import state_metrics,apply_candidate
from ..planner.scoring import geometry_score


def evaluate_fixed(request,candidate,oracle):
    by_id={x['candidate_id']:x for x in oracle['candidate_evaluations']}
    chosen=by_id[candidate['candidate_id']]; best=by_id[oracle['oracle_candidate_id']]
    errors=check_candidate(request,{'container':request['container']},candidate)
    after=apply_candidate(request,candidate)
    metrics=state_metrics(request['container'],after)
    metrics.update(hard_violations=len(errors),semantic_hard_violations=len(chosen['hard_violations']),
        soft_utility=chosen['soft_utility'],oracle_regret=best['soft_utility']-chosen['soft_utility'],
        oracle_hard_violation_regret=len(chosen['hard_violations'])-len(best['hard_violations']),
        oracle_hit=candidate['candidate_id']==oracle['oracle_candidate_id'],
        semantic_decision_required=oracle['semantic_decision_required'],geometry_score=geometry_score(candidate))
    return metrics,after


def describe(values,seed=0):
    a=np.asarray(values,dtype=float)
    rng=np.random.default_rng(seed)
    means=np.mean(rng.choice(a,size=(1000,len(a)),replace=True),axis=1)
    return dict(n=len(values),mean=float(a.mean()),median=float(np.median(a)),
                std=float(a.std(ddof=1)) if len(a)>1 else 0.0,
                ci95=[float(x) for x in np.quantile(means,[0.025,0.975])],
                p50=float(np.quantile(a,.5)),p95=float(np.quantile(a,.95)),maximum=float(a.max()))


def aggregate(decisions,episodes,seed):
    result={'ci_method':'deterministic percentile bootstrap, 1000 resamples; fixed DC CIs use scenario-cluster means', 'groups':[]}
    for track,rows in [('fixed',decisions),('episode',episodes)]:
        groups=defaultdict(list)
        for row in rows:groups[(row['method'],row['split'])].append(row)
        for (method,split),group in sorted(groups.items()):
            numeric=sorted({k for r in group for k,v in r.items() if isinstance(v,(int,float,bool))})
            stats={}
            for k in numeric:
                values=[float(r[k]) for r in group if isinstance(r.get(k),(int,float,bool))]
                if not values:continue
                stats[k]=describe(values,seed)
                if track=='fixed':
                    clusters=defaultdict(list)
                    for r in group:
                        if isinstance(r.get(k),(int,float,bool)):clusters[r['scenario_id']].append(float(r[k]))
                    stats[k]['ci95']=describe([statistics.mean(v) for v in clusters.values()],seed)['ci95']
                    stats[k]['ci_cluster_count']=len(clusters)
            nontrivial=[r for r in group if r.get('semantic_decision_required')]
            result['groups'].append(dict(track=track,method=method,split=split,n=len(group),metrics=stats,
                nontrivial_count=len(nontrivial),nontrivial_oracle_hit_rate=statistics.mean(float(r['oracle_hit']) for r in nontrivial) if nontrivial else None))
    return result
