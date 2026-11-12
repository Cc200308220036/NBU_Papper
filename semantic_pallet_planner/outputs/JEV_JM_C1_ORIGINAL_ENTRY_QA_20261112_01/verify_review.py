"""Independent saved-fact audit; stdlib only, no production imports or dispatch."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]; OUT=Path(__file__).resolve().parent
B=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_C1_ORIGINAL_PYTHON_RECHECK_20261112_01'
F=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01'
def load(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
m=load(B/'delivery_manifest.json')
for row in m['files']:
 p=ROOT/row['path'];assert sha(p)==row['sha256'] and p.stat().st_size==row['bytes'],row['path']
assert {p for p in B.rglob('*') if p.is_file() and p.name!='delivery_manifest.json'}=={ROOT/r['path'] for r in m['files'] if r['path'].startswith(str(B.relative_to(ROOT))+'/')}
protected=load(B/'protected_inputs.json')['files']
for name,s in protected.items():assert sha(ROOT/name)==s,name
snapshot=load(F/'source_manifest.json');pkg=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
actual={p.relative_to(pkg).as_posix():sha(p) for p in pkg.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(pkg).parts)}
assert actual==snapshot and len(actual)==505
f=load(F/'formal_freeze.json');plan=load(F/'materials/training_plan.json')
assert digest({k:v for k,v in f.items() if k!='receipt_digest'})==f['receipt_digest']
assert digest({k:v for k,v in plan.items() if k!='plan_digest'})==plan['plan_digest']==f['preparation_digest']
r=load(B/'preflight_receipt.json');checks={x['check']:x for x in r['checks']}
assert len(checks)==len(r['checks'])==37 and all(x['status']=='PASS' for x in checks.values())
assert r['status']=='PASS_READ_ONLY_PREFLIGHT_NOT_EXECUTION_AUTHORIZATION'
assert r['operation_root']==f['operation_root']=='/home/cyw/NBU_Papper'
monitor=load(B/'actual_monitor_identity.json');assert monitor['execution_environment']['executable']=='/home/cyw/anaconda3/bin/python'
assert checks['runtime_identity']['details']['actual']==f['runtime_identity']
pending=load(B/'pending_execution_checklist.json');assert len(pending['jobs'])==len(r['jobs'])==len(f['jobs'])==6
for i,(j,a,p) in enumerate(zip(f['jobs'],r['jobs'],pending['jobs']),1):
 ex=load(ROOT/j['execution_ref']['path']);config=ex['config']
 assert config['stability_monitor']==monitor and config['runtime_identity']['monitor_identity']==digest(monitor)
 assert digest(ex)==j['execution_digest'] and digest(config)==j['config_digest']
 assert checks['monitor_full_identity:'+str(i)]['details']['saved']==checks['monitor_full_identity:'+str(i)]['details']['actual']==monitor
 for k in ('job_id','task_id','allocation_id','execution_ref','execution_digest','config_digest','storage_root','max_sends','slot_id'):assert j[k]==a[k]==p[k],(i,k)
 assert a['status']==p['status']=='NOT_RUN' and a['actual_sends']==p['actual_sends']==0
 assert p['ordinal']==i and p['wave']==(1 if i<=3 else 2)
 assert j['storage_root']==str(Path(f['runtime_root'])/('baseline_'+str(i)))
 assert config['selector']=='jev_no_memory' and config['memory_mode']=='none'
assert [j['max_sends'] for j in f['jobs']]==[19,14,18,19,15,18]
assert f['budget']['baseline_send_upper']==103 and f['budget']['global_send_upper']==877
assert not r['execution_authorized'] and not pending['execution_authorized'] and pending['authorized_sends']==r['real_calls_authorized']==0
assert not any(r['actual_operations'].values())
c=load(B/'commands_and_results.json');assert c['collector_entry']=='/home/cyw/anaconda3/bin/python'
assert [x['label'] for x in c['commands']]==['original_validator','baseline_gate','suffix_gate'] and [x['exit_code'] for x in c['commands']]==[0,1,1]
assert not (B/'original_validator.stderr').read_text()
v=load(B/'original_validator.stdout');assert v['bytes']=='PASS' and v['read_only'] and not v['runtime_output_created']
for stage in ('baseline','suffix'):
 trace=(B/(stage+'_gate.stderr')).read_text()
 assert trace.rstrip().endswith('semantic_pallet_planner.jev_select.packaging_jev_sampling.SamplingError: FREEZE_NOT_A_SEND_PERMIT')
 assert 'line 187, in require_send_authorization' in trace and "require(False, 'FREEZE_NOT_A_SEND_PERMIT')" in trace
 assert not (B/(stage+'_gate.stdout')).read_text()
old=(B/'first_attempt/collect_recheck.py').read_text();new=(B/'collect_recheck.py').read_text()
assert old!=new and old.replace('semantic_pallet_planner.jev_select.contracts.JevSelectError: FREEZE_NOT_A_SEND_PERMIT','semantic_pallet_planner.jev_select.packaging_jev_sampling.SamplingError: FREEZE_NOT_A_SEND_PERMIT')==new
first=load(B/'first_attempt/preflight_receipt.json');assert first['status']=='STOP_READ_ONLY_RECHECK_FAILED'
assert [x['check'] for x in first['checks'] if x['status']=='FAIL']==['baseline_gate_expected_refusal']
assert checks['protected_bytes_unchanged']['details']['count']==len(protected)==613
refs=[]
def walk(v):
 if isinstance(v,dict):
  if set(v)=={'path','pointer','sha256'}:refs.append(v)
  for a in v.values():walk(a)
 elif isinstance(v,list):
  for a in v:walk(a)
walk(f);walk(plan)
for ref in refs:
 p=ROOT/ref['path'];assert sha(p)==ref['sha256']
 if ref['pointer']:
  value=load(p)
  for part in ref['pointer'].lstrip('/').split('/'):
   key=part.replace('~1','/').replace('~0','~');value=value[int(key)] if isinstance(value,list) else value[key]
assert len(refs)==90
assert not subprocess.check_output(['git','diff','3315f36c','HEAD','--','semantic_pallet_planner/src','semantic_pallet_planner/tests'],cwd=ROOT)
result=dict(version='jm_c1_original_entry_independent_saved_audit_v1',head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),status='PASS',manifest_files=len(m['files']),protected_inputs=len(protected),runtime_files=len(actual),nested_refs=len(refs),archived_checks=len(checks),jobs=6,baseline_upper=103,original_validator='ARCHIVED_EXIT0_NOT_RERUN_HERE',gates='ARCHIVED_EXPECTED_REFUSALS_EXIT1_NOT_RERUN_HERE',first_attempt='PRESERVED; ONLY COLLECTOR EXCEPTION EXPECTATION CHANGED',current_Linux_behavior='NOT_RUN',current_review='STDLIB_SAVED_BYTES_BINDINGS_AND_SOURCE_AUDIT_ONLY',real_calls_authorized=0)
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
