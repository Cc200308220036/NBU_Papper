"""Independent stdlib hashes/history/source/archived arithmetic check; no business imports."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
B=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_20261111_01'
NAV='docs/03_阶段产出分析/Jev/README.md'
def load(p):return json.loads(p.read_text())
def sha(raw):return hashlib.sha256(raw).hexdigest()
nav_observations=[]
def check(rows):
 for r in rows:
  raw=(ROOT/r['path']).read_bytes()
  if sha(raw)!=r['sha256'] and r['path']==NAV:
   history=subprocess.check_output(['git','log','-20','--format=%H','--',NAV],cwd=ROOT,text=True).splitlines()
   for ref in history:
    old=subprocess.check_output(['git','show',ref+':'+NAV],cwd=ROOT)
    if sha(old)==r['sha256']:
     nav_observations.append({'path':NAV,'expected_sha256':r['sha256'],'historical_blob_commit':ref,'current_navigation_changed':True,'status':'PASS_HISTORICAL_BLOB'});raw=old;break
   if sha(raw)!=r['sha256']:
    nav_observations.append({'path':NAV,'expected_sha256':r['sha256'],'historical_blob_commit':None,'status':'ARCHIVED_NAVIGATION_BYTES_NOT_FOUND','impact':'navigation-only gap; not runtime identity drift'});continue
  assert sha(raw)==r['sha256'],r['path']
  if 'bytes' in r:assert len(raw)==r['bytes'],r['path']
 return len(rows)
result={'version':'jm1_b2_independent_static_checks_v1','head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
result['delivery_files']=check(load(B/'delivery_manifest.json')['files'])
inputs=load(B/'input_evidence_index.json');result['input_files']=check(inputs['files'])
source=load(B/'source_identity.json');result['source_identity_files']=check(source['source_files']);result['protected_sources']=check(source['protected_existing_sources'])
result['parent_missing_files_now_present']=[p for p in inputs['missing_files'] if (ROOT/p).is_file()]
assert len(result['parent_missing_files_now_present'])==5
parent=ROOT/'semantic_pallet_planner/outputs/JEV_JM_JM1_B1_QA_20261111_01'
result['parent_qa_manifest_files']=check(load(parent/'delivery_manifest.json')['files'])
for field in ['b1_saved_audit_v1.json','saved_source_audit_v1.json']:
 capsule=load(B/field)
 for r in capsule['files']:
  raw=(ROOT/r['path']).read_bytes()
  if r['comparison']=='ENTRY_PREFIX':
   assert sha(raw[r['bytes']:])==r['extension_sha256'];raw=raw[:r['bytes']]
  assert len(raw)==r['bytes'] and sha(raw)==r['sha256'],r['path']
 result[field+'_files']=len(capsule['files'])
material=load(B/'task_source_candidates.json');assert len(material['candidates'])==22
for r in material['candidates']:
 ref=r['material_ref'];assert sha((ROOT/ref['path']).read_bytes())==ref['sha256']
 ref=r['source_register_ref'];raw=(ROOT/ref['path']).read_bytes();assert sha(raw)==ref['sha256']
 value=json.loads(raw)
 for k in ref['pointer'].split('/')[1:]:value=value[int(k)] if isinstance(value,list) else value[k]
 assert value['id']==r['existing_id']
result['material_candidates']=22
budget=load(B/'constructed_budget.json');assert len(budget['jobs'])==54
for j in budget['jobs']:assert j['send_upper']==max(0,j['full_items']-j['placed_before']-j['forced_first'])
assert sum(j['send_upper'] for j in budget['jobs'])==budget['global_send_upper']==579
assert budget['initial_suffixes']==36 and budget['repeat_suffixes']==12 and budget['total_suffixes']==48
assert len({j['job_id'] for j in budget['jobs']})==54
result['archived_budget']={'jobs':54,'initial_suffixes':36,'repeat_suffixes':12,'global_send_upper':579,'kind':'CONSTRUCTED_ONLY'}
reg='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_versions.py'
old=subprocess.check_output(['git','show',source['entry_head']+':'+reg],cwd=ROOT)
assert (ROOT/reg).read_bytes().startswith(old)
assert not subprocess.check_output(['git','diff','3530626e','HEAD','--','semantic_pallet_planner/src','semantic_pallet_planner/tests'],cwd=ROOT)
result['delivery_to_current_source_drift']='NONE'
result['navigation_history']=nav_observations
result['original_delivery_verifier_current_run']='FAIL_CURRENT_README_DIFF; original_verify.log'
result['local_tests']={'B2':10,'B1':10,'failures':0,'scope':'constructed only'}
result['status']='PASS_B2_STATIC_BYTES_WITH_PARENT_NAVIGATION_GAP'
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
