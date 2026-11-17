"""New GP2 constructions only; no saved GP4 states, orders, models or PCT."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sys
import time
from unittest.mock import patch
from semantic_pallet_planner.planner.space_candidates.generator import generate, _generate, CONFIG

ROOT=Path.cwd()
OUT=Path(__file__).resolve().parent
TEST=ROOT/'semantic_pallet_planner/tests/unit/test_space_candidates_gp2.py'
spec=importlib.util.spec_from_file_location('gp2_constructions',TEST)
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
def write(name,obj):
    p=OUT/name;p.parent.mkdir(exist_ok=True,parents=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
scenes=copy.deepcopy(t.SCENES)
left=t.placed('left',-2,0,0,6,8,2,capacity=2)
right=t.placed('right',4,0,0,2,8,2,capacity=2)
bridge=t.placed('bridge',0,0,2,10,8,2)
left['supported_load_kg']=0.75;right['supported_load_kg']=0.25
bridge['support_fractions']=[dict(item_id='left',fraction=0.75),dict(item_id='right',fraction=0.25)]
scenes['cavity_multilayer']=t.scene([left,right,bridge],[t.item(l=2,w=2,h=1,mass=4)])
scenes['below_seventy']=t.scene([t.placed('base',-2,0,0,6,10,2)],[t.item(l=10,w=10)])
scenes['square']=t.scene(buffer=[t.item(l=2,w=2)])
scenes['payload_empty']=t.scene(buffer=[t.item(mass=1001)])
summary=[];manifest=[];observations=[]
for name,scene in scenes.items():
    raw=t.encode(scene)
    p=OUT/'constructed'/f'{name}_input.json';p.parent.mkdir(exist_ok=True);p.write_bytes(raw)
    start=time.perf_counter();result=generate(raw);elapsed=time.perf_counter()-start
    assert result['status']!='ERROR',result['error']
    assert generate(raw)==result
    write(f'constructed/{name}_result.json',result)
    manifest.append({'scene':name,'path':str(p.relative_to(ROOT)),'sha256':sha(p),
                     'source':'synthetic hand construction; no historical or private order source',
                     'field_origin':'test_space_candidates_gp2.py helpers/SCENES or explicit construction in collect_evidence.py'})
    summary.append({'scene':name,'status':result['status'],'final':len(result['candidates']),
                    'items':[{k:ia[k] for k in ('item_id','raw_point_attempts','unique_actions','raw_valid_count','final_candidates','rejection_counts')} for ia in result['audit']['items']]})
    observations.append({'scene':name,'elapsed_seconds':elapsed})
faults={}
faults['real_height_disagreement']=generate(t.encode(t.scene(buffer=[t.item(h=2.0004)])))
faults['point_budget_TEST_DOUBLE']=_generate(t.encode(scenes['empty']),_point_limit=19)
with patch('semantic_pallet_planner.planner.space_candidates.generator.check_candidate',return_value=['INJECTED_TEST_ONLY']):
    faults['oracle_disagreement_TEST_DOUBLE']=generate(t.encode(scenes['empty']))
for name,r in faults.items():
    assert r['status']=='ERROR' and r['candidates']==[]
    write('faults/'+name+'.json',r)
write('input_manifest.json',{'version':'geometry_gp2_input_manifest_v1','inputs':manifest,
      'adapter':'geometry_public_physical_adapter_v1','scope':'CURRENT_PUBLIC_ONLY; all fields constructed explicitly; no missing physical defaults'})
write('constructed_summary.json',summary)
write('config_snapshot.json',CONFIG)
write('observations.json',{'python':sys.version,'executable':sys.executable,'platform':platform.platform(),'calls':observations,'semantic_digest_excludes_wall_clock':True})
source=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
files={str(p.relative_to(source)):sha(p) for p in sorted(source.rglob('*')) if p.suffix in ('.py','.json') and 'tests' not in p.relative_to(source).parts}
old=json.loads((ROOT/'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP1_FIX_20261117_01/source_manifest.json').read_text())['files']
changed=[p for p,h in old.items() if files.get(p)!=h]
assert not changed,changed
write('source_manifest.json',{'version':'geometry_gp2_source_manifest_v1','package_root':str(source.relative_to(ROOT)),
      'files':files,'unchanged_gp1_production_files':len(old),'changed_existing_production_files':changed,
      'added_production_files':sorted(set(files)-set(old)),
      'physical_interfaces':['domain.internal_item','domain.restore_placed','planner.constraints.evaluate_pose','evaluation.geometry_oracle.check_candidate'],
      'old_manifests_resigned':False})
print(json.dumps({'scenes':len(scenes),'source_files':len(files),'unchanged_existing':len(old),'summary':summary},ensure_ascii=False,indent=2))
