"""Freeze current code/config/fixed scope; no episode, generation or monitor."""
import hashlib,json,subprocess
from pathlib import Path
from test_geometry_order_p1 import SNAP,adapted
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p,geometry_order_execution as o
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields
OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01')
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
base=json.loads((OUT/'baseline_receipt.json').read_bytes())
src=Path('semantic_pallet_planner/src/semantic_pallet_planner')
current={str(f.relative_to(src)):hashlib.sha256(f.read_bytes()).hexdigest() for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
assert set(current)==set(base['files'])
changed=[k for k,h in current.items() if h!=base['files'][k]]
assert changed==['jev_select/schemas/checkpoint_v17.schema.json'],changed
save('source_manifest.json',{'files':current,'source_identity':digest(current),'source_files':len(current),'changed':changed,'baseline_identity':base['source_identity']})
tasks=[adapted('K02_INT'),adapted('K02')]
plan=p.prepare_order_plan(tasks,data_identity=digest('NUM_N1_R1_FIXED_SYNTHETIC'),scope=p.DEVELOPMENT,native=True)
admission={**identity_fields(plan),'version':'geometry_development_binding_v2','scope':p.DEVELOPMENT,'evidence':'TEST_DOUBLE','plan_digest':digest(plan)}
configs={j['job_id']:o.load_order_config(plan,j['job_id'],monitor_snapshot=SNAP,admission=admission) for j in plan['jobs']}
save('plan.json',plan);save('admission.json',admission);save('configs.json',configs);save('monitor_snapshot.json',SNAP)
for task in tasks:
 save(task['identity']['task_id']+'.identity.json',task['identity'])
 (OUT/(task['identity']['task_id']+'.raw.json')).write_bytes(task['raw'])
scope={'unit':'GP5_NUM_N1_R1_SCHEMA_AND_BOUNDED_REVALIDATION','source_identity':digest(current),'plan_digest':digest(plan),'config_digests':{k:digest(v) for k,v in configs.items()},
 'first_unexpected_failure':'STOP_NO_RETRY_NO_EXPANSION','C':['I0','I90','F0','F90','M0','M90'],
 'E':{'jobs':[j['job_id'] for j in plan['jobs']],'cases':['K02_INT','K02'],'max_new_monitors':16,'old_failed_E_monitors':1,'max_E_cumulative':17,'extra_seeds':0},
 'R':{'jobs':['J01','J03'],'phases':['SELECTED','MONITORED','COMMITTED'],'last_box_only':True,'resumes_max':6,'new_generation_publication_selection':0,'monitor_increment_max':2,'commit_increment_max':4,
 'snapshot_protocol':'At last-box phase hook copy full current root, fork a no-dispatch child and unwind a planned BaseException through original accounting/driver into copied IO paths only. Parent prefix bytes unchanged. No hand-edit of counters/status/checkpoint. Distinct preserved snapshots and recovery roots.'},
 'X_H':[{'name':name,'test_double_monitor_max':count,'execution':'saved-copy/pure contract unless explicitly stated'} for name,count in [
 ('X_pure_size_bool_rounding_unrepresentable_axis_yaw',0),('X_schema_unknown_version_unknown_field',0),('X_missing_proof_three_phases',0),('X_missing_shadow_derived_final_binding',0),('X_tampered_bytes_signed_zero',0),('X_swapped_evidence_raw_P_mismatch',0),('X_policy_source_config_backend_task_scope_drift',0),
 ('H_v14_execution_refusal',0),('H_v15_real_task_refusal',0),('H_v16_K02_INT_original_failure',1),('H_v1_snapshot_type_bit_refusal',0),('H_accounting_unknown_dispatch_missing_history',0),('H_terminal_commit_failure_validator',0),('H_strong_completion_missing_duplicate_error_no_commit',0),('ADMIN_real_task_read_adapt_digest_pre_episode_refusal',0)]],
 'X_H_max_monitors':1,'R1_real_kernel_LP_freeze_model_orders_GP6_install_agents':0,
 'notes':['X/H are separate from E/R; no blanket total<=18 claim','H terminal/completion use original saved-copy/contract checks, not extra live resumes or newly generated orders','First failed old J00 never resumed or modified']}
save('validation_scope.json',scope)
print('Frozen',len(current),'source files;',len(configs),'configs; fixed C/E/R/X/H names and separate budgets')
