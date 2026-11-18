"""Current-state layout proxies; no future arrivals or private candidate scores.

Scores are normalized geometric heuristics, not feasibility certificates. Full
physical and business checks remain the responsibility of the original layers.
"""
from functools import lru_cache
import json

import numpy as np

from .attribute_metrics_v2 import box_bounds, reconstruct
from .policy_v2 import matches
from ..protocol import canonical_json

PROBE_FRACTIONS = ((.25, .25), (.5, .25), (.5, .5))
MIN_HEADROOM_FRACTION = .1
COMPONENTS = ('floor', 'support', 'capacity', 'height')


def rectangle_quality(mask, xs, ys, probes):
    """Exact edge-aligned rectangles; count aspect-sensitive reference fits."""
    best = 0.
    fits = [False]*len(probes)
    for left in range(len(xs)-1):
        available = np.ones(len(ys)-1, dtype=bool)
        for right in range(left+1, len(xs)):
            available &= mask[right-1]
            edges = np.flatnonzero(np.diff(np.r_[False, available, False]))
            width = xs[right]-xs[left]
            for lo,hi in zip(edges[::2],edges[1::2]):
                depth = ys[hi]-ys[lo]
                best = max(best,width*depth)
                for k,(l,w) in enumerate(probes):
                    fits[k] |= (width+1e-9>=l and depth+1e-9>=w) or (width+1e-9>=w and depth+1e-9>=l)
    return float(best), sum(fits)/len(fits)


@lru_cache(maxsize=16384)
def _features(payload):
    value=json.loads(payload)
    container,placed,policy,mass = (value[k] for k in ('container','placed','policy','mass'))
    L,W,H=(container[k] for k in ('length_mm','width_mm','max_height_mm'))
    b=[box_bounds(p) for p in placed]
    xs=sorted({-L/2,L/2}|{x for bounds in b for x in bounds[:2]})
    ys=sorted({-W/2,W/2}|{y for bounds in b for y in bounds[2:4]})
    heights=np.zeros((len(xs)-1,len(ys)-1))
    owner=np.full(heights.shape,-1,dtype=int)
    for k,bounds in enumerate(b):
        x0,x1,y0,y1,_,z1=bounds
        ix,jx=xs.index(x0),xs.index(x1)
        iy,jy=ys.index(y0),ys.index(y1)
        sub=heights[ix:jx,iy:jy]
        higher=z1>sub
        owner[ix:jx,iy:jy][higher]=k
        sub[higher]=z1
    probes=[(L*l,W*w) for l,w in PROBE_FRACTIONS]
    floor_area,floor_fit=rectangle_quality(heights==0,xs,ys,probes)
    rebuilt=reconstruct(placed)
    stackable=np.zeros(heights.shape,dtype=bool)
    capacity=np.zeros(heights.shape)
    for k,p in enumerate(rebuilt):
        if not p['stackable']:
            continue
        mask=(owner==k)&(H-heights>=H*MIN_HEADROOM_FRACTION)
        stackable |= mask
        remaining=max(0.,p['top_load_limit_kg_synthetic']-p['supported_load_kg'])
        for rule in policy['hard_constraints']:
            if rule['type']=='fragile_load_limit' and matches(p,rule['selector']):
                remaining=min(remaining,max(0.,rule['threshold_kg']-p['supported_load_kg']))
        capacity[mask]=min(1.,remaining/max(mass,1e-9))
    support_area=0.;support_fit=0.
    for z in np.unique(heights[stackable]):
        area,fit=rectangle_quality(stackable&(heights==z),xs,ys,probes)
        if .5*area/(L*W)+.5*fit > .5*support_area/(L*W)+.5*support_fit:
            support_area,support_fit=area,fit
    weights=np.outer(np.diff(xs),np.diff(ys))
    return {'floor':.5*floor_area/(L*W)+.5*floor_fit,
            'support':.5*support_area/(L*W)+.5*support_fit,
            'capacity':float((weights*capacity).sum()/(L*W)),
            'height':max(0.,1.-float(heights.max())/H),
            'largest_floor_rectangle_mm2':floor_area,
            'floor_probe_fit_fraction':floor_fit,
            'best_support_rectangle_mm2':support_area,
            'support_probe_fit_fraction':support_fit}


def layout_features(container, placed, policy, current_mass_kg):
    # Return a fresh dictionary so caller mutation cannot corrupt the cache.
    return dict(_features(canonical_json({'container':container,'placed':placed,
                 'policy':policy,'mass':current_mass_kg})))


def layout_score(features, components=COMPONENTS):
    if not components or any(k not in COMPONENTS for k in components):
        raise ValueError('unknown/empty layout components')
    return sum(features[k] for k in components)/len(components)
