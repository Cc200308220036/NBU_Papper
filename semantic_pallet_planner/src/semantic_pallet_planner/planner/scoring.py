"""所有目标都在 [0,1] 区间内取最大值；权重在测试评价前固定。"""
WEIGHTS = {'compactness':0.35, 'height':0.25, 'stability':0.25, 'balance':0.15}


def geometry_score(candidate, weights=None):
    return round(sum(candidate['geometry_score_components'][k]*v for k,v in (weights or WEIGHTS).items()),9)


def pareto_candidates(candidates):
    keys = tuple(WEIGHTS)
    return [a for a in candidates if not any(
        all(b['geometry_score_components'][k]>=a['geometry_score_components'][k] for k in keys)
        and any(b['geometry_score_components'][k]>a['geometry_score_components'][k] for k in keys)
        for b in candidates)]
