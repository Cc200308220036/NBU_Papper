"""Exact public geometry measurements; no probes, loads or future prediction."""
from .....planner.constraints import rectangle_union_area

EPS = 1e-6
NARROW_MM = 100.0  # Declared geometric scale, independent of the 305/295 example.


def bounds(obj):
    p = obj['pose']; dx, dy, dz = obj['oriented_size_mm']
    return (p['x_mm']-dx/2, p['x_mm']+dx/2,
            p['y_mm']-dy/2, p['y_mm']+dy/2,
            p['z_base_mm'], p['z_base_mm']+dz)


def union_length(intervals):
    total = 0.; end = None
    for a, b in sorted(intervals):
        if b <= a: continue
        total += b-max(a, end if end is not None else a) if end is None or b > end else 0
        end = b if end is None else max(end, b)
    return total


def free_runs(lo, hi, intervals):
    cursor = lo; result = []
    for a, b in sorted(intervals):
        a, b = max(a, lo), min(b, hi)
        if b <= cursor: continue
        if a > cursor+EPS: result.append((cursor, a))
        cursor = max(cursor, b)
    if hi > cursor+EPS: result.append((cursor, hi))
    return result


def fragmentation(rectangles, container):
    """Integrate exact free runs on both axes, including pallet boundaries.

    Two separated free strips score differently from one continuous strip.
    Narrow area is a soft descriptor, never a declaration of unusable space.
    Axis averages avoid counting the same area twice as an area measurement.
    """
    limits = (-container['length_mm']/2, container['length_mm']/2,
              -container['width_mm']/2, container['width_mm']/2)
    narrow = []; split = []
    for axis in (0, 1):
        rects = rectangles if axis == 0 else [(r[2], r[3], r[0], r[1]) for r in rectangles]
        a, b, lo, hi = limits if axis == 0 else (limits[2], limits[3], limits[0], limits[1])
        cuts = sorted({a, b, *(max(a, min(b, x)) for r in rects for x in r[:2])})
        thin = extra = 0.
        for left, right in zip(cuts, cuts[1:]):
            active = [(r[2], r[3]) for r in rects if r[0] < right-EPS and r[1] > left+EPS]
            runs = free_runs(lo, hi, active)
            thin += (right-left)*sum(y-x for x, y in runs if y-x < NARROW_MM-EPS)
            extra += (right-left)*max(0, len(runs)-1)
        narrow.append(thin); split.append(extra/max(b-a, EPS))
    area = container['length_mm']*container['width_mm']
    return {'narrow_free_area_fraction': sum(narrow)/(2*area),
            'extra_free_runs': sum(split)/2,
            'occupied_union_area_mm2': rectangle_union_area(rectangles)}


def measure(state, candidate):
    x0, x1, y0, y1, z0, z1 = bounds(candidate)
    contacts = {s: [] for s in ('left', 'right', 'front', 'back')}
    aligned = {s: [] for s in contacts}; gaps = []
    for obj in state['placed_items']:
        a, b, c, d, e, f = bounds(obj)
        if min(z1, f)-max(z0, e) <= EPS: continue
        # Same-base side contact is separate from top/bottom support contact.
        same_base = abs(z0-e) <= EPS
        if min(y1, d)-max(y0, c) > EPS:
            for side, delta in [('left', x0-b), ('right', a-x1)]:
                if delta >= -EPS: gaps.append({'object_id': obj['item_id'], 'side': side, 'gap_mm': max(0., delta)})
                if same_base and abs(delta) <= EPS:
                    interval = (max(y0, c), min(y1, d)); contacts[side].append(interval)
                    if abs(y0-c) <= EPS or abs(y1-d) <= EPS: aligned[side].append(interval)
        if min(x1, b)-max(x0, a) > EPS:
            for side, delta in [('front', y0-d), ('back', c-y1)]:
                if delta >= -EPS: gaps.append({'object_id': obj['item_id'], 'side': side, 'gap_mm': max(0., delta)})
                if same_base and abs(delta) <= EPS:
                    interval = (max(x0, a), min(x1, b)); contacts[side].append(interval)
                    if abs(x0-a) <= EPS or abs(x1-b) <= EPS: aligned[side].append(interval)
    contact = sum(union_length(v) for v in contacts.values())
    alignment = sum(union_length(v) for v in aligned.values())
    perimeter = 2*((x1-x0)+(y1-y0))
    rects = [bounds(o)[:4] for o in state['placed_items'] if bounds(o)[4] <= z0+EPS < bounds(o)[5]-EPS]
    rects.append((x0, x1, y0, y1))
    return {'bounds_mm': [x0, x1, y0, y1, z0, z1], 'side_contact_length_mm': contact,
            'side_contact_ratio': round(contact/perimeter, 12),
            'aligned_contact_length_mm': alignment, 'aligned_contact_ratio': round(alignment/perimeter, 12),
            'gaps': gaps, 'support_item_ids': candidate['support']['support_item_ids'],
            **fragmentation(rects, state['container']),
            'remaining_capacity_prediction': 'NOT_IMPLEMENTED',
            'business_support_quality': 'NOT_IMPLEMENTED'}
