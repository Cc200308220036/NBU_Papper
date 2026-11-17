"""Stdlib saved-file checks only. No production imports, loops or solvers."""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('--sealed',action='store_true');args=ap.parse_args()
O=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_R1_20261117_01')
R=Path('semantic_pallet_planner/src/semantic_pallet_planner')
REPORT=Path('docs/03_阶段产出分析/几何规划模块/几何候选器GP3-N3-R1技术失败检查点恢复最小整改交付_20261117_01.md')
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def enc(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(enc(v)).hexdigest()
s=read(O/'source_manifest.json');before=read(O/'before_source_manifest.json')['files'];mid=read(O/'after_iteration_01_source_manifest.json')['files']
actual={p.relative_to(R).as_posix():sha(p) for p in R.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(R).parts)}
assert actual==s['files'] and len(actual)==542
changed=s['changed_existing'];assert changed==['jev_select/episode.py','jev_select/geometry_execution.py']
assert actual.keys()==before.keys()==mid.keys()
assert [k for k in actual if actual[k]!=before[k]]==[k for k in actual if k in changed]
for n in changed:
 assert sha(O/'source_snapshot'/n)==actual[n]
 assert sha(O/'before_source'/Path(n).name)==before[n]
 assert sha(O/'after_iteration_01_source'/Path(n).name)==mid[n]
for p in (O/'test_snapshot').iterdir():assert sha(p)==sha(Path('semantic_pallet_planner/tests/unit')/p.name)
# Historical source/navigation identities are explicitly pinned. Other old
# members must still match current original bytes, not hidden behind Git blobs.
external={str(R/n) for n in changed}|{str(REPORT.parent/'README.md')}
historical=0
for name,revision in [('GEOM_CANDIDATES_GP3_N3_20261117_01','eec656877c9a22255fc4dd2a7e5d50e39bbfee0b'),('GEOM_CANDIDATES_GP3_N3_QA_20261117_01','fe631adba7e20a040d68e8addd5642ce927ea395')]:
 for row in read(Path('semantic_pallet_planner/outputs')/name/'delivery_manifest.json')['files']:
  p=Path(row['path']);raw=subprocess.check_output(['git','show',revision+':'+str(p)]) if str(p) in external else p.read_bytes()
  assert hashlib.sha256(raw).hexdigest()==row['sha256'],str(p)
  historical+=1
cases=0;phase_records=0
for stage,source,behavior in [('before',before,'before_behavior.json'),('after_iteration_01',mid,'after_iteration_01_behavior.json'),('after',actual,'after_behavior.json')]:
 rows=read(O/behavior)
 for row in rows:
  p=O/stage/row['case'];cfg,t,cp=map(read,[p/'config.json',p/'task.json',p/'failure_checkpoint.json'])
  assert digest(source)==cfg['runtime_identity']['source_identity']==row['source_identity']
  assert digest(cfg)==cp['config_digest']==row['config_digest']
  assert digest(t)==cfg['fixture_task_digest']==row['fixture_digest']
  assert cp['record_digest']==digest({k:v for k,v in cp.items() if k!='record_digest'})
  for name in ('production_phases.json','recovery_phases.json'):
   for saved in read(p/name):
    assert saved['config_digest']==digest(cfg) and enc(saved['runtime_identity'])==enc(cfg['runtime_identity'])
    assert saved['record_digest']==digest({k:v for k,v in saved.items() if k!='record_digest'})
    phase_records+=1
  for blob in (p/'durable/blobs').iterdir():assert sha(blob)==blob.name
  ev=cp['pending_event'] if row['case']=='evaluation_failure' else cp['events'][-1]
  assert ev['monitor']['status']=='STABLE' and ev['monitor']['result']['diagnostics']['TEST_DOUBLE'] is True
  assert ev['monitor']['result']['kernel_calls']==0
  assert ev['monitor']['credential_digest']==digest({k:v for k,v in ev['monitor'].items() if k!='credential_digest'})
  if row['case']=='evaluation_failure':assert cp['phase']=='COMMITTED' and cp['reason']=='EVALUATION_ERROR' and cp['state']['placed_count']==1
  else:assert cp['phase']=='TERMINATED' and enc(ev['before'])==enc(ev['after']) and ev['action'] is None and cp['state']['placed_count']==0
  if stage=='before':assert row['recovery']['status']=='RECOVERY_REJECTED_FAIL' and (p/'recovery_failure_traceback.log').exists()
  else:
   assert row['recovery']['status']=='RESTORED'
   delta=row['recovery']['delta'];assert all(delta[k]==0 for k in ('generation','selection','monitor','commit'))
   assert delta['evaluation']==int(row['case']=='evaluation_failure')
   restored=read(p/'restored_result.json');assert enc(restored['final_state'])==enc(cp['state'])
   assert restored['summary']['placed_items']==int(row['case']=='evaluation_failure')
  cases+=1
b,a=read(O/'before_behavior.json'),read(O/'after_behavior.json')
assert all(x['fixture_digest']==y['fixture_digest'] and x['fault']==y['fault'] and x['source_identity']!=y['source_identity'] for x,y in zip(b,a))
neg=read(O/'negative_checks.json');assert len(neg)==25 and all(r['result']=='REJECTED' for r in neg)
for log,n in [('r1_tests_01.log',6),('test_geometry_execution_n3.log',10),('test_geometry_public_n2.log',11),('test_geometry_binding_r1.log',5)]:
 t=(O/log).read_text();assert f'Ran {n} tests' in t and '\nOK\n' in t
assert '3 passed' in (O/'legacy_runtime.log').read_text()
for p in (REPORT,REPORT.parent/'README.md'):
 for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),target
if args.sealed:
 m=read(O/'delivery_manifest.json')
 expected={p.as_posix() for p in O.rglob('*') if p.is_file() and p.name not in ('delivery_manifest.json','seal_verification.log')}
 expected|={REPORT.as_posix(),(REPORT.parent/'README.md').as_posix(),'semantic_pallet_planner/tests/unit/test_geometry_recovery_r1.py'}|{str(R/n) for n in changed}
 assert expected=={row['path'] for row in m['files']}
 for row in m['files']:
  p=Path(row['path']);assert sha(p)==row['sha256'] and p.stat().st_size==row['size_bytes'],str(p)
print(json.dumps({'status':'PASS_SAVED_FILES_AND_PINNED_HISTORY_ONLY','sealed':args.sealed,'production_files':542,'changed':2,'source_bound_case_records':cases,'isolated_phase_records':phase_records,'negative_records':25,'historical_manifest_members':historical,'production_imports':0,'loop_calls':0,'PCT_LP_calls':0,'model_calls':0,'A03':'PARTIAL','GP4':'NOT_READY'}))
