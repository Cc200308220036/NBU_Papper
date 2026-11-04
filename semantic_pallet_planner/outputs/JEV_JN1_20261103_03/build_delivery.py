"""Derive delivery receipts from frozen records. No order/selector/solver call."""
from pathlib import Path
import hashlib
from collections import Counter
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.packaging_metrics import distribution

OUT=Path(__file__).resolve().parent
REPO=OUT.parents[2]
RUN=OUT/'run'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=read(OUT/'plan/plan.json');summary=read(RUN/'summary.json');audit=read(OUT/'final_record_validation.json')
assert audit['status']=='PASS' and summary['status']=='PASS_IN_EXECUTED_SCOPE'
assert summary['categories']['NOT_RUN']==0 and summary['model_calls']==17
assert source_manifest()==plan['source_manifest']==read(OUT/'source_manifest.json')
rows=[];events=[];fair=[]
for j in plan['jobs']:
    job=RUN/'jobs'/j['job_id'];m=read(job/'metrics.json');rows.append({'job_id':j['job_id'],**m});events+=read(job/'checkpoint.json')['events']
for tid in plan['task_ids']:
    js=[j for j in plan['jobs'] if j['task_id']==tid]
    cfgs=[j['config'] for j in js]
    common=[k for k in cfgs[0] if k not in ('selector','model','runtime_identity')]
    assert all(all(c[k]==cfgs[0][k] for k in common) for c in cfgs)
    assert all(all(c['runtime_identity'][k]==cfgs[0]['runtime_identity'][k] for k in ('data_identity','task_identity','physical_identity','monitor_identity')) for c in cfgs)
    cs=[read(RUN/'jobs'/j['job_id']/'contexts'/f"{j['job_id']}_D0000.json") for j in js]
    assert all(all(c[k]==cs[0][k] for k in ('model_state','criteria','display_mapping')) for c in cs)
    fair.append({'task_id':tid,'same_public_config_keys':common,'same_initial_public_state_pool_mapping':True,'later_trajectory_pools_need_not_equal':True})
write(OUT/'same_protocol_review.json',{'version':'jev_jn1_b_same_protocol_v1','status':'PASS','tasks':fair,'allowed_method_differences':['selector','model for local-vs-remote','strategy_identity'],
 'same_source_manifest_digest':digest(plan['source_manifest']),'JN0_records_used_as_controls':False})
write(OUT/'per_job_results.json',rows)
write(OUT/'batch_statistics.json',{'version':'jev_jn1_b_statistics_v1','summary':summary,'historical_A_calls':1,'B_new_calls':17,'A_B_cumulative_calls':18,
 'historical_A_not_counted_as_complete_job':True,'B_full_order_jobs':6,'B_remote_jobs':2,'B_local_jobs':4,'monitors':dict(sum((Counter(r['monitor_statuses']) for r in rows),Counter())),
 'runtime_singleton_decisions':sum(r['singleton_decisions'] for r in rows),'cost_usd':'UNKNOWN','source_groups':2,'independent_unseen_sources':0})
write(OUT/'latency_summary.json',{'version':'jev_jn1_b_latency_v1',
 'request':summary['request_statistics']['request_latency_s'],
 'candidate':distribution([e['timings']['physical_generation_s'] for e in events if 'physical_generation_s' in e['timings']]),
 'selection':distribution([e['timings']['selection_s'] for e in events if 'selection_s' in e['timings']]),
 'decision':distribution([e['timings']['decision_segments_s'] for e in events if 'decision_segments_s' in e['timings']]),
 'monitor':distribution([e['monitor']['result']['duration_s'] for e in events if e.get('monitor') and e['monitor']['result']]),
 'active_job':distribution([r['failure_location']['active_wall_s'] for r in rows]),
 'interpretation':'saved wall segments; request not isolated inference; offline record validation excluded from active job time; quantiles include full sample counts'})
