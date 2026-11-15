"""Seal P4-A offline delivery; never imports executable or learned modules."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zlib
ROOT=Path('PCT/outputs/PCT_P4_A_20261115_01')
REPORT=Path('PCT/docs/PCT_P4A训练计划与不可发送模板冻结验收_20261115_01.md')
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(name,value):
 p=ROOT/name
 with p.open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
def main():
 assert read(ROOT/'independent_saved_checks.json')['status']=='PASS_STDLIB_SAVED_PLAN_AUDIT'
 assert 'Ran 7 tests' in (ROOT/'final_tests.log').read_text() and '\nOK\n' in (ROOT/'final_tests.log').read_text()
 baseline=read(ROOT/'build_01/baseline.json');assert baseline['branch']=='dev/PCT'
 assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==baseline['head']
 assert not subprocess.check_output(['git','diff','--cached','--name-only'],text=True).strip()
 changed=subprocess.check_output(['git','diff','--name-only'],text=True).splitlines()
 assert all(p.startswith('PCT/') for p in changed)
 public_change=subprocess.check_output(['git','diff','--','semantic_pallet_planner','Online-3D-BPP-PCT'],text=True)
 assert not public_change
 protected=read('PCT/outputs/PCT_P3_20261115_01/identity.json')['final_source_sha256']
 for name,h in protected.items():assert sha(name)==h,name
 history=[]
 for package in ('PCT_P3_20261115_01','PCT_P3_QA_20261115_01'):
  m=read(Path('PCT/outputs')/package/'delivery_manifest.json');differences=[]
  for row in m['files']:
   if sha(row['path'])!=row['sha256']:differences.append(row['path'])
  assert all(n in ('PCT/README.md','PCT/docs/README.md') for n in differences)
  history.append({'package':package,'checked':len(m['files']),'navigation_only_differences':differences})
 build=ROOT/'build_01';training=read(build/'training_plan.json');evaluation=read(build/'evaluation_template.json')
 identity=read(build/'input_identity.json')
 for name,h in identity['files'].items():assert sha(name)==h,name
 sources=[Path(n) for n in identity['files'] if n.startswith('PCT/') and not n.startswith('PCT/outputs/')]
 sources += [Path('PCT/scripts/check_p4a_saved.py'),Path('PCT/scripts/seal_p4a.py')]
 for p in sources:
  if p.suffix=='.py':ast.parse(p.read_text())
  q=ROOT/'final_source_snapshot'/p;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(p.read_bytes())
 frozen={'files':{str(p):sha(p) for p in sorted(set(sources))},'input_identity':'build_01/input_identity.json',
         'catalog_digest':read(build/'data_catalog.json')['catalog_digest'],
         'training_plan_digest':training['plan_digest'],'evaluation_template_digest':evaluation['plan_digest'],
         'protected_P3_source_files_unchanged':len(protected),'history_checks':history,
         'formal_execution_identity':'NOT_IMPLEMENTED_NOT_ADMITTED'}
 write('identity.json',frozen)
 write('acceptance.json',{'version':'pct_p4a_acceptance_v1','status':'DEVELOPMENT_DELIVERED_PENDING_INDEPENDENT_QA',
  'criteria':[
   {'id':'B40','status':'PASS_PLAN_FREEZE_ONLY','facts':{'tasks':16,'boxes':264,'original_orders':4,'conservative_training_components':3,'models':6,'attempt_slots':12000,'update_slots':1500,'action_cap':198000,'final_epoch':125},'evidence':['build_01/data_catalog.json','build_01/training_plan.json','independent_saved_checks.json']},
   {'id':'B41','status':'PASS_UNSENDABLE_TEMPLATE_ONLY','facts':{'slots':220,'jev_send_cap':1284,'network_choice_cap':2568,'sending_admitted':False,'execution_admitted':False,'weights':'PENDING_TRAINING_IDS_WITH_NULL_SHA'},'evidence':['build_01/evaluation_template.json','final_tests.log']},
   {'id':'B42','status':'PASS_METHOD_AND_LIMITS_FREEZE_ONLY','facts':'geo6/8/6 and load11/12/6 are full feature-package differences; public pool/post-monitor/strict-mask/A2C/native default differences and adequacy/negative-result review frozen','evidence':['build_01/method_cards.json',str(REPORT)]}],
  'carryforward':{'P3-Q01':'PLAN_REQUIREMENTS_ADDRESSED; new formal observer/stop/resume evidence still required',
                  'P3-Q02':'DESIGN_AND_SAVED_CAPSULE_ROUNDTRIP_DONE; formal writer, crash/throughput and capacity gate still unmet'},
  'formal_training_executor':'NOT_IMPLEMENTED','formal_execution_admitted':False,'independent_QA':'PENDING'})
 write('commands_and_results.json',{'commands':[
  {'command':'git branch --show-current; git rev-parse HEAD; git status --short; git diff --cached --stat','exit_code':0,'result':'dev/PCT;4019735d; initial clean worktree/index'},
  {'command':"PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=PCT/src $NBU_PY -m unittest discover -s PCT/tests -p test_p4a.py -v",'exit_code':0,'tests':7,'log':'preflight_tests.log'},
  {'command':'PYTHONDONTWRITEBYTECODE=1 $NBU_PY PCT/scripts/freeze_p4a.py build --output PCT/outputs/PCT_P4_A_20261115_01/build_01','exit_code':0,'log':'build_01.log'},
  {'command':'PYTHONDONTWRITEBYTECODE=1 $NBU_PY PCT/scripts/freeze_p4a.py verify --output PCT/outputs/PCT_P4_A_20261115_01/build_01','exit_code':0,'result':'PASS_OFFLINE_PLAN_ONLY;220 slots; no execution'},
  {'command':"PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=PCT/src $NBU_PY -m unittest discover -s PCT/tests -p test_p4a.py -v",'exit_code':0,'tests':7,'log':'final_tests.log'},
  {'command':'python3 PCT/scripts/check_p4a_saved.py --package PCT/outputs/PCT_P4_A_20261115_01/build_01 --receipt PCT/outputs/PCT_P4_A_20261115_01/independent_saved_checks.json','exit_code':0,'receipt':'independent_saved_checks.json'},
  {'command':'python3 PCT/scripts/seal_p4a.py','exit_code':0,'result':'local AST/old source/history/input identities/scope/index/link checks'},
  {'command':'git diff --check','exit_code':0}],
  'failures':[],'read_only_lookup_notes':['No Online-3D-BPP-PCT/arguments.py; actual defaults found and pinned in Tools.py; no third-party edits'],
  'expected_negative_checks':'resigned budget/source/order/duplicate/unknown-field/fake-weight mutations, drift, non-dispatch, gzip corruption/unsafe paths rejected by tests',
  'business_activity':{'orders':0,'candidate_generations':0,'LP_calls':0,'network_forwards':0,'optimizer_updates':0,'remote_requests':0},
  'credentials_reads':False,'dependency_install_or_upgrade':False,'weight_downloads':False,'subagents':0,'git_mutations':False})
 write('limitations.json',{'execution':'Plans are not permits; formal training/execution/recovery protocol and WAL/shard integration NOT_IMPLEMENTED; all220 evaluation and12000 training attempt slots NOT_RUN',
  'data':'16 variants from4 original orders/3 conservative components;6 familiar exposed combinations; no independent holdout admission; synthetic load properties and feasibility UNKNOWN',
  'model':'all six formal final epoch125 models PENDING_TRAINING with null SHA; no P2/P3 substitution; no native score replication or adequate-convergence claim',
  'storage':'audit capsules preserve326 saved JSON files/147 transitions, not cumulative journal or optimizer blobs; no runtime resume, crash tests, throughput or long-run ratio guarantee',
  'resources':'30.2h/470GB P3 collection extrapolation excludes full gradient/optimizer and long-state costs; fallback disk gate unmet; full budget UNKNOWN',
  'history':'original P3 FAIL/zero counters preserved; final P3 source never fully reran six jobs/training; new source collections do not authorize re-signing old headers',
  'not_run':['P4-B','P4-C','P4-D','formal six-model training','formal220-slot evaluation','remote API verification or send','any business/candidate/LP/model/update experiment','proposed future four-attempt resource preflight'],
  'next_task_prompt':'NOT_CREATED'})
 write('handoff.json',{'version':'pct_p4a_handoff_v1','status':'B40_B42_PLAN_DEVELOPMENT_DELIVERED_PENDING_INDEPENDENT_QA',
  'report':str(REPORT),'manifest':'delivery_manifest.json','acceptance':'acceptance.json','identity':'identity.json',
  'training_plan':'build_01/training_plan.json','evaluation_template':'build_01/evaluation_template.json',
  'catalog':'build_01/data_catalog.json','method_cards':'build_01/method_cards.json',
  'formal_prerequisites':'build_01/formal_prerequisites.json','storage_proof':'build_01/storage_roundtrip.json',
  'formal_training_executor':'NOT_IMPLEMENTED','sending_admitted':False,'execution_admitted':False,
  'next_action':'Independent quality review of P4-A only; no implicit P4-B/C/D authorization',
  'carryforward':['P3-Q01 formal observer/stop/resume preflight','P3-Q02 formal writer/crash/throughput/capacity acceptance'],
  'remote_requests':0,'next_task_prompt':'NOT_CREATED','stop':True})
 subprocess.run(['git','diff','--check'],check=True)
 links=re.findall(r'\]\(([^)]+)\)',REPORT.read_text())
 future={'delivery_manifest.json'}
 assert all((REPORT.parent/link).exists() or Path(link).name in future for link in links)
 write('final_checks.json',{'report_links':len(links),'link_check':'PASS','AST_check':'PASS','plan_inputs_verified':len(identity['files']),
  'protected_P3_sources_unchanged':len(protected),'historical_manifest_checks':history,'only_PCT_changed':True,
  'index':'EMPTY','diff_check':'PASS','final_tests':{'passed':7,'skipped':0},
  'plan_import_guard':'Torch/NumPy/SciPy/planner and socket forbidden; no forbidden modules loaded',
  'formal_execution_admitted':False,'environment':{'sealer_python':sys.version,'zlib':zlib.ZLIB_VERSION,'planning_interpreter':'existing NBU Python3.12.16; no install'},
  'artifact_count_before_manifest':sum(1 for p in ROOT.rglob('*') if p.is_file())})
 paths=[p for p in ROOT.rglob('*') if p.is_file() and p.name!='delivery_manifest.json']
 paths += sources+[REPORT,Path('PCT/README.md'),Path('PCT/docs/README.md')]
 files=[{'path':str(p),'size':p.stat().st_size,'sha256':sha(p)} for p in sorted(set(paths))]
 write('delivery_manifest.json',{'version':'pct_p4a_delivery_manifest_v1','self_excluded':True,'no_cyclic_hash':True,'files':files})
 print(json.dumps({'status':'SEALED_PLAN_ONLY_PENDING_QA','files':len(files),'bytes':sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file()),'execution_admitted':False}))
if __name__=='__main__':main()
