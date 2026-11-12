"""Independent stdlib offline freeze review. No business import or runtime mutation."""
import hashlib,json,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
B=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01';HEAD='8b15b534a25b40c4b6a991d0a317bb2529ec6841'
def load(p):return json.loads(p.read_text())
def sha(v):return hashlib.sha256(v).hexdigest()
def digest(v):return sha(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def rr(r):
 raw=(ROOT/r['path']).read_bytes();assert sha(raw)==r['sha256'],r['path'];v=json.loads(raw)
 for part in r.get('pointer','').split('/')[1:]:
  part=part.replace('~1','/').replace('~0','~');v=v[int(part)] if isinstance(v,list) else v[part]
 return v
def ref(path):return {'path':path,'pointer':'','sha256':sha((ROOT/path).read_bytes())}
m=load(B/'delivery_manifest.json');result={'version':'jm_b2_freeze_closure_independent_checks_v1','head':HEAD}
for r in m['files']:
 raw=(ROOT/r['path']).read_bytes();assert sha(raw)==r['sha256'] and len(raw)==r['bytes'],r['path']
result['delivery_files']=len(m['files'])
snapshot=load(B/'source_manifest.json');package=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
actual={p.relative_to(package).as_posix():sha(p.read_bytes()) for p in sorted(package.rglob('*')) if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(package).parts)}
assert actual==snapshot;result['runtime_source_files']=len(actual)
f=load(B/'formal_freeze.json');p=rr(f['plan_ref']);old=rr(f['historical_plan_ref']);hm=rr(f['historical_manifest_ref'])
assert f['receipt_digest']==digest({k:v for k,v in f.items() if k!='receipt_digest'})
assert p['plan_digest']==digest({k:v for k,v in p.items() if k!='plan_digest'})
assert f['formal_frozen'] and f['state']=='FROZEN_OFFLINE' and f['execution_authorized'] is False
assert f['preparation_digest']==p['plan_digest'] and f['runtime_identity']==p['runtime_identity']
assert f['runtime_identity']['source']==digest(snapshot)
assert not p['formal_frozen'] and not p['execution_authorized'] and p['missing_qa']==[] and len(p['qa_refs'])==5
assert old['qa_refs']==[] and len(old['missing_qa'])==5 and old['formal_frozen'] is False
assert any(row['path']==f['historical_plan_ref']['path'] and row['sha256']==f['historical_plan_ref']['sha256'] for row in hm['files'])
for r in f['qa_refs']:
 assert ref(r['path'])==r
assert len(f['qa_refs'])==10 and p['qa_refs']==f['qa_refs'][:5]
qa_count=0
for audit in f['qa_audit']:
 manifest=load(ROOT/audit['manifest_path'])
 for row in manifest['files']:
  if row['path']=='docs/03_阶段产出分析/Jev/README.md':
   assert any(n['expected_sha256']==row['sha256'] and n['status']=='MUTABLE_NAVIGATION_EXCLUDED_NONBLOCKING' for n in audit['navigation'])
  else:
   raw=(ROOT/row['path']).read_bytes();assert sha(raw)==row['sha256'] and len(raw)==row['bytes'];qa_count+=1
 assert audit['verified_non_navigation']==[ref(r['path']) for r in manifest['files'] if r['path']!='docs/03_阶段产出分析/Jev/README.md']
