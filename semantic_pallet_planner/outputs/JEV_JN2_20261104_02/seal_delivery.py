"""Final requirement audit and byte manifest. No episode, selection or monitor dispatch."""
from pathlib import Path
import json
import re
import subprocess
from semantic_pallet_planner.jev_select import packaging_comparisons as c
from semantic_pallet_planner.jev_select import packaging_counterfactual as f
from semantic_pallet_planner.jev_select.contracts import digest,validate_schema
from semantic_pallet_planner.jev_select.ledger import read,write
r=Path('semantic_pallet_planner/outputs/JEV_JN2_20261104_02');p=read(r/'comparison_plan.json');summary=read(r/'comparison_summary.json')
checks=[]
def check(name,ok,evidence):
 assert ok,name
 checks.append({'requirement':name,'status':'PROVEN','evidence':evidence})
check('explicit JN2-B scope and stop',read(r/'handoff.json')['stage']=='JN2-B' and read(r/'comparison_dataset_receipt.json')['JN3_executed'] is False,['execution_contract.txt','handoff.json'])
protected=read(r/'tests/protected_before.json')
check('A/JN1/data/historical reports and AGENTS unchanged',all(f.sha(n)==h for n,h in protected.items()),['protected_before_after.json'])
check('current371 analysis bytes equal frozen analysis identity',len(p['analysis_source_manifest'])==371 and c.source_manifest()==p['analysis_source_manifest'] and all(f.sha(r/'analysis_code_snapshot'/n)==h for n,h in p['analysis_source_manifest'].items()),['analysis_source_manifest.json','analysis_code_snapshot/'])
check('execution367 bytes identical to original A',len(p['execution_source_manifest'])==367 and p['execution_source_manifest']==read(Path(c.A_DEFAULT)/'source_manifest.json') and all(f.sha(r/'runtime/semantic_pallet_planner'/n)==h for n,h in p['execution_source_manifest'].items()),['execution_source_manifest.json','compatibility_review.json'])
algorithm=read(Path(c.A_DEFAULT)/'algorithm_snapshot_manifest.json')
check('original v2 monitor algorithm and auxiliary files retained',all(f.sha(r/'runtime/semantic_pallet_planner/jev_select/stability'/n)==h for n,h in algorithm.items()),['runtime/semantic_pallet_planner/jev_select/stability/','compatibility_review.json'])
check('four outcome-independent decisions in two admitted train sources',[e['decision_id'] for e in p['entries']]==['J0000_D0000','J0000_D0005','J0003_D0000','J0003_D0003'] and len({e['source_group'] for e in p['entries']})==2,['comparison_plan.json','inputs/'])
check('A3 reused and B9 cumulative12 with no expansion',summary['budget']['A_used']==3 and summary['budget']['B_started']==9 and summary['budget']['cumulative_started']==summary['budget']['cumulative_max']==12,['budget_ledger.json','batch_history.json'])
check('plan and rules frozen before all new suffix dispatches',read(r/'preregistration.json')['new_suffixes_started']==0 and read(r/'preregistration.json')['plan_digest']==digest(p) and r.joinpath('preregistration.json').stat().st_mtime_ns<min((r/'forks'/e['group_id']/'execution_receipt.json').stat().st_mtime_ns for e in p['entries'] if e['mode']=='NEW'),['preregistration.json','plan_anchor.json','dispatch_intents/'])
new_commits=new_monitors=0
for e in p['entries']:
 payload=read(r/'inputs'/f"{e['group_id']}.json")['value'];s=payload['snapshot'];task=payload['task']
 check(e['group_id']+' train/task/source/cursor/buffer binding',task['partition']=='train' and task['source_group_id']==e['source_group'] and task['task_id']==e['task_id'] and s['cursor']==s['state']['arrival_count'] and s['buffer']==s['state']['pending_items'] and s['state']['arrived_ids']==[x['item_id'] for x in task['items'][:s['cursor']]],['inputs/'+e['group_id']+'.json','saved_record_validation.json'])
 check(e['group_id']+' probabilities and exact intervention sampling',e['first_actions']==f.interventions(s)['branches'],['comparison_plan.json','inputs/'+e['group_id']+'.json'])
 root=c.REPO/e['location'];cp_plan=read(root/'branch_plan.json')
 for i,first in enumerate(e['first_actions']):
  job=root/'branches'/f'B{i:02d}';cp=read(job/'checkpoint.json');receipt=read(job/'branch_receipt.json');validate_schema('packaging_branch_receipt_v1',receipt)
  decisions=[x for x in cp['events'] if x.get('decision_id')];initial=decisions[0]
  check(e['group_id']+f'/B{i:02d} same-prefix exact first once',initial['before']==s['state'] and initial['bundle']['physical_candidates']==s['pool']['physical_candidates'] and initial['context']['display_mapping']==s['mapping'] and initial['selection']['selected_candidate_id']==first['candidate']['candidate_id'] and sum(x['decision_id']==f'B{i:02d}_D0000' for x in decisions)==1,[str(job.relative_to(c.REPO))+'/checkpoint.json'])
  check(e['group_id']+f'/B{i:02d} natural monitored stop and full denominator',cp['reason']=='STOP_NO_PHYSICAL_CANDIDATE' and receipt['status']['category']=='EMPTY_POOL' and receipt['metrics']['loading']['planned_items']==len(task['items']) and receipt['metrics']['branch_metrics']['suffix_increment']['items']==sum(x['event']=='PLACE' for x in cp['events']),[str(job.relative_to(c.REPO))+'/branch_receipt.json'])
  check(e['group_id']+f'/B{i:02d} unchanged local follow policy and zero model calls',receipt['continuation']['method']=='local_geometry_test_double' and receipt['model_calls']==0 and all(x['selection'] is None or x['selection']['source'] in ('test_double','singleton') for x in decisions) and all(x['context']['model_state']['memories']==[] for x in decisions if x.get('context')),[str(job.relative_to(c.REPO))+'/actions/'])
  if e['mode']=='NEW':new_commits+=receipt['metrics']['branch_metrics']['suffix_increment']['items'];new_monitors+=receipt['metrics']['monitor_statuses']['STABLE']
