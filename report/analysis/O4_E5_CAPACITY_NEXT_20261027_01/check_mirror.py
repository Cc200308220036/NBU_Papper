"""Public spatial mirror counterexample with required gap and no contact."""
import copy
import json
from pathlib import Path
from semantic_pallet_planner.o4.extensions.e2.data import request, object_at, policy, relative
from semantic_pallet_planner.o4.extensions.data import region, spatial
from semantic_pallet_planner.o4.fixtures import rule, eq
from semantic_pallet_planner.o4.extensions.e5.layout_v3 import planning

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
PLAN=ROOT/'semantic_pallet_planner/outputs/PLAN_O4_E5_CAPACITY_NEXT_SMALL_20261027_01'
assert Path(planning.__file__).resolve().is_relative_to(PLAN/'code_snapshot')
config=json.loads((PLAN/'plan.json').read_text())['configurations']['B0']
box=copy.deepcopy(config['container']);box.update(length_mm=400,width_mm=100,max_height_mm=100)
cases=[]
for sign,direction in [(-1,'left_of'),(1,'right_of')]:
    ast=policy([relative(direction=direction,gap=50),rule('contact','forbidden_contact'),spatial('r',target=eq('cargo_category','food'),region_id='zone')])
    lo,hi=sorted([sign*100,sign*200])
    req,state=request(ast,placed=[object_at('B','household_cleaner')],regions=[region('zone',lo,hi,-50,50)],container=box)
    selected,groups,trace,reason=planning.choose(state,req,ast,config,'single')
    assert selected is not None and selected['pose']['x_mm']==sign*150 and selected['pose']['y_mm']==0
    cases.append({'request':req,'ast':ast,'selected':selected,'reason':reason})
with (HERE/'mirror_checks.json').open('x') as f:
    json.dump({'status':'PASS','cases':cases,'loaded_module':planning.__file__,'extra_search_calls':0,'new_api_attempts':0},f,ensure_ascii=False,indent=2)
print('B0 mirrored region + 50mm gap + forbidden contact PASS')
