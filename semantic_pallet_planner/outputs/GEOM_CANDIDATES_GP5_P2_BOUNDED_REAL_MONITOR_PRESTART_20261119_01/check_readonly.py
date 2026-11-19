"""Read identities only; no freeze, permits, ledger initialization or dispatch."""
from pathlib import Path
import json, hashlib, subprocess, sys
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.geometry_order_execution import validate_monitor_snapshot
from semantic_pallet_planner.jev_select.stability.runtime import environment as monitor_environment
from semantic_pallet_planner.jev_select.contracts import digest
O=Path(__file__).parent
B=O.parent
D=B/'GEOM_CANDIDATES_GP5_P2_R1_EXTERNAL_REVIEW_BINDING_20261119_01'
S=Path('semantic_pallet_planner/src/semantic_pallet_planner')
read=lambda f:json.loads(f.read_bytes())
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
def write(n,v):(O/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
files={str(f.relative_to(S)):sha(f) for f in S.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(S).parts)}
assert files==read(D/'source_manifest.json')['files']
assert digest(files)=='3b58b72f9f31913afb0e2180911dadad0c02c10f58171f8eeb632f3988b4b956'
plan=read(D/'acceptance_plan_DRAFT.json');p.validate_order_plan(plan)
tasks=[]
for case,identity in zip(('K01','K02'),plan['tasks'],strict=True):
 raw=(D/f'{case}_task.json').read_bytes()
 adapted=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=identity['raw_sha256'])
 assert adapted['identity']==identity
 tasks.append({'case':case,'path':str(D/f'{case}_task.json'),'identity':identity})
meta=B/'GEOM_CANDIDATES_GP5_P2_REAL_MONITOR_PREPARATION_20261119_01/monitor_metadata_READONLY_NOT_FROZEN.json'
snap=read(meta)['snapshot'];actual=monitor_environment()
try:
 validate_monitor_snapshot(snap);result='PASS_READONLY'
except Exception as e:
 result=str(e)
 assert result=='geometry_order_monitor_environment',result
changed={k:{'historical':snap['execution_environment'].get(k),'actual':actual.get(k)} for k in set(actual)|set(snap['execution_environment']) if actual.get(k)!=snap['execution_environment'].get(k)}
root=B/'GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01'
assert not root.exists(),'PROPOSED_RUNTIME_ROOT_ALREADY_EXISTS'
write('identity_readonly.json',{'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_identity':digest(files),'source_files':len(files),'source_and_runtime_contract_drift':False,'environment':p.environment(),'environment_digest':digest(p.environment()),'tasks':tasks,'monitor_metadata_reference':{'path':str(meta),'sha256':sha(meta)},'monitor_metadata_digest':digest(snap),'monitor_preflight':result,'monitor_source_dependencies':'PASS_BEFORE_ENVIRONMENT_CHECK','monitor_algorithm_identity':snap['algorithm_identity'],'historical_monitor_environment':snap['execution_environment'],'actual_monitor_environment':actual,'monitor_environment_differences':changed,'new_freeze':'NOT_ISSUED','historical_freeze_reusable':False})
write('startup_proposal.json',{'unit':'GP5_P2_BOUNDED_REAL_MONITOR_USABILITY','status':'PENDING_USER_EXECUTION_AUTHORIZATION','execution_authorized':False,'historical_draft_reference':{'path':str(D/'acceptance_plan_DRAFT.json'),'sha256':sha(D/'acceptance_plan_DRAFT.json'),'digest':digest(plan)},'historical_draft_is_execution_plan':False,'proposed_runtime_root':str(root),'proposed_shared_call_ledger_path':str(root/'shared_call_ledger.json'),'runtime_root_exists':False,'active_ledger':'NOT_CREATED','limits_proposal':{'assessment_entries':8,'solver_calls':128,'model_calls':0},'fresh_denominator':4,'recovery_denominator':6,'feature_profile':'F0_existing_facts','scope':p.ACCEPTANCE,'runtime_version':plan['runtime_version'],'publication_policy_digest':plan['publication_policy_digest'],'gates':[{'gate':'USER_EXPLICIT_EXECUTION_AND_BUDGET_AUTHORIZATION','status':'MISSING'},{'gate':'NEW_ACTUAL_HOST_FREEZE_AND_SHARED_LEDGER','status':'NOT_ISSUED_PENDING_AUTHORIZATION'},{'gate':'INDEPENDENT_LAUNCH_REVIEW_OF_SAME_FROZEN_PLAN','status':'MISSING'},{'gate':'MATCHING_AUTHORIZATION_LAUNCH_RECORD_LEDGER_PREFLIGHT','status':'NOT_READY'}],'stop':'No freeze before explicit authorization; no dispatch before all gates; no self-signed review.'})
write('fixed_denominator_NOT_RUN.json',{'primary':[{**r,'actual':'NOT_RUN','actual_metrics':None,'actual_action':None,'actual_termination':None} for r in read(D/'matrix_DRAFT.json')['rows']],'recovery':read(D/'recovery_DRAFT.json')['rows'],'primary_denominator':4,'recovery_denominator':6,'real_assessment_entries_this_turn':0,'real_solver_calls_this_turn':0,'model_calls_this_turn':0,'freeze_this_turn':0,'timing':'NOT_RUN','service_cost':'NA_NO_SERVICE_CALL','local_compute_cost':'UNKNOWN'})
write('command_receipts.json',{'commands':[{'command':'git status --short; git branch --show-current; git rev-parse --abbrev-ref --symbolic-full-name @{u}; git rev-parse HEAD','result':'dev/jev-select; origin/dev/jev-select; 2c4f8e87; worktree/index clean'},{'command':'git pull --ff-only','result':'initial sandbox FETCH_HEAD read-only; escalated retry succeeded fast-forward 2c4f8e87..1ff6d93c; no merge/rebase/stash/reset'},{'command':'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src python semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_R1_EXTERNAL_REVIEW_BINDING_QA_20261119_01/check_archive.py','result':'PASS current30 historical manifests33 historical files31 source591 DRAFT4+6; identity/static checks only'},{'command':'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src python '+str(O/'check_readonly.py'),'result':'PASS source/tasks/proposed paths; historical monitor environment rejected as recorded; no freeze or dispatch'}]})
print(json.dumps({'source':digest(files),'files':len(files),'monitor_preflight':result,'environment_differences':changed,'root_exists':root.exists(),'real_dispatch':0},ensure_ascii=False,indent=2))
