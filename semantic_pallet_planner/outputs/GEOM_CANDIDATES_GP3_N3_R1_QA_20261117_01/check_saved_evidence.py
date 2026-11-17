"""Independent saved-fact and identity checks only. No production calls/imports."""
from pathlib import Path
import hashlib,json,subprocess,collections
O=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_R1_20261117_01')
BASE=Path('semantic_pallet_planner/outputs')
R=Path('semantic_pallet_planner/src/semantic_pallet_planner')
NAV='docs/03_阶段产出分析/几何规划模块/README.md'
HEAD='b41fdb55f5857a54e4d426974660bd269fd1f107'
def enc(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(v):return hashlib.sha256(v).hexdigest()
def digest(v):return sha(enc(v))
def read(p):return json.loads(p.read_bytes())
def blob(rev,p):return subprocess.run(['git','show',rev+':'+p],check=True,capture_output=True).stdout
m=read(O/'delivery_manifest.json')
for x in m['files']:
 p=Path(x['path']);raw=p.read_bytes()
 if sha(raw)!=x['sha256'] and str(p)==NAV:raw=blob(HEAD,str(p))
 assert sha(raw)==x['sha256'] and len(raw)==x['size_bytes'],str(p)
s=read(O/'source_manifest.json');before=read(O/'before_source_manifest.json')['files'];mid=read(O/'after_iteration_01_source_manifest.json')['files']
actual={p.relative_to(R).as_posix():sha(p.read_bytes()) for p in R.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(R).parts)}
assert actual==s['files'] and len(actual)==542
assert before==read(BASE/'GEOM_CANDIDATES_GP3_N3_20261117_01/source_manifest.json')['files']
assert set(actual)==set(before)==set(mid)
changed=sorted(k for k in actual if actual[k]!=before[k]);assert changed==['jev_select/episode.py','jev_select/geometry_execution.py']
for n in changed:
 assert sha((O/'source_snapshot'/n).read_bytes())==actual[n]
 assert sha((O/'before_source'/Path(n).name).read_bytes())==before[n]
 assert sha((O/'after_iteration_01_source'/Path(n).name).read_bytes())==mid[n]
