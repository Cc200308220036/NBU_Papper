"""One independent-process cost sample on saved public states, not an episode."""
import argparse
import json
import os
from pathlib import Path
import time
from semantic_pallet_planner.o4.common import read, write
from semantic_pallet_planner.o4.extensions.e5 import planning as original
from semantic_pallet_planner.o4.extensions.e2 import candidates as old_candidates, runtime
from semantic_pallet_planner.o4.extensions.e5.layout_v2 import planning
from semantic_pallet_planner.o4.extensions.e5.layout_v2 import candidates as new_candidates

parser = argparse.ArgumentParser()
parser.add_argument('--plan', required=True); parser.add_argument('--experiment', required=True)
parser.add_argument('--output', required=True); args = parser.parse_args()
plan = read(Path(args.plan)/'plan.json'); root = Path(args.experiment)
if not Path(planning.__file__).resolve().is_relative_to(Path(args.plan).resolve()/'code_snapshot'):
    raise RuntimeError('timing must import the frozen snapshot')
output = Path(args.output)
if output.exists(): raise FileExistsError(output)
rows = []
for job in plan['l2_jobs']:
    if job['stage'] != 'L2' or job['group'] != 'A': continue
    saved = read(root/'episodes'/f'{job["job_id"]}.json')
    decisions = [(i, e) for i, e in enumerate(saved['events']) if e.get('groups')]
    # The second observed decision is fixed before timing and never selected
    # according to its measured latency or which group performs better.
    index, event = decisions[min(1, len(decisions)-1)]
    for group in ('A', 'D'):
        original.clear_cache(); planning.clear_cache()
        old_candidates._cached_generation.cache_clear(); runtime._cached_state.cache_clear()
        started = time.perf_counter()
        result = original.choose(event['before'], event['request'], event['response']['policy_ast'],
                                 plan['group_configurations'][group], job['method'])
        seconds = time.perf_counter()-started
        cold_cache = {'legacy_root': original._cached.cache_info()._asdict(),
                      'new_root': planning._cached.cache_info()._asdict(),
                      'legacy_candidates': old_candidates._cached_generation.cache_info()._asdict(),
                      'new_candidates': new_candidates._cached.cache_info()._asdict()}
        warmed = time.perf_counter()
        root_cache = original._cached if group == 'A' else planning._cached
        hits_before = root_cache.cache_info().hits
        original.choose(event['before'], event['request'], event['response']['policy_ast'],
                        plan['group_configurations'][group], job['method'])
        hot_seconds = time.perf_counter()-warmed
        rows.append({'task_id': job['task_id'], 'method': job['method'], 'group': group,
                     'event_index': index, 'seconds': seconds, 'hot_seconds': hot_seconds,
                     'hot_root_hit': root_cache.cache_info().hits == hits_before+1,
                     'cold_cache_info': cold_cache, 'logical_evaluations': result[2]['evaluations'],
                     'cache_scope': 'cold_root_and_candidate_and_state_caches',
                     'sample_scope': 'same_saved_public_state_not_order_replay'})
        print(job['task_id'], job['method'], group, round(seconds, 4), flush=True)
write(output, {'pid': os.getpid(), 'module_path': planning.__file__, 'rows': rows,
               'new_api_attempts': 0, 'planned_cold_decisions': 24, 'recorded_cold_decisions': len(rows),
               'planned_hot_decisions': 24, 'recorded_hot_decisions': len(rows)})
