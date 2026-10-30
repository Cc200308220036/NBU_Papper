"""V2/pilot public facts, reconstructed from poses without generator private state."""
import copy
import math
from itertools import combinations

TOL_MM = 1e-6


def box_bounds(p):
    x, y, z = (p['pose'][k] for k in ('x_mm', 'y_mm', 'z_base_mm'))
    l, w, h = p['oriented_size_mm']
    return x-l/2, x+l/2, y-w/2, y+w/2, z, z+h


def face_contact(a, b):
    aa, bb = box_bounds(a), box_bounds(b)
    for axis in (0, 2, 4):
        adjacent = abs(aa[axis+1]-bb[axis]) <= TOL_MM or abs(bb[axis+1]-aa[axis]) <= TOL_MM
        other = [k for k in (0, 2, 4) if k != axis]
        if adjacent and all(min(aa[k+1], bb[k+1])-max(aa[k], bb[k]) > TOL_MM for k in other):
            return True
    return False


def reconstruct(records):
    """Ignore recorded load/support fields; area-split load, including indirect load."""
    out = copy.deepcopy(records)
    by_id = {p['item_id']: p for p in out}
    if len(by_id) != len(out):
        raise ValueError('duplicate item_id')
    for p in out:
        if any(v <= 0 or not math.isfinite(v) for v in p['oriented_size_mm']):
            raise ValueError('invalid dimensions')
        ab = box_bounds(p)
        edges = []
        if ab[4] > TOL_MM:
            for b in out:
                if b is p:
                    continue
                bb = box_bounds(b)
                if abs(bb[5]-ab[4]) <= TOL_MM:
                    area = max(0, min(ab[1], bb[1])-max(ab[0], bb[0])) * max(0, min(ab[3], bb[3])-max(ab[2], bb[2]))
                    if area > 0:
                        edges.append((b['item_id'], area))
        total = sum(a for _, a in edges)
        p['support_fractions'] = [{'item_id': i, 'fraction': a/total} for i, a in edges]
        p['supported_load_kg'] = 0.0
    for p in sorted(out, key=lambda p: p['pose']['z_base_mm'], reverse=True):
        for e in p['support_fractions']:
            by_id[e['item_id']]['supported_load_kg'] += (p['mass_kg']+p['supported_load_kg'])*e['fraction']
    return out


def transition(case, candidate):
    before = reconstruct(case['placed_items'])
    item = copy.deepcopy(next(i for i in case['available_items'] if i['item_id'] == candidate['pick_item_id']))
    item.update(pose=copy.deepcopy(candidate['pose']), oriented_size_mm=list(candidate['oriented_size_mm']))
    return before, reconstruct([*before, item])


def raw_metrics(placed):
    heavy = [p for p in placed if p['weight_class'] == 'heavy']
    fragile = [p for p in placed if p['fragile']]
    mass = sum(p['mass_kg'] for p in heavy)
    contacts = [sorted([a['item_id'], b['item_id']]) for a, b in combinations(placed, 2) if face_contact(a, b)]
    return {
        'fragile_load_by_item_kg': {p['item_id']: p['supported_load_kg'] for p in fragile},
        'fragile_load_ratio_max': max((p['supported_load_kg']/p['top_load_limit_kg_synthetic'] for p in fragile if p['top_load_limit_kg_synthetic'] > 0), default=None),
        'heavy_mass_weighted_z_mm': sum(p['mass_kg']*p['pose']['z_base_mm'] for p in heavy)/mass if mass else None,
        'heavy_center_distance_mm': sum(p['mass_kg']*math.hypot(p['pose']['x_mm'], p['pose']['y_mm']) for p in heavy)/mass if mass else None,
        'contact_pairs': sorted(contacts), 'fragile_target_count': len(fragile), 'heavy_target_count': len(heavy),
    }


def public_relations(case, candidate):
    before, after = transition(case, candidate)
    a, b = raw_metrics(before), raw_metrics(after)
    delta = {k: b[k]-a[k] if a[k] is not None and b[k] is not None else None
             for k in ('fragile_load_ratio_max', 'heavy_mass_weighted_z_mm', 'heavy_center_distance_mm')}
    load_delta = {i: b['fragile_load_by_item_kg'][i]-v for i, v in a['fragile_load_by_item_kg'].items()}
    delta['fragile_load_by_existing_item_kg'] = load_delta
    delta['fragile_added_load_kg'] = sum(load_delta.values()) if load_delta else None
    delta['new_contact_pairs'] = [p for p in b['contact_pairs'] if p not in a['contact_pairs']]
    return {'before': a, 'after': b, 'delta': delta}
