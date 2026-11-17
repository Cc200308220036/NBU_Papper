"""Independent stdlib identities and saved-action arithmetic only; no generation."""
from pathlib import Path
from fractions import Fraction
from decimal import Decimal
import hashlib,json,csv,collections,statistics,subprocess
O=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP4_20261117_01')
R=Path('semantic_pallet_planner/src/semantic_pallet_planner')
NAV='docs/03_阶段产出分析/几何规划模块/README.md'
HEAD='adbdf21ded76df9ba4704087841ccff6154b53b7'
POINTS=['P01_ffcfcc6e4af4','P02_f17e03ef6116','P03_81c78da5f3a7','P04_53bacc63aa29','P05_392be366b95d']
OLD='e2_original_v1';NEW='ems_surface_hybrid_v1'
def enc(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(v):return hashlib.sha256(v).hexdigest()
def digest(v):return sha(enc(v))
def read(p):return json.loads(Path(p).read_bytes())
def num(v):
 assert type(v) in (int,float)
 return Fraction(v) if type(v) is int else Fraction(Decimal(repr(v)))
def key(c):return (c['pick_item_id'],*(num(x) for x in c['oriented_size_mm']),c['pose']['yaw_deg'],*(num(c['pose'][x]) for x in ('x_mm','y_mm','z_base_mm')))
def auditkey(k):return (k[0],*(Fraction(x) for x in k[1:]))
def pointer(v,path):
 for k in path.lstrip('/').split('/') if path else []:
  k=k.replace('~1','/').replace('~0','~');v=v[int(k)] if type(v) is list else v[k]
 return v
def seal(v):assert v['record_digest']==digest({k:x for k,x in v.items() if k!='record_digest'})
src=read(O/'source_manifest.json')['files'];actual={p.relative_to(R).as_posix():sha(p.read_bytes()) for p in R.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(R).parts)}
assert actual==src==read('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_R1_20261117_01/source_manifest.json')['files'] and len(actual)==542
m=read(O/'delivery_manifest.json')
for row in m['files']:
 p=Path(row['path']);raw=p.read_bytes()
 if sha(raw)!=row['sha256'] and str(p)==NAV:raw=subprocess.run(['git','show',HEAD+':'+str(p)],check=True,capture_output=True).stdout
 assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'],str(p)
