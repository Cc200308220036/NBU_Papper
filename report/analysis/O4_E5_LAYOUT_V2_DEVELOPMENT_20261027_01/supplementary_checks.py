"""A few targeted checks on the final frozen source, never a full batch rerun."""
import copy
from pathlib import Path
from semantic_pallet_planner.o4.common import read, write, O4Error
from semantic_pallet_planner.o4.extensions.e2.data import request, object_at, policy
from semantic_pallet_planner.o4.fixtures import rule
from semantic_pallet_planner.o4.extensions.e5.layout_v2.planning import choose
from semantic_pallet_planner.o4.extensions.e5.layout_v2.config import DEFAULT
from semantic_pallet_planner.o4.extensions.e5.episode import stable
from semantic_pallet_planner.o4.extensions.e5.episode import episode
from semantic_pallet_planner.o4.extensions.e5.data import construct_tasks
from semantic_pallet_planner.o4.extensions.e5.backends import LocalCompiler
from semantic_pallet_planner.o4.extensions.e5.layout_v2.planning import clear_cache

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
plan_path = ROOT/'semantic_pallet_planner/outputs/PLAN_O4_E5_LAYOUT_V2_20261027_01'
plan = read(plan_path/'plan.json'); config = plan['group_configurations']['D']
container = copy.deepcopy(config['container']); container.update(length_mm=100, width_mm=100, max_height_mm=400)
ast = policy([rule('label', limit='label')])
req, state = request(ast, placed=[object_at('B', z=0, label=2.), object_at('C', z=100, mass=1., label=100.)],
                     available=[object_at('A', mass=2.)], container=container)
selected, groups, trace, reason = choose(state, req, ast, config, 'single')
assert selected is None and reason == 'no_compiled_business_candidate'
assert groups[0]['candidates'] and all('load:B' in r['after']['violations'] for r in groups[0]['evaluation']['evaluations'])
# Counterexample changes only the explicit test cap, never a development order.
req2, state2 = request(ast, placed=[object_at('B', z=0, label=3.), object_at('C', z=100, mass=1., label=100.)],
                       available=[object_at('A', mass=2.)], container=container)
selected2, groups2, trace2, reason2 = choose(state2, req2, ast, config, 'single')
assert selected2 is not None and selected2['pose']['z_base_mm'] == 200
a = choose(state2, req2, ast, config, 'single'); b = choose(state2, req2, ast, config, 'single')
assert stable(list(a)) == stable(list(b))
task = construct_tasks()[0]
first = episode(task, 'public_parser', 'single', config, LocalCompiler('public_parser'), 'supplementary_repeat')
clear_cache()
repeat = episode(task, 'public_parser', 'single', config, LocalCompiler('public_parser'), 'supplementary_repeat')
restore = episode(task, 'public_parser', 'single', config, LocalCompiler('public_parser'), 'supplementary_repeat', resume=first['checkpoints'][1])
normalized = lambda r: stable({k: v for k, v in r.items() if k != 'checkpoints'})
assert normalized(first) == normalized(repeat) == normalized(restore)
write(HERE/'supplementary_checks.json', {'status': 'PASS', 'checks': ['indirect_cumulative_load_rejection',
      'exact_cumulative_load_boundary_allows_third_layer', 'frozen_cache_metadata_stable', 'second_construct_independent_repeat_restore'],
      'loaded_module': choose.__module__, 'new_api_attempts': 0,
      'first_candidate': selected2, 'rejection_reason': reason})
print('4 supplementary frozen-source checks passed')