rows=[];phases=blobs=0
for stage,src,behavior in [('before',before,'before_behavior.json'),('after_iteration_01',mid,'after_iteration_01_behavior.json'),('after',actual,'after_behavior.json')]:
 for row in read(O/behavior):
  p=O/stage/row['case'];cfg,t,cp,counts=[read(p/n) for n in ('config.json','task.json','failure_checkpoint.json','counts.json')]
  assert digest(src)==row['source_identity']==cfg['runtime_identity']['source_identity']
  assert digest(cfg)==row['config_digest']==cp['config_digest']==cp['execution_binding']['config_digest']
  assert digest(t)==row['fixture_digest']==cp['task_digest']==cfg['fixture_task_digest']
  assert cp['record_digest']==digest({k:v for k,v in cp.items() if k!='record_digest'})
  assert enc(read(p/'failure_result.json')['checkpoint'])==enc(cp)
  for name in ('production_phases.json','recovery_phases.json'):
   for saved in read(p/name):
    assert saved['record_digest']==digest({k:v for k,v in saved.items() if k!='record_digest'})
    assert saved['config_digest']==digest(cfg) and enc(saved['runtime_identity'])==enc(cfg['runtime_identity'])
    phases+=1
  for f in (p/'durable/blobs').iterdir():assert sha(f.read_bytes())==f.name;blobs+=1
  def get(ref):
   raw=(p/'durable/blobs'/ref['sha256']).read_bytes();assert sha(raw)==ref['sha256'];return raw
  ev=cp['pending_event'] if row['case']=='evaluation_failure' else cp['events'][-1]
  side=json.loads(get(ev['geometry_ref']));i=json.loads(get(side['input']))
  nraw,graw=get(i['native']),get(i['geometry'])
  assert enc(side['bundle'])==enc(ev['bundle']) and enc(side['audit']['config'])==enc(cfg)
  assert digest(side['audit'])==ev['bundle']['geometry_audit_digest']
  assert side['audit']['native_bytes_hex']==nraw.hex() and side['audit']['geometry_bytes_hex']==graw.hex()
  assert sha(nraw)==i['binding']['native_snapshot_sha256'] and sha(graw)==i['binding']['geometry_input_sha256']
  assert enc(json.loads(nraw)['current_state'])==enc(ev['before'])
  mon=ev['monitor'];assert mon['status']=='STABLE' and mon['result']['diagnostics']['TEST_DOUBLE'] is True and mon['result']['kernel_calls']==0
  assert mon['credential_digest']==digest({k:v for k,v in mon.items() if k!='credential_digest'})
  assert mon['binding']['state_digest']==digest(ev['before']) and mon['binding']['action_digest']==digest(ev['proposed_action'])
  assert enc(counts['recovery'])==enc(row['recovery'])
  delta={k:counts['after_resume'][k]-counts['before_resume'][k] for k in counts['after_resume']}
  assert delta==row['recovery']['delta']
  if row['case']=='evaluation_failure':
   assert cp['phase']=='COMMITTED' and cp['reason']=='EVALUATION_ERROR'
   assert cp['state']['placed_count']==1 and enc(cp['state'])==enc(ev['after'])
   assert ev['event']=='PLACE' and ev['reason'] is None and ev['error']['code']=='EVALUATION_ERROR'
   assert ev['business_after'] is None and ev['reference_after'] is None
  else:
   assert cp['phase']=='TERMINATED' and cp['pending_event'] is None and cp['state']['placed_count']==0
   assert enc(cp['state'])==enc(ev['before'])==enc(ev['after']) and ev['action'] is None
   assert ev['event']=='COMMIT_FAILURE'
   if stage!='before':assert cp['reason']==ev['reason']==ev['error']['code']=='GEOMETRY_COMMIT_TECHNICAL_ERROR'
  if stage=='before':
   assert row['recovery']['status']=='RECOVERY_REJECTED_FAIL'
   log=(p/'recovery_failure_traceback.log').read_text();assert row['recovery']['error'] in log
  else:
   assert row['recovery']['status']=='RESTORED' and all(delta[k]==0 for k in ('generation','selection','monitor','commit'))
   assert delta['evaluation']==int(row['case']=='evaluation_failure')
   restored=read(p/'restored_result.json');assert enc(restored['final_state'])==enc(cp['state'])
   assert restored['summary']['placed_items']==int(row['case']=='evaluation_failure')
   if row['case']=='evaluation_failure':assert sum(e['event']=='PLACE' for e in restored['events'])==1
   else:
    for field in ('placed_items','placed_mass_kg','placed_item_ratio','placed_volume_ratio','placed_mass_ratio'):assert restored['summary'][field]==0
    assert len(restored['final_state']['pending_items'])==1
  rows.append({'stage':stage,'case':row['case'],'source':row['source_identity'],'recovery':row['recovery']})
b,a=read(O/'before_behavior.json'),read(O/'after_behavior.json')
assert len(b)==len(a)==2
for x,y in zip(b,a):assert x['case']==y['case'] and x['fixture_digest']==y['fixture_digest'] and x['fault']==y['fault'] and x['source_identity']!=y['source_identity']
neg=read(O/'negative_checks.json');assert len(neg)==25 and all(r['result']=='REJECTED' for r in neg)
assert len({(x['case'],x['mutation']) for x in neg})==25
# Read-only qualification for proposed GP4 scope: original five public snapshots.
gp0=BASE/'GEOM_CANDIDATES_GP0_20261116_01';inventory=read(gp0/'input_manifest.json');points=[]
for x in inventory['points']:
 p=Path(x['snapshot']['path']);raw=p.read_bytes();assert sha(raw)==x['snapshot']['sha256'];v=json.loads(raw)
 assert 'current_public_state' in v and 'public_observation' in v
 points.append({'point_id':x['point_id'],'snapshot':str(p),'sha256':sha(raw),'declaration':x['status'],'local_check':'raw hash and public fields only; no current runtime comparability test'})
assert len(points)==5 and [p['point_id'] for p in points]==inventory['fixed_point_ids']
print(json.dumps({'status':'PASS_SAVED_FACTS_ONLY','manifest_members':len(m['files']),'production_files':542,'changed':changed,'unchanged':540,'source_bound_case_records':rows,'phase_records':phases,'blob_file_copies':blobs,'negative_records':25,'GP4_public_inputs':points,'production_imports':0,'candidate_generation':0,'loop_recovery_PCT_LP_models':0,'real_exact_v3_E2E':'NOT_RUN'},ensure_ascii=False,indent=2))
