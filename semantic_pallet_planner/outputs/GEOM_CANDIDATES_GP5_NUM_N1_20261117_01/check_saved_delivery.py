"""Read-only saved-byte/schema/source checks after the mandated runtime stop.
No project imports, generation, transition, monitoring or recovery execution.
"""
import ast,hashlib,json,subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
OUT=Path(__file__).parent
ROOT=Path.cwd()
def read(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
base=read(OUT/'baseline_receipt.json');src=Path('semantic_pallet_planner/src/semantic_pallet_planner')
current={str(p.relative_to(src)):sha(p.read_bytes()) for p in src.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(src).parts)}
changed=[k for k,h in base['files'].items() if current.get(k)!=h];new=sorted(set(current)-set(base['files']))
protected=[k for k in base['files'] if k.startswith(('planner/','evaluation/','o4/','jev_select/stability/')) and k!='jev_select/stability/monitor.py']+['jev_select/geometry_runtime_contracts.py','jev_select/geometry_runtime_input.py']
assert all(current[k]==base['files'][k] for k in protected)
assert all(current[k]==h for k,h in base['files'].items() if k.startswith('jev_select/schemas/'))
for k in changed+new:
 if k.endswith('.py'):ast.parse((src/k).read_text(),filename=k)
 if k.endswith('.schema.json'):Draft202012Validator.check_schema(read(src/k))
for row in base['manifests']:
 mpath=Path(row['manifest']);assert sha(mpath.read_bytes())==row['sha256']
 for r in read(mpath)['files']:
  b=subprocess.check_output(['git','show',row['navigation_revision']+':'+r['path']]) if Path(r['path']).name=='README.md' else Path(r['path']).read_bytes()
  assert sha(b)==r['sha256'] and len(b)==r['size_bytes']
# Identify the overbroad new constraint without reassessing the saved candidate.
schemas=src/'jev_select/schemas'
v17=read(schemas/'checkpoint_v17.schema.json');v16=read(schemas/'checkpoint_v16.schema.json')
old=v16['$defs']['monitor_result']['properties']['candidate_id'];newid=v17['$defs']['monitor_result']['properties']['candidate_id']
assert not list(Draft202012Validator(old).iter_errors('synth_1'))
errors=list(Draft202012Validator(newid).iter_errors('synth_1'));assert errors
cp=read(OUT/'E/jobs/J00/checkpoint.json');ev=cp['pending_event'];assert cp['phase']=='SELECTED'
ref=ev['geometry_ref'];raw=(OUT/'E/jobs/J00/blobs'/ref['sha256']).read_bytes();assert sha(raw)==ref['sha256'];side=json.loads(raw)
blobs=side['audit']['publication']['blobs']
for key,hexbytes in blobs.items():
 b=bytes.fromhex(hexbytes);assert sha(b)==key and (OUT/'E/jobs/J00/blobs'/key).read_bytes()==b
account=read(OUT/'E/jobs/J00/accounting.json');calls=read(OUT/'test_double_calls.json')
assert len(calls)==1 and account['cumulative']['commit_attempts']==account['cumulative']['commit_successes']==0
save('failure_analysis.json',{'observed_outer_failure':read(OUT/'stop.json')['detail'],'observed_saved_phase':cp['phase'],
 'static_verified_defect':{'path':'checkpoint_v17.schema.json#/$defs/monitor_result/properties/candidate_id','v16_contract':old,'v17_contract':newid,'probe_literal':'synth_1','old_accepts':True,'new_rejects':True},
 'causal_assessment':'The new blanket candidate_id restriction incorrectly reaches the unchanged kernel result box item ID. Saved selected checkpoint and test-double call are observed. First MONITORED checkpoint rejection is inferred from the source and schema; the subsequent events/3 error is the observed traceback. The in-memory MONITORED/terminal event was not saved, and is not reconstructed as runtime evidence.',
 'archived_publication':{'mappings':len(side['audit']['publication']['record']['ordered_mappings']),'blobs':len(blobs),'validation_counts':side['audit']['publication']['record']['validation_counts'],'sizes':[c['oriented_size_mm'] for c in side['bundle']['physical_candidates']]},
 'monitor_entries':account['cumulative']['monitor_entries'],'actual_test_double_calls':len(calls),'actual_commit_attempts':0,'actual_commit_successes':0,'real_kernel_LP_freeze_model_calls':0,'retries':0,'remaining_E_jobs':7,'R_runs':0,'unrun_gates':['new-backend publication','second integer box','float full jobs','saved recovery','runtime X','old H behavior','strong completion behavior'],'status':'FAIL_STOPPED_PENDING_QA'})
identity=sha(json.dumps(current,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
save('source_manifest.json',{'files':current,'source_identity':identity,'source_files':len(current),'changed_existing':changed,'new':new,'baseline_identity':base['source_identity']})
save('static_verification.json',{'status':'PASS_STATIC_BYTES_AND_SCHEMA_SYNTAX_ONLY','protected_files_checked':len(protected),'old_schemas_unchanged':True,'changed_python_AST':'PASS','new_schema_Draft202012_syntax':'PASS','old_delivery_and_QA_manifests':'PASS','runtime_acceptance':'FAIL_STOPPED','production_imports_in_this_checker':0})
print('PASS static bytes/AST/schema syntax; confirmed monitor_result item-ID schema defect; runtime FAIL retained, no replay')
