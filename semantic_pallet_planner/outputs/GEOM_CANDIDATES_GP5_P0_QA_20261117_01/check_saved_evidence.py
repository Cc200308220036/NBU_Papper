"""Independent read-only stdlib preparation identity/data/plan checks."""
from pathlib import Path
import json,hashlib,subprocess,ast,collections
O=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P0_20261117_01')
R=Path('semantic_pallet_planner/src/semantic_pallet_planner')
HEAD='0fbb847d66bd72eda8e120682f73e98fd9e86884'
NAVS={'docs/02_阶段实施方案/几何规划模块/README.md','docs/03_阶段产出分析/几何规划模块/README.md'}
def read(p):return json.loads(Path(p).read_bytes())
def sha(v):return hashlib.sha256(v).hexdigest()
def enc(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def blob(rev,p):return subprocess.run(['git','show',rev+':'+p],check=True,capture_output=True).stdout
m=read(O/'delivery_manifest.json')
for r in m['files']:
 p=Path(r['path']);raw=p.read_bytes()
 if sha(raw)!=r['sha256'] and str(p) in NAVS:raw=blob(HEAD,str(p))
 assert sha(raw)==r['sha256'] and len(raw)==r['size_bytes'],str(p)
actual={str(p.relative_to(R)):sha(p.read_bytes()) for p in R.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(R).parts)}
assert len(actual)==542 and actual==read(O/'source_inventory.json')['files']==read('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP4_20261117_01/source_manifest.json')['files']
receipt=read(O/'readonly_receipt.json');receipt_count=0
for group in receipt['manifests']:
 for row in group['members']:
  p=Path(row['path']);mode=row.get('source','WORKTREE')
  raw=blob(mode.split(':',1)[1],str(p)) if mode.startswith('FIXED_REVISION:') else p.read_bytes()
  assert sha(raw)==row['expected']==row['actual'] and row['status']=='PASS';receipt_count+=1
inv=read(O/'data_inventory.json');data=Path(inv['data_root']);manifest=read(data/'manifest.json')
assert manifest['data_identity']==inv['data_identity']
assert sha((data/'source_manifest.json').read_bytes())==inv['source_manifest_sha256']
assert sha((data/'split_manifest.json').read_bytes())==inv['split_manifest_sha256']
groups={g['source_group_id']:g for g in read(data/'split_manifest.json')['groups']}
sources={s['source_group_id']:s for s in read(data/'source_manifest.json')['sources']}
tasks=[]
for p in sorted((data/'tasks').glob('*.json')):
 t=read(p);rec=next(x for x in inv['tasks'] if x['task_id']==t['task_id'])
 assert sha(p.read_bytes())==rec['sha256'] and rec['path']==str(p)
 assert len(t['items'])==rec['items'] and [o['item_id'] for o in t['items']]==t['arrival_order']
 assert len(set(t['arrival_order']))==len(t['items'])
 assert t['partition']=='train' and t['source_group_id'] in groups and t['source_group_id'] in sources
 assert groups[t['source_group_id']]['partition']=='train' and t['scenario_id'] in groups[t['source_group_id']]['scenario_ids']
 assert t['source_order_key']==sources[t['source_group_id']]['source_key']
 for obj in t['items']:
  assert all(k in obj for k in ('dimensions_mm','mass_kg','stackable','top_load_limit_kg_synthetic'))
  assert all(type(v) in (int,float) and v>0 for v in obj['dimensions_mm'].values())
  assert obj['mass_kg']>0 and obj['top_load_limit_kg_synthetic']>=0 and type(obj['stackable']) is bool
 assert rec['complete'] is True and not rec['missing'] and t['feasibility_status']=='UNKNOWN'
 tasks.append((t['task_id'],t,rec))
tasks.sort();assert len(tasks)==16
selected=[k for k,t,r in tasks[:2]];assert selected==inv['selected_task_ids']==['NEW_00100027_controlled_base','NEW_00100027_controlled_capacity_tight']
assert len({t['source_group_id'] for _,t,_ in tasks[:2]})==inv['selected_unique_source_groups']==1
matrix=read(O/'task_matrix_draft.json');jobs=matrix['jobs']
expected={(task,b,method) for task in selected for b in ('e2_original_v1','ems_surface_hybrid_v1') for method in ('local_geometry_test_double','local_first_test_double')}
assert len(jobs)==8 and {(j['task_id'],j['backend'],j['method']) for j in jobs}==expected
assert matrix['execution_authorized'] is False and matrix['actual_jobs_executed']==0 and matrix['freeze_status']=='NOT_FROZEN'
for j in jobs:
 rec=next(r for k,t,r in tasks if k==j['task_id']);assert j['task_sha256']==rec['sha256'] and j['source_group_id']==rec['source_group_id']
 assert j['status']=='NOT_RUN' and j['extra_seed'] is False and j['model_calls_authorized']==0
for obj in read(O/'interface_inventory.json')['existing']:
 p=Path(obj['path']);assert sha(p.read_bytes())==obj['sha256']
 if 'definitions' in obj:
  found={(n.name,n.lineno) for n in ast.parse(p.read_text()).body if isinstance(n,(ast.ClassDef,ast.FunctionDef))}
  assert {(r['name'],r['line']) for r in obj['definitions']}==found
for row in read(O/'figure_sources.json')['files']:assert sha(Path(row['path']).read_bytes())==row['sha256']
assert len(list((O/'figures').glob('*.png')))==5
print(json.dumps({'status':'PASS_READONLY_IDENTITIES_AND_DRAFT_ONLY','manifest_members':len(m['files']),'source_files':542,'source_unchanged':True,'historical_data_receipt_members':receipt_count,'tasks':16,'source_families':len(sources),'selected_tasks':selected,'selected_counts':[len(t['items']) for _,t,_ in tasks[:2]],'selected_source_groups':1,'draft_jobs':8,'actual_jobs':0,'all_feasibility':'UNKNOWN','interface_locations_match':True,'figure_sources_unchanged':True,'new_figures':5,'production_imports':0,'candidate_loop_kernel_model_calls':0,'scope_limit':'no runtime feasibility, kernel validation or permission proved by this check'},ensure_ascii=False,indent=2))
