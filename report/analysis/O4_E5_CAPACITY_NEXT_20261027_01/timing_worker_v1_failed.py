"""One of three independent cost processes; saved state, no episode or model."""
import argparse
import json
import os
import time
from pathlib import Path
from semantic_pallet_planner.o4.extensions.e5 import planning as entry
from semantic_pallet_planner.o4.extensions.e5.layout_v3 import planning as B0
from semantic_pallet_planner.o4.extensions.e5.layout_v2 import candidates as B_candidates
from semantic_pallet_planner.o4.extensions.e2 import candidates as A_candidates, runtime
from semantic_pallet_planner.o4.extensions.e5.layout_v2.quality import measure

p = argparse.ArgumentParser(); p.add_argument('--output', required=True); a = p.parse_args()
ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'semantic_pallet_planner/outputs'
PLAN = OUT/'PLAN_O4_E5_CAPACITY_NEXT_F_20261027_01'
SMALL = OUT/'PLAN_O4_E5_CAPACITY_NEXT_SMALL_20261027_01'
plan = json.loads((PLAN/'plan.json').read_text()); small = json.loads((SMALL/'plan.json').read_text())
assert Path(B0.__file__).resolve().is_relative_to(PLAN/'code_snapshot')
assert not Path(a.output).exists()
rows = []
for saved in small['reuse']:
    if saved['group'] != 'A': continue
    result = json.loads((ROOT/saved['path']).read_text())
    decisions = [(i,e) for i,e in enumerate(result['events']) if 'search_trace' in e]
    # Predeclared fourth decision (or last if fewer): outside Q1-Q4 fixed states.
    index, e = decisions[min(3,len(decisions)-1)]
    for group in ('A', 'F'):
        entry.clear_cache(); B0.clear_cache(); B_candidates.clear_cache()
        A_candidates._cached_generation.cache_clear(); runtime._cached_state.cache_clear()
        started = time.perf_counter()
        selected, groups, trace, reason = entry.choose(e['before'], e['request'], e['response']['policy_ast'], plan['configurations'][group], saved['method'])
        seconds = time.perf_counter()-started
        cache = entry._cached if group == 'A' else B0._cached
        hits = cache.cache_info().hits; start_hot = time.perf_counter()
        entry.choose(e['before'], e['request'], e['response']['policy_ast'], plan['configurations'][group], saved['method'])
        hot = time.perf_counter()-start_hot
        # Isolate metadata scoring cost using already sampled public poses.
        # No placement, AST evaluation, successor search or future information.
        metadata = [c for g in groups for c in g['generation'].get('public_enumerated_candidates', [])] if group == 'F' else []
        quality_started = time.perf_counter()
        for c in metadata: measure(e['before'], c)
        isolated_quality = time.perf_counter()-quality_started if metadata else 0.
        rows.append({'task_id': saved['task_id'], 'method': saved['method'], 'group': group,
            'source_path': saved['path'], 'source_sha256': saved['sha256'], 'event_index': index,
            'seconds': seconds, 'hot_seconds': hot, 'hot_root_hit': cache.cache_info().hits == hits+1,
            'logical_evaluations': trace['evaluations'], 'sampling_seconds_root': sum(g['generation']['elapsed_seconds'] for g in groups),
            'full_pool_quality_work_root': sum(g['generation'].get('full_pool_quality_evaluations',0) for g in groups),
            'isolated_full_pool_quality_seconds_root': isolated_quality, 'isolated_quality_metadata_count': len(metadata),
            'component_scope': 'root generation includes quality; isolated quality remeasurement on saved metadata, not subtraction from end-to-end; extra AST/placement evaluations=0',
            'selected': None if selected is None else {'pick': selected['pick_item_id'], 'pose': selected['pose']},
            'cache_scope': 'cold root, B0 candidate, delegated B candidate, legacy candidate, runtime state; independent process',
            'scope': 'cost samples only, not extra performance order records or T0 diagnosis'})
        print(saved['task_id'], saved['method'], group, round(seconds,4), flush=True)
with Path(a.output).open('x') as f:
    json.dump({'pid': os.getpid(), 'loaded_module': B0.__file__, 'rows': rows, 'new_api_attempts': 0}, f, indent=2)
