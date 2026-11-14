"""Saved-fact QA only. No planner imports, candidate rebuilding, orders or LP.
Reads archived inputs/results, current bytes, and recomputes arithmetic/digests.
"""
import hashlib,json,math,subprocess
from collections import Counter
from pathlib import Path
Q=Path(__file__).parent;D=Path('PCT/outputs/PCT_P1_B_20261114_01')
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dg(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def main():
 identity=read(D/'identity.json');manifest=read(D/'delivery_manifest.json')
 mismatches=[r['path'] for r in manifest['files'] if sha(r['path'])!=r['sha256']]
 sources=[p for p,h in identity['source_configuration_schema_sha256'].items() if sha(p)!=h]
 old=read(D/'final_verification/legacy_resources.json')['resources']
 assert all(sha(r['path'])==r['baseline_sha256']==r['actual_sha256'] for r in old)
 assert not mismatches and not sources,(mismatches,sources)
 rows=[];selected_total=0;committed_total=0;numeric=[]
 for record in read(D/'case_index.json')['rows']:
  path=Path(record['path']);ep=read(path);root=path.parent;t=read(root/'task.json');c=read(root/'config.json');binding=read(root/'execution.json')
  assert binding['task_digest']==dg(t) and binding['config_digest']==dg(c)
  assert c['runtime_identity']['task_identity']==dg(t)
  assert c['stability_monitor']['algorithm']=='pct_exact_pose_network_v3' and c['stability_monitor']['enabled'] is True
  assert c['stability_monitor']==read(D/'final_verification/exact_freeze.json')
  st=ep['final_state'];placed=st['placed_items'];loading=ep['summary']['loading']
  assert len(t['items'])<=3 and loading['planned_items']==len(t['items'])
  assert loading['placed_items']==len(placed)==st['placed_count']
  assert math.isclose(loading['placed_mass_kg'],sum(x['mass_kg'] for x in placed))
  assert math.isclose(loading['placed_volume_mm3'],sum(math.prod(x['oriented_size_mm']) for x in placed))
  stages=[read(p) for p in sorted((root/'stages').glob('*.json'))]
  for cp in stages:
   assert cp['record_digest']==dg({k:v for k,v in cp.items() if k!='record_digest'})
  events=[e for e in ep['events'] if e.get('decision_id')]
  successful=0;statuses=[]
  for event in events:
   did=event['decision_id'];m=event.get('monitor');sel=event.get('selection')
   phases=[(i,cp) for i,cp in enumerate(stages) if cp.get('pending_event') and cp['pending_event']['decision_id']==did]
   def first(phase):return next((i for i,cp in phases if cp['phase']==phase),None)
   if m:
    selected_total+=1;statuses.append(m['status']);assert sel and event['proposed_action']
    assert first('DECISION_READY')<first('SELECTED')<first('MONITORED')
    assert m['result_digest']==dg(m['result']) and m['credential_digest']==dg({k:v for k,v in m.items() if k!='credential_digest'})
    expected={'state_digest':dg(event['before']),'candidate_digest':event['context']['display_mapping'][sel['selected_display_id']]['candidate_digest'],'action_digest':dg(event['proposed_action']),'selection_digest':dg(sel),'context_digest':dg(event['context']),'bundle_digest':dg(event['bundle']),'decision_id':did,'config_digest':dg(c),'runtime_identity':c['runtime_identity']}
    assert m['binding']==expected
    if m['status']!='STABLE':assert event['before']==event['after'] and event['action'] is None
    if event['action'] is not None:
     assert m['status']=='STABLE' and event['action']==event['proposed_action']
     assert first('MONITORED')<first('COMMITTED');successful+=1
    for obj,field in [('display_mapping','mapping_digest'),('criteria','criteria_digest'),('model_state','model_state_digest'),('request_body','request_body_digest')]:assert dg(event['context'][obj])==event['context']['local_binding'][field]
   if event['event']=='PLACE':assert m and m['status']=='STABLE'
  assert successful==len(placed)
  assert ep['checkpoint']['reason']==record['reason'] and statuses==record['statuses']
  committed_total+=successful
  rows.append({'path':str(path),'kind':record['evidence_kind'],'reason':record['reason'],'planned':len(t['items']),'placed':len(placed),'statuses':statuses,'stage_count':len(stages)})
 # Independent force balance arithmetic on saved input/forces (no solver).
 numpath=D/'numeric_recheck/test_real_kernel_boundaries_and_residuals/real_kernel.json'
 for r in read(numpath):
  value=r['result'];res={'case':r['name'],'status':value['status']}
  if r['name']=='stable':
   boxes=[{'item_id':'ground','mass_kg':1,'bottom_center_mm':[0,0,0]},r['input']]
   reactions=value['diagnostics']['reactions'];per=[]
   for b in boxes:
    outgoing=[x for x in reactions if x['upper']==b['item_id']];incoming=[x for x in reactions if x['lower']==b['item_id']]
    mass=math.fsum(x['mass_kg'] for x in outgoing)-b['mass_kg']-math.fsum(x['mass_kg'] for x in incoming)
    moments=[math.fsum(x['mass_kg']*x['point_mm'][a] for x in outgoing)-b['mass_kg']*(b['bottom_center_mm'][a]+[500,400][a])-math.fsum(x['mass_kg']*x['point_mm'][a] for x in incoming) for a in (0,1)]
    assert abs(mass)<1e-8 and max(map(abs,moments))<1e-5
    per.append({'item_id':b['item_id'],'mass_residual_kg':mass,'moment_residual_kg_mm':moments})
   assert all(x['mass_kg']>=0 and math.isfinite(x['mass_kg']) for x in reactions)
   res['independently_recomputed']=per
  numeric.append(res)
 result={'status':'PASS_SAVED_FACTS_ONLY','source_hash_count':len(identity['source_configuration_schema_sha256']),'source_mismatches':sources,'delivery_file_count':len(manifest['files']),'delivery_mismatches':mismatches,'old_resources':len(old),'episodes':len(rows),'selected_monitor_records':selected_total,'commits':committed_total,'rows':rows,'numeric':numeric,'developer_test_counts':{n:json.loads(read(D/'final_verification'/n)['stdout']) for n in ['p1b_tests.json','p1a_regression.json']},'not_run_this_QA':['order','candidate generation','LP','developer aggregate validator','unit business tests','installation','model requests']}
 (Q/'saved_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k not in ['rows','numeric','developer_test_counts']},ensure_ascii=False))
if __name__=='__main__':main()
