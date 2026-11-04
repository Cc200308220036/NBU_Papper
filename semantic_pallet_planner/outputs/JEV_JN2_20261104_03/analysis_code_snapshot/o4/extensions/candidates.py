"""Public-only E1 candidate enrichment; no AST or reference enters generation."""
import copy
import time
from ...domain import internal_item, restore_placed, PalletState
from ...planner.generator import ExtremePointGenerator
from ...planner.constraints import candidate_points, evaluate_pose
from ...evaluation.geometry_oracle import check_candidate
from ..common import digest, O4Error
from ..buffer.buffer_state import physical

VERSION = 'o4_e1_public_regions_candidates_v1'


def key(c):
    return (c['pose']['x_mm'], c['pose']['y_mm'], c['pose']['z_base_mm'], c['pose']['yaw_deg'], c['pick_item_id'])


def generate(state, pick, regions, config):
    started = time.perf_counter()
    case = physical(state, pick)
    if len(case['available_items']) != 1:
        raise O4Error('invalid_pick')
    settings = copy.deepcopy(config); settings['container'] = case['container']
    if settings['candidate_generator']['yaw_degrees'] != [0, 90] or settings['candidate_generator']['top_k'] != 16:
        raise O4Error('invalid_candidate_config', 'E1 freezes yaw=[0,90], Top-K=16')
    baseline = ExtremePointGenerator(settings).generate(PalletState.from_dict(case))
    old = baseline.candidate_set.data['candidates']
    item = internal_item(case['available_items'][0]); placed = restore_placed(case['placed_items'])
    all_valid = {key(c): copy.deepcopy(c) for c in old}
    region_groups = {}; rejected = {}; attempted = 0
    # Round-robin public region strata reserve at most one representative per
    # region/yaw/height, then fill by ordinary geometry. No policy is accepted.
    for r in sorted(regions, key=lambda r: r['region_id']):
        for yaw in (0, 90):
            l, w = item['dimensions'][:2] if yaw == 0 else item['dimensions'][:2][::-1]
            zs = sorted({0., *(p['z1'] for p in placed)})
            for z in zs:
                group = []
                xs = (r['x_min_mm'], r['x_max_mm']-l, (r['x_min_mm']+r['x_max_mm']-l)/2)
                ys = (r['y_min_mm'], r['y_max_mm']-w, (r['y_min_mm']+r['y_max_mm']-w)/2)
                for x, y in sorted(set((x, y) for x in xs for y in ys)):
                    attempted += 1
                    raw, reason = evaluate_pose(item, placed, x, y, z, l, w, yaw, settings)
                    if raw is None:
                        rejected[reason] = rejected.get(reason, 0)+1
                        continue
                    c = raw['visible']
                    errors = check_candidate(case, {'container': case['container']}, c)
                    if errors:
                        rejected['independent_physics'] = rejected.get('independent_physics', 0)+1
                        continue
                    all_valid[key(c)] = c
                    # Containment here is a PUBLIC sampling stratum, independent
                    # of whether any instruction asks for this region or object.
                    cx,cy=c['pose']['x_mm'],c['pose']['y_mm']
                    if (cx-l/2 >= r['x_min_mm']-1e-6 and cx+l/2 <= r['x_max_mm']+1e-6
                            and cy-w/2 >= r['y_min_mm']-1e-6 and cy+w/2 <= r['y_max_mm']+1e-6):
                        group.append(c)
                if group:
                    region_groups[(r['region_id'], yaw, z)] = group
    def score(c):
        from ...planner.scoring import geometry_score
        return (-geometry_score(c), key(c))
    selected = {}
    for group in region_groups.values():
        representative = min(group, key=score)
        if len(selected) < 16:
            selected.setdefault(key(representative), representative)
    for c in sorted(all_valid.values(), key=score):
        if len(selected) == 16:
            break
        selected.setdefault(key(c), c)
    out = []
    for c in sorted(selected.values(), key=key):
        c = copy.deepcopy(c)
        c['candidate_fingerprint'] = digest({'pick': pick, 'pose': c['pose'], 'size': c['oriented_size_mm'], 'version': VERSION})
        c['candidate_id'] = 'E1_' + c['candidate_fingerprint'][:16]
        out.append(c)
    return out, {'version': VERSION, 'baseline_candidates': old, 'baseline_count': len(old),
                 'public_enriched_physical_count': len(all_valid), 'region_strata': len(region_groups),
                 'region_attempts': attempted, 'rejections': rejected, 'returned_count': len(out),
                 'topk_truncated': len(all_valid) > 16, 'elapsed_seconds': time.perf_counter()-started}