check('43 new stable commits counted once without fork prefix',new_commits==new_monitors==43,['monitor_coverage_summary.json','forks/*/branches/*/branch_receipt.json'])
check('pilot pause complete6 then continuation12 without repeats',read(r/'pilot_snapshot/budget_ledger.json')['cumulative_started']==6 and read(r/'pilot_continuation_verification.json')['pilot_completed_group_files_unchanged'],['pilot_gate.json','pilot_continuation_verification.json','pilot_snapshot/'])
rows=c.records(r,p)
check('all8 comparisons independently match branch receipts',len(rows)==8 and all(read(r/'comparisons'/f"{x['comparison_id']}.json")==x for x in rows),['comparisons/','saved_record_validation.json'])
for x in rows:validate_schema('packaging_comparison_record_v1',x)
check('fixed validity/labels/delta and full positive-negative denominator',summary==c.summarize_records(r,p,rows) and summary['labels']=={'improved':0,'neutral':6,'degraded':0,'trade_off':2,'invalid':0},['comparison_plan.json/label_rule','comparison_summary.json','tests/final.xml'])
check('both intervention kinds and two source indexes retained',summary['coverage']=={'SAME_BOX_DIFFERENT_POSE':4,'CROSS_BOX_SELECTION':4} and len(read(r/'source_index.json'))==2,['source_index.json','comparison_summary.json'])
check('JN3 engineering and experience readiness separated',read(r/'comparison_dataset_receipt.json')['JN3_engineering_admitted'] is True and read(r/'comparison_dataset_receipt.json')['experience_input_status']=='NOT_READY' and not read(r/'comparison_dataset_receipt.json')['experience_eligible_pairs'],['comparison_dataset_receipt.json','engineering_acceptance.json'])
audit=read(r/'saved_record_validation.json')
check('standard validator and completed resume dispatch nothing',audit['status']=='PASS' and audit['saved_bytes_unchanged'] and audit['completed_resume_new_suffixes']==0 and all(v==0 for v in audit['controller_dispatch_counts'].values()) and all(all(v==0 for v in x['guards'].values()) for x in audit['frozen_readonly_workers']),['saved_record_validation.json'])
check('duplicate registration rejected without new run',audit['duplicate_registration_rejected']=='comparison_already_registered_use_resume' and not (r.parent/'NEVER_CREATED_DUPLICATE_JN2_B').exists(),['saved_record_validation.json'])
check('frozen analysis portability full validation passed',json.loads((r/'frozen_full_validation.log').read_text().splitlines()[-1])['status']=='PASS',['verify_frozen_analysis.py','frozen_full_validation.log'])
for n in ['tests/final_guard.json','tests/finalization_guard.json','tests/prepare_guard.json','pilot_guard.json','pilot_validation_guard.json','continuation_guard.json','audit_guard.json','frozen_analysis_guard.json','frozen_full_guard.json']:
 check('zero network/credential/historical writes: '+n,all(v==0 for v in read(r/n)['counts'].values()),[n])
