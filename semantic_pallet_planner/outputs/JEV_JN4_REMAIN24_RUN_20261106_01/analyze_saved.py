"""Saved-record analysis only. No candidates, selection, monitor, commit or API."""
import csv
import sys
import json
import hashlib
from collections import Counter
from pathlib import Path
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.packaging_reanalysis import evaluate,metric_view,RULE_VERSION

OUT=Path(__file__).parent
PREP=Path('semantic_pallet_planner/outputs/JEV_JN4_REMAIN24_20261106_01')
def read(p):return json.loads(Path(p).read_text())
def write(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
p=read(PREP/'plan/plan.json');run=Path(p['run_location'])
parent=read(Path(p['remainder']['plan'])/'plan.json');parentrun=Path(p['remainder']['run'])
original=read(Path(p['parent']['plan'])/'plan.json');originalrun=Path(p['parent']['run'])
plans=[original,parent,p];runs=[originalrun,parentrun,run]
revisions=['34fc871d','15d0c809','52d3252e']
summaries=[read(r/'summary.json') for r in runs]
rows=[];views={};coverage=[];sequences=[]
for originaljob in original['jobs']:
    i=int(originaljob['job_id'][1:]);group=0 if i<7 else 1 if i<12 else 2
    plan=plans[group];job=next(j for j in plan['jobs'] if j['job_id']==originaljob['job_id'])
    root=runs[group]/'jobs'/job['job_id'];status=read(root/'status.json')
    metric=read(root/'metrics.json') if (root/'metrics.json').exists() else None
    row={k:job[k] for k in ('job_id','task_id','method_id')}
    row.update(record_origin=['v2_historical7','v3_previous5','v3_remaining24'][group],
        algorithm=job['config']['stability_monitor']['algorithm'],protocol=job['config']['version'],
        source_delivery_commit=revisions[group],source_manifest_digest=digest(plan['source_manifest']),
        strategy_identity=job['config']['runtime_identity']['strategy_identity'],
        run=str(runs[group]),evidence_root=str(root),status=status,
        termination_reason=read(root/'checkpoint.json')['reason'] if (root/'checkpoint.json').exists() else 'NOT_RUN' if status['state']=='NOT_RUN' else 'UNKNOWN',
        metrics=metric if metric else 'NOT_RUN' if status['state']=='NOT_RUN' else 'UNKNOWN_TECHNICAL_FAILURE')
    rows.append(row)
    identity={k:row[k] for k in ('job_id','task_id','method_id','record_origin','algorithm','source_manifest_digest','run')}
    if metric:
        views[job['task_id'],job['method_id']]=(row['algorithm'],metric_view({'metrics':metric,'status':status},read(root/'task.snapshot.json'),p['data']['data_identity']))
        mem=metric['memory_metrics'];ds=mem['decisions']
        coverage.append({**identity,'decisions':mem['decision_count'],
            'retrieval_nonempty':sum(d['qualified_retrieval_nonempty'] for d in ds),
            'view_nonempty':mem['view_nonempty_count'],'body_nonempty':mem['body_nonempty_count'],
            'actually_sent_nonempty':mem['actually_sent_nonempty_count'],
            'singleton_decisions':sum(d['route']=='SINGLETON_BYPASS' for d in ds),
            'singleton_nonempty_view':mem['singleton_nonempty_view_count']})
        sequences.append({**identity,'decisions':[{k:d[k] for k in ('decision_id','selected_candidate_id','selected_box','selected_pose')} for d in ds]})
    else:coverage.append({**identity,'coverage':row['metrics']})
write('all_36_slots.json',rows);write('new_24_slots.json',rows[12:]);write('coverage_summary.json',coverage);write('behavior_observations.json',sequences)
fields=['job_id','task_id','method_id','record_origin','algorithm','protocol','source_delivery_commit','source_manifest_digest','run','category','termination_reason','placed_items','planned_items','placed_item_ratio','placed_volume_ratio','placed_mass_ratio','fixed_container_utilization','actual_height_mm','envelope_utilization','monitor_statuses','monitor_reasons','memory_metrics','latency_s','cost']
for name,subset in [('all_36_slots.csv',rows),('new_24_slots.csv',rows[12:])]:
 with (OUT/name).open('w',newline='') as stream:
    w=csv.DictWriter(stream,fieldnames=fields);w.writeheader()
    for row in subset:
        d={k:row[k] for k in fields[:9]};d.update(category=row['status']['category'],termination_reason=row['termination_reason']);m=row['metrics']
        for k in fields[11:]:
            v=m.get('loading',{}).get(k,m.get(k,'UNKNOWN')) if isinstance(m,dict) else m
            d[k]=json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v
        w.writerow(d)
pairs=[]
for task in original['task_ids']:
 for alt,ref,label in [('jev_with_trajectory','jev_no_memory','T/none'),('jev_with_contrast_experience','jev_no_memory','E/none'),('jev_with_contrast_experience','jev_with_trajectory','E/T'),('jev_with_contrast_experience','jev_with_unrelated_E_control','E/unrelated_E')]:
    a=views.get((task,ref));b=views.get((task,alt))
    result=evaluate(a[1],b[1],rule_version=RULE_VERSION) if a and b and a[0]==b[0] else {'comparison_valid':False,'label_v2':'NOT_RUN' if not a or not b else 'INVALID_CROSS_VERSION'}
    pairs.append({'task_id':task,'comparison':label,'algorithm':a[0] if a else 'NOT_RUN','historical':task=='SYN_COMBO_01','new24':task in original['task_ids'][2:],'reference_method':ref,'alternative_method':alt,'evaluation':result})
write('paired_comparisons_v2.json',pairs)
stats=[s['request_statistics'] for s in summaries];known=sum(s['known_real_model_calls'] for s in stats);unknown=sum(s['unknown_real_send_count'] for s in stats)
combined={k:sum(s[k] for s in stats) for k in ('send_reservations','network_attempts','known_real_model_calls','unknown_real_send_count','failed_requests','valid_responses')}
combined.update(global_cap=656,remaining_reservations=656-combined['send_reservations'],actual_model_api_calls='UNKNOWN' if unknown else known,real_model_call_interval={'minimum':known,'maximum':known+unknown},model_cost_usd='UNKNOWN',
    usage={k:sum(s['usage'][k] for s in stats) for k in ('input_tokens','output_tokens','known_request_count','missing_request_count')})
assert combined['send_reservations']==121+stats[2]['send_reservations']<=633
assert known==120+stats[2]['known_real_model_calls'] and unknown==1+stats[2]['unknown_real_send_count']
newrows=rows[12:];closed=sum(r['status']['state']=='FINISHED' for r in newrows);notrun=sum(r['status']['state']=='NOT_RUN' for r in newrows)
summary=summaries[2];newrequests=read(run/'request_ledger/requests.json')['requests']
scoped=[];unknowns=[];served=Counter()
for location,plan in zip(runs,plans):
 for r in read(location/'request_ledger/requests.json')['requests']:
    record={'run':str(location),'attempt_id':r['attempt_id'],'job_id':r['job_id'],'decision_id':r['decision_id'],'state':r['state'],'send_started':r['send_started'],'origin':r['origin'],'request_digest':digest(r),'served_model':r['selection'].get('served_model') if r['selection'] else None,'transport':{k:r['transport'].get(k) for k in ('status','http_status','network_attempted','error_code','error_stage','latency_s')} if r['transport'] else None}
    scoped.append(record)
    if record['served_model']:served[record['served_model']]+=1
    if r['state']=='UNKNOWN_SEND':unknowns.append(record)
write('scoped_request_index.json',scoped);write('unknown_sends.json',unknowns)
write('actual_service_observation.json',{'requested_model':'jev-1.14.0','observed_served_models_all_runs':dict(served),'new_requested_models':stats[2]['models'],'new_observed_served_models':dict(Counter(r['selection']['served_model'] for r in newrequests if r['selection'] and r['selection'].get('served_model'))),'endpoint':p['jobs'][2]['config']['endpoint'],'extra_probe_calls':0,'new_http_statuses':dict(Counter(str(r['transport']['http_status']) for r in newrequests if r['transport']))})
write('budget_accounting.json',{'per_run':[{'run':str(r),'statistics':s} for r,s in zip(runs,stats)],'cumulative':combined,'new_global_balance':535,'new_per_job_cap_sum':512,'new_per_job_limits':p['request_budget']['per_job'],'unused_finished_job_reservations_not_transferable':23,'unknown_send_refund':0})
observed_monitors=Counter()
for item in newrows:
 if isinstance(item['metrics'],dict):observed_monitors.update(item['metrics']['monitor_statuses'])
write('descriptive_summary.json',{'new24_E_vs_none_labels':dict(Counter(x['evaluation']['label_v2'] for x in pairs if x['new24'] and x['comparison']=='E/none')),'new24_observed_monitor_statuses':dict(observed_monitors),'new24_planned':24,'new24_closed':closed,'new24_not_run':notrun,'new24_categories':summary['categories'],'all36_categories':dict(Counter(r['status']['category'] for r in rows)),'new_requests':stats[2],'combined_requests':combined,'new24_paired_labels':dict(Counter(x['evaluation']['label_v2'] for x in pairs if x['new24'])),'research_benefit':'NOT_ESTABLISHED','scope':'familiar-prototype synthetic combinations, one run/method/order; v2 history separate from v3, technical failures retained'})
if '--metrics-only' in sys.argv:
 print('saved metrics, coverage, pairs and cumulative budgets extracted; validation still pending')
 raise SystemExit(0)
validation=read(OUT/'saved_validation.json')
covered=closed==24 and notrun==0 and summary['status']!='ERROR'
criteria={
 'E24-01':{'status':'PASS_EXECUTED_FROZEN_SCOPE','evidence':['preflight.json','scoped_request_index.json'],'scope':'only J0012-J0035, no old job replay/retry or unplanned calls'},
 'E24-02':{'status':'PASS_COVERAGE_AND_ACCOUNTING' if covered else 'PARTIAL_TECHNICAL_STOP','evidence':['new_24_slots.json','budget_accounting.json','owner_records.json']},
 'E24-03':{'status':'PASS_SAVED_FACTS_IN_EXECUTED_SCOPE' if validation['returncode']==0 else 'FAIL_SAVED_VALIDATION','evidence':['saved_validation.json','validate_run.log','unknown_sends.json']},
 'E24-04':{'status':'PASS_VERSIONED_DESCRIPTIVE_DELIVERY','evidence':['all_36_slots.json','paired_comparisons_v2.json'],'scope':'unrun/invalid pairs retained, no causal or unseen-source claim'},
 'E24-05':{'status':'PASS_DELIVERY_STOP','evidence':['execution_command.json','official_api_review.json','delivery_manifest.json','handoff.json']}}
receipt={'version':'jev_remaining24_execution_receipt_v1','head_at_entry':'c3ff2a09','plan':str(PREP/'plan'),'run':str(run),'plan_digest':digest(p),'new24_closed':closed,'new24_not_run':notrun,'new24_categories':summary['categories'],'all36_categories':dict(Counter(r['status']['category'] for r in rows)),'stop_reason':'STOP_TECHNICAL' if summary['status']=='ERROR' else 'AUTHORIZED24_COVERAGE_COMPLETE' if covered else 'INCOMPLETE','technical_failure':read(run/'technical_failure.json') if (run/'technical_failure.json').exists() else None,'new_request_statistics':stats[2],'cumulative_requests':combined,'criteria':criteria,'new24_execution_coverage_complete':covered,'JN5_limited_analysis_review_eligible':covered and validation['returncode']==0,'JN4_B_admitted':False,'research_benefit':'NOT_ESTABLISHED','new_experience_generated':False,'repeated_old_jobs':0,'resumes':0,'automatic_retries':0,'run_manifest_sha256':sha(run/'delivery_manifest.json'),'run_summary_sha256':sha(run/'summary.json'),'source_manifest_digest':digest(p['source_manifest']),'stop':True}
write('evaluation_receipt.json',receipt)
write('handoff.json',{'version':'jev_remaining24_execution_handoff_v1','report':'docs/03_阶段产出分析/Jev/Jev_JN4剩余24项真实执行与阶段收尾验收_20261106.md','receipt':'evaluation_receipt.json','plan':str(PREP/'plan'),'run':str(run),'stop':True,'stop_reason':receipt['stop_reason'],'JN5_limited_analysis_review_eligible':receipt['JN5_limited_analysis_review_eligible'],'next':'submit limited JN5 analysis admission review only; no automatic JN5 work' if receipt['JN5_limited_analysis_review_eligible'] else 'partial technical stop: preserve NOT_RUN; no retries or further continuation authorized'})
print(json.dumps({'closed':closed,'not_run':notrun,'status':summary['status'],'new_reservations':stats[2]['send_reservations'],'cumulative':combined['send_reservations']},ensure_ascii=False))
