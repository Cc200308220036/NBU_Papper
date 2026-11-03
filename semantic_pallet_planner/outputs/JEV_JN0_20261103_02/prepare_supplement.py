"""Freeze authorized JN0 supplement, from repository root; zero order dispatch."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import hashlib
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.packaging_experiment import prepare_packaging_plan
from semantic_pallet_planner.jev_select.experiment import source_manifest

root=Path('semantic_pallet_planner/outputs/JEV_JN0_20261103_02');old=Path('semantic_pallet_planner/outputs/JEV_JN0_20261103_01')
prior=read(old/'plan_revision_02/plan.json');source=source_manifest();before=read(root/'baseline_source_manifest.json')
assert not (root/'supplement_spec.json').exists()
run_spec={'task_ids':prior['task_ids'],'method_ids':prior['method_ids'],'watchdog':prior['watchdog']}
write(root/'run_spec.json',run_spec)
receipt=prepare_packaging_plan('semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02',run_spec,root/'plan')
plan=read(root/'plan/plan.json')
assert [(j['task_id'],j['method_id']) for j in plan['jobs']]==[(j['task_id'],j['method_id']) for j in prior['jobs']]
for oldj,newj in zip(prior['jobs'],plan['jobs']):
    a=dict(oldj['config']);b=dict(newj['config']);a.pop('runtime_identity');b.pop('runtime_identity');assert a==b
    assert oldj['task_digest']==newj['task_digest']
spec={'version':'jev_jn0_supplement_spec_v1','purpose':'JN0 supplemental acceptance only; no JN1 implementation or model API',
    'preregistered_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),
    'parent_delivery':old.as_posix(),'parent_manifest_sha256':hashlib.sha256((old/'delivery_manifest.json').read_bytes()).hexdigest(),
    'original_plan_digest':digest(prior),'original_readiness_sha256':hashlib.sha256((old/'full_order_readiness.json').read_bytes()).hexdigest(),
    'original_failure_job':'J0000','original_categories':{'ERROR':1,'NOT_RUN':7},
    'task_ids':plan['task_ids'],'method_ids':plan['method_ids'],'ordered_jobs':[{'job_id':j['job_id'],'task_id':j['task_id'],'method_id':j['method_id']} for j in plan['jobs']],
    'new_plan_digest':digest(plan),'source_manifest_digest':digest(source),'data_identity':plan['data_identity'],
    'execution_protocol':plan['execution_version'],'algorithm':'pct_contact_network_v2','result_version':'pct_stability_result_v2',
    'monitor_enabled':True,'display_order_seed':plan['jobs'][0]['config']['display_order_seed'],'watchdog':plan['watchdog'],
    'budget':{'historical_actual_starts':1,'historical_planned_slots':8,'new_planned_slots':8,'new_actual_starts_max':8,'cumulative_actual_starts_max':9},
    'failure_reexecution':'Only original J0000 is preregistered for one new-identity from-start repair verification; no automatic retry.',
    'batches':[{'job_ids':['J0000','J0001'],'gate':'Both close, standard saved-record validation and read-only summary pass; monitor range reviewed before continuation'},
               {'job_ids':[f'J{i:04d}' for i in range(2,8)],'gate':'Explicit continuation after pilot receipt; source unchanged'}],
    'stop':'Technical error, watchdog or cancellation stops later jobs; unexplained/systematic UNASSESSABLE requires stopping; never edit code and auto-reopen budget.',
    'model_calls_authorized':0,'origin':'LOCAL_TEST_DOUBLE_NOT_JEV'}
write(root/'supplement_spec.json',spec);write(root/'supplement_receipt.json',{'version':spec['version'],'spec_digest':digest(spec)})
write(root/'source_change_review.json',{'before_files':len(before),'after_files':len(source),'modified':[n for n in before if before[n]!=source.get(n)],
    'added':[n for n in source if n not in before],'removed':[n for n in before if n not in source],
    'physical_unchanged':plan['physical_manifest']==prior['physical_manifest'],
    'monitor_unchanged':all(a['config']['stability_monitor']==b['config']['stability_monitor'] for a,b in zip(prior['jobs'],plan['jobs'])),
    'public_configs_unchanged_except_frozen_runtime_identity':True,'gitignore_changed':False})
print(receipt)
print('All 8 new slots frozen before pilot; maximum cumulative actual starts 9.')
