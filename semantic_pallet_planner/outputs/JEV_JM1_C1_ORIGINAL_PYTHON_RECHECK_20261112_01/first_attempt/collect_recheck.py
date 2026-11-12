"""Evidence-only recheck. Writes only beside this file; never issues permits or runs jobs."""
import hashlib,json,os,shlex,subprocess,sys,traceback
from pathlib import Path
ROOT=Path.cwd(); OUT=Path(__file__).resolve().parent
BASE=Path('semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01')
OLD=Path('semantic_pallet_planner/outputs/JEV_JM1_C1_PRESEND_CHECK_20261112_01')
QA=Path('semantic_pallet_planner/outputs/JEV_JM_C1_PRESEND_QA_20261112_01')
PYTHON='/home/cyw/anaconda3/bin/python'
def load(p): return json.loads(Path(p).read_text())
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(n,v): (OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
checks=[];commands=[];protected={}; jobs=[]
def check(name,ok,detail):
 checks.append(dict(check=name,status='PASS' if ok else 'FAIL',details=detail))
 if not ok: raise RuntimeError(name)
def run(label,args):
 env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONPATH='semantic_pallet_planner/src')
 p=subprocess.run(args,env=env,capture_output=True,text=True)
 (OUT/(label+'.stdout')).write_text(p.stdout);(OUT/(label+'.stderr')).write_text(p.stderr)
 row=dict(label=label,command='PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src '+shlex.join(args),exit_code=p.returncode,stdout=label+'.stdout',stderr=label+'.stderr')
 commands.append(row);return p
f=load(BASE/'formal_freeze.json');plan=load(BASE/'materials/training_plan.json')
for j in f['jobs']:
 jobs.append(dict(task_id=j['task_id'],job_id=j['job_id'],allocation_id=j['allocation_id'],storage_root=j['storage_root'],execution_ref=j['execution_ref'],execution_digest=j['execution_digest'],config_digest=j['config_digest'],max_sends=j['max_sends'],slot_id=j['slot_id'],status='NOT_RUN',reason='NO_REAL_EXECUTION_AUTHORIZATION',actual_sends=0))
