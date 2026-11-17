"""Standard-library read-only inventory; no production imports or execution permit."""
import hashlib,json,pathlib,subprocess,sys,math
P=pathlib.Path
OUT=P('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P0_20261117_01')
GP=P('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP4_20261117_01')
QA=P('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP4_QA_20261117_01')
DATA=P('semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02')
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(n,d):(OUT/n).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def git(*args):return subprocess.check_output(['git',*args]).decode().strip()
head=git('rev-parse','HEAD')
checks=[]
for folder,rev in [(GP,'adbdf21ded76df9ba4704087841ccff6154b53b7'),(QA,'e1422b01c371d0d1cd03e14d0979fe86d9f6c5e4')]:
 rows=[]
 for r in read(folder/'delivery_manifest.json')['files']:
  p=P(r['path']);actual=sha(p);mode='WORKTREE'
  if p.name=='README.md':
   actual=hashlib.sha256(subprocess.check_output(['git','show',rev+':'+str(p)])).hexdigest();mode='FIXED_REVISION:'+rev
  rows.append({'path':str(p),'expected':r['sha256'],'actual':actual,'status':'PASS' if actual==r['sha256'] else 'FAIL','source':mode})
 checks.append({'manifest':str(folder/'delivery_manifest.json'),'members':rows})
rows=[]
for rel,h in read(DATA/'delivery_manifest.json').items():
 p=DATA/rel;rows.append({'path':str(p),'expected':h,'actual':sha(p) if p.exists() else None,'status':'PASS' if p.exists() and sha(p)==h else 'FAIL'})
checks.append({'manifest':str(DATA/'delivery_manifest.json'),'members':rows})
source=read(GP/'source_manifest.json')['files'];base=P('semantic_pallet_planner/src/semantic_pallet_planner')
current={str(p.relative_to(base)):sha(p) for p in base.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and 'tests' not in p.relative_to(base).parts}
save('source_inventory.json',{'files':current,'equal_GP4':current==source,'count':len(current)})
assert current==source
assert all(r['status']=='PASS' for c in checks for r in c['members'])
save('readonly_receipt.json',{'version':'gp5_p0_readonly_receipt_v1','entry_head':'adbdf21ded76df9ba4704087841ccff6154b53b7','sync_head':head,'branch':git('branch','--show-current'),'upstream':git('rev-parse','--abbrev-ref','--symbolic-full-name','@{upstream}'),'initial_worktree':'CLEAN','initial_index':'EMPTY','pull_attempts':[{'result':'FAILED before fetch','reason':'.git/FETCH_HEAD read-only sandbox'},{'result':'FF_ONLY_SUCCESS','execution':'approved sandbox escalation','from':'adbdf21d','to':head}],'rules':['AGENTS.md'],'interpreter':sys.version,'manifests':checks,'production_equal_GP4':True,'historical_navigation':'fixed Git revisions; original manifests never rewritten','business_network':'NOT_RUN; git synchronization only'})
sources={r['source_group_id']:r for r in read(DATA/'source_manifest.json')['sources']}
groups={g['source_group_id']:g for g in read(DATA/'split_manifest.json')['groups']}
tasks=[]
for p in sorted((DATA/'tasks').glob('*.json')):
 d=read(p);missing=[]
 for k in ('task_id','items','container','arrival_order','partition','source_group_id','source_order_key','scenario_id','buffer_capacity','candidate_limits'):
  if k not in d:missing.append(k)
 ids=[o['item_id'] for o in d['items']]
 if d['arrival_order']!=ids or len(set(ids))!=len(ids):missing.append('arrival/ID consistency')
 for o in d['items']:
  for k in ('dimensions_mm','mass_kg','stackable','top_load_limit_kg_synthetic'):
   if k not in o:missing.append(o['item_id']+':'+k)
  if not all(math.isfinite(v) and v>0 for v in o['dimensions_mm'].values()) or o['mass_kg']<=0 or o['top_load_limit_kg_synthetic']<0:missing.append('invalid physical values')
 group=groups.get(d['source_group_id']);source=sources.get(d['source_group_id'])
 if not group or group['partition']!='train' or d['scenario_id'] not in group['scenario_ids'] or not source or source['source_key']!=d['source_order_key']:missing.append('source/split binding')
 tasks.append({'task_id':d['task_id'],'path':str(p),'sha256':sha(p),'partition':d['partition'],'source_group_id':d['source_group_id'],'source_order_key':d['source_order_key'],'source_order_id':d['source_order_id'],'layer':d['layer'],'items':len(ids),'planned_volume_mm3':sum(math.prod(o['dimensions_mm'].values()) for o in d['items']),'planned_mass_kg':sum(o['mass_kg'] for o in d['items']),'arrival_order_sha256':hashlib.sha256(json.dumps(d['arrival_order'],separators=(',',':')).encode()).hexdigest(),'complete':not missing,'missing':missing,'feasibility_status':d['feasibility_status']})
