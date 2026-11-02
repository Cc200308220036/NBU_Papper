"""用于评价和环境提交的独立状态转移与指标计算。

绝不使用生成器私有的 result_state 或 load_increments。
"""
import copy
import math
from .geometry_oracle import bounds, support_rect, propagate
from collections import defaultdict


def apply_candidate(case, candidate):
    placed = copy.deepcopy(case['placed_items'])
    item = copy.deepcopy(next(i for i in case['available_items'] if i['item_id']==candidate['pick_item_id']))
    cb = bounds(candidate)
    areas = []
    if cb[4]>0:
        for p in placed:
            pb = bounds(p)
            if abs(pb[5]-cb[4])>1e-6:
                continue
            rect = support_rect(cb,pb)
            if rect:
                areas.append((p['item_id'],(rect[1]-rect[0])*(rect[3]-rect[2])))
    total = sum(a for _,a in areas)
    fractions = [{'item_id':sid,'fraction':a/total} for sid,a in areas]
    increments = defaultdict(float)
    by_id = {p['item_id']:p for p in placed}
    for edge in fractions:
        propagate(edge['item_id'],item['mass_kg']*edge['fraction'],by_id,increments)
    for sid,value in increments.items():
        by_id[sid]['supported_load_kg'] += value
    item.update(pose=copy.deepcopy(candidate['pose']),oriented_size_mm=list(candidate['oriented_size_mm']),
                supported_load_kg=0.0,support_fractions=fractions)
    placed.append(item)
    return placed


def state_metrics(container,placed):
    volume = sum(math.prod(x['oriented_size_mm']) for x in placed)
    mass = sum(x['mass_kg'] for x in placed)
    cx = sum(x['mass_kg']*x['pose']['x_mm'] for x in placed)/mass if mass else 0
    cy = sum(x['mass_kg']*x['pose']['y_mm'] for x in placed)/mass if mass else 0
    supports=[]
    from .geometry_oracle import union_area
    for a in placed:
        if a['pose']['z_base_mm']<=0: continue
        ab=bounds(a); rects=[]
        for b in placed:
            if a is b: continue
            bb=bounds(b)
            if abs(bb[5]-ab[4])<1e-6:
                rect=support_rect(ab,bb)
                if rect: rects.append(rect)
        supports.append(union_area(rects)/(a['oriented_size_mm'][0]*a['oriented_size_mm'][1]))
    return dict(placed_count=len(placed), volume_utilization=volume/(container['length_mm']*container['width_mm']*container['max_height_mm']),
                max_height_mm=max((p['pose']['z_base_mm']+p['oriented_size_mm'][2] for p in placed),default=0),
                center_of_mass_offset_mm=math.hypot(cx,cy), minimum_support_ratio=min(supports,default=1.0),
                mean_support_ratio=sum(supports)/len(supports) if supports else 1.0, total_mass_kg=mass)
