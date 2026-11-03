"""Installed v2 physical probe; deliberately independent of source/tests cwd."""
from pathlib import Path
from importlib.resources import files
import importlib.abc
import importlib.metadata
import hashlib
import json
import socket
import sys

attempts=[]
class MinimalDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'gym','gymnasium','torch','stable_baselines3','matplotlib','PIL','yaml','jsonschema','httpx','requests'}:
            attempts.append(fullname)
            raise AssertionError('unnecessary import '+fullname)
sys.meta_path.insert(0,MinimalDependencies())
def forbidden(*a,**k):raise AssertionError('network forbidden')
socket.socket.connect=forbidden;socket.create_connection=forbidden
from semantic_pallet_planner.jev_select import stability
assert 'numpy' not in sys.modules and 'scipy' not in sys.modules
from semantic_pallet_planner.jev_select.stability.balance_adapter import assess_candidate,algorithm_identity
from semantic_pallet_planner.jev_select.stability.balance_contracts import load_config
import semantic_pallet_planner.jev_select.stability.balance_adapter as adapter
assert '/install_venv/' in adapter.__file__ and 'site-packages' in adapter.__file__
Box=stability.BoxInput;State=stability.PlacedState;C=(1000,800,1000)
roots=tuple(Box('s'+str(i),(40,40,100),1,(*xy,0)) for i,xy in enumerate([(-100,-80),(100,-80),(0,100)]))
tri=assess_candidate(State(C,roots),Box('bridge',(260,240,100),3,(0,0,100)),load_config())
assert tri.status=='STABLE'
reactions=[r for r in tri.diagnostics['reactions'] if r['upper']=='bridge']
assert abs(sum(r['mass_kg'] for r in reactions)-3)<1e-8
for d,target in [(0,1500),(1,1200)]:
    assert abs(sum(r['mass_kg']*r['point_mm'][d] for r in reactions)-target)<1e-6
assert all(r['mass_kg']>=0 for r in reactions)
base=Box('base',(60,200,100),1,(0,0,0));shelf=Box('shelf',(240,200,100),4,(0,0,100))
shared=State(C,(base,shelf,Box('left',(40,100,100),1,(-80,0,200)),Box('right',(40,100,100),1,(80,0,200))))
shared_result=assess_candidate(shared,Box('top',(240,100,100),20,(0,0,300)),load_config())
assert shared_result.status=='STABLE' and abs(shared_result.diagnostics['ground_mass_kg']-27)<1e-8
heavy=assess_candidate(State(C,(base,Box('shelf',(200,200,100),1,(0,0,100)))),Box('top',(100,100,100),10,(60,0,200)),load_config())
assert heavy.status=='UNSTABLE' and heavy.diagnostics['infeasibility_certificate']['verified']
redistribution_state=State(C,(
    Box('gleft',(60,200,100),1,(-100,0,0)),Box('gright',(200,200,100),1,(100,0,0)),
    Box('pleft',(140,200,100),1,(-100,0,100)),Box('pright',(140,200,100),1,(100,0,100))))
redistribution=assess_candidate(redistribution_state,Box('bridge',(140,100,100),4,(20,0,200)),load_config())
assert redistribution.status=='STABLE'
height_mismatch=assess_candidate(State(C,(Box('ground',(100,100,100),1,(0,0,0)),)),Box('top',(100,100,100),1,(0,0,120)),load_config())
assert height_mismatch.reason_code=='POSE_HEIGHT_MISMATCH'
assert 'reactions' not in height_mismatch.diagnostics and height_mismatch.diagnostics['evaluated_scope']=='geometry_precheck'
root=files(stability)
resources=['BALANCE_DESIGN.md','BALANCE_CHANGES.md','vendor/pct/LICENSE','vendor/pct/UPSTREAM.md',
           'vendor/pct/compatibility.patch','vendor/pct/upstream_manifest.json',
           'configs/pct_contact_network_v2.json','schemas/stability_config_v2.schema.json',
           'schemas/stability_result_v2.schema.json']
assert not any(k.endswith('.pct_adapter') or '.evaluation.' in k or k.endswith('.episode') for k in sys.modules)
print(json.dumps({'status':'PASS','cwd':str(Path.cwd()),'module_file':adapter.__file__,
    'python':sys.version,'optional_import_attempts':attempts,
    'resources_sha256':{name:hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest() for name in resources},
    'distribution_requires':importlib.metadata.requires('semantic-pallet-planner'),
    'algorithm_identity':algorithm_identity(),'triangle':tri.to_dict(),
    'shared_ancestor':shared_result.to_dict(),'heavy_ancestor':heavy.to_dict(),'global_redistribution':redistribution.to_dict(),'height_mismatch':height_mismatch.to_dict()},indent=2,allow_nan=False))
