"""Stdlib saved-byte/set verification only. Never imports production or dispatches."""
import argparse,csv,hashlib,json,re,subprocess
from collections import Counter
from fractions import Fraction
from pathlib import Path
O=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP4_20261117_01')
R=Path('semantic_pallet_planner/src/semantic_pallet_planner')
REPORT=Path('docs/03_阶段产出分析/几何规划模块/几何候选器GP4五保存状态零执行候选比较交付_20261117_01.md')
a=argparse.ArgumentParser();a.add_argument('--sealed',action='store_true');args=a.parse_args()
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def enc(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(enc(v)).hexdigest()
def key(c):return (c['pick_item_id'],*(str(Fraction(str(v))) for v in c['oriented_size_mm']),str(c['pose']['yaw_deg']),*(str(Fraction(str(c['pose'][k]))) for k in ('x_mm','y_mm','z_base_mm')))
actual={p.relative_to(R).as_posix():sha(p) for p in R.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(R).parts)}
assert actual==read(O/'source_manifest.json')['files'] and len(actual)==542
f=read(O/'freeze_manifest.json')
for r in f['files']:assert sha(r['path'])==r['sha256'],r['path']
assert read(O/'generation_started.json')['freeze_sha']==sha(O/'freeze_manifest.json')
plan=read(O/'comparison_plan.json');result=read(O/'comparison.json');summary=read(O/'generation_summary.json')
assert plan['state_denominator']==result['state_denominator']==5 and result['item_denominator']==15
assert [r['point_id'] for r in result['states']]==plan['points']
assert summary['provider_calls']==10 and len(list((O/'states').glob('*/*/generation_reserved.json')))==10
old_manifest=read(O/'historical/input_manifest.json')
for p in old_manifest['points']:assert sha(O/'inputs'/p['point_id']/'original_snapshot.json')==p['snapshot']['sha256']
counts=Counter();old_cache=Counter();request_bytes=[]
for state in result['states']:
 p=state['point_id'];d=O/'states'/p;common=read(d/'common_binding.json');admission=read(d/'common_admission.json')
 assert sha(d/'B_native.json')==common['native_snapshot_sha256'] and sha(d/'B_geometry.json')==common['geometry_input_sha256']
 assert common['environment_digest']==digest(read(O/'environment.json'))
 assert admission['status']=='PASS' and admission['common_input_digest']==digest(common)
 pools={};raw=None
 for backend in plan['backends']:
  cfg=read(O/'configs'/p/(backend+'.json'));b,a,t,c=map(read,[d/backend/'bundle.json',d/backend/'audit.json',d/backend/'telemetry.json',d/backend/'context.json'])
  assert cfg['version']=='jev_packaging_geometry_compare_v14' and cfg['construction_only'] is True
  assert cfg['candidate_backend']==backend==b['candidate_backend']==a['backend_binding']['candidate_backend']
  assert cfg['runtime_identity']['source_identity']==digest(actual)
  assert digest(cfg)==a['backend_binding']['config_digest']==c['local_binding']['config_digest']
  assert enc(a['config'])==enc(cfg) and enc(a['common_binding'])==enc(common) and enc(a['common_admission'])==enc(admission)
  assert bytes.fromhex(a['native_bytes_hex'])==(d/'B_native.json').read_bytes() and bytes.fromhex(a['geometry_bytes_hex'])==(d/'B_geometry.json').read_bytes()
  assert a['backend_binding']['generator_config_digest']==cfg['generator_config_digest']==digest(read(O/'configs'/('generator_'+backend+'.json')))
  assert digest(a)==b['geometry_audit_digest'] and digest(a['backend_binding'])==b['backend_binding_digest']
  assert enc(b['physical_candidates'])==enc(b['selectable_candidates'])
  pools[backend]={key(x) for x in b['physical_candidates']}
  assert len(pools[backend])==len(b['physical_candidates'])<=48
  assert all(v<=16 for v in Counter(x['pick_item_id'] for x in b['physical_candidates']).values())
  assert all(x['pose']['yaw_deg'] in (0,90) for x in b['physical_candidates'])
  body=read(d/backend/'request.json');assert enc(body)==enc(c['request_body'])
  n=len(enc(body));assert n==state['backends'][backend]['request_bytes']<=96000;request_bytes.append(n)
  assert not any(word in enc(body).decode() for word in ('e2_original_v1','ems_surface_hybrid_v1','profile','host','monitor','geometry_audit','SURFACE_CORNER','EMS_STYLE_3D'))
  if backend=='e2_original_v1':
   assert a['generation']['raw_valid_candidates']=='NOT_AVAILABLE_OLD_E2_INTERFACE'
   assert t['cache_supported'] is True;old_cache.update(hits=t['cache_hits'],misses=t['cache_misses'])
  else:
   assert t['cache_supported'] is False and t['cache_hits'] is None and t['cache_misses'] is None
   rr=[r for it in a['generation']['audit']['items'] for r in it['raw_valid_candidates']];raw={key(r['candidate']) for r in rr}
   assert len(raw)==len(rr) and pools[backend]<=raw
   counts['raw']+=len(raw);counts['compressed']+=len(raw-pools[backend])
   counts['surface_only']+=sum('SURFACE_CORNER' in r['sources'] and 'EMS_STYLE_3D' not in r['sources'] for r in rr)
   for it in a['generation']['audit']['items']:
    assert it['enumeration_complete'] and it['raw_valid_count']==len(it['raw_valid_candidates'])
    assert it['coverage']['compressed_count']==it['raw_valid_count']-it['final_candidates']
 x,y=pools[plan['backends'][0]],pools[plan['backends'][1]];cmp=state['final_comparison']
 assert {tuple(v) for v in cmp['intersection']}==x&y and {tuple(v) for v in cmp['OLD_ONLY']}==x-y and {tuple(v) for v in cmp['NEW_ONLY']}==y-x
 assert state['raw_raw_comparison'] is None and state['raw_raw_status']=='NOT_AVAILABLE_OLD_FULL_RAW'
 counts.update(old=len(x),new=len(y),intersection=len(x&y),old_only=len(x-y),new_only=len(y-x))
 assert not ((x-y)&raw)
