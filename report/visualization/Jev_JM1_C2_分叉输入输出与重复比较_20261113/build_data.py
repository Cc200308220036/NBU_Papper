"""Saved-only visualization exporter. No production imports or model/solver execution."""
import base64, hashlib, json, math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
WEB=OUT/'web'
C2=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_C2_REAL_SUFFIXES_20261113_01'
C1=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_C1_REAL_BASELINES_20261112_01'
sources={}
def mapped(path):
 p=Path(path)
 if p.is_absolute():
  try:p=ROOT/p.relative_to('/home/cyw/NBU_Papper')
  except ValueError:pass
 else:p=ROOT/p
 p=p.resolve();p.relative_to(ROOT);return p

def read(path):
 p=mapped(path);raw=p.read_bytes();sources[str(p.relative_to(ROOT))]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
def refread(ref):
 d=read(ref['path']);assert sources[str(mapped(ref['path']).relative_to(ROOT))]==ref['sha256'];return d

def src(path,pointer=''):
 p=mapped(path);return dict(path=str(p.relative_to(ROOT)),pointer=pointer,sha256=sources[str(p.relative_to(ROOT))])
def write(path,d):path.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def js(path,name,d):path.write_text(name+'='+json.dumps(d,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')+';\n')
def state(s):return {k:s[k] for k in ['container','placed_count','arrival_count','end_of_stream','buffer_capacity','placed_items','pending_items'] if k in s}

def main():
 (WEB/'data').mkdir(parents=True,exist_ok=True)
 ledger=read(C2/'branch_ledger.json')['jobs'];index=[];totals=dict(jobs=0,pairs=0,requests=0,commits=0,forced=0,events=0,stages=0);checks=[]
 for pf in sorted((C2/'points').glob('*.json')):
  point=read(pf);pid=point['point_id'];cond=point['public_conditions'];prefix=refread(cond['public_prefix_ref']);pool=refread(cond['pool_ref']);pubpath=mapped(cond['pool_ref']['path']).parent/'public.json';public=read(pubpath)
  evidence=public['probability_evidence'];parent_response=json.loads(base64.b64decode(evidence['raw_base64']));public['parent_probabilities']=parent_response['answers']['next_action']['probabilities']
  runs=[];pairs=[refread(x) for x in point['comparisons']]
  for j in [x for x in ledger if x['point_id']==pid]:
   storage=mapped(j['storage_root']);epath=storage/'episode.json';ep=read(epath);act=read(storage/'activation.json');head=refread(j['checkpoint_head_ref']);initial=act['initial_checkpoint']['state'];assert state(initial)==state(ep['events'][0]['before'])
   rows=refread(j['raw_requests_ref'])['requests'];requestmap={x['decision_id']:x for x in rows};events=[]
   for i,e in enumerate(ep['events']):
    context=e.get('context') or {};selection=e.get('selection') or {};bundle=e.get('bundle') or {};mapping=context.get('display_mapping',{});physical={x['candidate_id']:x for x in bundle.get('physical_candidates',[])};cs=[]
    for label,m in sorted(mapping.items()):
     c=physical[m['candidate_id']];cs.append(dict(label=label,**c))
    req=rows and requestmap.get(e.get('decision_id'));response=None
    if req:
     raw=base64.b64decode(req['transport']['raw_body_b64']);assert hashlib.sha256(raw).hexdigest()==req['transport']['raw_sha256'];response=raw.decode('utf-8');assert context['request_body']['state']['memories']==[]
     contextpath=storage/'ledger/contexts'/f"{e['decision_id']}.json";saved=read(contextpath);assert saved==context
    before=state(e['before']);after=state(e['after']);old={x['item_id'] for x in before['placed_items']};new=[x['item_id'] for x in after['placed_items'] if x['item_id'] not in old]
    assert len(new)==(1 if e['event']=='PLACE' else 0)
    events.append(dict(event=e['event'],decision_id=e.get('decision_id'),reason=e.get('reason'),before=before,after=after,new_ids=new,selection=selection,candidates=cs,context=context,response=response,transport={k:v for k,v in req['transport'].items() if k not in ['raw_body_b64']} if req else None,monitor=e.get('monitor'),generation_counts=bundle.get('generation_counts'),source=src(epath,f'/events/{i}')))
   m=j['metrics'];placed=ep['final_state']['placed_items'];assert len(placed)==m['placed_items'];assert math.isclose(sum(x['mass_kg'] for x in placed),m['placed_mass_kg'],abs_tol=1e-8)
   volume=sum(math.prod(x['oriented_size_mm']) for x in placed);assert volume==m['placed_volume_mm3'];assert sum(x['event']=='PLACE' for x in events)==m['commits'];assert len(rows)==m['requests'];assert events[0]['selection']['source']=='FORCED_FROM_FROZEN_POOL'
   assert events[0]['selection']['selected_candidate_id']==j['candidate_id']
   final=head['sequence'];stagefiles=sorted((storage/'stages').glob('*.json'));assert len(stagefiles)==final
   # Stage data is read once for identity; never concatenate cumulative events.
   previous=hashlib.sha256(json.dumps(act,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
   for sf in stagefiles:
    stage=read(sf)
    if previous is not None:assert stage['previous_digest']==previous
    assert stage['record_digest']==hashlib.sha256(json.dumps({k:v for k,v in stage.items() if k!='record_digest'},ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    previous=hashlib.sha256(json.dumps(stage,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
   assert previous==head['digest']
   assert read(stagefiles[-1])['checkpoint']==ep['checkpoint']
   run=dict(job_id=j['job_id'],slot=j['repeat_slot'],kind=j['branch_kind'],action=j['exact_action'],label=j['forced_label'],candidate_id=j['candidate_id'],metrics=m,initial=state(initial),events=events,final=state(ep['final_state']),reason=j['reason'],status=j['status'],source=src(epath),stage_head=src(storage/'checkpoint_head.json'),stage_count=final)
   runs.append(run);totals['jobs']+=1;totals['requests']+=len(rows);totals['commits']+=m['commits'];totals['forced']+=m['forced_actions'];totals['events']+=len(events);totals['stages']+=final
   checks.append(dict(job_id=j['job_id'],state_metrics_actions_requests='PASS',stage_chain='PASS',events=len(events)))
  for pair in pairs:
   a=next(x for x in runs if x['job_id']==pair['alternative_job']);b=next(x for x in runs if x['job_id']==pair['reference_job']);assert a['initial']==b['initial'];assert a['events'][0]['candidates']==b['events'][0]['candidates']
   for key in ['placed_volume_ratio','placed_items','placed_mass_kg','actual_height_mm','envelope_utilization']:assert math.isclose(a['metrics'][key]-b['metrics'][key],pair['evaluation']['delta'][key],abs_tol=1e-8)
  totals['pairs']+=len(pairs)
  data=dict(version='jm_c2_visualization_v1',point=point,prefix=prefix,pool=pool,public=public,runs=runs,pairs=pairs,source=src(pf));js(WEB/'data'/f'{pid}.js','window.CASES["'+pid+'"]',data)
  index.append(dict(id=pid,task=point['task_id'],placed=cond['placed_count'],kind=cond['intervention'],labels=point['labels'],grade=point['evidence_grade'],repeat=point['repeat_registered'],action_reference=cond['exact_reference_action'],action_alternative=cond['exact_alternative_action']))
 assert totals==dict(jobs=18,pairs=9,requests=57,commits=75,forced=18,events=168,stages=450)
 js(WEB/'index-data.js','window.INDEX',dict(points=index,totals=totals,denominators=read(C2/'full_denominators.json'),source_support=read(C2/'source_and_start_support.json'),experience=read(C2/'experience_input_readiness.json')))
 write(OUT/'source_manifest.json',dict(version='jm_c2_visualization_sources_v1',files=sources));(OUT/'qa').mkdir(exist_ok=True);write(OUT/'qa/data_checks.json',dict(status='PASS',checks=checks,totals=totals,scope='saved byte hashes, stage chain references, exact actions, initial pairs, loading metrics and stored deltas; no model/physics execution'))
 print(json.dumps(totals))
if __name__=='__main__':main()
