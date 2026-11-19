"""Read-only original-host preflight; never issues review/launch or executes orders."""
from pathlib import Path
import json,hashlib,subprocess
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.geometry_order_execution import validate_monitor_snapshot
from semantic_pallet_planner.jev_select.contracts import digest,validate_schema
from semantic_pallet_planner.jev_select.geometry_native_protocol import wire,identity_fields
from semantic_pallet_planner.jev_select.stability.runtime import environment as monitor_environment
R=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01')
O=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_HOST_PREFLIGHT_20261119_01')
read=lambda f:json.loads(f.read_bytes())
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
before={str(f):sha(f) for f in R.rglob('*') if f.is_file()}
plan=read(R/'acceptance_plan_FROZEN.json');snap=read(R/'monitor_snapshot.json');req=read(R/'startup_review_request.json')
p.validate_order_plan(plan);validate_monitor_snapshot(snap)
assert digest(plan)==req['plan_digest']=='2e97da50ad87c91b50b0259129f1dfc0b584e11c653d23a9a25830f3499d6433'
assert digest(snap)==req['monitor_digest']=='b6cda604eaf1640c48c7d6d71fb536f4ef777cac56ca2de0c01b8ed4dda3ab07'
S=Path('semantic_pallet_planner/src/semantic_pallet_planner')
files={str(f.relative_to(S)):sha(f) for f in S.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(S).parts)}
assert files==read(R/'source_manifest.json')['files'] and digest(files)==plan['source_identity']
for case,t in zip(('K01','K02'),plan['tasks'],strict=True):
 assert p.adapt_task((R/f'{case}_task.json').read_bytes(),origin='SYNTHETIC_FIXED',expected_sha256=t['raw_sha256'])['identity']==t
for key in ('plan_reference','monitor_reference','authorization_reference'):p.read_reference(req[key])
auth=read(R/'user_authorization.json');validate_schema(wire(plan,'geometry_scope_authorization_v1'),auth)
assert auth['status']=='APPROVED' and auth['scope']==plan['scope'] and auth['plan_digest']==digest(plan)
assert all(auth[k]==v for k,v in identity_fields(plan).items())
provenance=read(R/'authorization_provenance.json')
assert provenance['user_message_exact']=='我明确授权执行' and provenance['plan_digest']==digest(plan)
assert (plan['assessment_limit'],plan['solver_limit'],plan['model_calls_max'])==(8,128,0)
ledger=read(Path(plan['call_ledger_path']))
assert ledger=={'version':'geometry_call_ledger_v1','plan_digest':digest(plan),'evidence':'REAL_KERNEL','limits':{'assessment_entries':8,'solver_calls':128},'calls':[],'counts':{'assessment_entries':0,'solver_calls':0,'test_double_assessments':0}}
assert len(read(R/'run_denominator_NOT_RUN.json')['rows'])==4 and all(r['status']=='NOT_RUN' for r in read(R/'run_denominator_NOT_RUN.json')['rows'])
assert len(read(R/'recovery_NOT_RUN.json')['rows'])==6 and all(r['status']=='NOT_RUN' for r in read(R/'recovery_NOT_RUN.json')['rows'])
assert before=={str(f):sha(f) for f in R.rglob('*') if f.is_file()}
result={'unit':'GP5_P2_BOUNDED_REAL_MONITOR_USABILITY','synced_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'host_preflight':'PASS_READONLY','source_files':len(files),'source_identity':digest(files),'plan_digest':digest(plan),'monitor_digest':digest(snap),'actual_order_environment':p.environment(),'actual_monitor_environment':monitor_environment(),'dependency_identity':snap['algorithm_identity']['dependencies'],'authorization_context':'Original conversation visible to execution agent: user explicitly authorized following 4+6,8/128/0 scope; no repeat authorization required. Independent window must verify context before signing.','runtime_files_unchanged':True,'runtime_file_hashes':before,'independent_review':'MISSING','launch_record':'NOT_ISSUED','four_job_joint_admission_preflight':'NOT_RUN_MISSING_REVIEW_AND_LAUNCH','dispatch':'NOT_READY','primary':'4/4 NOT_RUN','recovery':'6/6 NOT_RUN','real_assessments_this_turn':0,'actual_LP_this_turn':0,'model_calls_this_turn':0,'freeze_this_turn':0,'ledger':ledger,'stop':'INDEPENDENT_WINDOW_REVIEW_AND_LAUNCH_REQUIRED'}
(O/'host_preflight.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('PASS original Linux host/source/tasks/snapshot/dependencies/auth binding/zero ledger; runtime unchanged. STOP missing independent review and launch; real execution0.')
