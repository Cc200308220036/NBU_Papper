"""Seal the P3 delivery without changing experimental headers or histories."""
import ast
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess
ROOT=Path(__file__).resolve().parents[2]
BASE=Path('PCT/outputs/PCT_P3_20261115_01')
REPORT=Path('PCT/docs/PCT_P3限定本地诊断与小步训练验收_20261115_01.md')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(name,x):
 p=BASE/name
 if p.exists():raise ValueError('Delivery record already exists: '+name)
 p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def main():
 audit=read(BASE/'final_saved_audit.json');assert audit['status']=='PASS_SAVED_FACTS'
 probes=read(BASE/'prefix_recovery/results.json');assert len(probes)==4
 status=read(BASE/'attempt_02/dispatch_status.json');assert status['training']=='TWO_UPDATES_COMPLETE'
 assert 'Ran 8 tests' in (BASE/'final_tests.log').read_text() and '\nOK\n' in (BASE/'final_tests.log').read_text()
 source_paths=list(Path('PCT/src').rglob('*.py'))+list(Path('PCT/src').rglob('*.schema.json'))
 source_paths+=list(Path('PCT/tests').glob('test_p3*.py'))
 source_paths+=[Path('PCT/scripts')/n for n in ('run_p3.py','audit_p3.py','verify_p3_prefix_recovery.py','seal_p3.py')]
 public=Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select')
 external=[str(public/n) for n in ('packaging_versions.py','contracts.py','packaging_runtime.py','stability/monitor.py')]
 source_paths += [Path(n) for n in external]
 for p in source_paths:
  if p.suffix=='.py':ast.parse(p.read_text())
 identity={str(p):sha(p) for p in source_paths}
 for p in source_paths:
  q=BASE/'final_source_snapshot'/p;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(p.read_bytes())
 diff=subprocess.check_output(['git','diff','--',*external],text=True)
 (BASE/'external_changes.patch').write_text(diff)
 changed=subprocess.check_output(['git','diff','--name-only'],text=True).splitlines()
 assert all(p.startswith('PCT/') or p in external for p in changed)
 assert not subprocess.check_output(['git','diff','--cached','--name-only'],text=True).strip()
 subprocess.run(['git','diff','--check'],check=True)
 links=[]
 for target in re.findall(r'\]\(([^)]+)\)',REPORT.read_text()):
  if '://' not in target:
   links.append({'target':target,'exists':(REPORT.parent/target.split('#')[0]).exists()})
 # Records written below account for currently absent delivery links.
 future={'acceptance.json','commands_and_results.json','limitations.json','handoff.json','delivery_manifest.json'}
 assert all(x['exists'] or Path(x['target']).name in future for x in links)
 save('baseline.json',{'branch':'dev/PCT','head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
      'user_qa_baseline':'18115158143f1c3d346d5267e1548dd1282faf92','initial_worktree':'CLEAN','initial_index':'EMPTY',
      'existing_p2c_and_qa':'already committed in 116f022e; preserved','git_mutations':'NONE'})
 save('authorization.json',{'scope':'P3 B30-B33 fixed local diagnostics and two bounded updates',
      'public_files_explicitly_authorized':external,'remote_requests_authorized':0,'subagents':0,
      'prefix_tests':'necessary saved-prefix recovery tests within original monitor/network bounds, no full-order replay',
      'fixed_matrix_attempts':6,'fixed_training_attempts':16,'optimizer_steps':2})
 save('identity.json',{'version':'pct_p3_delivery_identity_v1','execution_identity':'attempt_02/pre_execution_identity.json',
      'final_source_sha256':identity,'final_source_snapshot':'final_source_snapshot',
      'execution_source_differences':audit['current_source_differences_from_execution'],
      'historical_headers_resigned':False,'recovery_current_final_source':'REFUSE_HISTORICAL_SOURCE_DRIFT',
      'use_execution_snapshot_for_saved_audit':True})
 save('commands_and_results.json',{'commands':[
      {'command':"PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=PCT/src $NBU_PY -m unittest discover -s PCT/tests -p test_p3_training.py -v",'exit_code':0,'tests':4,'purpose':'initial math and initial optimizer/RNG preflight'},
      {'command':'PYTHONDONTWRITEBYTECODE=1 $NBU_PY PCT/scripts/run_p3.py run --output PCT/outputs/PCT_P3_20261115_01/attempt_01','exit_code':1,'result':'preflight missing geometric weight path; no plan/jobs/monitor/update'},
      {'command':"PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=PCT/src:semantic_pallet_planner/src $NBU_PY -m unittest discover -s PCT/tests -p 'test_p3*.py' -v",'exit_code':0,'tests':6,'purpose':'pre-dispatch integration and math'},
      {'command':'PYTHONDONTWRITEBYTECODE=1 $NBU_PY PCT/scripts/run_p3.py run --output PCT/outputs/PCT_P3_20261115_01/attempt_02','exit_code':0,'result':'six jobs and 16 attempts/two updates'},
      {'command':'$NBU_PY PCT/scripts/audit_p3.py --run PCT/outputs/PCT_P3_20261115_01/attempt_02 --output PCT/outputs/PCT_P3_20261115_01/saved_audit.json','exit_code':1,'result':'22 saved audit count assertions failed; original hook missed intermediate stages; not 22 execution failures'},
      {'command':'PYTHONDONTWRITEBYTECODE=1 $NBU_PY PCT/scripts/verify_p3_prefix_recovery.py','exit_code':0,'result':'four one-pending-action prefix tests; no new full orders'},
      {'command':'$NBU_PY PCT/scripts/audit_p3.py --run PCT/outputs/PCT_P3_20261115_01/attempt_02 --output PCT/outputs/PCT_P3_20261115_01/saved_audit_corrected.json','exit_code':0,'result':'supplemented stage counts; originals preserved'},
      {'command':"PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=PCT/src:semantic_pallet_planner/src $NBU_PY -m unittest discover -s PCT/tests -p 'test_p3*.py' -v",'exit_code':0,'tests':7,'purpose':'corrected JournalSink observer'},
      {'command':"PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=PCT/src:semantic_pallet_planner/src $NBU_PY -m unittest discover -s PCT/tests -p 'test_p3*.py' -v",'exit_code':0,'tests':8,'log':'final_tests.log','purpose':'add real singleton value-only precheck; no optimizer update'},
      {'command':'PCT_P3_FROZEN_SOURCE=PCT/outputs/PCT_P3_20261115_01/attempt_02/source_snapshot/PCT/src PYTHONDONTWRITEBYTECODE=1 $NBU_PY PCT/scripts/audit_p3.py --run PCT/outputs/PCT_P3_20261115_01/attempt_02 --output PCT/outputs/PCT_P3_20261115_01/final_saved_audit.json','exit_code':0,'log':'final_saved_audit.log','purpose':'frozen execution source, no re-signing'},
      {'command':'python3 PCT/scripts/seal_p3.py','exit_code':1,'result':'system Python3.9 AST cannot parse existing public Python3.12 f-string; before seal records or model execution'},
      {'command':'$NBU_PY PCT/scripts/seal_p3.py','exit_code':0,'purpose':'AST/source/link/scope/index/hash checks and final seal'},
      {'command':'git diff --check','exit_code':0}],
      'remote_requests':0,'fixed_matrix_reruns':0,'extra_optimizer_steps':0})
 save('limitations.json',{'research':['random and two-step engineering weights only','two exposed tasks, synthetic load properties, satisfiability UNKNOWN','no unseen sources or generalization','all six jobs stop at empty pool; no global infeasibility proof'],
      'engineering':['original hook counters wrong; corrected supplemental receipts and final observer tests retained',
      'original planned cuts not reached; four bounded prefix continuations replace recovery evidence, not historical success',
      'no whole matrix or optimizer rerun after final code correction; execution and final source identities differ',
      'raw inference_s zero and checkpoint_io_s excluded as unmeasured; use measured public selection/monitor/session times',
      'model pure-forward and optimizer-only timing NOT_MEASURED','singletons absent naturally; fixture value-only check separately counted',
      'truncation and zero transitions only preflight tested','training recovery at completed update boundaries; arbitrary mid-batch orchestration and crash between step and publication NOT_RUN',
      'initial run lacked outer training snapshot lock; final entry adds JobLock; atomic snapshot publication and restored contents were verified',
      'full-state journals costly; formal scale sharding/storage feasibility not accepted','CPU frozen environment only; current final source must reject archived run source drift'],
      'not_run':['P4','formal 22-task matrix','six-model formal training','remote Jev','unseen evaluation','native original-paper replication','dependency upgrades','additional data/seed collection']})
 save('acceptance.json',{'version':'pct_p3_acceptance_v1','status':'DEVELOPMENT_DELIVERED_PENDING_INDEPENDENT_QA','criteria':[
      {'id':'B30','status':'PASS','scope':'6/6 archived; complete orders 0/6, natural empty pool 6/6, technical failures 0; metrics saved-fact verified','evidence':['attempt_02/matrix_results.json','final_saved_audit.json']},
      {'id':'B31','status':'PASS_BOUNDED_UPDATE_BOUNDARY','scope':'16 attempts,147 transitions,2 updates; finite losses/gradients/parameters, reward/public commit alignment, exact populated Adam and RNG roundtrip; arbitrary mid-batch recovery NOT_RUN','evidence':['attempt_02/training/update_1.json','attempt_02/training/update_2.json','attempt_02/training/snapshots','final_tests.log']},
      {'id':'B32','status':'PASS_WITH_CORRECTION','scope':'original bad zeros and failed cuts retained, supplementary immutable-stage accounting, four prefix recoveries, fixed JournalSink observer; pure-forward/optimizer-only timing NOT_MEASURED','evidence':['saved_audit.json','final_saved_audit.json','prefix_recovery/results.json','final_tests.log','resource_metrics.json']},
      {'id':'B33','status':'PASS_LIMITED_COVERAGE','scope':'matrix60 and training147 natural choices, no natural singleton; no task/seed substitution; source independence not established','evidence':['final_saved_audit.json']}],
      'independent_QA':'PENDING','P4_admitted':False})
 save('handoff.json',{'version':'pct_p3_handoff_v1','status':'P3_DEVELOPMENT_DELIVERED_PENDING_INDEPENDENT_QA',
      'report':str(REPORT),'acceptance':'acceptance.json','manifest':'delivery_manifest.json','identity':'identity.json',
      'execution_snapshot':'attempt_02/source_snapshot','final_source_snapshot':'final_source_snapshot',
      'P1C_Q01':'CLOSED_FOR_P3_SUPPLEMENTAL_SESSION_ACCOUNTING; original event seals unchanged',
      'model_versions':['pct_adapted_geo_v1','pct_adapted_load_v1'],'execution_version':'pct_p3_execution_v1',
      'config_version':'pct_p3_config_v1','training_snapshot_version':'pct_p3_training_snapshot_v1',
      'next_action':'Independent quality review of P3 only; inspect original instrumentation failure and final corrective tests separately',
      'research_benefit':'NOT_ESTABLISHED','remote_requests':0,'P4_authorized_or_started':False,
      'next_task_prompt':'NOT_CREATED','stop':True})
 final_bytes=sum(p.stat().st_size for p in BASE.rglob('*') if p.is_file())
 save('resource_metrics.json',{'dispatch':status,'matrix':audit['matrix_totals'],'training':audit['training_totals'],
      'prefix_recovery':probes,'preflight_real_singleton_critic_forwards':1,'preflight_optimizer_steps':0,
      'matrix_plus_probe_monitors':62,'matrix_plus_probe_network_choices':43,'whole_stage_monitors':209,
      'core_forward_only_latency':'NOT_MEASURED','event_zero_placeholders':'not used as measurements',
      'formal_collection_estimate':audit['resource_estimate'],'delivery_bytes_before_final_manifest':final_bytes})
 save('final_checks.json',{'source_AST':'PASS','source_count':len(identity),'diff_check':'PASS','index':'EMPTY',
      'public_changed_files':external,'only_authorized_scope':True,'report_links_checked':len(links),
      'frozen_audit':'PASS','final_tests':{'passed':8,'skipped':0},'source_hashes':'identity.json',
      'historical_headers_or_monitor_seals_changed':False})
 paths=[p for p in BASE.rglob('*') if p.is_file() and p.name!='delivery_manifest.json']
 paths += [REPORT,Path('PCT/README.md'),Path('PCT/docs/README.md')]+source_paths
 files=[{'path':str(p),'size':p.stat().st_size,'sha256':sha(p)} for p in sorted(set(paths))]
 save('delivery_manifest.json',{'version':'pct_p3_delivery_manifest_v1','self_excluded':True,'no_cyclic_hash':True,'files':files})
 print(json.dumps({'files':len(files),'delivery_bytes':sum(p.stat().st_size for p in BASE.rglob('*') if p.is_file()),'status':'SEALED_PENDING_INDEPENDENT_QA'}))
if __name__=='__main__':main()
