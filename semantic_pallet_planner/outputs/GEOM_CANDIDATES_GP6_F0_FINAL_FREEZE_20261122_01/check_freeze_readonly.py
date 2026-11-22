"""Material-only check. Does not issue approval or run joint preflight/kernel/transport."""
from pathlib import Path
import importlib.util,json,hashlib
root=Path.cwd(); out=root/'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_F0_FINAL_FREEZE_20261122_01'
identity=json.loads((out/'freeze_identity.json').read_text()); target=json.loads((out/'target_binding.json').read_text())
spec=importlib.util.spec_from_file_location('driver',root/identity['driver_path']); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
plan=json.loads((out/'gp6_f0_order_plan_FROZEN.json').read_text())
assert m.sha_file(root/identity['driver_path'])==identity['driver_sha256']
assert m.digest(plan)==identity['plan_digest']
draft=m.read_json(root/'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_F0_FORMAL_RUNNER_20261122_01/gp6_f0_order_plan_DRAFT_v2.json')
assert {k for k in plan if plan[k]!=draft[k]}=={'status','request_ledger_path','call_ledger_path'}
m.jev_proto.validate_jev_plan(plan)
run=root/target['run_root']; assert not run.exists();m.check_ledger_run_root_separation(plan,run)
paths=[root/plan[k] for k in ['request_ledger_path','call_ledger_path']]
before=[p.read_bytes() for p in paths]; entries=sorted(str(p.relative_to(out)) for p in out.rglob('*'))
req,rsha=m.check_initial_request_ledger_readonly(plan);call,csha=m.check_initial_call_ledger_readonly(plan)
assert before==[p.read_bytes() for p in paths]
assert entries==sorted(str(p.relative_to(out)) for p in out.rglob('*'))
assert not run.exists()
assert not list((out/'ledgers').glob('*.lock'))
print(json.dumps({'status':'PASS_MATERIAL_CHECK_ONLY','plan_digest':m.digest(plan),'driver_sha256':identity['driver_sha256'],'request_ledger_sha256':rsha,'call_ledger_sha256':csha,'requests':len(req['requests']),'counts':call['counts'],'ledger_bytes_unchanged':True,'directory_entries_unchanged':True,'business_directory_created':False,'joint_preflight':'NOT_RUN','model_calls':0,'monitor_calls':0,'lp_calls':0,'keys_read':False},indent=2))
