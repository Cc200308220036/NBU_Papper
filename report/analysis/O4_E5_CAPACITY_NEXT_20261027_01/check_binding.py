"""Frozen B0 action binding and AST cache boundaries, no extra searches."""
import copy
import json
from pathlib import Path
from semantic_pallet_planner.o4.common import O4Error
from semantic_pallet_planner.o4.extensions.e2.planning import action_for, commit
from semantic_pallet_planner.o4.extensions.e2.data import policy
from semantic_pallet_planner.o4.extensions.e5.layout_v2.planning import choose as old_choose
from semantic_pallet_planner.o4.extensions.e5.layout_v3 import planning
from semantic_pallet_planner.o4.extensions.e5.layout_v3.config import v2_config

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=ROOT/'semantic_pallet_planner/outputs'
PLAN=OUT/'PLAN_O4_E5_CAPACITY_NEXT_SMALL_20261027_01'
assert Path(planning.__file__).resolve().is_relative_to(PLAN/'code_snapshot')
config=json.loads((PLAN/'plan.json').read_text())['configurations']['B0']
case=json.loads((OUT/'EXP_O4_E5_CAPACITY_NEXT_T0_20261027_01/inputs.json').read_text())['Q6']
s,req,ast=case['state'],case['request'],case['ast'];before=copy.deepcopy(s)
a=old_choose(s,req,ast,v2_config(config),'single');b=planning.choose(s,req,ast,config,'single')
old_pool=[c for g in a[1] for c in g['candidates']];new_pool=[c for g in b[1] for c in g['candidates']]
response={'schema_version':'o4_e2_response_v1',**{k:req[k] for k in ('request_id','state_hash','observation_digest','instruction_digest')},'policy_ast':ast}
try:
    commit(s,req['regions'],req,response,new_pool,action_for(req,old_pool,a[0]))
except O4Error as exc:
    assert exc.code=='invalid_binding'
else:raise AssertionError('cross-version action accepted')
after=commit(s,req['regions'],req,response,new_pool,action_for(req,new_pool,b[0]))
assert after['placed_count']==s['placed_count']+1 and s==before
misses=planning._cached.cache_info().misses
planning.choose(s,req,policy([]),config,'single')
assert planning._cached.cache_info().misses==misses+1 and s==before
with (HERE/'binding_checks.json').open('x') as f:
    json.dump({'status':'PASS','checks':['cross_version_stale_pool_rejected','fresh_B0_bound_commit_allowed_on_clone','different_AST_does_not_hit_root_cache','root_unchanged'],
               'loaded_module':planning.__file__,'extra_search_calls':0,'new_api_attempts':0},f,indent=2)
print('frozen B0 binding and AST-cache checks PASS')
