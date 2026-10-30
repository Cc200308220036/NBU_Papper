"""Same E2 public coordinates, alignment reserve, then public coverage refill."""
import copy
import json
import time
from functools import lru_cache
from ....common import canonical, digest
from ...e2.candidates import generate as old_generate, key
from .....planner.scoring import geometry_score
from .diagnostics import reconstruct
from .quality import measure
from .config import validate
from . import VERSION


def coverage(c, sources, regions, container):
    x, y, z, yaw, _ = key(c); dx, dy, _ = c['oriented_size_mm']
    labels = {f'yaw:{yaw}', f'height:{z}'}
    for source in sources:
        if source.startswith('neighbor:'):
            _, _, gap, side = source.split(':'); labels.add(f'direction_gap:{side}:{gap}')
    for r in regions:
        if x-dx/2 >= r['x_min_mm']-1e-6 and x+dx/2 <= r['x_max_mm']+1e-6 and y-dy/2 >= r['y_min_mm']-1e-6 and y+dy/2 <= r['y_max_mm']+1e-6:
            labels.add(f'region:{r["region_id"]}:{yaw}')
    if abs(abs(x)-container['length_mm']/2+dx/2) <= 1e-6 or abs(abs(y)-container['width_mm']/2+dy/2) <= 1e-6:
        labels.add('pallet_boundary')
    return labels


def _generate(state, pick, regions, config):
    cfg = validate(config['o4_e5_layout'])
    if not cfg['candidate_retention']: return old_generate(state, pick, regions, config)
    started = time.perf_counter()
    old, full, sources, audit, reconstruction_seconds = reconstruct(state, pick, regions, config)
    qualities = {key(c): measure(state, c) for c in full}
    labels = {key(c): coverage(c, sources[key(c)], regions, state['container']) for c in full}
    selected = {}; reasons = {}; represented = set()
    def keep(c, why):
        k = key(c); selected[k] = c; reasons[k] = why; represented.update(labels[k])
    # A length-based alignment reserve; no wall reward and no probe ranking.
    aligned = [c for c in full if qualities[key(c)]['aligned_contact_length_mm'] > 1e-6]
    for c in sorted(aligned, key=lambda c: (-qualities[key(c)]['aligned_contact_ratio'], -geometry_score(c), key(c)))[:cfg['alignment_reserve']]:
        keep(c, 'aligned_contact_length_reserve')
    # Refill from the legacy returned set, maximizing newly covered public strata.
    # Every loss is reported; a finite K cannot preserve all possible relations.
    while len(selected) < 16:
        rest = [c for c in old if key(c) not in selected]
        if not rest: rest = [c for c in full if key(c) not in selected]
        if not rest: break
        c = min(rest, key=lambda c: (-len(labels[key(c)]-represented), -geometry_score(c), key(c)))
        keep(c, 'legacy_pool_public_coverage_refill')
    result = []
    for c in sorted(selected.values(), key=key):
        c = copy.deepcopy(c)
        c['candidate_fingerprint'] = digest({'pick': pick, 'pose': c['pose'], 'size': c['oriented_size_mm'],
                                             'version': VERSION+'_same_pool_retention_v1', 'config': cfg})
        c['candidate_id'] = 'E5L2_'+c['candidate_fingerprint'][:16]; result.append(c)
    old_coverage = set().union(*(labels[key(c)] for c in old)) if old else set()
    new_coverage = set().union(*(labels[key(c)] for c in result)) if result else set()
    audit = copy.deepcopy(audit)
    audit.update(version=VERSION+'_same_pool_retention_v1', returned_count=len(result),
                 retention=[{'pose': c['pose'], 'reason': reasons[key(c)], 'sources': sources[key(c)]} for c in result],
                 coverage_gained=sorted(new_coverage-old_coverage), coverage_lost=sorted(old_coverage-new_coverage),
                 generation_seconds={'reconstruction_seconds': reconstruction_seconds},
                 full_pool_quality_evaluations=len(full), cost_scope='full_pool_sampling_and_quality_separate_from_256_search_count',
                 elapsed_seconds=time.perf_counter()-started)
    return result, audit


@lru_cache(maxsize=64)
def _cached(serialized): return _generate(*json.loads(serialized))


def generate(state, pick, regions, config):
    public = {k: state[k] for k in ('container', 'pending_items', 'placed_items', 'event_index')}
    started = time.perf_counter(); hits = _cached.cache_info().hits
    result, audit = copy.deepcopy(_cached(canonical([public, pick, regions, config])))
    hit = _cached.cache_info().hits > hits
    audit['elapsed_seconds'] = time.perf_counter()-started
    audit['generation_seconds'] = {'cache_hit': hit, 'full_pool_quality_evaluations_executed':
                                 0 if hit else audit.get('full_pool_quality_evaluations', 0)}
    return result, audit


def clear_cache(): _cached.cache_clear()
