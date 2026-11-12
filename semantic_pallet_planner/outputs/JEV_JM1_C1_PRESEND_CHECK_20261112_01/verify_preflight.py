"""Read-only evidence collector; prints JSON. Never runs orders, gates or solvers."""
import json, hashlib, sys, platform, subprocess, importlib.metadata
from pathlib import Path
root=Path.cwd(); base=root/'semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01'
def load(p): return json.loads(Path(p).read_text())
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def git(*args): return subprocess.check_output(['git',*args],text=True).strip()
f=load(base/'formal_freeze.json'); plan=load(base/'materials/training_plan.json')
checks=[]
def record(name,ok,details): checks.append(dict(check=name,status='PASS' if ok else 'FAIL',details=details))
record('operation_root',str(root.resolve())==f['operation_root'],str(root.resolve()))
for folder in [base,root/'semantic_pallet_planner/outputs/JEV_JM_B2_FREEZE_CLOSURE_QA_20261112_01',root/'semantic_pallet_planner/outputs/JEV_JM_C1_DELIVERY_QA_20261112_01']:
 m=load(folder/'delivery_manifest.json'); rows=m['files']; bad=[]
 for r in rows:
  p=root/r['path']
  if r['path']=='docs/03_阶段产出分析/Jev/README.md': continue
  if not p.is_file() or sha(p)!=r['sha256'] or p.stat().st_size!=r['bytes']: bad.append(r['path'])
 record('manifest:'+folder.name,not bad,dict(entries=len(rows),bad=bad,navigation='shared README excluded only'))
from semantic_pallet_planner.jev_select.experiment import source_manifest
saved=load(base/'source_manifest.json'); actual=source_manifest()
record('runtime_source_set',saved==actual,dict(saved_count=len(saved),actual_count=len(actual),differences=sorted(k for k in saved.keys()|actual.keys() if saved.get(k)!=actual.get(k))))
from semantic_pallet_planner.jev_select.contracts import digest,validate_schema
from jsonschema import Draft202012Validator
from semantic_pallet_planner.jev_select import packaging_jev_v13 as v13
schema_dir=root/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/schemas'
for name,value in [('jm_training_freeze_v1',f),('jm_training_plan_v1',plan)]:
 errors=[e.message for e in Draft202012Validator(load(schema_dir/(name+'.schema.json'))).iter_errors(value)]
 record('schema:'+name,not errors,errors)
record('freeze_digest',f['receipt_digest']==digest({k:v for k,v in f.items() if k!='receipt_digest'})=='255afe2a80736838105c759a46597aa8853bdba736b7795672a491b86bbbcce1',f['receipt_digest'])
record('preparation_digest',plan['plan_digest']==digest({k:v for k,v in plan.items() if k!='plan_digest'})==f['preparation_digest']=='cf082c9bb1213f84394c32c7c618b0a467f5925898fed6cc6313a6319f52ab9b',plan['plan_digest'])
record('python_dependencies_source',v13.identity()==f['runtime_identity'],dict(saved=f['runtime_identity'],actual=v13.identity(),executable=sys.executable))
refs=[]
def walk(v):
 if isinstance(v,dict):
  if set(v)=={'path','pointer','sha256'}: refs.append(v)
  for x in v.values(): walk(x)
 elif isinstance(v,list):
  for x in v: walk(x)
walk(f); walk(plan)
bad=[]
for r in refs:
 p=root/r['path']
 if not p.is_file() or sha(p)!=r['sha256']: bad.append(r)
record('freeze_and_plan_references',not bad,dict(count=len(refs),bad=bad))
from semantic_pallet_planner.jev_select.stability.monitor import exact_freeze
current_monitor=exact_freeze() # identity/environment only, no assess_candidate or solver
jobs=[]; differences=[]
def delta(a,b,path=''):
 if isinstance(a,dict) and isinstance(b,dict):
  for k in sorted(a.keys()|b.keys()): delta(a.get(k),b.get(k),path+'/'+k)
 elif a!=b: differences.append(dict(field=path,saved=a,current=b))
for i,j in enumerate(f['jobs'],1):
 ex=load(root/j['execution_ref']['path']); c=ex['config']
 validate_schema('jm_v13_execution',ex); validate_schema('config',c)
 expected=str(Path(f['runtime_root'])/('baseline_'+str(i)))
 record('job_binding:'+str(i),j['storage_root']==ex['storage_root']==expected and digest(ex)==j['execution_digest'] and digest(c)==j['config_digest'] and j['job_id']==ex['job_id'] and j['max_sends']==ex['max_sends'],dict(job_id=j['job_id'],root=expected))
 record('config_method:'+str(i),c['selector']=='jev_no_memory' and c['memory_mode']=='none' and c['jm_mode']=='REMOTE_INJECTED',dict(selector=c['selector'],memory_mode=c['memory_mode'],model=c['model']))
 if i==1: delta(c['stability_monitor'],current_monitor)
 jobs.append(dict(ordinal=i,wave=1+(i-1)//3,task_id=j['task_id'],job_id=j['job_id'],execution_ref=j['execution_ref'],storage_root=j['storage_root'],max_sends=j['max_sends'],status='NOT_RUN',reason='MONITOR_IDENTITY_MISMATCH_AND_NO_AUTHORIZATION',actual_sends=0))
record('monitor_environment_identity',not differences,differences)
record('runtime_root_absent',not Path(f['runtime_root']).exists(),dict(path=f['runtime_root'],exists=Path(f['runtime_root']).exists()))
b=f['budget']; caps=[j['max_sends'] for j in f['jobs']]
record('budget',caps==[19,14,18,19,15,18] and sum(caps)==b['baseline_send_upper']==103 and b['initial_suffix_send_upper']==564 and b['repeat_suffix_send_upper']==210 and b['suffix_send_upper']==774 and b['global_send_upper']==877,dict(per_job=caps,wave1=sum(caps[:3]),wave2=sum(caps[3:]),baseline=103,suffix_reserved=774,total_reserved=877,authorized=0))
# Static gate inspection only: invoking a gate would fail during identity validation first.
import inspect
from semantic_pallet_planner.jev_select import packaging_jev_training_freeze as freeze, packaging_jev_training_plan as prep
record('two_send_gates_static',"require(False, 'FREEZE_NOT_A_SEND_PERMIT')" in inspect.getsource(freeze.require_send_authorization),dict(freeze=inspect.getsource(freeze.require_send_authorization),preparation=inspect.getsource(prep.require_send_authorization),permit=inspect.getsource(v13.validate_send_permit),dynamic='NOT_RUN_AFTER_IDENTITY_STOP'))
print(json.dumps(dict(version='jm_c1_presend_check_v1',head=git('rev-parse','HEAD'),requested_head='9cd053e474be9fc3e8a252c420258dc388ffacb1',head_policy='provenance only; QA-only successors preserved; no frozen identity overwritten',checks=checks,jobs=jobs,status='STOP_MONITOR_IDENTITY_MISMATCH',execution_authorized=False,real_calls_authorized=0,research_result='NOT_RUN',cost='UNKNOWN',operations=dict(credentials=0,permits=0,sends=0,orders=0,forks=0,candidate_rebuilds=0,LP=0),not_verified=['dynamic baseline/suffix gate refusal after valid preflight','remaining sequential production-validator checks after jm13_monitor_identity','real transport/provider protocol/credential/permit validation','real orders/recovery/monitor solve/public export/sampling/epsilon/fork_plan'],stop=True),ensure_ascii=False,indent=2))