required=['comparison_plan.json','compatibility_review.json','parent_reference.json','budget_ledger.json','comparison_dataset_receipt.json','source_index.json','engineering_acceptance.json','handoff.json','interface_contract.json','actual_commands.sh','commands.json','source_manifest.json','execution_source_manifest.json','analysis_source_manifest.json','test_verification.json','environment.json','execution_contract.txt']
check('all named delivery artifacts present',all((r/n).exists() for n in required),required)
docs=[Path('docs/03_阶段产出分析/Jev/Jev_JN2-B有限训练对比材料与经验输入准入验收_20261104.md'),Path('docs/03_阶段产出分析/Jev/README.md'),Path('docs/02_阶段实施方案/Jev/README.md')]
links=0
for doc in docs:
 for target in re.findall(r'\]\(([^)]+)\)',doc.read_text()):
  if '://' not in target and not target.startswith('#'):
   assert (doc.parent/target.split('#')[0]).exists(),(doc,target);links+=1
check('report and updated navigation links resolve',links>0,[x.as_posix() for x in docs])
check('no automatic commit and no gitignore change',subprocess.check_output(['git','rev-parse','--short','HEAD'],text=True).strip()=='8caa95a9' and not subprocess.check_output(['git','diff','--','.gitignore'],text=True),['Git HEAD/status'])
write(r/'completion_audit.json',{'status':'PROVEN_COMPLETE','checks':checks,'scope':'JN2-B engineering G01-G05 and combined N08-N09; experience NOT_READY; no JN3 execution'})
write(r/'final_verification.json',{'status':'PASS','requirements_proven':len(checks),'protected_files_unchanged':len(protected),'analysis_files':371,'execution_files':367,'A_reused':3,'B_new':9,'cumulative_suffixes':12,'comparisons':8,'labels':summary['labels'],'new_model_calls':0,'doc_links':links,'engineering_complete':True,'experience_input_status':'NOT_READY','JN3_executed':False})
write(r/'delivery_manifest.json',{'version':'jev_jn2_b_delivery_manifest_v1','files_sha256':f.file_manifest(r),'external_documents_sha256':{d.as_posix():f.sha(d) for d in docs},'analysis_source_digest':digest(p['analysis_source_manifest']),'execution_source_digest':digest(p['execution_source_manifest'])})
assert read(r/'delivery_manifest.json')['files_sha256']==f.file_manifest(r)
assert all(f.sha(n)==h for n,h in protected.items())
print({'status':'PASS','requirement_checks':len(checks),'delivery_files':len(read(r/'delivery_manifest.json')['files_sha256']),'new_suffixes':9,'total_suffixes':12,'experience_input_status':'NOT_READY'})
