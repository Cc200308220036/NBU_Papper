"""Uncovered N07 boundaries on frozen B0: indirect and multi-support loads."""
import copy
import json
from pathlib import Path
from semantic_pallet_planner.o4.extensions.e2.data import request, object_at, policy
from semantic_pallet_planner.o4.fixtures import rule
from semantic_pallet_planner.o4.extensions.e5.layout_v3 import planning

HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[2]
PLAN = ROOT/'semantic_pallet_planner/outputs/PLAN_O4_E5_CAPACITY_NEXT_SMALL_20261027_01'
assert Path(planning.__file__).resolve().is_relative_to(PLAN/'code_snapshot')
config = json.loads((PLAN/'plan.json').read_text())['configurations']['B0']
ast = policy([rule('label', limit='label')]); cases = []
for limit in (2., 3.):
    box = copy.deepcopy(config['container']); box.update(length_mm=100, width_mm=100, max_height_mm=400)
    req, state = request(ast, placed=[object_at('B', z=0, label=limit), object_at('C', z=100, mass=1., label=100.)], available=[object_at('A', mass=2.)], container=box)
    c, groups, trace, reason = planning.choose(state, req, ast, config, 'single')
    assert (c is not None) == (limit == 3.)
    if c is None: assert groups[0]['candidates'] and all('load:B' in r['after']['violations'] for r in groups[0]['evaluation']['evaluations'])
    else: assert c['pose']['z_base_mm'] == 200
    cases.append({'kind': 'indirect_load', 'limit': limit, 'request': req, 'ast': ast, 'selected': c, 'reason': reason, 'groups': groups})
for limit in (.5, 1.):
    box = copy.deepcopy(config['container']); box.update(length_mm=200, width_mm=100, max_height_mm=200)
    req, state = request(ast, placed=[object_at('B', x=-50, label=1.), object_at('C', x=50, label=limit)], available=[object_at('A', size=(200,100,100), mass=2.)], container=box)
    c, groups, trace, reason = planning.choose(state, req, ast, config, 'single')
    assert (c is not None) == (limit == 1.)
    if c: assert set(c['support']['support_item_ids']) == {'B','C'} and c['pose']['z_base_mm'] == 100
    cases.append({'kind': 'multi_support', 'limit': limit, 'request': req, 'ast': ast, 'selected': c, 'reason': reason, 'groups': groups})
with (HERE/'three_dimensional_checks.json').open('x') as f:
    json.dump({'status': 'PASS', 'loaded_module': planning.__file__, 'cases': cases, 'new_api_attempts': 0, 'extra_search_calls': 0}, f, ensure_ascii=False, indent=2)
print('4 frozen-B0 indirect/multi-support boundary checks PASS')
