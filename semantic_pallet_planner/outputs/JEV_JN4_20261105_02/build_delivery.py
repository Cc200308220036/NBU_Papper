"""Seal the supplement only; never mutate the first NOT_READY package."""
from pathlib import Path
import hashlib,json,shutil,subprocess
from collections import Counter
import xml.etree.ElementTree as ET
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.packaging_evaluation_protocol import VERSION,VERSIONS,REGISTRY,METHODS
from semantic_pallet_planner.jev_select import packaging_evaluation_orders as orders
from semantic_pallet_planner.jev_select.packaging_evaluation_plan import CONTROL_RULE
ROOT=Path('semantic_pallet_planner/outputs/JEV_JN4_20261105_02')
OLD=Path('semantic_pallet_planner/outputs/JEV_JN4_20261105_01')
PACKAGE=Path('semantic_pallet_planner/src/semantic_pallet_planner')
REPORT=Path('docs/03_阶段产出分析/Jev/Jev_JN4-A来源正向准入与六方法统一协议补充验收_20261105.md')
DOCS=[REPORT,Path('docs/02_阶段实施方案/Jev/README.md'),Path('docs/03_阶段产出分析/Jev/README.md')]
def load(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(n,v):
 p=ROOT/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def results(n):
 suites=ET.parse(ROOT/'tests'/n).findall('.//testsuite');r={k:sum(int(s.get(k,0)) for s in suites) for k in ['tests','failures','errors','skipped']}
 assert r['tests'] and not r['failures'] and not r['errors'],r
 return r

def main():
 integration=results('final.xml');closure=results('closure.xml');stops=results('stops.xml')
 for name in ['final_guard.json','closure_guard.json','stops_guard.json']:
  assert not any(load(ROOT/'tests'/name)['counts'].values()),name
 assert load(ROOT/'engineering_final_guard.json')['status']=='PASS'
 assert not any(load(ROOT/'engineering_final_guard.json')['counts'].values())
 engineering=load(ROOT/'engineering_final/receipt.json');assert engineering['status']=='PASS_CONSTRUCTED_FAKE_ONLY'
 current=source_manifest();initial=load(ROOT/'engineering/plan/plan.json')['source_manifest']
 postdiff=sorted(k for k in current if current[k]!=initial.get(k));assert postdiff==['jev_select/packaging_evaluation_orders.py'],postdiff
 write('source_manifest.json',current)
 for n,h in current.items():
  target=ROOT/'code_snapshot'/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PACKAGE/n,target);assert sha(target)==h
 cfg=load(ROOT/'engineering_final/plan/plan.json')['jobs'][0]['config'];algorithm=cfg['stability_monitor']['algorithm_identity']['files_sha256']
 for n,h in algorithm.items():
  src=PACKAGE/'jev_select/stability'/n;assert sha(src)==h
  target=ROOT/'code_snapshot/jev_select/stability'/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
 write('algorithm_archive_manifest.json',algorithm)
 assert current==load(ROOT/'engineering_final/plan/plan.json')['source_manifest']
 parent=load(OLD/'delivery_manifest.json');assert all(sha(OLD/n)==h for n,h in parent['files_sha256'].items())
 assert {p.relative_to(OLD).as_posix() for p in OLD.rglob('*') if p.is_file() and p!=OLD/'delivery_manifest.json'}==set(parent['files_sha256'])
 write('parent_identity_verification.json',{'head':'3164a6c1','initial_worktree':'clean','parent':str(OLD),'manifest_sha256':sha(OLD/'delivery_manifest.json'),
  'files_verified':len(parent['files_sha256']),'status':'PASS_BYTE_IDENTITIES_ONLY','parent_status':'NOT_READY_UNCHANGED','no_parent_resigning':True})
 original=load(OLD/'source_manifest.json');changed=sorted(k for k,h in original.items() if current.get(k)!=h);added=sorted(set(current)-set(original));assert not set(original)-set(current)
 assert all(current[k]==h for k,h in original.items() if '/schemas/' in k)
 write('source_change_review.json',{'baseline_files':len(original),'production_files':len(current),'modified_existing':changed,'added':added,'deleted':[],
   'old_schema_bytes_unchanged':True,'post_integration_change':postdiff,'post_integration_reason':'saved-record validation errors force ERROR and STOP_TECHNICAL gate; no continuation/resend',
   'post_integration_validation':closure,'common_episode_memory_physics_unchanged_since_integration':True})
 before=load(ROOT/'protected_before.json');allow={'docs/03_阶段产出分析/Jev/README.md'}
 assert all(sha(n)==h for n,h in before.items() if n not in allow)
 write('protected_before_after.json',{'status':'PASS','protected_before_files':len(before),'unchanged':len(before)-len(allow),'permitted_index_updates':sorted(allow|{'docs/02_阶段实施方案/Jev/README.md'}),
   'old_NOT_READY_package_file_set_and_bytes':'UNCHANGED','unexpected_changes':[]})
 admission=load(ROOT/'source_admission.json');assert admission['source_count']==0
 counts=dict(Counter(r['status'] for r in admission['records']))
 write('source_authority_discovery.json',{'version':'jev_source_authority_discovery_v1','registered_raw_corpus':'raw/bed_bpp/bed-bpp_v1.json','raw_sha256':admission['raw_sha256'],
   'source_audit':str(OLD/'source_audit.json'),'source_audit_sha256':admission['source_audit_sha256'],
   'available_original_metadata':['semantic_pallet_dataset_v1/provenance/manifest.json',str(OLD/'history_inventory.json'),str(OLD/'exposure_records.json')],
   'authority_status':'NO_INDEPENDENTLY_TRUSTED_ISSUER_CONFIGURED','provenance_status':'NO_SUFFICIENT_SIGNED_CLOSED_LIFECYCLE_PROOF_AVAILABLE',
   'real_trust_policy':'source_trust_policy.json','fixture_roots_are_not_real_trust_roots':True,'source_status_counts':counts,
   'missing':['authenticated custodian identity/trust configuration','lifecycle origin and complete use/exposure evidence through frozen cutoff','all aliases/variants/forks review and linked evidence files'],
   'static_access':'source metadata audit only; no formal policy/model queries or trajectories'})
 write('split_manifest.json',{'version':'jev_evaluation_source_split_v2','train':[r['source_identity']['component'] for r in admission['records'] if r['status']=='CONTAMINATED'],
   'dev':[],'test':[],'excluded':[{'component':r['source_identity']['component'],'status':r['status'],'gaps':r['gaps']} for r in admission['records'] if r['status']!='CONTAMINATED'],
   'train_is_contamination_quarantine_not_new_training_authorization':True,'old_splits_unchanged':True})
 shutil.copyfile(OLD/'plan/data_build_registration.json',ROOT/'data_build_registration.original.json')
 shutil.copyfile(OLD/'statistical_analysis_plan.json',ROOT/'statistical_analysis_plan.json')
 write('data_build_readiness.json',{'status':'NOT_READY','real_sources_admitted':0,'real_dataset_package':'NOT_MATERIALIZED','tasks':0,'variants':0,
  'registration':'data_build_registration.original.json','strata':[[14,20,2,0],[21,30,2,0],[31,40,2,0]],
  'format':'length min/max, required components, eligible components','constructor':'packaging_evaluation_data.build','loader':'packaging_evaluation_data.load_dataset',
  'positive_fixture':'constructed_data_fixture/dataset','positive_fixture_sources':6,'positive_fixture_is_real_data':False,
  'frozen_calibration':{'m_ref_kg':8.586,'scale_kg':9},'feasibility':'UNKNOWN retained; no witnesses; no method-based selection'})
 snap=orders.snapshots();write('memory/unrelated_E_snapshot.json',snap['control'])
 write('memory/snapshot_refs.json',{**{m:{'path':str(orders.PARENTS[m]+'/'+orders.FILES[m]),'snapshot_digest':snap[m]['snapshot_digest'],'sha256':sha(Path(orders.PARENTS[m])/orders.FILES[m])} for m in ('T','E')},
  'control':{'path':'memory/unrelated_E_snapshot.json','snapshot_digest':snap['control']['snapshot_digest'],'rule':CONTROL_RULE}})
 write('interface_contract.json',{'version':'jev_evaluation_interface_v1','versions':VERSIONS,'method_registry':REGISTRY,'method_order':METHODS,
   'source_admission':'packaging_source_provenance.adjudicate/audit_admissions + pinned CLI policy/audit identities',
   'data':'packaging_evaluation_data.build/load_dataset; explicit new test task schema; old loader guard intact',
   'plan':'packaging_evaluation_orders.prepare/validate_plan; fixture, exact exposed development, signed real dataset scopes distinct',
   'run':'run_validation -> common._run_job -> run_episode; explicit Fake; formal purpose rejected for all six methods',
   'memory':'explicit v10 per-decision MemoryView and private genuine reference receipt; model sees only registered actual view',
   'ledger':'EvaluationLedger, per-job + shared budget/config identity; local/singleton zero; UNKNOWN_SEND stops, no retries',
   'persistence':['DECISION_READY','SELECTED','MONITORED','COMMITTED','TERMINATED'],
   'readonly_validation':'validate_run and CLI validate-run; ERROR receipt causes nonzero exit; no dispatch',
   'no_implicit_credentials_or_network':True,'model_availability':'UNKNOWN_NOT_PROBED','dependencies':orders.dependencies()})
 write('formal_experiment_matrix.json',{'version':'jev_evaluation_formal_matrix_pending_v2','frozen':False,'task_ids':[],'jobs':[],'method_ids':METHODS,'repetitions':1,
   'natural_job_slots':0,'remote_job_slots':0,'per_job_send_caps':{},'shared_batch_send_cap':0,
   'reason':'NO_SUFFICIENT_VERIFIED_REAL_SOURCES','engineering_fixture_plan':'engineering_final/plan/plan.json',
   'future_formula':'6 admitted independent components x 1 variant x 1 repeat x 6 methods =36 slots /24 remote; send caps=4*sum(actual planned box counts)',
   'not_a_runnable_formal_plan':True})
 write('test_results.json',{'integration':integration,'integration_source_snapshot':'engineering/code_snapshot','early_monitor_stop_batch':stops,
   'final_closure_checks':closure,'final_source_snapshot':'code_snapshot','do_not_sum_overlapping_batches':True,
   'post_integration_only_change':postdiff,'history_counts_reused':False,'actual_model_api_calls':0,'formal_test_orders_executed':0,
   'failure_logs':'dev/dev2/additional initial failures retained; not final passes','new_six_method_evidence':'new v10 tests plus final engineering_final records; not old three-method tests'})
 criteria={'D01':'ENGINEERING_PASS_REAL_DATA_NOT_READY','D02':'CONSTRUCTED_INTERFACE_PASS_REAL_PACKAGE_NOT_MATERIALIZED','D03':'SIX_METHOD_ENGINEERING_PASS_FORMAL_MATRIX_NOT_FROZEN',
   'D04':'PASS_CONTROL_AND_ANALYSIS_CONTRACT','D05':'PASS_FAKE_ENGINEERING_AND_REGISTERED_REGRESSION','D06':'DELIVERED_NOT_READY'}
 write('engineering_acceptance.json',{'version':'jev_jn4_a_supplement_acceptance_v1','criteria':criteria,'six_method_engineering_complete':True,'validation_scope':'constructed/development + Fake only',
   'data_ready':False,'formal_matrix_frozen':False,'JN4_B_admitted':False,'integration':integration,'final_closure_checks':closure,
   'actual_model_api_calls':0,'actual_formal_test_jobs_executed':0})
 write('evaluation_plan_receipt.json',{'version':'jev_evaluation_plan_receipt_v2','stage':'JN4-A_SUPPLEMENT','status':'NOT_READY','criteria':criteria,
   'six_method_engineering_complete':True,'data_ready':False,'formal_matrix_frozen':False,'JN4_B_admitted':False,
   'production_files':len(current),'source_digest':digest(current),'dependencies':orders.dependencies(),'verified_real_sources':0,'real_tasks':0,'real_variants':0,
   'formal_natural_job_slots':0,'formal_remote_job_slots':0,'formal_shared_send_cap':0,'actual_model_api_calls':0,'credential_reads':0,'actual_formal_test_jobs_executed':0,
   'engineering_evidence':{'current':'engineering_final/receipt.json','current_fake_jobs':6,'current_simulated_transports':12,'earlier_preserved':'engineering/receipt.json','earlier_simulated_transports':12},
   'nonempty_formal_plan':None,'formal_matrix':'formal_experiment_matrix.json','research_benefit':'NOT_ESTABLISHED',
   'gaps':['independent trusted source custodians/attestations with complete scoped lifecycle and aliases review','at least two admitted real components in each frozen length stratum','real derived data materialization and a nonempty frozen formal plan after admission'],
   'stop':'JN4-A only; no JN4-B, model calls, new forks, experience generation or source expansion'})
 write('handoff.json',{'version':'jev_jn4_a_supplement_handoff_v1','parent':str(OLD),'parent_status':'NOT_READY_UNCHANGED','receipt':'evaluation_plan_receipt.json',
   'six_method_engineering_complete':True,'data_ready':False,'formal_matrix_frozen':False,'JN4_B_admitted':False,
   'report':str(REPORT),'next':'provide auditable trusted provenance, then use admission/data/plan APIs; do not run formal test in this stage',
   'source_admission':'source_admission.json','interface':'interface_contract.json','formal_plan':None,'actual_model_api_calls':0,'actual_formal_test_jobs_executed':0,'stop':True})
 # Actual test sources, including fixtures reused by engineering script.
 tests=[*Path('semantic_pallet_planner/tests/unit').glob('test_packaging_evaluation*.py'),Path('semantic_pallet_planner/tests/unit/test_packaging_source_provenance.py'),
   Path('semantic_pallet_planner/tests/unit/test_packaging_memory_pilot.py'),Path('semantic_pallet_planner/tests/unit/test_packaging_remote.py'),Path('semantic_pallet_planner/tests/unit/test_packaging_orders.py'),
   Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_packaging_runtime.py'),Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_packaging_load.py')]
 for p in tests:
  dest=ROOT/'test_snapshot'/p;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
 write('test_manifest.json',{str(p):sha(p) for p in tests})
 # Preserve current and archived static guards outside the protected run roots.
 verify=Path('semantic_pallet_planner/outputs/VERIFY_JN4_A_SUPPLEMENT_20261105_01')
 for p in verify.glob('*guard.json'):
  v=load(p);assert v['status']=='PASS' and not any(v['counts'].values()),p
  shutil.copyfile(p,ROOT/p.name)
 report=REPORT.read_text();marker='本次实际验证见'
 if marker in report:
  report=report.replace(marker,f'本机集成{integration["tests"]}项通过；最后仅调整收尾错误保护，最终源码针对性复验{closure["tests"]}项通过，与集成批次有重叠，不相加。六方法恢复与旧协议公共代码在集成后未改变。实际验证见',1)
  REPORT.write_text(report)
 sourcepaths=['semantic_pallet_planner/src/semantic_pallet_planner/jev_select','semantic_pallet_planner/tests/unit']+[str(p) for p in DOCS]
 patch=subprocess.run(['git','diff','HEAD','--',*sourcepaths],capture_output=True,check=True).stdout
 new=subprocess.run(['git','ls-files','-z','--others','--exclude-standard','--',*sourcepaths],capture_output=True,text=True,check=True).stdout.split('\0')
 for n in filter(None,new):
  q=subprocess.run(['git','diff','--no-index','--','/dev/null',n],capture_output=True);assert q.returncode==1;patch+=q.stdout
 (ROOT/'source_changes.patch').write_bytes(patch)
 docs={str(p):sha(p) for p in DOCS}
 mapping={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(ROOT.rglob('*')) if p.is_file() and p!=ROOT/'delivery_manifest.json'}
 write('delivery_manifest.json',{'version':'jev_jn4_a_supplement_delivery_v1','status':'NOT_READY','JN4_B_admitted':False,'files_sha256':mapping,'documentation_sha256':docs,
   'source_files':len(current),'source_digest':digest(current),'nested_manifests_included':True,'exclusion':'root delivery_manifest.json only'})
 print(json.dumps({'status':'NOT_READY_DELIVERED','six_method_engineering':True,'real_sources':0,'source_files':len(current),'files':len(mapping),'integration':integration,'closure':closure}))

if __name__=='__main__':main()
