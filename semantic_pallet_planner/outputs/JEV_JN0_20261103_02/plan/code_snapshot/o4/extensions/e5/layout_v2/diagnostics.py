"""Read-only reconstruction of the frozen E2 pool and retention provenance."""
import copy
import time
from collections import defaultdict
from .....domain import internal_item, restore_placed
from .....planner.constraints import candidate_points, evaluate_pose
from .....planner.scoring import geometry_score
from .....evaluation.geometry_oracle import check_candidate
from ....buffer.buffer_state import physical
from ....common import digest, O4Error
from ...e2.candidates import generate, key, VERSION
from ...e2.planning import select_layout
from ...e2.runtime import evaluate_candidates
from .quality import measure


def source_proposals(state, pick, regions):
    case = physical(state, pick)
    item = internal_item(case['available_items'][0]); placed = restore_placed(case['placed_items'])
    levels = sorted({0., *(p['z1'] for p in placed)})
    proposals = defaultdict(set)
    def add(x, y, z, dx, dy, yaw, source):
        proposals[(x+dx/2, y+dy/2, z, yaw, pick)].add(source)
    for yaw in (0, 90):
        dx, dy = item['dimensions'][:2] if yaw == 0 else item['dimensions'][:2][::-1]
        for x, y, z in candidate_points(placed, dx, dy, state['container']):
            add(x, y, z, dx, dy, yaw, 'extreme_boundary')
        for r in sorted(regions, key=lambda r: r['region_id']):
            xs = (r['x_min_mm'], r['x_max_mm']-dx, (r['x_min_mm']+r['x_max_mm']-dx)/2)
            ys = (r['y_min_mm'], r['y_max_mm']-dy, (r['y_min_mm']+r['y_max_mm']-dy)/2)
            for x in set(xs):
                for y in set(ys):
                    for z in levels: add(x, y, z, dx, dy, yaw, 'region:'+r['region_id'])
        for p in placed:
            for gap in (0, 50, 100):
                xs = (p['x0'], p['x1']-dx, (p['x0']+p['x1']-dx)/2)
                ys = (p['y0'], p['y1']-dy, (p['y0']+p['y1']-dy)/2)
                positions = [('left', p['x0']-dx-gap, y) for y in ys]+[('right', p['x1']+gap, y) for y in ys]
                positions += [('front', x, p['y0']-dy-gap) for x in xs]+[('back', x, p['y1']+gap) for x in xs]
                for side, x, y in positions:
                    for z in levels: add(x, y, z, dx, dy, yaw, f'neighbor:{p["item_id"]}:{gap}:{side}')
    return proposals


def reconstruct(state, pick, regions, config):
    """Reuse the authoritative sampled poses, rehydrate metadata once per pose."""
    started = time.perf_counter()
    top, generation = generate(state, pick, regions, config)
    proposals = source_proposals(state, pick, regions)
    case = physical(state, pick); item = internal_item(case['available_items'][0])
    placed = restore_placed(case['placed_items']); settings = copy.deepcopy(config); settings['container'] = state['container']
    full = []; sources = {}
    for c in generation['public_enumerated_candidates']:
        x, y, z, yaw, _ = key(c); dx, dy, _ = c['oriented_size_mm']
        raw, error = evaluate_pose(item, placed, x-dx/2, y-dy/2, z, dx, dy, yaw, settings)
        if error or raw is None: raise O4Error('pool_reconstruction_mismatch', str(key(c)))
        visible = raw['visible']
        if check_candidate(case, {'container': state['container']}, visible): raise O4Error('independent_physics_failed')
        visible['candidate_fingerprint'] = digest({'pick': pick, 'pose': visible['pose'], 'size': visible['oriented_size_mm'], 'version': VERSION})
        visible['candidate_id'] = 'E2_'+visible['candidate_fingerprint'][:16]
        full.append(visible); sources[key(c)] = sorted(proposals[key(c)])
        if not sources[key(c)]: raise O4Error('missing_candidate_provenance')
    if len(full) != generation['public_enriched_physical_count']: raise O4Error('pool_count_mismatch')
    return top, full, sources, generation, time.perf_counter()-started