result['QA_primary_refs']=10;result['QA_non_navigation_manifest_files']=qa_count
for key in ('selection_rule','requested_count','smaller_scope_reason','catalog_ref','input_refs','sampling','gates','model_declaration'):assert p[key]==old[key],key
assert rr(p['audit_ref'])==rr(old['audit_ref'])
def budget_without_jobs(b):return {**b,'baseline_jobs':[{k:v for k,v in r.items() if k!='job_id'} for r in b['baseline_jobs']]}
assert budget_without_jobs(p['budget'])==budget_without_jobs(old['budget'])
sched=rr(p['schedule_ref']);new_ex=[];ns=[]
for i,(a,b,j) in enumerate(zip(p['assignments'],old['assignments'],f['jobs'])):
 assert {k:v for k,v in a.items() if k not in ('execution_ref','job_id')}=={k:v for k,v in b.items() if k not in ('execution_ref','job_id')}
 ex=rr(a['execution_ref']);prev=rr(b['execution_ref']);task=rr(a['task_ref']);ns.append(len(task['items']));new_ex.append(ex)
 assert ex['task']==prev['task'] and ex['config']['runtime_identity']['task_identity']==digest(ex['task'])
 assert {k:v for k,v in ex['config'].items() if k!='runtime_identity'}=={k:v for k,v in prev['config'].items() if k!='runtime_identity'}
 assert {k:v for k,v in ex['config']['runtime_identity'].items() if k!='strategy_identity'}=={k:v for k,v in prev['config']['runtime_identity'].items() if k!='strategy_identity'}
 assert ex['identity']==f['runtime_identity'] and ex['max_sends']==a['full_items']==len(task['items'])
 assert ex['record_digest']==digest({k:v for k,v in ex.items() if k!='record_digest'})
 assert ex['storage_root']==f['runtime_root']+f'/baseline_{i+1}'
 expected={'task_id':a['task_id'],'slot_id':a['slot_id'],'job_id':a['job_id'],'allocation_id':ex['allocation_id'],'storage_root':ex['storage_root'],'execution_ref':a['execution_ref'],'execution_digest':digest(ex),'config_digest':digest(ex['config']),'task_digest':a['runtime_task_digest'],'arrival_digest':a['arrival_digest'],'strategy_identity':ex['config']['runtime_identity']['strategy_identity'],'physical_identity':ex['config']['runtime_identity']['physical_identity'],'monitor_identity':ex['config']['runtime_identity']['monitor_identity'],'max_sends':ex['max_sends']}
 assert j==expected
assert len(new_ex)==6 and sched['executions']==new_ex and sched['storage_root']==f['runtime_root']
assert f['runtime_root']==f['operation_root']+'/'+str(Path(f['plan_ref']['path']).parent/'future_runs')
assert f['budget']==p['budget'] and f['sampling']==p['sampling']
initial=sum(3*(n-1)+3*max(0,n-2) for n in ns);repeat=sum(sorted([3*max(0,n-z-1) for n in ns for z in (0,1)],reverse=True)[:4])
assert (sum(ns),initial,repeat,initial+repeat,sum(ns)+initial+repeat)==(103,564,210,774,877)
assert [f['budget'][k] for k in ['baseline_send_upper','initial_suffix_send_upper','repeat_suffix_send_upper','suffix_send_upper','global_send_upper']]==[103,564,210,774,877]
assert f['admission']['new_delivery_review']=='PENDING_INDEPENDENT_QA' and f['admission']['C1']=='NOT_AUTHORIZED'
h=load(B/'historical_protection.json')
for r in h['files']:
 current=(ROOT/r['path']).read_bytes();assert sha(current)==r['current_sha256']
 if r['comparison']=='EXACT':assert sha(current)==r['entry_sha256']
 elif r['comparison'].startswith('UNCHANGED_ENTRY_PREFIX'):
  oldbytes=subprocess.check_output(['git','show',h['entry_head']+':'+r['path']],cwd=ROOT)
  assert sha(oldbytes)==r['entry_sha256'] and current.startswith(oldbytes)
 else:assert r['comparison']=='AUTHORIZED_QA_JMB2P_01_TEST_CHANGE'
result['protected_files']=len(h['files'])
a=ET.parse(B/'offline_junit.xml').getroot();b=ET.parse(B/'targeted_junit.xml').getroot()
ac=a.findall('.//testcase');bc=b.findall('.//testcase');failed=[c for c in ac if c.find('failure') is not None]
assert len(ac)==26 and len(failed)==1 and not a.findall('.//error')
assert len(bc)==1 and not b.findall('.//failure') and not b.findall('.//error')
assert failed[0].attrib['name']==bc[0].attrib['name']=='test_full_qa_freeze_and_drift_rejections'
message=ET.tostring(failed[0],encoding='unicode');assert 'FREEZE_IDENTITY_OR_BINDING_DRIFT' in message and 'FREEZE_QA_INVENTORY' in message
result['archived_tests']={'initial':{'total':26,'pass':25,'fail':1},'targeted':{'total':1,'pass':1},'unique_covered_after_test_assertion_fix':26,'not_full_suite_rerun':True}
result['budget']={'baseline':103,'initial':564,'repeat':210,'suffix':774,'global':877}
result['frozen_identity']=f['receipt_digest'];result['plan_identity']=p['plan_digest']
result['study_unchanged']=True;result['original_missing_QA_plan_preserved']=True
result['runtime_root']=f['runtime_root'];result['real_execution_authorized']=False
result['current_runtime_verifier']='NOT_RUN: local dependency/runtime/root differs; no identity/schema substitution; independent saved-byte audit only'
result['status']='PASS_FROZEN_OFFLINE_BINDINGS_AND_ARCHIVE_CHECKS'
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
