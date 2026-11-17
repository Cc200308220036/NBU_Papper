"""Read-only sealed artifact/source/blob/checkpoint verification; no production imports."""
import hashlib,json,pathlib,re,subprocess
P=pathlib.Path
OUT=P('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P1_20261117_01')
BASE=P('semantic_pallet_planner/src/semantic_pallet_planner')
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(canonical(v)).hexdigest()
manifest=read(OUT/'delivery_manifest.json');assert len({r['path'] for r in manifest['files']})==len(manifest['files'])
for r in manifest['files']:
 p=P(r['path']);assert p.stat().st_size==r['size_bytes'] and sha(p)==r['sha256'],p
source=read(OUT/'source_manifest.json');current={str(p.relative_to(BASE)):sha(p) for p in BASE.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(BASE).parts)}
assert current==source['files'] and digest(current)==source['source_identity']
checks=0;monitor_checks=0
for p in (OUT/'final_evidence').rglob('*.json'):
 d=read(p)
 def visit(v):
  global checks,monitor_checks
  if isinstance(v,dict):
   if v.get('version')=='jev_checkpoint_v16':
    assert v['record_digest']==digest({k:x for k,x in v.items() if k!='record_digest'}),p
    assert v['execution_binding']['scope']=='DEVELOPMENT_SYNTHETIC_ONLY'
    checks+=1
   if v.get('version')=='selected_action_monitor_v1':
    assert v['result_digest']==digest(v['result']) and v['credential_digest']==digest({k:x for k,x in v.items() if k!='credential_digest'}),p
    assert v['result'] is not None and v['result']['diagnostics']['TEST_DOUBLE'] is True,p
    assert v['result']['kernel_calls']==0
    monitor_checks+=1
   for x in v.values():visit(x)
  elif isinstance(v,list):
   for x in v:visit(x)
 visit(d)
blobs=[]
for path in (OUT/'final_evidence').rglob('blobs/*'):
 if path.is_file():assert sha(path)==path.name;blobs.append(str(path))
assert checks>0 and monitor_checks>0 and blobs
# Fixed historical navigation, never mutable HEAD re-signing.
for group in read(OUT/'readonly_receipt.json')['history']:
 assert sha(P(group['manifest']))==group['sha256']
 for r in group['members']:
  data=subprocess.check_output(['git','show',r['navigation_revision']+':'+r['path']]) if r['navigation_revision'] else P(r['path']).read_bytes()
  assert hashlib.sha256(data).hexdigest()==r['sha256']
plan=read(OUT/'p2_draft/acceptance_plan_DRAFT.json');assert plan['status']=='DRAFT' and plan['source_identity']==source['source_identity']
real=read(OUT/'final_evidence/test_real_tasks_admin_adaptation_and_formal_gates_before_episode/run_denominator.json');assert len(real['rows'])==8 and all(r['status']=='NOT_RUN' for r in real['rows'])
subprocess.run(['git','diff','--check'],check=True)
assert not subprocess.check_output(['git','diff','--cached','--name-only']).strip()
print(json.dumps({'status':'PASS_READ_ONLY_INTEGRITY','manifest_members':len(manifest['files']),'production_files':len(current),
 'checkpoint_occurrences':checks,'test_double_monitor_occurrences':monitor_checks,'durable_blob_files':len(blobs),
 'counts_not_independent_cases':True,'actual_kernel_freeze_LP_model_orders':'NOT_RUN','integer_multistep_issue':'OPEN',
 'scope':'saved bytes/digests only; not behavioral or numerical reexecution'},ensure_ascii=False,indent=2))
