"""Post-stop read-only source/saved-fact analysis, standard library only.
No project imports, rerun, shadow physics, monitor, transition or resume.
"""
import ast,hashlib,json,re,subprocess
from pathlib import Path
OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01')
def read(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(v):return sha(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
base=read(OUT/'baseline_receipt.json');source=read(OUT/'source_manifest.json');src=Path('semantic_pallet_planner/src/semantic_pallet_planner')
actual={str(f.relative_to(src)):sha(f.read_bytes()) for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
assert actual==source['files'] and digest(actual)==source['source_identity']
assert [k for k,h in actual.items() if h!=base['files'][k]]==['jev_select/schemas/checkpoint_v17.schema.json']
before=read(OUT/'checkpoint_v17.before.schema.json');after=read(src/'jev_select/schemas/checkpoint_v17.schema.json');copy=json.loads(json.dumps(before));copy['$defs']['monitor_result']['properties']['candidate_id'].pop('pattern');assert copy==after
assert after['$defs']['monitor_result']==read(src/'jev_select/schemas/checkpoint_v16.schema.json')['$defs']['monitor_result']
for row in base['manifests']:
 m=Path(row['manifest']);assert sha(m.read_bytes())==row['sha256']
 for r in read(m)['files']:
  raw=subprocess.check_output(['git','show',row['navigation_revision']+':'+r['path']]) if Path(r['path']).name=='README.md' and 'source_snapshot' not in r['path'] else Path(r['path']).read_bytes()
  assert sha(raw)==r['sha256'] and len(raw)==r['size_bytes']
episode=read(OUT/'E/jobs/J00/episode.json');account=read(OUT/'E/jobs/J00/accounting.json');run=read(OUT/'E/run.json');calls=read(OUT/'call_accounting.json');cp=episode['checkpoint']
assert cp['phase']=='TERMINATED' and cp['reason']=='ALL_ITEMS_PLACED' and len(cp['state']['placed_items'])==2
assert run['rows'][0]['status']=='COMPLETE' and all(r['status']=='NOT_RUN' for r in run['rows'][1:])
assert account['cumulative']=={'selector_calls':1,'singleton_executions':1,'monitor_entries':2,'monitor_reuses':0,'commit_attempts':2,'commit_successes':2}
assert account['invocations'][-1]['status']=='RETURNED'
assert calls['R1_E_monitors']==2 and calls['E_cumulative']==3 and calls['R1_R_monitors']==calls['R1_X_H_monitors']==0
schema_roles=[];blob_count=0
for event in episode['events']:
 if event['event']!='PLACE':continue
 candidate=next(x for x in event['bundle']['physical_candidates'] if x['candidate_id']==event['selection']['selected_candidate_id'])
 box=event['monitor']['result']['candidate_id'];assert box==candidate['pick_item_id']
 assert re.fullmatch(r'GP5N3_[0-9a-f]{64}',candidate['candidate_id'])
 assert event['action']==event['proposed_action'] and event['monitor']['status']=='STABLE'
 chosen_item=next(x['item'] for x in event['before']['pending_items'] if x['item']['item_id']==candidate['pick_item_id'])
 axes=('length','width','height') if candidate['pose']['yaw_deg']==0 else ('width','length','height')
 expected=[chosen_item['dimensions_mm'][k] for k in axes]
 assert candidate['oriented_size_mm']==expected and all(type(a) is type(b) for a,b in zip(candidate['oriented_size_mm'],expected))
 ref=event['geometry_ref'];raw=(OUT/'E/jobs/J00/blobs'/ref['sha256']).read_bytes();assert sha(raw)==ref['sha256'];artifact=json.loads(raw)
 for key,hexbytes in artifact['audit']['publication']['blobs'].items():
  raw=bytes.fromhex(hexbytes);assert sha(raw)==key and (OUT/'E/jobs/J00/blobs'/key).read_bytes()==raw;blob_count+=1
 schema_roles.append({'candidate_id':candidate['candidate_id'],'monitor_result_box_id':box,'oriented_size_mm':candidate['oriented_size_mm'],'yaw':candidate['pose']['yaw_deg']})
dims=read(OUT/'GP5_SYNTH_K02_INT.raw.json')['items'][0]['dimensions_mm'];assert list(dims.values())==[60,100,80]
assert cp['state']['placed_items'][0]['oriented_size_mm']==[dims[k] for k in ('length','width','height')]
stop=read(OUT/'stop.json');assert stop['group']=='E' and 'AssertionError' in stop['traceback']
for p in [OUT/'run_bounded_validation.py',OUT/'prepare_validation.py',Path('semantic_pallet_planner/tests/unit/test_geometry_native_schema_roles_r1.py')]:ast.parse(p.read_text())
save('failure_analysis.json',{'issue':'GP5-NUM-N1-R1-HARNESS-01','status':'OPEN_VALIDATION_HARNESS_DEFECT','production_J00':'COMPLETE_TWO_BOXES','suite_status':'FAIL_STOPPED_AFTER_J00','cause':'Validation assertion uses dimensions_mm.values(), whose canonical JSON key order is height,length,width. It compares [60,100,80] to valid oriented [100,80,60], ignoring named axis/yaw mapping.','observed_dictionary_key_order':list(dims),'observed_values_order':list(dims.values()),'observed_placement_size':cp['state']['placed_items'][0]['oriented_size_mm'],'correct_named_axis_saved_fact_check':'PASS_READ_ONLY_NO_REPLAY','traceback_ref':'stop.json','raw_E_results_note':'Harness catch overwrote its J00 status to TECHNICAL_FAILURE while completed summary remains true. Original production E/run.json and episode/accounting say COMPLETE/RETURNED. Raw files retained; normalized summary separates these statuses.','schema_fix_runtime_evidence':schema_roles,'monitors_new_E':2,'old_failed_E':1,'E_cumulative':3,'R_runs':0,'X_H_monitors':0,'remaining_E':'7_NOT_RUN','reruns':0,'scope':'Read saved facts only; do not claim R/new-backend/X/H/ADMIN acceptance'})
save('saved_verification.json',{'status':'PASS_SAVED_BYTES_AND_NAMED_AXIS_ANALYSIS_ONLY','source_identity':source['source_identity'],'source_files':len(actual),'production_diff':'one monitor_result candidate_id pattern removed; every other production file unchanged','old_manifests_members':sum(x['members'] for x in base['manifests']),'publication_blob_references_verified':blob_count,'production_J00_complete':True,'suite_harness_failure_confirmed':True,'no_production_imports':True,'no_rerun':True})
print('PASS saved bytes/source/single-field diff; J00 production COMPLETE, harness axis-order assertion FAIL; no replay')