assert dict(counts)=={'old':220,'new':185,'intersection':52,'old_only':168,'new_only':133,'raw':204,'compressed':19,'surface_only':0}
assert old_cache=={'hits':0,'misses':15}
items=read(O/'decomposition.json');assert len(items)==15
assert sum(i['old_only_absent_new_raw'] for i in items)==168 and sum(i['old_only_removed_new_compression'] for i in items)==0
assert len(read(O/'action_details.json'))==405
for name,n in [('states.csv',5),('items.csv',15),('decomposition.csv',15),('action_details.csv',405),('timing_and_requests.csv',10)]:
 with (O/name).open() as stream:assert len(list(csv.DictReader(stream)))==n
assert len(list((O/'figures').glob('*.png')))==5
assert 'Ran 5 tests' in (O/'preflight_tests.log').read_text() and '\nOK\n' in (O/'preflight_tests.log').read_text()
# Frozen historical navigation snapshots, no mutable Git revision.
history=0
for name,rev in [('GEOM_CANDIDATES_GP3_N3_R1_20261117_01','b41fdb55f5857a54e4d426974660bd269fd1f107'),('GEOM_CANDIDATES_GP3_N3_R1_QA_20261117_01','735b669c3e496d893aed55bc5759927f4d396643')]:
 for row in read(Path('semantic_pallet_planner/outputs')/name/'delivery_manifest.json')['files']:
  p=Path(row['path']);raw=subprocess.check_output(['git','show',rev+':'+str(p)]) if p==REPORT.parent/'README.md' else p.read_bytes()
  assert hashlib.sha256(raw).hexdigest()==row['sha256'],str(p);history+=1
for p in (REPORT,REPORT.parent/'README.md'):
 for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),target
if args.sealed:
 m=read(O/'delivery_manifest.json');expected={p.as_posix() for p in O.rglob('*') if p.is_file() and p.name not in ('delivery_manifest.json','seal_verification.log')}
 expected|={REPORT.as_posix(),(REPORT.parent/'README.md').as_posix()};assert {v['path'] for v in m['files']}==expected
 for row in m['files']:
  p=Path(row['path']);assert sha(p)==row['sha256'] and p.stat().st_size==row['size_bytes'],str(p)
print(json.dumps({'status':'PASS_SAVED_BYTES_SETS_AND_FIXED_HISTORY_ONLY','sealed':args.sealed,'states':5,'items':15,'provider_reservations':10,'counts':dict(counts),'max_request_bytes':max(request_bytes),'figures':5,'historical_manifest_members':history,'production_imports':0,'generation_calls':0,'execution_calls':0,'model_calls':0,'PCT_LP_calls':0,'A03':'PARTIAL','GP5_GP6':'NOT_AUTHORIZED'}))
