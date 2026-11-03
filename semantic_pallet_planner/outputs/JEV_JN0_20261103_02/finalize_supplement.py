"""Package supplemental acceptance after formal runs and saved audit; no execution."""
from pathlib import Path
from collections import Counter
import hashlib
import xml.etree.ElementTree as ET
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.experiment import source_manifest,file_manifest

root=Path('semantic_pallet_planner/outputs/JEV_JN0_20261103_02');old=Path('semantic_pallet_planner/outputs/JEV_JN0_20261103_01')
plan=read(root/'plan/plan.json');spec=read(root/'supplement_spec.json');baseline=read(root/'baseline_verification.json')
summary=read(root/'run/summary.json');validation=read(root/'record_validation.json');scope=read(root/'monitor_scope_review.json')
assert digest(spec)==read(root/'supplement_receipt.json')['spec_digest']
assert plan['source_manifest']==source_manifest()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(old/'delivery_manifest.json')==baseline['protected_old_manifest_sha256']
assert sha(old/'full_order_readiness.json')==baseline['old_readiness_sha256']
assert sha(Path('docs/03_阶段产出分析/Jev/Jev_JN0完整订单入口与本地基线开发验收_20261103.md'))==baseline['old_report_sha256']
old_files=read(old/'delivery_manifest.json')['files_sha256']
assert all(sha(old/n)==h for n,h in old_files.items())
assert file_manifest(old/'run')==read(old/'run/delivery_manifest.json')
write(root/'protected_after.json',{'status':'PASS','historical_files_verified':len(old_files),'old_manifest_readiness_report_bytes_unchanged':True,'original_error_retained':read(old/'run/jobs/J0000/status.json')['category']=='ERROR','original_not_run_retained':all(read(old/'run/jobs'/f'J{i:04d}'/'status.json')['category']=='NOT_RUN' for i in range(1,8))})
ledger=[]
for j in plan['jobs']:
    jid=j['job_id'];prior=read(old/'run/jobs'/jid/'status.json');now=read(root/'run/jobs'/jid/'status.json')
    ledger.append({'record_id':'historical_'+jid,'plan':'original','job_id':jid,'task_id':j['task_id'],'method_id':j['method_id'],
        'source_group_id':j['source_group_id'],'category':prior['category'],'actually_started':prior['state']!='NOT_RUN',
        'consumes_actual_start_budget':prior['state']!='NOT_RUN','evidence':str(old/'run/jobs'/jid),'replacement_of':None})
    ledger.append({'record_id':'supplement_'+jid,'plan':'supplement','job_id':jid,'task_id':j['task_id'],'method_id':j['method_id'],
        'source_group_id':j['source_group_id'],'category':now['category'],'actually_started':now['state']!='NOT_RUN',
        'consumes_actual_start_budget':now['state']!='NOT_RUN','evidence':str(root/'run/jobs'/jid),
        'replacement_of':'historical_'+jid if prior['category']=='ERROR' else None,
        'fulfills_original_slot':'historical_'+jid if prior['category']=='NOT_RUN' else None})
actual=sum(r['actually_started'] for r in ledger);new=sum(r['actually_started'] for r in ledger if r['plan']=='supplement')
assert actual<=9 and new<=8
write(root/'cumulative_job_ledger.json',{'version':'jev_jn0_cumulative_job_ledger_v1','original_planned_slots':8,'new_planned_slots':8,
    'historical_actual_starts':actual-new,'new_actual_starts':new,'cumulative_actual_starts':actual,'max_cumulative_actual_starts':9,
    'interpretation':'16 plan slots are not 16 actual attempts or independent sources; original ERROR is never erased.',
    'rows':ledger})
rows=[read(p) for p in sorted((root/'run/jobs').glob('*/metrics.json'))]
write(root/'per_job_results.json',rows)
tests={}
for name in ('verification_01','finalization_followup'):
    t=ET.parse(root/f'tests/{name}.xml').getroot().find('testsuite')
    tests[name]={k:t.get(k) for k in ('tests','failures','errors','skipped','time')}