empty=[]
for j in plan['jobs']:
    if read(RUN/'jobs'/j['job_id']/'status.json')['category']!='EMPTY_POOL':continue
    e=read(RUN/'jobs'/j['job_id']/'checkpoint.json')['events'][-1]
    empty.append({'job_id':j['job_id'],'task_id':j['task_id'],'decision_id':e['decision_id'],'generation_counts':e['bundle']['generation_counts'],
                  'placed':len(e['before']['placed_items']),'arrived':e['before']['arrival_count'],'pending':[p['item']['item_id'] for p in e['before']['pending_items']],
                  'source':'original stored sampler rejection counts only; no new enumeration or global infeasibility proof'})
write(OUT/'empty_pool_diagnostics.json',empty)
index=read(RUN/'decision_index.json');real=[r for r in index if r['method']=='jev_no_memory' and r['eligible_training_decision']]
assert len(real)==17 and Counter(r['task_id'] for r in real)=={plan['task_ids'][0]:11,plan['task_ids'][1]:6}
write(OUT/'jn2_decision_index.json',{'version':'jev_jn2_decision_index_v1','run_manifest_sha256':sha(RUN/'delivery_manifest.json'),
 'run_index':'run/decision_index.json','all_decisions':index,'real_multi_candidate_training_decisions':real,'winner_filtering':False})
limits=['two exposed training sources; all task feasibility UNKNOWN and capacities synthetic',
 'six complete-order attempts naturally stop:5 EMPTY_POOL,1 UNASSESSABLE; zero fully loaded orders, no global infeasibility claim',
 'POSE_HEIGHT_MISMATCH conservative top-down/under-overhang boundary retained; affected pairs comparison_valid=false',
 'only17 new real multi-candidate choices, no real UNSTABLE/ERROR/UNKNOWN_SEND observed; negative recovery paths tested with constructed tasks',
 'native probabilities retained; explicit service rank unavailable and tie rule UNKNOWN; not physical confidence or generated explanation',
 'actual billed cost UNKNOWN; no retries,extra probes or second campaign',
 'limited descriptive sample cannot establish policy benefit,full-order reliability or unseen generalization',
 'JN2 forks/continuation/reference branches not implemented or run; require separate authorization']
input_receipt={'version':'jev_jn2_input_receipt_v1','stage':'JN1-B-to-JN2','status':'READY_IN_DECLARED_SCOPE',
 'plan_digest':digest(plan),'run_manifest_sha256':sha(RUN/'delivery_manifest.json'),'data_identity':plan['data_identity'],
 'source_manifest_digest':digest(plan['source_manifest']),'source_groups':[j['source_group_id'] for j in plan['jobs'] if j['method_id']=='jev_no_memory'],
 'all_decisions':55,'real_multi_candidate_decisions':17,'real_decisions_per_task':dict(Counter(r['task_id'] for r in real)),
 'index':'jn2_decision_index.json','record_schema':'plan/code_snapshot/jev_select/schemas/packaging_full_order_decision_v1.schema.json',
 'private_tasks':'plan/tasks and run/jobs/*/task.snapshot.json; private full order not selector input',
 'prefix_restore_material':'DecisionRecord.before + arrival_cursor + buffer + saved public candidate pool/mapping; stages and original checkpoints bound to plan/runtime identities',
 'probability_ranking':'native probability maps; no provider explicit ordered ranks; tie rule UNKNOWN; future fork rule must be preregistered',
 'input_gaps':[],'JN2_admitted':True,'JN2_executed':False,'required_next_contract':'same saved prefix/pool,original action plus identical continuation reference,retain all branches/no benefit claims beyond scope',
 'limits':limits}