result=dict(version='jm_c1_original_python_recheck_v1',date='2026-11-12',head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),operation_root=str(ROOT),plan='JM-plan-v2',checks=checks,jobs=jobs,real_calls_authorized=0,execution_authorized=False,actual_operations=dict(credentials=0,permits=0,sends=0,orders=0,forks=0,candidate_rebuilds=0,LP=0),research_result='NOT_RUN',cost='UNKNOWN',stop=True)
try:
 check('original_entry_available',Path(PYTHON).is_file() and os.access(PYTHON,os.X_OK),dict(path=PYTHON,is_symlink=Path(PYTHON).is_symlink(),link_target=os.readlink(PYTHON) if Path(PYTHON).is_symlink() else None))
 check('actual_entry',sys.executable==PYTHON,sys.executable)
 check('operation_root',str(ROOT.resolve())==f['operation_root'],str(ROOT.resolve()))
 # Inventory all three input deliveries; only known mutable navigation is excluded.
 for folder in (BASE,OLD,QA):
  rows=load(folder/'delivery_manifest.json')['files'];bad=[];excluded=[]
  protected[str(folder/'delivery_manifest.json')]=sha(folder/'delivery_manifest.json')
  for r in rows:
   if r['path']=='docs/03_阶段产出分析/Jev/README.md': excluded.append(r);continue
   p=Path(r['path'])
   if not p.is_file() or sha(p)!=r['sha256'] or p.stat().st_size!=r['bytes']: bad.append(r['path'])
   if p.is_file():protected[str(p)]=sha(p)
  check('manifest:'+folder.name,not bad,dict(entries=len(rows),bad=bad,mutable_navigation_excluded=excluded))
 # Actual unchanged production script; do not replace its return with supplemental checks.
 p=run('original_validator',[PYTHON,str(BASE/'verify_delivery.py')])
 check('original_validator',p.returncode==0,commands[-1])
 original=json.loads(p.stdout);check('original_success_receipt',original['bytes']=='PASS' and original['read_only'] is True and original['runtime_output_created'] is False,original)
 from semantic_pallet_planner.jev_select import packaging_jev_v13 as v13
 from semantic_pallet_planner.jev_select.experiment import source_manifest
 from semantic_pallet_planner.jev_select.contracts import digest,validate_schema
 from semantic_pallet_planner.jev_select.stability.monitor import exact_freeze
 from jsonschema import Draft202012Validator
 saved_sources=load(BASE/'source_manifest.json'); current_sources=source_manifest()
 check('505_source_set',current_sources==saved_sources and len(saved_sources)==505,dict(count=len(saved_sources),source_digest=digest(current_sources)))
 package=Path('semantic_pallet_planner/src/semantic_pallet_planner')
 for name in saved_sources: protected[str(package/name)]=sha(package/name)
 check('runtime_identity',v13.identity()==f['runtime_identity'],dict(saved=f['runtime_identity'],actual=v13.identity()))
 actual=exact_freeze();save('actual_monitor_identity.json',actual)
 for i,j in enumerate(f['jobs'],1):
  ex=load(j['execution_ref']['path']);c=ex['config'];v13.validate_execution(ex)
  check('monitor_full_identity:'+str(i),c['stability_monitor']==actual and c['runtime_identity']['monitor_identity']==digest(actual),dict(saved=c['stability_monitor'],actual=actual))
  expected=str(Path(f['runtime_root'])/('baseline_'+str(i)))
  check('job_binding:'+str(i),ex['storage_root']==j['storage_root']==expected and ex['job_id']==j['job_id'] and digest(ex)==j['execution_digest'] and digest(c)==j['config_digest'] and ex['max_sends']==j['max_sends'],dict(root=expected,job_id=j['job_id'],max_sends=j['max_sends']))
  check('config_method:'+str(i),c['selector']=='jev_no_memory' and c['memory_mode']=='none' and c['jm_mode']=='REMOTE_INJECTED',dict(selector=c['selector'],memory_mode=c['memory_mode'],model=c['model'],jm_mode=c['jm_mode']))
 schema=package/'jev_select/schemas'
 for name,value in [('jm_training_freeze_v1',f),('jm_training_plan_v1',plan)]:
  errors=[e.message for e in Draft202012Validator(load(schema/(name+'.schema.json'))).iter_errors(value)]
  check('schema:'+name,not errors,errors)
 check('frozen_digests',f['receipt_digest']==digest({k:v for k,v in f.items() if k!='receipt_digest'})=='255afe2a80736838105c759a46597aa8853bdba736b7795672a491b86bbbcce1' and plan['plan_digest']==f['preparation_digest']==digest({k:v for k,v in plan.items() if k!='plan_digest'})=='cf082c9bb1213f84394c32c7c618b0a467f5925898fed6cc6313a6319f52ab9b',dict(receipt_digest=f['receipt_digest'],preparation_digest=f['preparation_digest']))
 refs=[]
 def walk(v):
  if isinstance(v,dict):
   if set(v)=={'path','pointer','sha256'}:refs.append(v)
   for x in v.values():walk(x)
  elif isinstance(v,list):
   for x in v:walk(x)
 walk(f);walk(plan)
 bad=[]
 for ref in refs:
  p=Path(ref['path'])
  if not p.is_file() or sha(p)!=ref['sha256']:bad.append(ref)
  if p.is_file():protected[str(p)]=sha(p)
 check('qa_plan_references',not bad,dict(count=len(refs),bad=bad))
 caps=[j['max_sends'] for j in f['jobs']];b=f['budget']
 check('budget',caps==[19,14,18,19,15,18] and sum(caps)==b['baseline_send_upper']==103 and b['initial_suffix_send_upper']==564 and b['repeat_suffix_send_upper']==210 and b['suffix_send_upper']==774 and b['global_send_upper']==877,dict(per_job=caps,waves=[sum(caps[:3]),sum(caps[3:])],baseline_upper=103,initial_suffix_reserved=564,repeat_suffix_reserved=210,suffix_reserved=774,total_reserved=877,authorized=0))
 # Stage gates validate identity first then refuse. No permit argument supplied.
 for stage in ('baseline','suffix'):
  p=run(stage+'_gate',[PYTHON,'-m','semantic_pallet_planner.jev_select.packaging_jev_training_freeze',stage+'-gate',str(BASE/'formal_freeze.json'),'--root','.'])
  expected='semantic_pallet_planner.jev_select.contracts.JevSelectError: FREEZE_NOT_A_SEND_PERMIT'
  check(stage+'_gate_expected_refusal',p.returncode==1 and p.stderr.rstrip().endswith(expected),dict(**commands[-1],expected_exception=expected,exception_phase='after validate_frozen_plan; explicit require(False) in require_send_authorization',permit=None))
 check('runtime_output_absent',not Path(f['runtime_root']).exists(),dict(path=f['runtime_root'],exists=Path(f['runtime_root']).exists()))
 check('protected_bytes_unchanged',all(sha(p)==s for p,s in protected.items()),dict(count=len(protected)))
 result.update(status='PASS_READ_ONLY_PREFLIGHT_NOT_EXECUTION_AUTHORIZATION',issue=dict(id='PRE-C1-ENV-01',status='RESOLVED_BY_ORIGINAL_ENTRY_PENDING_INDEPENDENT_QA'),next_stage_admission='AWAIT_INDEPENDENT_QA_AND_EXPLICIT_AUTHORIZATION',not_verified=['real credential/provider protocol/transport/permit','real order/recovery/LP/public export/sampling/epsilon/fork_plan'])
except Exception as e:
 result.update(status='STOP_READ_ONLY_RECHECK_FAILED',issue=dict(id='PRE-C1-ENV-01',status='NOT_CLOSED'),failure=repr(e),not_verified=['all steps after first failure','real C1/C2 and provider/LP'])
 (OUT/'collector_failure.stderr').write_text(traceback.format_exc())
finally:
 save('commands_and_results.json',dict(version='jm_c1_original_entry_commands_v1',commands=commands,collector_entry=sys.executable))
 save('protected_inputs.json',dict(version='jm_c1_readonly_protection_v1',files=protected))
 save('preflight_receipt.json',result)
 print(json.dumps(dict(status=result['status'],checks=len(checks),failed=[c['check'] for c in checks if c['status']=='FAIL']),ensure_ascii=False))
