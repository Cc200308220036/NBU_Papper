"""Assemble only this closure's receipts and manifest; all inputs are read-only."""
import hashlib,json,re,subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

root=Path.cwd();out=Path(__file__).resolve().parent
entry='90bd018d55cc4c2b562dfb6aa9f7241170c0b831'
report='docs/03_阶段产出分析/Jev/Jev_JM1-B2正式冻结收尾补交验收_20261112_01.md'
versions='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_versions.py'
test='semantic_pallet_planner/tests/unit/test_packaging_jev_training_plan.py'
new_module='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_jev_training_freeze.py'
new_schema='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/schemas/jm_training_freeze_v1.schema.json'
new_test='semantic_pallet_planner/tests/unit/test_packaging_jev_training_freeze.py'
index='docs/03_阶段产出分析/Jev/README.md'
def save(name,value):(out/name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def row(path):
 raw=path.read_bytes();return {'path':path.relative_to(root).as_posix(),'sha256':sha(raw),'bytes':len(raw)}
receipt=json.loads((out/'formal_freeze.json').read_text())
plan=json.loads((out/'materials/training_plan.json').read_text())
initial=ET.parse(out/'offline_junit.xml').getroot().findall('.//testcase')
targeted=ET.parse(out/'targeted_junit.xml').getroot().findall('.//testcase')
key=lambda t:(t.attrib['classname'],t.attrib['name'])
failed={key(t) for t in initial if t.find('failure') is not None or t.find('error') is not None}
passed={key(t) for t in initial if t.find('failure') is None and t.find('error') is None and t.find('skipped') is None}
assert len(initial)==26 and len(failed)==1 and len(passed)==25
assert len(targeted)==1 and all(t.find('failure') is None and t.find('error') is None for t in targeted)
assert {key(t) for t in targeted}==failed
save('test_receipt.json',{'version':'jm_b2_closure_local_test_receipt_v1','initial':{'tests':26,'passed':25,'failed':1,'log':'offline_tests.log','junit':'offline_junit.xml'},'initial_failure':'QA inventory mutation was rejected; new test expected FREEZE_QA_INVENTORY but actual canonical receipt comparison returned FREEZE_IDENTITY_OR_BINDING_DRIFT. Test assertion only corrected.','targeted':{'tests':1,'passed':1,'log':'targeted_tests.log','junit':'targeted_junit.xml'},'final_unique_cases_verified':26,'preparation_cases':20,'freeze_cases':6,'status':'ALL_UNIQUE_CASES_VERIFIED_AFTER_TARGETED_TEST_ASSERTION_CORRECTION','original18_archive':'PRESERVED_NOT_REWRITTEN','forbidden_operations':'fixture fails on network/credentials/episode/v13 execution/candidates/sampling/monitor/LP','archived_claims_not_counted_as_current':True})
# Protect every tracked pre-existing source/test except the explicitly allowed two.
paths=subprocess.check_output(['git','-c','core.quotepath=false','ls-files','semantic_pallet_planner/src','semantic_pallet_planner/tests'],text=True).splitlines()
extra=[
 'semantic_pallet_planner/outputs/JEV_JM1_B2_FORMAL_PREP_20261112_01',
 'semantic_pallet_planner/outputs/JEV_JM_B2_FORMAL_PREP_QA_20261112_01',
 'semantic_pallet_planner/outputs/JEV_JM_V13_FIX_QA_20261112_01',
 'docs/03_阶段产出分析/Jev/Jev_JM1-B2正式计划离线准备与冻结缺口交接_20261112_01.md',
 'docs/03_阶段产出分析/Jev/Jev_JM1-B2正式计划离线准备独立质检与冻结收尾交接_20261112_01.md',
 'docs/03_阶段产出分析/Jev/Jev_JM1-v13整改独立复核与B2正式计划准备限定准入_20261112_01.md']
paths+=subprocess.check_output(['git','-c','core.quotepath=false','ls-files',*extra],text=True).splitlines()
protected=[]
for path in sorted(set(paths)):
 old=subprocess.check_output(['git','show',entry+':'+path]);current=(root/path).read_bytes()
 if path==test:status='AUTHORIZED_QA_JMB2P_01_TEST_CHANGE'
 elif path==versions:
  assert current.startswith(old),path;status='UNCHANGED_ENTRY_PREFIX_WITH_ADDITIVE_FREEZE_REGISTRATION'
 else:assert old==current,path;status='EXACT'
 protected.append({'path':path,'entry_sha256':sha(old),'current_sha256':sha(current),'comparison':status})
changed=subprocess.check_output(['git','-c','core.quotepath=false','diff','--name-only',entry],text=True).splitlines()
assert set(changed)<={test,versions,index},changed
save('historical_protection.json',{'version':'jm_b2_closure_historical_bytes_v1','entry_head':entry,'files_checked':len(protected),'files':protected,'tracked_changes':changed,'original_preparation_QA_report_and_archive_bytes':'EXACT','source_physics_monitor_candidates_and_old_schemas':'EXACT','historical_runtime_identities':'NOT_RESIGNED; new runtime package identity expected','status':'PASS_BYTES_ONLY'})
nav=[]
for name in ['JEV_JM_V13_FIX_QA_20261112_01','JEV_JM_B2_FORMAL_PREP_QA_20261112_01']:
 m=json.loads((root/'semantic_pallet_planner/outputs'/name/'delivery_manifest.json').read_text())
 expected=next(r for r in m['files'] if r['path']==index)
 old=subprocess.check_output(['git','show',entry+':'+index]);now=(root/index).read_bytes()
 nav.append({'parent':name,'historical_expected':expected,'entry_head_sha256':sha(old),'current_sha256':sha(now),'entry_matches_expected':sha(old)==expected['sha256'],'current_matches_expected':sha(now)==expected['sha256'],'interpretation':'Mutable navigation only; expected bytes not rewritten. Prior parent exact-navigation gap retained; all non-navigation QA files verified separately.'})
save('qa_navigation_evidence.json',{'version':'jm_b2_closure_navigation_gap_v1','entries':nav,'non_navigation_verified_files':sum(len(a['verified_non_navigation']) for a in receipt['qa_audit']),'manifest_unchanged':True})
old=json.loads((root/receipt['historical_plan_ref']['path']).read_text())
save('study_invariants.json',{'version':'jm_b2_closure_study_invariants_v1','old_plan_ref':receipt['historical_plan_ref'],'new_plan_ref':receipt['plan_ref'],'old_preparation_digest':old['plan_digest'],'new_preparation_digest':plan['plan_digest'],'new_formal_freeze_identity':receipt['receipt_digest'],'old_missing_qa_count':len(old['missing_qa']),'old_qa_refs_count':len(old['qa_refs']),'old_formal_frozen':old['formal_frozen'],'new_parent_qa_ref_count':len(plan['qa_refs']),'final_two_round_QA_ref_count':len(receipt['qa_refs']),'task_order':[r['task_id'] for r in plan['assignments']],'same_task_files_arrival_sources_sampling_repeats':'VALIDATED_BY_FREEZE_PLAN_AGAINST_OLD_BYTES','budget_invariant':[103,564,210,774,877],'allocation_change_reason':'New package storage root yields new allocation/job IDs; config strategy/source identity changes for new protocol files. No study/algorithm/data change.','final_operation_root':receipt['operation_root'],'final_runtime_root':receipt['runtime_root'],'runtime_output_exists':Path(receipt['runtime_root']).exists(),'materialization':receipt['materialization']})
save('acceptance.json',{'version':'jm_b2_closure_acceptance_v1','M12-01':{'status':'PASS_OFFLINE_FROZEN','scope':'Six actual tasks/order/waves/source/arrival/config/baseline budget/sampling + complete two-round QA binding'},'M12-04':{'status':'PASS_OFFLINE_FROZEN','baseline':103,'initial_suffix':564,'repeat':210,'suffix':774,'global':877,'counts':[6,12,36,12,48],'actual_model_calls':0,'concrete_suffix_jobs':'NOT_MATERIALIZED_DEFER_C1'},'M12-07':{'status':'PASS_PLAN_PART_ONLY','baseline_suffix_gates':'SEPARATE_ALWAYS_REFUSE_SENDING','C1_stop_after_materialization':True,'C2':'SEPARATE_CONCRETE_FROZEN_C1_PLAN_REQUIRED','real_pools_actions':'NOT_MATERIALIZED_DEFER_C1'},'QA-JMB2P-01':{'developer_remediation':'IMPLEMENTED_AND_LOCALLY_VALIDATED','independent_closure':'PENDING_QA','original18':'UNCHANGED'},'engineering_status':'B2_FORMAL_OFFLINE_FREEZE_DELIVERED_AWAIT_QA','evidence_readiness':'OFFLINE_FREEZE_COMPLETE_REAL_MATERIALIZATION_NOT_RUN','research_result':'NOT_RUN','execution_authorized':False,'independent_review':'PENDING','send_permission':'NOT_ISSUED'})
save('commands_and_scope.json',{'version':'jm_b2_closure_commands_v1','commands':[
 'PYTHONPATH=semantic_pallet_planner/src python -m pytest semantic_pallet_planner/tests/unit/test_packaging_jev_training_plan.py semantic_pallet_planner/tests/unit/test_packaging_jev_training_freeze.py -q --junitxml=semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01/offline_junit.xml',
 'PYTHONPATH=semantic_pallet_planner/src python -m pytest semantic_pallet_planner/tests/unit/test_packaging_jev_training_freeze.py::test_full_qa_freeze_and_drift_rejections -q --junitxml=semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01/targeted_junit.xml',
 'PYTHONPATH=semantic_pallet_planner/src python semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01/prepare_delivery.py',
 'python semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01/finalize_delivery.py',
 'PYTHONPATH=semantic_pallet_planner/src python semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01/verify_delivery.py',
 'git diff --check'],'verification_scope':'Saved bytes/identity/schema/arithmetic/offline configuration and refusal tests only. No original verifier invoked and no historical artifact writes.','initial_failure':'See test_receipt.json; initial log preserved.'})
save('handoff.json',{'version':'jm_b2_formal_freeze_closure_handoff_v1','unit':'JM1-B2正式冻结收尾补交','plan':'JM-plan-v2','specified_base':'c21d6b511e4c33e5ff0acfd4a51931c896edb60d','entry_head':entry,'engineering_status':'B2_FORMAL_OFFLINE_FREEZE_DELIVERED_AWAIT_INDEPENDENT_QA','evidence_readiness':'OFFLINE_FREEZE_COMPLETE_REAL_MATERIALIZATION_NOT_RUN','research_result':'NOT_RUN','formal_freeze':'formal_freeze.json','formal_frozen':True,'execution_authorized':False,'real_calls_authorized':0,'new_preparation_plan':'materials/training_plan.json','final_plan_identity':receipt['receipt_digest'],'preparation_identity':plan['plan_digest'],'old_missing_material_plan':'PRESERVED_UNCHANGED; see formal_freeze.historical_plan_ref','QA_inputs':'qa_evidence_index.json','interfaces':'interface_receipt.json','identities':'source_identity.json','source_manifest':'source_manifest.json','budget':'budget_receipt.json','study_invariants':'study_invariants.json','test_receipt':'test_receipt.json','tests':['offline_junit.xml','offline_tests.log','targeted_junit.xml','targeted_tests.log'],'freeze_check':'freeze_validation.json','acceptance':'acceptance.json','protection':'historical_protection.json','operations':'operations.json','manifest':'delivery_manifest.json','verify':'verify_delivery.py (read-only stdout)','report':report,'next_stage_admission':'INDEPENDENT_QA_ONLY; C1/C2_NOT_AUTHORIZED; NO_SEND_PERMIT','remaining':{'new_package_independent_review':'PENDING','epsilon_points_actions_suffix_jobs':'NOT_MATERIALIZED_DEFER_C1','real_service':'NOT_RUN','real_LP':'NOT_RUN','C1':'NOT_RUN','C2':'NOT_RUN'},'stop':True,'stop_reason':'完成B2收尾后交回独立质检；不签发送许可、不执行C1/C2、不编写下一任务提示词'})
links=re.findall(r'\]\(([^)]+)\)',(root/report).read_text())
for link in links:
 assert ((root/report).parent/link.split('#')[0]).resolve().exists(),link
assert report.split('/')[-1] in (root/index).read_text()
save('navigation_receipt.json',{'report':report,'report_links_checked':len(links),'status':'PASS','shared_index':index,'shared_index_outside_immutable_runtime_and_manifest':True})
files=[row(path) for path in sorted(out.rglob('*')) if path.is_file() and path.name not in ['delivery_manifest.json','delivery_checks.json']]
files += [row(root/p) for p in [versions,test,new_module,new_schema,new_test,report]]
save('delivery_manifest.json',{'version':'jm_b2_closure_delivery_manifest_v1','self_hash_excluded':True,'delivery_checks_excluded':True,'shared_navigation_excluded':True,'files':files})
print(json.dumps({'manifest_files':len(files),'protected_originals':len(protected),'report_links':len(links),'final_unique_tests':len(passed|{key(t) for t in targeted}),'frozen_offline':True,'execution_authorized':False}))
