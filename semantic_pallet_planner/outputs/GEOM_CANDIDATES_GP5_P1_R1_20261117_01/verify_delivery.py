"""Read-only R1 identity and saved arithmetic verification; no project imports."""
import hashlib,json,subprocess
from pathlib import Path
OUT=Path(__file__).parent
SRC=Path('semantic_pallet_planner/src/semantic_pallet_planner')
def read(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(v):return sha(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
source=read(OUT/'source_manifest.json')
actual={str(p.relative_to(SRC)):sha(p.read_bytes()) for p in SRC.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(SRC).parts)}
assert actual==source['files'] and digest(actual)==source['source_identity']
for k in source['modified']+source['added']:assert (OUT/'code_snapshot'/k).read_bytes()==(SRC/k).read_bytes()
before=read(OUT/'before_source_manifest.json')['files']
for k,h in read(OUT/'protected_identity_check.json')['protected_files'].items():assert h==actual[k]==before[k]
for pkg,revision in [('GEOM_CANDIDATES_GP5_P1_20261117_01','c7f99638e4d5ab603b3a6e86c02f589555ea7b55'),('GEOM_CANDIDATES_GP5_P1_QA_20261117_01','95ffbb428bb6b4e647ccbd5b2040281fedf63dbe')]:
 for row in read(OUT.parent/pkg/'delivery_manifest.json')['files']:
  raw=subprocess.check_output(['git','show',revision+':'+row['path']]) if Path(row['path']).name=='README.md' or row['path'].startswith('semantic_pallet_planner/src/') else Path(row['path']).read_bytes()
  assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'],row['path']
# Detect bare objects, including nullable object unions (not just type=object).
holes=[]
for name in ['checkpoint_v16','config_v16','candidate_bundle_v16','decision_context_v16','selection_result_v16','geometry_order_metrics_v1','geometry_order_run_v1','geometry_real_kernel_receipt_v2','geometry_kernel_completion_review_v1','geometry_order_accounting_v1']:
 def walk(v,path=''):
  if isinstance(v,dict):
   typ=v.get('type',[])
   if (typ=='object' or isinstance(typ,list) and 'object' in typ) and not any(k in v for k in ('properties','additionalProperties','patternProperties','maxProperties')):holes.append([name,path])
   for k,x in v.items():walk(x,path+'/'+k)
  elif isinstance(v,list):
   for i,x in enumerate(v):walk(x,path+'/'+str(i))
 walk(read(SRC/'jev_select/schemas'/(name+'.schema.json')))
assert not holes,holes
E=OUT/'final_evidence'
for phase in ('SELECTED','MONITORED','COMMITTED'):
 r=read(E/'test_accounted_driver_and_recovery'/phase/'accounted_result.json');a=r['summary']['accounting'];delta=a['invocation_delta']
 assert delta['selector_calls']==delta['singleton_executions']==0
 assert delta['monitor_entries']==int(phase=='SELECTED') and delta['monitor_reuses']==int(phase=='MONITORED')
 assert delta['commit_successes']==delta['commit_attempts']==int(phase!='COMMITTED')
 assert a['cumulative']['commit_successes']==r['summary']['placed_items']==1
 assert r['summary']['completed'] and r['summary']['planned_items']==1
k=read(E/'test_k01_local_first_targets_and_k02_singleton_counts/K02_accounted.json')
assert k['summary']['accounting']['cumulative']=={'selector_calls':1,'singleton_executions':1,'monitor_entries':2,'monitor_reuses':0,'commit_attempts':2,'commit_successes':2}
assert k['summary']['placed_item_ratio']==k['summary']['placed_volume_ratio']==k['summary']['placed_mass_ratio']==1
for phase in ('ERROR','COMMIT_FAILURE'):
 r=read(E/'test_error_monitor_and_commit_failure_accounting'/phase/'accounted_failure.json')
 assert r['summary']['placed_items']==0 and r['summary']['accounting']['cumulative']['commit_successes']==0
negative=read(E/'test_completion_contract_missing_duplicate_error_only_no_commit_recovery/completion_contract_results.json')
assert len(negative['negative'])==9 and all(r['result']=='REJECTED' for r in negative['negative'])
for p in E.rglob('accounted_result.json'):
 assert p.stat().st_size>0
# The retained integer issue is still an actual synthetic technical failure.
r=read(E/'test_integer_multistep_type_conflict_is_preserved_technical_failure/integer_type_conflict.json')
assert r['summary']['placed_items']==1 and r['summary']['termination_reason']=='RUNTIME_INPUT_INVALID'
o=r['final_state']['placed_items'][0]
assert [type(v).__name__ for v in o['oriented_size_mm']]==['float','float','int']
# Raw actual tasks are administrator-only; byte, normalized and runtime identities stay separate.
for row in read(E/'test_real_tasks_admin_adaptation_and_formal_gates_before_episode/identities.json'):
 raw=(OUT.parent/'DATA_JEV_PACKAGING_LOAD_20261102_02/tasks'/(row['task_id']+'.json')).read_bytes()
 assert sha(raw)==row['raw_sha256'] and digest(json.loads(raw))==row['normalized_digest'] and len(json.loads(raw)['items'])==19
assert 'Ran 19 tests' in (OUT/'test.log').read_text() and (OUT/'test.log').read_text().rstrip().endswith('OK')
if (OUT/'delivery_manifest.json').exists():
 for row in read(OUT/'delivery_manifest.json')['files']:
  raw=Path(row['path']).read_bytes();assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'],row['path']
print('PASS: R1 source/snapshots, 46 protected files, historical pinned manifests, nested schemas, saved recovery/accounting/arithmetic, retained NUM failure and raw-task identities; no business imports/execution')
