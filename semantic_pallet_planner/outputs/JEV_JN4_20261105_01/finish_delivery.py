"""Seal acceptance AFTER completed offline tests. No model/order execution."""
from pathlib import Path
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
import hashlib
ROOT=Path('semantic_pallet_planner/outputs/JEV_JN4_20261105_01')
REPORT='docs/03_阶段产出分析/Jev/Jev_JN4-A独立来源审计与正式实验冻结准入验收_20261105.md'
DOCS=[REPORT,'docs/02_阶段实施方案/Jev/README.md','docs/03_阶段产出分析/Jev/README.md']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def write(n,v):(ROOT/n).write_text(json.dumps(v,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
tree=ET.parse(ROOT/'tests/final.xml');suites=tree.findall('.//testsuite')
counts={k:sum(int(s.attrib.get(k,0)) for s in suites) for k in ['tests','errors','failures','skipped']}
assert counts['tests'] and counts['errors']==counts['failures']==0,counts
report=Path(REPORT);text=report.read_text();marker='本次测试结果及实际命令见'
if marker in text:text=text.replace(marker,f"本次最终固定源码离线测试{counts['tests']}项，失败{counts['failures']}、错误{counts['errors']}、跳过{counts['skipped']}。实际结果及命令见",1);report.write_text(text)
assert load(ROOT/'tests/final_guard.json')['counts']=={'network':0,'credential':0}
verification=Path('semantic_pallet_planner/outputs/VERIFY_JN4_A_20261105_01')
for name in ['plan_guard.json','parent_saved_guard.json']:
 value=load(verification/name);assert value['status']=='PASS' and not any(value['counts'].values()),value
 shutil.copyfile(verification/name,ROOT/name)
write('test_results.json',{'final':counts,'historical_test_counts_reused':False,
 'initial_failed_interrupted':'tests/offline.xml, offline.log and guard.json retained, not included in final pass total',
 'scope':'new admission/control/plan + legacy JN3/v6 orders/remote/T/E/packaging-load Fake/constructed tests; no formal test order',
 'new_unified_six_method_execution_tests':'NOT_RUN_NOT_IMPLEMENTED'})
states={'D01':'NOT_READY','D02':'BLOCKED','D03':'PARTIAL','D04':'PASS_DESIGN_ONLY','D05':'PARTIAL','D06':'PARTIAL'}
plan=load(ROOT/'plan/plan.json');audit=load(ROOT/'source_audit.json')
write('engineering_acceptance.json',{'stage':'JN4-A','status':'PARTIAL_WITH_EXPLICIT_DATA_AND_EXECUTION_GAPS','criteria':states,
 'offline_test_results':counts,'static_plan':'VALID_BLOCKED_PLAN','execution_admission':'EXPECTED_REJECTION',
 'parent_saved_records':'PASS_ARCHIVED_SOURCE_UNDER_READONLY_GUARD_NO_DISPATCH',
 'static_data':'PASS_EXISTING_EXPOSED_16_TASK_PACKAGE_ONLY','new_data_and_six_method_protocol':'NOT_RUN_NOT_IMPLEMENTED',
 'actual_model_api_calls':0,'actual_formal_test_jobs_executed':0,'credential_reads':0,'JN4_B_admitted':False})
receipt={'version':'jev_evaluation_plan_receipt_v1','stage':'JN4-A','status':'NOT_READY','criteria':states,
 'plan':'plan/plan.json','plan_digest':plan['plan_digest'],'execution_plan_kind':'jev_evaluation_plan_blocked_v1',
 'JN4_B_admitted':False,'audited_raw_orders':10003,'audited_components':len(audit['components']),
 'exposure_counts':audit['counts'],'verified_unseen_sources':0,'tasks':0,'variants':0,'planned_repetitions':1,
 'designed_methods':6,'natural_job_slots':0,'remote_job_slots':0,'per_job_send_caps':{},'shared_batch_send_cap':0,
 'actual_model_api_calls':0,'actual_formal_test_jobs_executed':0,'actual_credential_reads':0,
 'model_availability':'UNKNOWN_NOT_PROBED','actual_cost_usd':'UNKNOWN','blockers':plan['blockers'],
 'research_benefit':'NOT_ESTABLISHED','stopped_after':'JN4-A audit/design/blocking delivery, no JN4-B',
 'next_stage_conditions':['source-component history attestation or separately authorized auditable new source delivery',
 'materialize independent new data with separate version and frozen calibration, no performance filtering',
 'implement and Fake-validate unified six-method protocol using shared engine, new closed schemas and persistence',
 'freeze a new nonempty matrix with exact tasks, model/service/dependency identities and technical first gate; do not re-sign this blocked historical plan']}
write('evaluation_plan_receipt.json',receipt)
write('handoff.json',{'version':'jev_jn4_a_handoff_v1','stage':'JN4-A','status':'NOT_READY','JN4_B_admitted':False,
 'receipt':'evaluation_plan_receipt.json','plan':'plan/plan.json','plan_digest':plan['plan_digest'],
 'report':REPORT,'actual_model_api_calls':0,'actual_formal_test_jobs_executed':0,
 'consumer':'packaging_evaluation_plan validate; check-execution-admission must reject; no runnable jobs',
 'do_not':'dispatch v9, invent unseen sources, alter old T/E/config/data or expand collection',
 'blockers':plan['blockers'],'next_stage_conditions':receipt['next_stage_conditions'],'stop':True})
before=load(ROOT/'protected_before.json');allowed=['docs/03_阶段产出分析/Jev/README.md']
changed=[n for n,h in before.items() if sha(n)!=h and n not in allowed];assert not changed,changed
history=load(ROOT/'history_inventory.json')['files'];assert all(sha(n)==h for n,h in history.items())
write('protected_before_after.json',{'status':'PASS_IN_DECLARED_SCOPE','original_files':len(before),
 'unchanged_protected_files':len(before)-len(allowed),'changed_unexpected':changed,
 'allowed_index_updates':allowed+['docs/02_阶段实施方案/Jev/README.md'],
 'history_metadata_files_verified':len(history),'history_metadata_unchanged':True,
 'scope':'both data identities, full raw/V1 package and selected parent packages/reports; no blanket claim for unlisted historical files'})
tests=[
 'semantic_pallet_planner/tests/unit/test_packaging_evaluation_plan.py',
 'semantic_pallet_planner/tests/unit/test_packaging_memory_pilot.py',
 'semantic_pallet_planner/tests/unit/test_packaging_orders.py',
 'semantic_pallet_planner/tests/unit/test_packaging_remote.py',
 'semantic_pallet_planner/tests/unit/test_packaging_experience.py',
 'semantic_pallet_planner/tests/unit/test_packaging_contrast.py',
 'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_packaging_load.py']
(ROOT/'test_snapshot').mkdir(exist_ok=True)
for n in tests:shutil.copyfile(n,ROOT/'test_snapshot'/Path(n).name)
write('test_manifest.json',{n:sha(n) for n in tests})
source=load(ROOT/'source_manifest.json');package=Path('semantic_pallet_planner/src/semantic_pallet_planner')
assert all(sha(package/n)==h and sha(ROOT/'plan/code_snapshot'/n)==h for n,h in source.items())
paths=['semantic_pallet_planner/src/semantic_pallet_planner/jev_select','semantic_pallet_planner/tests/unit/test_packaging_evaluation_plan.py']+DOCS
patch=subprocess.run(['git','diff','HEAD','--',*paths],capture_output=True,check=True).stdout
for n in ['semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_source_audit.py',
 'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_evaluation_plan.py',
 'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/schemas/evaluation_control_v1.schema.json',
 'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/schemas/evaluation_plan_blocked_v1.schema.json',tests[0],REPORT]:
 result=subprocess.run(['git','diff','--no-index','--','/dev/null',n],capture_output=True);assert result.returncode==1;patch+=result.stdout
(ROOT/'source_changes.patch').write_bytes(patch)
write('source_change_review.json',{'existing_modified':['jev_select/contracts.py'],'added_production_files':4,
 'production_count':len(source),'old_schema_bytes_unchanged':True,'patch':'source_changes.patch','full_snapshot':'plan/code_snapshot',
 'no_core_execution_or_physics_changes':True,'actual_tests':counts})
write('commands.json',{'cwd':'NBU_Papper repository root','environment':'existing python; PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src',
 'executed':[
  'git status --short; git log -6 --oneline; rg --files -g AGENTS.md',
  'source audit executed as inline Python using historical_metadata/exposure_records/audit_sources; frozen rules saved first; equivalent entry: run_source_audit.py --repo . --output NEW_DIRECTORY',
  'python semantic_pallet_planner/outputs/JEV_JN4_20261105_01/build_delivery.py',
  'python semantic_pallet_planner/outputs/JEV_JN4_20261105_01/offline_test_guard.py semantic_pallet_planner/outputs/JEV_JN4_20261105_01/tests/final_guard.json -q '+ ' '.join(tests)+' --junitxml=semantic_pallet_planner/outputs/JEV_JN4_20261105_01/tests/final.xml',
  'python semantic_pallet_planner/outputs/JEV_JN3_20261105_01/readonly_guard.py semantic_pallet_planner/outputs/VERIFY_JN4_A_20261105_01/plan_guard.json semantic_pallet_planner.jev_select.packaging_evaluation_plan validate --output semantic_pallet_planner/outputs/JEV_JN4_20261105_01 --repo .',
  'python semantic_pallet_planner/outputs/JEV_JN3_20261105_01/readonly_guard.py semantic_pallet_planner/outputs/VERIFY_JN4_A_20261105_01/parent_saved_guard.json script semantic_pallet_planner/outputs/JEV_JN3_20261105_01/verify_frozen.py --output semantic_pallet_planner/outputs/JEV_JN3_20261105_01 --repo .',
  'python semantic_pallet_planner/outputs/JEV_JN4_20261105_01/finish_delivery.py',
  'python semantic_pallet_planner/outputs/JEV_JN4_20261105_01/verify_delivery.py --output semantic_pallet_planner/outputs/JEV_JN4_20261105_01 --repo .'],
 'initial_runs':'tests/offline.* is failed/interrupted pre-registration-fix run, retained; tests/final.* is completed final-source run',
 'not_executed':['model API','formal test full orders including local baselines','JN4-B','new data build','new training forks or experience generation']})
manifest={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(ROOT.rglob('*')) if p.is_file() and p.name!='delivery_manifest.json'}
write('delivery_manifest.json',{'version':'jev_jn4_a_delivery_v1','stage':'JN4-A','status':'NOT_READY',
 'files_sha256':manifest,'documentation_sha256':{n:sha(n) for n in DOCS},'plan_digest':plan['plan_digest'],
 'source_files':len(source),'source_digest':hashlib.sha256(json.dumps(source,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),'manifest_exclusion':'delivery_manifest.json only; no self-referential hash','JN4_B_admitted':False})
print(json.dumps({'status':'NOT_READY_DELIVERED','tests':counts,'files':len(manifest),'JN4_B_admitted':False}))