f=read(O/'freeze_manifest.json')
for row in f['files']:assert sha(Path(row['path']).read_bytes())==row['sha256']
assert read(O/'generation_started.json')['freeze_sha']==sha((O/'freeze_manifest.json').read_bytes())
plan=read(O/'comparison_plan.json');result=read(O/'comparison.json');summ=read(O/'generation_summary.json');orig=read(O/'historical/input_manifest.json')
assert plan['points']==POINTS==[s['point_id'] for s in summ['states']]==[s['point_id'] for s in result['states']]
assert result['state_denominator']==5 and result['item_denominator']==15 and summ['provider_calls']==10
rows=[];totals=collections.Counter();all_details=[];times={OLD:[],NEW:[]}
for point,summary,comp in zip(POINTS,summ['states'],result['states']):
 d=O/'states'/point;inputdir=O/'inputs'/point;snapshot=read(inputdir/'original_snapshot.json');provenance=read(inputdir/'public_provenance.json')
 original=next(p for p in orig['points'] if p['point_id']==point)
 assert sha((inputdir/'original_snapshot.json').read_bytes())==original['snapshot']['sha256']
 for item in provenance['field_provenance']:assert digest(pointer(snapshot,item['snapshot_pointer']))==item['value_digest']
 assert enc(read(d/'state.json'))==enc(snapshot['current_public_state']) and enc(read(d/'observation.json'))==enc(snapshot['public_observation'])
 common=read(d/'common_binding.json');admission=read(d/'common_admission.json');seal(common);seal(admission)
 nraw=(d/'B_native.json').read_bytes();graw=(d/'B_geometry.json').read_bytes()
 assert sha(nraw)==common['native_snapshot_sha256'] and sha(graw)==common['geometry_input_sha256']
 assert enc(json.loads(nraw)['current_state'])==enc(snapshot['current_public_state'])
 assert admission['common_input_digest']==digest(common) and admission['status']=='PASS'
 pools={};rawset=None;attempts=set();outcomes={};item_rows=[]
 for backend in (OLD,NEW):
  p=d/backend;cfg,b,a,ctx,body,outcome,tele=[read(x) for x in [O/'configs'/point/(backend+'.json'),p/'bundle.json',p/'audit.json',p/'context.json',p/'request.json',p/'outcome.json',p/'telemetry.json']]
  assert cfg['construction_only'] is True and cfg['version']=='jev_packaging_geometry_compare_v14'
  assert outcome['status']=='OK' and outcome['provider_calls']==1 and summary['backends'][backend]['status']=='OK'
  assert read(p/'generation_reserved.json')['config_digest']==digest(cfg)
  assert cfg['runtime_identity']['source_identity']==digest(src) and enc(cfg)==enc(a['config'])
  assert enc(a['common_binding'])==enc(common) and enc(a['common_admission'])==enc(admission)
  assert a['native_bytes_hex']==nraw.hex() and a['geometry_bytes_hex']==graw.hex()
  seal(a['backend_binding']);assert a['backend_binding']['config_digest']==digest(cfg)==ctx['local_binding']['config_digest']
  assert a['backend_binding']['candidate_backend']==b['candidate_backend']==backend
  assert digest(a)==b['geometry_audit_digest'] and digest(a['backend_binding'])==b['backend_binding_digest']
  pool=b['physical_candidates'];pools[backend]={key(c) for c in pool};assert len(pools[backend])==len(pool)<=48
  assert enc(pool)==enc(b['selectable_candidates']) and digest(pool)==b['physical_digest']==b['selectable_digest']
  assert all(x<=16 for x in collections.Counter(c['pick_item_id'] for c in pool).values())
  for c in pool:assert c['pose']['yaw_deg'] in (0,90)
  for fld,target in [('mapping_digest','display_mapping'),('model_state_digest','model_state'),('criteria_digest','criteria'),('request_body_digest','request_body')]:assert ctx['local_binding'][fld]==digest(ctx[target])
  assert enc(body)==enc(ctx['request_body']) and len(enc(body))==outcome['request_bytes']<=96000
  assert not any(w in enc(body).decode() for w in ('geometry_audit','e2_original_v1','ems_surface_hybrid_v1','SURFACE_CORNER','host','monitor','profile'))
  byid={c['candidate_id']:c for c in pool}
  for label,ref in ctx['display_mapping'].items():
   c=byid[ref['candidate_id']];assert ref['candidate_digest']==digest(c) and enc(ctx['criteria'][label]['pose'])==enc(c['pose'])
  all_details.extend((point,backend,key(c),c) for c in pool)
  times[backend].append(summary['backends'][backend]['provider_wall_s'])
  if backend==OLD:
   assert a['generation']['raw_valid_candidates']=='NOT_AVAILABLE_OLD_E2_INTERFACE'
   assert tele['cache_hits']==0 and tele['cache_misses']==3
   totals['old_projection']+=sum(len(x['public_enumerated_candidates']) for x in a['generation']['items'])
  else:
   assert tele['cache_supported'] is False and tele['cache_hits'] is None and tele['cache_misses'] is None
   raw=[r for i in a['generation']['audit']['items'] for r in i['raw_valid_candidates']];rawset={key(r['candidate']) for r in raw}
   assert len(rawset)==len(raw) and pools[NEW]<=rawset
   for item in a['generation']['audit']['items']:
    assert item['raw_valid_count']==len(item['raw_valid_candidates']) and item['enumeration_complete']
    assert item['coverage']['compressed_count']==item['raw_valid_count']-item['final_candidates']
    for row in item['unique_action_outcomes']:attempts.add(auditkey(row['action_key']));outcomes[auditkey(row['action_key'])]=row['outcomes']
    totals['unique_proposals']+=item['unique_actions'];totals['rejection_instances']+=sum(item['rejection_counts'].values())
   for row in raw:assert set(row['sources'])=={'EMS_STYLE_3D','SURFACE_CORNER'}
   totals['raw']+=len(rawset);totals['compressed']+=len(rawset-pools[NEW])
 x,y=pools[OLD],pools[NEW];i=x&y;oo=x-y;nn=y-x
 for field,ks in [('intersection',i),('OLD_ONLY',oo),('NEW_ONLY',nn)]:assert {auditkey(k) for k in comp['final_comparison'][field]}==ks
 assert comp['raw_raw_comparison'] is None and comp['raw_raw_status']=='NOT_AVAILABLE_OLD_FULL_RAW'
 assert not oo&rawset
 absent=oo-attempts;rejected=oo&attempts
 totals.update(old=len(x),new=len(y),intersection=len(i),old_only=len(oo),new_only=len(nn),old_only_absent_saved_proposal_keys=len(absent),old_only_saved_attempt_but_not_raw=len(rejected))
 rows.append({'point':point,'old':len(x),'raw':len(rawset),'new':len(y),'intersection':len(i),'old_only':len(oo),'new_only':len(nn),'old_only_absent_saved_proposal_keys':len(absent),'old_only_saved_attempt_but_not_raw':len(rejected),'attempted_old_only_outcomes':[{'key':[str(v) for v in k],'outcomes':outcomes[k]} for k in sorted(rejected)]})
assert all(totals[k]==v for k,v in {'old':220,'new':185,'intersection':52,'old_only':168,'new_only':133,'raw':204,'compressed':19,'old_projection':543,'unique_proposals':568,'rejection_instances':786}.items())
assert len(all_details)==405
for table,n in [('states.csv',5),('items.csv',15),('decomposition.csv',15),('action_details.csv',405),('timing_and_requests.csv',10)]:
 with (O/table).open() as f:assert len(list(csv.DictReader(f)))==n
for backend,vals in times.items():assert result['timing_aggregate'][backend]['median_seconds']==statistics.median(vals) and result['timing_aggregate'][backend]['max_seconds']==max(vals)
assert len(list((O/'figures').glob('*.png')))==5
print(json.dumps({'status':'PASS_INDEPENDENT_SAVED_SETS_ONLY','manifest_members':len(m['files']),'production_files':542,'production_unchanged':True,'states':5,'state_item_pairs':15,'provider_reservations':10,'rows':rows,'totals':dict(totals),'surface_only_raw':0,'source_rule':'all saved new raw have both EMS and surface; not a rerun ablation','final_action_details':405,'visual_inspection':'separate manual image review, not performed by script','production_imports':0,'candidate_generation':0,'execution_PCT_LP_models':0},ensure_ascii=False,indent=2))