write(root/'test_receipts.json',tests)
tech=sum(summary['categories'][c] for c in ('ERROR','COMMIT_FAILURE','SELECTION_FAILURE','TECHNICAL_LIMIT','CANCELED'))
complete_matrix=summary['recorded_jobs']==8 and summary['categories']['NOT_RUN']==0 and tech==0
criteria={
'N01':{'status':'PASS','evidence':['baseline_verification.json','plan/task_inventory.json','supplement_spec.json'],'detail':'Same frozen data, original four exposed train sources; all feasibility UNKNOWN.'},
'N02':{'status':'PASS' if complete_matrix else 'PARTIAL','evidence':['run/summary.json','pilot_run.log','remaining_run.log','pilot_summarize.log','final_summarize.log'],'detail':'Eight exact terminal outcomes and standard closure; natural failure allowed.'},
'N03':{'status':'PASS' if complete_matrix and validation['status']=='PASS' else 'PARTIAL','evidence':['record_validation.json','negative_record_checks.json','protected_after.json','cumulative_job_ledger.json','tests/verification_01.xml'],'detail':'Identity/refusal/recovery/error handling tested; old failure preserved, all denominators explicit.'},
'N04':{'status':'PASS' if complete_matrix and len(read(root/'run/paired_differences.json'))==4 else 'PARTIAL','evidence':['run/paired_differences.json','per_job_results.json','monitor_scope_review.json','plan/plan.json'],'detail':'Four-source descriptive diagnostics; invalid causal comparisons explicitly marked; local selector factory retained.'}}
all_pass=all(v['status']=='PASS' for v in criteria.values())
admitted=all_pass and scope['JN1_admitted']
write(root/'engineering_acceptance.json',{'version':'jev_jn0_supplement_acceptance_v1','status':'PASS_IN_DECLARED_SCOPE' if all_pass else 'PARTIAL',
    'criteria':criteria,'tests':tests,'formal_technical_errors':tech,'actual_new_starts':new,'actual_cumulative_starts':actual,
    'original_acceptance_status':'PARTIAL_UNCHANGED','research_benefit':'NOT_ESTABLISHED'})
write(root/'full_order_readiness.json',{'version':'jev_jn0_supplement_readiness_v1','status':'READY_IN_DECLARED_SCOPE' if admitted else 'NOT_READY',
    'N01_N04':criteria,'JN1_admitted':admitted,'JN1_reason':scope['JN1_reason'],'actual_new_starts':new,'actual_cumulative_starts':actual,
    'source_coverage':4,'method_coverage':2,'original_denominator':8,'new_denominator':8,'original_categories':{'ERROR':1,'NOT_RUN':7},
    'new_summary':summary,'monitor_scope_review':'monitor_scope_review.json',
    'not_run':['real model API','nonempty memory','training forks','unseen-source validation','historical full replay','monitor on/off full matrix'],
    'interfaces':{'execution':plan['execution_version'],'plan':plan['version'],'run':'jev_packaging_full_order_run_v1','selector_factory':'semantic_pallet_planner.jev_select.packaging_protocol.selector_factory','methods':plan['method_ids']},
    'limitations':['exposed train sources only; UNKNOWN unchanged','synthetic packaging capacity','vertical quasistatic model; conservative drop-height and strict internal reaction boundary','natural failure and UNASSESSABLE are not physical collapse'],
    'evidence':['run/delivery_manifest.json','record_validation.json','cumulative_job_ledger.json','protected_after.json'],
    'stop':'JN1 admission is a prerequisite conclusion, not permission to implement or call Jev.'})
report=Path('docs/03_阶段产出分析/Jev/Jev_JN0补验收与JN1准入确认_20261103.md')
write(root/'handoff.json',{'version':'jev_jn0_supplement_handoff_v1','status':'PASS_IN_DECLARED_SCOPE' if all_pass else 'PARTIAL','JN1_admitted':admitted,
    'report':report.as_posix(),'report_sha256':sha(report),'parent_delivery':old.as_posix(),'parent_manifest_sha256':sha(old/'delivery_manifest.json'),
    'supplement_spec_digest':digest(spec),'plan_digest':digest(plan),'source_manifest_digest':digest(source_manifest()),
    'readiness':'full_order_readiness.json','acceptance':'engineering_acceptance.json','standard_run':'run','cumulative_ledger':'cumulative_job_ledger.json',
    'commands':'commands.json','actual_new_starts':new,'actual_cumulative_starts':actual,'model_calls':0,
    'archive_policy':'JN artifact directory and logs eligible under existing Git rules; caches/venvs excluded; no add/commit/push',
    'stop':'Supplement delivered; original PARTIAL and failure intact; no JN1 work.'})
manifest={p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file() and p!=root/'delivery_manifest.json'}
write(root/'delivery_manifest.json',{'version':'jev_jn0_supplement_delivery_manifest_v1','files_sha256':manifest})
print('Supplement delivery:',len(manifest),'files; new starts',new,'cumulative',actual,'JN1 admitted',admitted)
