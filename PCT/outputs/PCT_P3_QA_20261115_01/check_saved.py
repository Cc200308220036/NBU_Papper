# -*- coding: utf-8 -*-
"""P3 saved facts only. No Torch/planner imports, orders, gradients or LP."""
import hashlib,json,math,struct
from pathlib import Path
Q=Path(__file__).parent;D=Path('PCT/outputs/PCT_P3_20261115_01');RUN=D/'attempt_02'
def read(p):return json.loads(Path(p).read_text())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def dg(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]
def volume(items):return sum(math.prod(x['oriented_size_mm']) for x in items)
def main():
 man=read(D/'delivery_manifest.json');bad=[r['path'] for r in man['files'] if sha(r['path'])!=r['sha256']];assert not bad,bad
 identity=read(D/'identity.json');assert all(sha(p)==h for p,h in identity['final_source_sha256'].items())
 pre=read(RUN/'pre_execution_identity.json');assert all(sha(RUN/'source_snapshot'/p)==h for p,h in pre['source_sha256'].items())
 drift=[p for p,h in pre['source_sha256'].items() if sha(p)!=h];assert set(drift)==set(identity['execution_source_differences'])
 plan=read(RUN/'plan.json');assert plan['plan_digest']==dg({k:v for k,v in plan.items() if k!='plan_digest'})
 roots=[('diagnostic',Path(j['output'])) for j in plan['jobs']]+[('training',RUN/'training'/f'training_{i:02d}') for i in range(16)]
 rows=[];trajectories=[];totals={k:dict(decisions=0,candidate_actions=0,choices=0,monitors=0,commits=0,network_choices=0,kernel_calls=0) for k in ('diagnostic','training')}
 for mode,root in roots:
  h=read(root/'header.json');ep=read(root/'episode.json');t=h['task'];c=h['config'];summary=ep['summary'];state=ep['final_state'];events=ep['events']
  assert h['header_digest']==dg({k:v for k,v in h.items() if k!='header_digest'}) and c['p3_plan_digest']==plan['plan_digest']
  assert ep['checkpoint']['state']==state and ep['checkpoint']['events']==events and ep['checkpoint']['reason']=='STOP_NO_PHYSICAL_CANDIDATE'
  loading=summary['loading'];mass=sum(x['mass_kg'] for x in state['placed_items']);vol=volume(state['placed_items']);n=len(state['placed_items']);C=t['container'];cv=C['length_mm']*C['width_mm']*C['max_height_mm']
  assert loading['placed_items']==n==state['placed_count'] and loading['planned_items']==len(t['items'])
  assert math.isclose(loading['placed_mass_kg'],mass) and math.isclose(loading['placed_volume_mm3'],vol)
  assert math.isclose(loading['placed_mass_ratio'],mass/sum(x['mass_kg'] for x in t['items']))
  assert math.isclose(loading['placed_volume_ratio'],vol/sum(math.prod(x['dimensions_mm'].values()) for x in t['items']))
  assert math.isclose(summary['fixed_container_utilization'],vol/cv)
  counts=totals[mode];ts=[]
  for e in events:
   if e.get('bundle') is None:continue
   counts['decisions']+=1;counts['candidate_actions']+=len(e['bundle']['physical_candidates']);counts['choices']+=int(e['route']=='CHOICE_REQUIRED')
   s=e.get('selection');m=e.get('monitor')
   if not s:assert not m and e['action'] is None;continue
   assert s['local_binding_digest']==dg(e['context']['local_binding'])
   pool=e['bundle']['selectable_candidates'];chosen=next(x for x in pool if x['candidate_id']==s['selected_candidate_id'])
   mapping=e['context']['display_mapping'][s['selected_display_id']];assert dg(chosen)==mapping['candidate_digest']
   if m:
    counts['monitors']+=1;counts['kernel_calls']+=m['result']['kernel_calls']
    assert m['status']==m['result']['status']=='STABLE' and m['result_digest']==dg(m['result'])
    assert m['credential_digest']==dg({k:v for k,v in m.items() if k!='credential_digest'})
    assert m['binding']['candidate_digest']==dg(chosen) and m['binding']['selection_digest']==dg(s)
   if e['event']=='PLACE':counts['commits']+=1;assert m and e['action']==e['proposed_action']
   if h['model_binding'] is not None:
    r=read(root/'records'/(e['decision_id']+'.json'))
    assert r['record_digest']==dg({k:v for k,v in r.items() if k!='record_digest'}) and r['selection']==s and r['context_digest']==dg(e['context'])
    assert r['exact_candidate']==chosen and r['model_identity']==c['model_identity']
    o=r['output'];p=o['probabilities'];i=o['leaf_index'];num=len(pool)
    assert len(p)==16 and all(math.isfinite(x) and 0<=x<=1 for x in p) and abs(sum(p)-1)<1e-5 and p[num:]==[0.]*(16-num) and p[i]>0
    if c['p3_mode']=='diagnostic':assert i==p.index(max(p))
    counts['network_choices']+=int(e['route']=='CHOICE_REQUIRED')
    if mode=='training':ts.append(dict(reward=10*(volume(e['after']['placed_items'])-volume(e['before']['placed_items']))/cv,value=o['value'],probability=p[i],choice=e['route']=='CHOICE_REQUIRED'))
  assert counts['commits']>=n
  if mode=='training':assert math.isclose(sum(x['reward'] for x in ts),10*vol/cv,abs_tol=1e-8);trajectories.append(ts)
  rows.append(dict(mode=mode,job_id=h['job_id'],task=t['task_id'],method=c['selector'],placed=n,planned=len(t['items']),volume_ratio=loading['placed_volume_ratio'],mass_ratio=loading['placed_mass_ratio'],reason=ep['checkpoint']['reason']))
 # Recompute n-step target and scalar losses from collection values/probabilities.
 update_checks=[]
 for update in (1,2):
  saved=read(RUN/'training'/f'update_{update}.json');batch=trajectories[(update-1)*8:update*8];values=[];targets=[];probs=[]
  segments=[]
  for ts in batch:
   target=[None]*len(ts);sg=[]
   for start in range(0,len(ts),5):
    end=min(start+5,len(ts));boot=ts[end]['value'] if end<len(ts) else 0;v=boot
    for i in range(end-1,start-1,-1):v=f32(f32(ts[i]['reward'])+v);target[i]=v
    sg.append(dict(start=start,end_exclusive=end,actual_length=end-start,bootstrap=boot))
   segments.append(sg);targets.extend(target);values.extend(x['value'] for x in ts);probs.extend(x['probability'] for x in ts)
  assert segments==saved['segments'] and len(values)==saved['transition_count'] and saved['choice_count']==len(values)
  assert all(abs(x-y)<1e-6 for x,y in zip(probs,saved['probabilities']))
  actor=sum(-f32(t-v)*math.log(p) for t,v,p in zip(targets,values,probs))/len(values)
  critic=sum(f32(t-v)**2 for t,v in zip(targets,values))/len(values)
  assert abs(actor-saved['actor_loss'])<1e-4 and abs(critic-saved['critic_loss'])<1e-4 and abs(actor+critic-saved['loss'])<1e-4
  assert saved['parameters_changed'] and saved['before']!=saved['after'] and saved['optimizer_rng_roundtrip']=='EXACT'
  snapshot=read(RUN/'training/snapshots'/f'update_{update}'/'snapshot.json')
  assert snapshot['record_digest']==dg({k:v for k,v in snapshot.items() if k!='record_digest'})==saved['snapshot_record_digest']
  assert sha(RUN/'training/snapshots'/f'update_{update}'/'state.pt')==snapshot['state_sha256']
  update_checks.append(dict(update=update,transitions=len(values),recomputed_actor=actor,recomputed_critic=critic,recomputed_loss=actor+critic,recorded_loss=saved['loss'],snapshot_bytes='MATCH',optimizer_rng_restore='ARCHIVED_ASSERTION_NOT_RERUN'))
 audit=read(D/'final_saved_audit.json');assert audit['status']=='PASS_SAVED_FACTS' and not audit['failures']
 for mode,key in [('diagnostic','matrix_totals'),('training','training_totals')]:
  a=audit[key]['actual_calls'];b=totals[mode]
  assert b['monitors']==a['monitor_calls'] and b['commits']==a['commits'] and b['candidate_actions']==a['candidate_actions'] and b['network_choices']==a['policy_choice_forwards']
 prefix_checks=[]
 for r in read(D/'prefix_recovery/results.json'):
  root=D/'prefix_recovery'/r['phase'];source=RUN/'jobs'/r['source_job'];paths=sorted((root/'journal').glob('*.json'))
  for i in range(r['prefix_last_sequence']+1):assert (root/'journal'/f'{i:08d}.json').read_bytes()==(source/'journal'/f'{i:08d}.json').read_bytes()
  new=[read(p)['checkpoint'] for p in paths[r['prefix_last_sequence']+1:]]
  assert sum(c['phase']=='MONITORED' for c in new)==r['counts']['monitor_calls'] and sum(c['phase']=='COMMITTED' for c in new)==r['counts']['commits']
  assert dg(read(paths[-1])['checkpoint'])==r['tail_checkpoint_digest'] and read(paths[-1])['checkpoint']['phase']=='READY'
  prefix_checks.append({'phase':r['phase'],'counts':r['counts'],'prefix_bytes':'MATCH'})
 result=dict(status='PASS_SAVED_P3_ONLY',delivery_files=len(man['files']),final_source_files=len(identity['final_source_sha256']),execution_source_files=len(pre['source_sha256']),execution_vs_final_differences=drift,jobs=rows,totals=totals,updates=update_checks,prefix_recovery=prefix_checks,not_run=['orders','candidates','LP','network forward','training update','optimizer restoration','current final runtime business tests','installation','remote requests'])
 (Q/'saved_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k not in ('jobs','prefix_recovery','execution_vs_final_differences')},ensure_ascii=False))
if __name__=='__main__':main()