write(OUT/'jn2_input_receipt.json',input_receipt)
accept={
'B01':{'status':'PASS','detail':'two different exposed sources,6jobs,fixed JEV/geometry/first order; same v6/source/physical/monitor; old packages unchanged','evidence':['preregistration.json','plan/plan.json','same_protocol_review.json','protected_before_after.json']},
'B02':{'status':'PASS','detail':'full natural runs,5 empty and1 declared range stop; all17 real choices exact monitored/committed; no8-event cap','evidence':['run/job_ledger.json','run/decision_index.json','per_job_results.json','monitor_scope_review.json']},
'B03':{'status':'PASS','detail':'17 reservations/network attempts/valid responses;0 failed/unknown/singleton/reuse in live runs; ledger authoritative; usage207033/6784,actual billUNKNOWN','evidence':['run/request_ledger/requests.json','run/summary.json','batch_statistics.json','tests/current_local.xml']},
'B04':{'status':'PASS','detail':'116 local tests;pilot3jobs audited before continuation;6job full denominator;repeated final read-only validator no network/select/generation/commit/PCT','evidence':['tests/current_local.xml','pilot_release.json','pilot_record_validation.json','final_record_validation.json']},
'B05':{'status':'PASS','detail':'six per-job metrics,all6 pair comparisons;first-source range pairs invalid;no cherry-picked outcomes or policy-benefit claim','evidence':['per_job_results.json','run/paired_differences.json','empty_pool_diagnostics.json','monitor_scope_review.json','latency_summary.json']},
'B06':{'status':'PASS','detail':'readiness and versioned DecisionRecord/schema,index55 records incl17 real multicandidate training decisions;no JN2 input gap,no fork execution','evidence':['jev_no_memory_readiness.json','interface_contract.json','jn2_decision_index.json','jn2_input_receipt.json']}}
ns={
'N05':{'status':'PASS_IN_DECLARED_SCOPE','basis':'A registered v6+source completion, B new sealed full-order plan/run and actual same-protocol three-method execution'},
'N06':{'status':'PASS_IN_DECLARED_SCOPE','basis':'A+B official contract,strict parsing and exact binding;17 B native responses,real origin/usage/unknown cost;current local negative tests'},
'N07':{'status':'PASS_IN_DECLARED_SCOPE','basis':'historical A single choice plus B2real full-order jobs+4local controls;all naturally closed and audited;no failure substitution;not full loading reliability'}}
write(OUT/'engineering_acceptance.json',{'version':'jev_jn1_b_acceptance_v1','stage':'JN1-B','status':'PASS_IN_DECLARED_SCOPE','B01_B06':accept,'N05_N07':ns,
 'A01_A07_reference':'../JEV_JN1_20261103_01/engineering_acceptance.json','S01_S05_reference':'../JEV_JN1_20261103_02/engineering_acceptance.json',
 'full_JN1_engineering_complete':True,'all_orders_loaded':False,'research_benefit':'NOT_ESTABLISHED','JN2_admitted':True,'JN2_executed':False,'limits':limits})
ready={'version':'jev_no_memory_readiness_v1','stage':'JN1-B','status':'PASS_IN_DECLARED_SCOPE','B01_B06':{k:v['status'] for k,v in accept.items()},'N05_N07':ns,
 'parent_receipts':plan['parent_receipts'],'plan_digest':digest(plan),'run_manifest_sha256':sha(RUN/'delivery_manifest.json'),
 'source_manifest_digest':digest(plan['source_manifest']),'data_identity':plan['data_identity'],'execution_version':plan['execution_version'],
 'full_order_jobs':6,'real_full_order_jobs':2,'local_full_order_jobs':4,'request_budget':plan['request_budget'],'actual_requests':summary['request_statistics'],
 'historical_A_calls':1,'B_new_calls':17,'A_B_cumulative_calls':18,'JN1_engineering_complete':True,'full_loading_completed_orders':0,
 'JN2_admitted':True,'JN2_input_receipt':'jn2_input_receipt.json','JN2_executed':False,'research_benefit':'NOT_ESTABLISHED','limits':limits}
