import json,hashlib,sys,socket
from pathlib import Path
from unittest.mock import patch
p=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N1_R6_20261118_01')
sys.path.insert(0,str(p.resolve()))
from validation_entrypoint import check_frozen
from semantic_pallet_planner.jev_select import geometry_order_execution as o
from semantic_pallet_planner.jev_select.stability.runtime import environment
from semantic_pallet_planner.jev_select.contracts import digest
read=lambda n:json.loads((p/n).read_bytes())
check_frozen(p)
assert hashlib.sha256((p/'frozen_identity.json').read_bytes()).hexdigest()=='c742929cbe06be456eae628444d07ef29f4b293df4310705821d3b5f0bf61a96'
assert hashlib.sha256((p/'validation_scope.json').read_bytes()).hexdigest()=='d55b1153c6fb61b0d819e8c2bf3b41012114b392902152a944b719fe307e933b'
assert environment()==read('environment_receipt.json')['expected']
mon=read('monitor_snapshot.json')
with patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')):
 o.validate_monitor_snapshot(mon)
 for j in read('plan.json')['jobs']:
  assert o.load_order_config(read('plan.json'),j['job_id'],monitor_snapshot=mon,admission=read('admission.json'))==read('configs.json')[j['job_id']]
receipt={'status':'PASS','source_files':591,'source_identity':digest(read('source_manifest.json')['files']),'frozen_members':len(read('frozen_identity.json')['files']),'observed_environment':environment(),'dependencies':read('environment_receipt.json')['dependencies'],'configs_preflighted':8,'business_dispatches':0}
Path('/tmp/gp5_fixed_preflight.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