tasks.sort(key=lambda t:t['task_id']);selected=[t for t in tasks if t['complete'] and t['partition']=='train'][:2]
for t in tasks:t['decision']='INCLUDED_LEXICOGRAPHIC_FIRST_TWO' if t in selected else ('EXCLUDED_MISSING_INPUT' if t['missing'] else 'OUTSIDE_FIRST_TWO_NOT_SCORED')
save('data_inventory.json',{'version':'gp5_p0_data_inventory_v1','scope':'ADMINISTRATOR_PLAN_ONLY; future items never provided to provider/context','data_root':str(DATA),'data_identity':read(DATA/'manifest.json')['data_identity'],'source_manifest_sha256':sha(DATA/'source_manifest.json'),'split_manifest_sha256':sha(DATA/'split_manifest.json'),'exposed_training_only':True,'independent_new_sources':0,'task_count':len(tasks),'source_families':sources,'tasks':tasks,'selected_task_ids':[t['task_id'] for t in selected],'selected_unique_source_groups':len(set(t['source_group_id'] for t in selected)),'completeness_scope':'file hashes, required physical fields, arrival IDs, source/train binding; no loader/physical/runtime feasibility validation'})
jobs=[]
for t in selected:
 for b in ('e2_original_v1','ems_surface_hybrid_v1'):
  for m in ('local_geometry_test_double','local_first_test_double'):
   jobs.append({'job_id':'DRAFT_J%02d'%(len(jobs)+1),'task_id':t['task_id'],'task_sha256':t['sha256'],'source_group_id':t['source_group_id'],'backend':b,'method':m,'status':'NOT_RUN','extra_seed':False,'model_calls_authorized':0})
save('task_matrix_draft.json',{'version':'geometry_real_order_matrix_draft_v1','status':'DRAFT_NOT_EXECUTABLE_NOT_A_PERMIT','jobs':jobs,'max_jobs':8,'actual_jobs_executed':0,'new_seeds':0,'selected_orders_are_same_family':True,'freeze_status':'NOT_FROZEN','execution_authorized':False})
inputs=[GP/'comparison.json',GP/'gp4_plots.py',GP/'gp4_common.py']
for p in sorted((GP/'inputs').rglob('*.json')):inputs.append(p)
for point in sorted((GP/'states').iterdir()):
 inputs.extend([point/'state.json',point/'e2_original_v1'/'bundle.json',point/'ems_surface_hybrid_v1'/'bundle.json'])
inputs.extend(sorted((GP/'figures').glob('*.png')))
save('figure_sources.json',{'files':[{'path':str(p),'sha256':sha(p)} for p in inputs],'rules':'saved input/state/bundle/comparison only; Fraction(repr(float)) matching; original colors/aspect/limits/markers/footprints unchanged; only layout differs'})
print('READONLY_AUDIT_PASS',head,len(current),len(tasks),[t['task_id'] for t in selected])