write(OUT/'jev_no_memory_readiness.json',ready)
write(OUT/'handoff.json',{'version':'jev_jn1_b_handoff_v1','stage':'JN1-B','status':'PASS_IN_DECLARED_SCOPE','parent_receipts':plan['parent_receipts'],
 'data_identity':plan['data_identity'],'source_manifest_digest':digest(plan['source_manifest']),'plan_digest':digest(plan),
 'source_data_identity':sha(REPO/plan['dataset']/'source_manifest.json'),'split_identity':sha(REPO/plan['dataset']/'split_manifest.json'),
 'algorithm_identity_digest':digest(plan['jobs'][0]['config']['stability_monitor']['algorithm_identity']),
 'job_config_identities':{j['job_id']:digest(j['config']) for j in plan['jobs']},'methods':plan['method_contract'],'interfaces':'interface_contract.json',
 'job_ledger':'run/job_ledger.json','request_ledger':'run/request_ledger/requests.json','request_statistics':summary['request_statistics'],
 'historical_A_calls':1,'B_new_calls':17,'A_B_cumulative_calls':18,'B01_B06':{k:v['status'] for k,v in accept.items()},'N05_N07':ns,
 'readiness':'jev_no_memory_readiness.json','JN2_admitted':True,'JN2_input':'jn2_input_receipt.json','JN2_executed':False,
 'full_JN1_engineering_complete':True,'research_benefit':'NOT_ESTABLISHED','limits':limits,
 'report':'docs/03_阶段产出分析/Jev/Jev_JN1-B真实完整订单与同协议本地对照验收_20261103.md',
 'stop':'JN1-B delivered; remaining16 unused reservation slots do not authorize extra jobs;no JN2,agents,automatic commit/push',
 'archive_policy':'existing ignores unchanged;no automatic git add/commit/push'})
write(OUT/'commands.json',{'version':'jev_jn1_b_commands_v1','cwd':'NBU_Papper','environment':'existing Python, PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src',
 'commands':[
 {'command':'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python semantic_pallet_planner/outputs/JEV_JN1_20261103_03/run_local_tests.py','result':'116 passed,96 warnings;tests/current_local.xml and .log;real network/credential file counters0'},
 {'command':'python -m semantic_pallet_planner.jev_select plan-packaging-remote-orders --dataset semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02 --output semantic_pallet_planner/outputs/JEV_JN1_20261103_03/plan','result':'6jobs,2sources,global send reservation limit33'},
 {'command':'python -m semantic_pallet_planner.jev_select run-packaging-remote-orders --plan semantic_pallet_planner/outputs/JEV_JN1_20261103_03/plan --output semantic_pallet_planner/outputs/JEV_JN1_20261103_03/run --api-key-file typesafe_api_key.md','result':'pilot only,first3closed;remaining3NOT_RUN;11real sends'},
 {'command':'python semantic_pallet_planner/outputs/JEV_JN1_20261103_03/audit_run.py','result':'pilot guard audit twice,PASS'},
 {'command':'python -m semantic_pallet_planner.jev_select run-packaging-remote-orders --plan semantic_pallet_planner/outputs/JEV_JN1_20261103_03/plan --output semantic_pallet_planner/outputs/JEV_JN1_20261103_03/run --api-key-file typesafe_api_key.md --resume --continue-pending','result':'second3closed,no first-task rerun,Btotal17real sends'},
 {'command':'python semantic_pallet_planner/outputs/JEV_JN1_20261103_03/audit_run.py','result':'final guard audit twice,PASS,all run files unchanged'},
 {'command':'python semantic_pallet_planner/outputs/JEV_JN1_20261103_03/scope_review.py','result':'stored geometry only,onePOSE_HEIGHT_MISMATCH,no solver'},
 {'command':'git diff --check','result':'PASS'}],
 'local_development':'Earlier8/13/114/115-case checks overlap;not summed. Admission and reuse metadata were completed before the final116-case run and formal freeze.',
 'supplemental_pilot_check':'Initial ad-hoc same-state check used unsorted glob and compared different decision indices. Explicit D0000 comparison passed without source/identity change. Standard pilot gate/audit already passed;runner also validated gate before second-task dispatch.',
 'not_run':['JN0 matrix','historical full replay','extra probes/retries','DeepSeek','memory/forks/unseen evaluation','JN2']})
print({'status':'PASS','B01_B06':'PASS','N05_N07':'PASS_IN_DECLARED_SCOPE','JN2_input':len(real),'JN2_admitted':True})