def retention_reasons(full, sources, regions):
    """Mirror E2's published strata selection, with reasons and exact-set check."""
    strata = defaultdict(list); regional = defaultdict(list)
    for c in full:
        for src in sources[key(c)]:
            if src.startswith('neighbor:'):
                _, _, gap, side = src.split(':'); strata[(int(gap), side)].append(c)
            if src.startswith('region:'):
                r = next(r for r in regions if r['region_id'] == src.split(':')[1])
                x, y, _, yaw, _ = key(c); dx, dy, _ = c['oriented_size_mm']
                if x-dx/2 >= r['x_min_mm']-1e-6 and x+dx/2 <= r['x_max_mm']+1e-6 and y-dy/2 >= r['y_min_mm']-1e-6 and y+dy/2 <= r['y_max_mm']+1e-6:
                    regional[(r['region_id'], yaw)].append(c)
    rank = lambda c: (-geometry_score(c), key(c))
    selected = {}; reasons = defaultdict(list)
    def keep(c, why, limit):
        if len(selected) < limit:
            selected.setdefault(key(c), c); reasons[key(c)].append(why)
    for group in sorted(strata): keep(min(strata[group], key=rank), f'direction_gap_representative:{group}', 12)
    for group in sorted(regional):
        if len(selected) == 16: break
        keep(min(regional[group], key=rank), f'region_yaw_representative:{group}', 16)
    for c in sorted(full, key=rank):
        if len(selected) == 16: break
        keep(c, 'geometry_fill', 16)
    return selected, reasons


def inspect_group(state, req, ast, pick, config):
    top, full, sources, generation, seconds = reconstruct(state, pick, req['regions'], config)
    retained, reasons = retention_reasons(full, sources, req['regions'])
    if set(retained) != {key(c) for c in top}: raise O4Error('retention_reconstruction_mismatch')
    chosen, trace, evaluated = select_layout(req, ast, top)
    top_keys = {key(c) for c in top}; allowed = {}; selected_key = key(chosen) if chosen else None
    # Contract limits remain 16 per runtime call; diagnostic batches are not search work.
    for offset in range(0, len(full), 16):
        result = evaluate_candidates(req, ast, full[offset:offset+16])
        allowed.update({row['candidate_id']: row for row in result['evaluations']})
    rows = []
    for c in full:
        k = key(c); business = allowed[c['candidate_id']]; in_top = k in top_keys
        eligible = c['candidate_id'] in trace['eligible_labels'] if in_top else None
        stage = 'compression' if not in_top else 'hard_filter' if not business['allowed'] else 'soft_budget' if not eligible else 'selected' if k == selected_key else 'position_ranking'
        rows.append({'candidate': c, 'sources': sources[k], 'physics': 'PASS',
                     'quality': measure(state, c), 'geometry_score': geometry_score(c),
                     'retained': in_top, 'retention_reasons': reasons[k] if in_top else ['not_selected_by_frozen_strata_and_geometry_fill'],
                     'business_allowed': business['allowed'], 'business_rejection_codes': business['after']['violations'],
                     'soft_budget_eligible': eligible, 'decision_stage': stage,
                     'first_differing_rank_component': 'geometry_score' if stage == 'position_ranking' and geometry_score(c) < geometry_score(chosen)-1e-12 else 'stable_pose' if stage == 'position_ranking' else stage})
    return {'pick_item_id': pick, 'rows': rows, 'trace': trace, 'selected': chosen,
            'counts': {'sampled_physical': len(full), 'topk': len(top), 'sampled_business_allowed': sum(r['business_allowed'] for r in rows),
                       'topk_business_allowed': len(evaluated['allowed_ids']), 'topk_soft_eligible': len(trace['eligible_labels'])},
            'sampling': {k: v for k, v in generation.items() if k not in ('baseline_candidates', 'public_enumerated_candidates')},
            'diagnostic_seconds': seconds, 'cost_scope': 'full_pool_diagnostic_not_search_evaluations',
            'global_infeasibility': 'NOT_PROVEN'}
