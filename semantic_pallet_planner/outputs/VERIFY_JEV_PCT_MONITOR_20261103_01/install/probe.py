from pathlib import Path
import sys,json
from importlib.resources import files
from semantic_pallet_planner.jev_select.stability.monitor import load_monitor_config,validate_checkpoint
from semantic_pallet_planner.jev_select.stability.balance_adapter import assess_candidate,algorithm_identity
from semantic_pallet_planner.jev_select.stability.balance_contracts import load_config
from semantic_pallet_planner.jev_select.stability import BoxInput,PlacedState
from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
from semantic_pallet_planner.jev_select.episode import run_episode
from semantic_pallet_planner.jev_select.contracts import digest
root=Path('/home/cyw/NBU_Papper/semantic_pallet_planner/outputs/VERIFY_JEV_PCT_MONITOR_20261103_01')
import semantic_pallet_planner.jev_select.stability.monitor as mod
assert 'site-packages' in mod.__file__
p=files('semantic_pallet_planner.jev_select.stability')
for name in ('schemas/monitor_record_v1.schema.json','configs/monitor_v1.json','configs/pct_contact_network_v2.json','vendor/pct/LICENSE'):
 assert p.joinpath(name).read_bytes()
r=assess_candidate(PlacedState((1000,1000,1000)),BoxInput('floor',(100,100,100),1,(0,0,0)),load_config())
assert r.status=='STABLE' and r.version=='pct_stability_result_v2'
task=json.loads((root/'constructed_integration/stable.json').read_text())['task']
counts={}
for enabled in (False,True):
 cfg=load_monitor_config(data_identity=digest('INSTALLED_CONSTRUCTED'),task_digest=digest(task),enabled=enabled)
 ep=run_episode(task,LocalPackagingDouble(),cfg,job_id='I',method=cfg['selector'])
 validate_checkpoint(ep['checkpoint'],task,cfg,'I',cfg['selector'])
 assert ep['final_state']['placed_count']==1
 counts[str(enabled)]=ep['summary']['monitor_statistics']
result={'status':'PASS','scope':'offline wheel; venv with existing system site packages, non-source cwd, isolated python',
 'module':mod.__file__,'python':sys.version,'config':load_config().__dict__,'algorithm_identity':algorithm_identity(),'statistics':counts}
(root/'install/probe_result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'status':'PASS','module':mod.__file__}))
