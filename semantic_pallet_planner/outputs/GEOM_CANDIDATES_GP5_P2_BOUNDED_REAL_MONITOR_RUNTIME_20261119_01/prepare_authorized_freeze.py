from pathlib import Path
import json,hashlib,subprocess
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.stability.monitor import exact_freeze
from semantic_pallet_planner.jev_select.geometry_order_execution import validate_monitor_snapshot
from semantic_pallet_planner.jev_select.geometry_order_meter import CallBudget
from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields,wire
from semantic_pallet_planner.jev_select.geometry_kernel_completion import required_coverage
from semantic_pallet_planner.jev_select.contracts import digest,validate_schema
from semantic_pallet_planner.jev_select.ledger import write
B=Path('semantic_pallet_planner/outputs')
D=B/'GEOM_CANDIDATES_GP5_P2_R1_EXTERNAL_REVIEW_BINDING_20261119_01'
R=B/'GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01'
S=Path('semantic_pallet_planner/src/semantic_pallet_planner')
read=lambda f:json.loads(f.read_bytes())
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
assert subprocess.check_output(['git','branch','--show-current'],text=True).strip()=='dev/jev-select'
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()=='1ff6d93c20a747ab348071e01ef682266b571f0c'
files={str(f.relative_to(S)):sha(f) for f in S.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(S).parts)}
assert files==read(D/'source_manifest.json')['files']
assert not R.exists(),'NO_OVERWRITE_RUNTIME_ROOT'
tasks=[]
for case in ('K01','K02'):
 raw=(D/f'{case}_task.json').read_bytes()
 t=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=sha(D/f'{case}_task.json'))
 assert t['identity']==read(D/f'{case}_identity.json');tasks.append(t)
old=read(D/'acceptance_plan_DRAFT.json')
plan=p.prepare_order_plan(tasks,data_identity=old['data_identity'],scope=p.ACCEPTANCE,native=True)
plan.update(status='FROZEN',assessment_limit=8,solver_limit=128,call_ledger_path=str(R/'shared_call_ledger.json'))
p.validate_order_plan(plan)
# Newly generated on this actual host under the user's explicit authorization.
snap=exact_freeze();validate_monitor_snapshot(snap)
R.mkdir()
write(R/'monitor_snapshot.json',snap)
write(R/'acceptance_plan_FROZEN.json',plan)
write(R/'source_manifest.json',{'source_files':len(files),'source_identity':digest(files),'files':files})
for case,t in zip(('K01','K02'),tasks,strict=True):
 (R/f'{case}_task.json').write_bytes(t['raw']);write(R/f'{case}_identity.json',t['identity'])
auth={**identity_fields(plan),'version':wire(plan,'geometry_scope_authorization_v1'),'scope':p.ACCEPTANCE,'plan_digest':digest(plan),'status':'APPROVED'}
validate_schema(wire(plan,'geometry_scope_authorization_v1'),auth)
write(R/'user_authorization.json',auth)
write(R/'authorization_provenance.json',{'date':'2026-11-19','timezone':'Asia/Shanghai','user_message_exact':'我明确授权执行','context':'Response to previous final specifying four primary, six recovery, assessment8/LP128/model0 and independent launch review before dispatch.','recorded_by':'execution agent; transcription of actual user authorization, not independent review','authorized_limits':{'assessment_entries':8,'solver_calls':128,'model_calls':0},'plan_digest':digest(plan),'monitor_digest':digest(snap),'authorization_reference':{'path':str(R/'user_authorization.json'),'sha256':sha(R/'user_authorization.json')}})
b=CallBudget(R/'shared_call_ledger.json',plan,evidence='REAL_KERNEL',job_id='PRESTART_NO_CALL')
assert b.value['calls']==[] and b.value['counts']=={'assessment_entries':0,'solver_calls':0,'test_double_assessments':0}
write(R/'required_coverage.json',required_coverage(plan));write(R/'run_denominator_NOT_RUN.json',p.draft_run(plan))
recovery=read(D/'recovery_DRAFT.json');recovery.update(plan_digest=digest(plan),status='FROZEN_SCOPE_NOT_RUN');write(R/'recovery_NOT_RUN.json',recovery)
write(R/'startup_review_request.json',{'unit':'GP5_P2_BOUNDED_REAL_MONITOR_USABILITY','status':'PENDING_INDEPENDENT_LAUNCH_REVIEW','plan_digest':digest(plan),'source_identity':digest(files),'environment_digest':plan['environment_digest'],'monitor_digest':digest(snap),**identity_fields(plan),'plan_reference':{'path':str(R/'acceptance_plan_FROZEN.json'),'sha256':sha(R/'acceptance_plan_FROZEN.json')},'monitor_reference':{'path':str(R/'monitor_snapshot.json'),'sha256':sha(R/'monitor_snapshot.json')},'authorization_reference':{'path':str(R/'user_authorization.json'),'sha256':sha(R/'user_authorization.json')},'shared_ledger_path':plan['call_ledger_path'],'launch_record':'NOT_ISSUED','independent_review':'MISSING','dispatch':'NOT_READY','self_signed_review':False,'limits':{'assessment_entries':8,'solver_calls':128,'model_calls':0},'primary':4,'recovery':6})
write(R/'freeze_receipt.json',{'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_files':len(files),'source_identity':digest(files),'plan_digest':digest(plan),'monitor_digest':digest(snap),'read_only_monitor_validation':'PASS','new_actual_host_freeze':True,'historical_freeze_reused':False,'raw_inputs_preserved':True,'shared_ledger_counts':b.value['counts'],'real_assessments':0,'actual_LP':0,'model_calls':0,'dispatches':0,'recovery_dispatches':0,'stop':'INDEPENDENT_LAUNCH_REVIEW_AND_MATCHING_LAUNCH_RECORD_REQUIRED'})
print(json.dumps({'plan_digest':digest(plan),'monitor_digest':digest(snap),'root':str(R),'counts':b.value['counts'],'status':'FROZEN_PENDING_INDEPENDENT_LAUNCH_REVIEW'},indent=2))
