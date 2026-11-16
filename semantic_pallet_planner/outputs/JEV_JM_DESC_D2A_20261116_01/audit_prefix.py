"""Read-only standard-library evidence auditor. Prints JSON; creates no state/permit.
Run from repo root. No production imports, execution entrypoints or solver calls.
Legacy seals intentionally reproduce legacy JSON canonicalization, while exact
semantic comparisons use Decimal parsed directly from original JSON lexemes.
"""
import hashlib
import json
import platform
import subprocess
from decimal import Decimal
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

OUT = Path('semantic_pallet_planner/outputs/JEV_JM_DESC_D2A_20261116_01')
manifest = json.loads((OUT/'input_manifest.json').read_text())
allowed = {r['path']: r for r in manifest['files']}
reads = []
checks = []
fields = []

def sha(b): return hashlib.sha256(b).hexdigest()
def canonical(v): return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def digest(v): return sha(canonical(v).encode())
def read(p, exact=False):
    p = str(p)
    if p not in allowed: raise ValueError('outside frozen whitelist: '+p)
    raw = Path(p).read_bytes()
    if sha(raw) != allowed[p]['sha256']: raise ValueError('frozen bytes changed: '+p)
    if p not in reads: reads.append(p)
    return json.loads(raw, parse_float=Decimal) if exact else json.loads(raw)
def check(name, condition, detail=''):
    checks.append({'check':name,'status':'MATCH' if condition else 'CONFLICT','detail':detail})
def field(name, path, pointer, value, binding, sufficient=True):
    fields.append({'field':name,'path':str(path),'sha256':allowed[str(path)]['sha256'],'pointer':pointer,
                   'value_or_identity':value,'binding':binding,'evidence_status':'PRESENT',
                   'import_sufficiency':'EVIDENCE_PRESENT_IMPLEMENTATION_NOT_TESTED' if sufficient else 'BLOCKED',
                   'missing_or_conflict':'see checks; no inference/reconstruction',
                   'impact':'future bridge must verify equality before constructing any new runtime'})
def sealed(v): return v.get('record_digest') == digest({k:x for k,x in v.items() if k!='record_digest'})

B='semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01'
C='semantic_pallet_planner/outputs/JEV_JM1_C1_REAL_BASELINES_20261112_01'
R=B+'/materials/future_runs/baseline_1'
D='semantic_pallet_planner/outputs/JEV_JM_DESC_D1_DESIGN_20261116_01'
Q='semantic_pallet_planner/outputs/JEV_JM_DESC_D1_QA_20261116_01'
# Check only permitted bytes against historical manifests, never read every run artifact.
old_index={r['path']:r for r in read(C+'/delivery_manifest.json')['files']}
for row in read(B+'/delivery_manifest.json')['files']:
    old_index.setdefault(row['path'],row)
for p in allowed:
    if p in old_index:
        check('historical_byte:'+p, allowed[p]['sha256']==old_index[p]['sha256'])
for base in [D,Q]:
    for row in read(base+'/delivery_manifest.json')['files']:
        if row['path'] in allowed: check('delivery_byte:'+row['path'],allowed[row['path']]['sha256']==row['sha256'])
        else: checks.append({'check':'delivery_scope:'+row['path'],'status':'NOT_READ','detail':'outside runtime audit whitelist; shared navigation not expanded'})

activation=read(R+'/activation.json'); ex=activation['execution']; stages=[]
for i in range(1,11):
    p=R+f'/stages/{i:06}.json'; row=read(p); stages.append(row)
    check(f'stage_{i}_seal',sealed(row)); check(f'stage_{i}_checkpoint_seal',sealed(row['checkpoint']))
    check(f'stage_{i}_execution',row['execution_digest']==digest(ex))
    check(f'stage_{i}_sequence',row['sequence']==i)
    if i>1: check(f'stage_{i}_chain',row['previous_digest']==digest(stages[-2]))
check('activation_seal',sealed(activation));check('execution_seal',sealed(ex))
check('stage_1_chain',stages[0]['previous_digest']==digest(activation))
p=R+'/stages/000010.json'; cp=stages[-1]['checkpoint'];e=cp['pending_event'];state=cp['state']
check('target_phase',cp['phase']=='DECISION_READY' and e['decision_id']==manifest.get('target','JM1_C1_NEW_00100027_controlled_base_3632016712acb138_D0001'))
check('unselected_target',e['selection'] is None and e['monitor'] is None and e['after']==e['before'])
check('state_before',state==e['before']);check('task_digest',cp['task_digest']==digest(ex['task']))
check('config_digest',cp['config_digest']==digest(ex['config']))
field('decision_location',p,'/checkpoint',{'decision_id':e['decision_id'],'sequence':10,'phase':cp['phase'],'cursor':cp['cursor'],'decision':cp['decision']},'before target selection; never terminal checkpoint')
for k in state:
    field('runtime.'+k,p,'/checkpoint/state/'+k,{'semantic_digest':digest(state[k]),'count':len(state[k]) if isinstance(state[k],(list,dict)) else state[k]},'state == pending_event.before')
for k in ['task_digest','config_digest','runtime_identity','events']:
    field(k,p,'/checkpoint/'+k,{'digest':digest(cp[k])},'immutable historical runtime binding')
for k in ['bundle','context','observation']:
    field(k,p,'/checkpoint/pending_event/'+k,{'digest':digest(e[k])},'same decision; retain full saved payload, not public projection alone')

taskpath='semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02/tasks/NEW_00100027_controlled_base.json'
task=read(taskpath)
check('original_task_bytes',allowed[taskpath]['sha256']=='230ea8b1d6766fb4898b75da8afcea1738afd27e66a38d1ffa0a82409e332a89')
assignment=read(B+'/materials/training_plan.json')['assignments'][0]
check('runtime_task_assignment',assignment['runtime_task_digest']==digest(ex['task']) and assignment['task_ref']['sha256']==allowed[taskpath]['sha256'])
check('frozen_task_digest',ex['task']['frozen_task_digest']==digest(task))
check('task_arrival_unchanged',task['arrival_order']==ex['task']['arrival_order'])
check('runtime_item_projection',all(all(old[k]==new[k] for k in ('item_id','dimensions_mm','mass_kg','stackable','top_load_limit_kg_synthetic','fragile','weight_class')) and new['product_category']=='general' for old,new in zip(task['items'],ex['task']['items'])))
field('runtime_task_projection',R+'/activation.json','/execution/task',{'digest':digest(ex['task']),'frozen_task_digest':ex['task']['frozen_task_digest'],'differences_from_raw':['attributes','frozen_task_digest','instruction_text','items','reference_policy']},'raw task is NOT runtime task; historical runtime_task projection source + frozen_task_digest + training_plan assignment bind both; do not import raw task as runtime')
check('task_count',len(task['items'])==19)
check('cursor_and_arrivals',cp['cursor']==state['arrival_count']==4 and state['arrived_ids']==task['arrival_order'][:4])
items={x['item_id']:x for x in ex['task']['items']}
check('buffer_item_payloads',all(x['item']==items[x['item']['item_id']] and task['arrival_order'][x['arrival_index']]==x['item']['item_id'] for x in state['pending_items']))
check('buffer_slots', [x['slot'] for x in state['pending_items']]==[0,1,2])
check('arrived_partition',set(state['arrived_ids'])=={x['item']['item_id'] for x in state['pending_items']}|{x['item_id'] for x in state['placed_items']})
field('original_task',taskpath,'',{'task_id':task['task_id'],'count':19,'semantic_digest':digest(task),'arrival_order_digest':digest(task['arrival_order'])},'private future payload identity/arrival consistency only; not copied to public selection inputs')
field('buffer_binding',p,'/checkpoint/state/pending_items',{'ids':[x['item']['item_id'] for x in state['pending_items']],'arrival_indices':[x['arrival_index'] for x in state['pending_items']]},'task arrival prefix, exact item payloads and slots')

commit=stages[6]['checkpoint']['pending_event'];mon=stages[5]['checkpoint']['pending_event']
check('inherited_stable',mon['monitor']['status']=='STABLE' and commit['monitor']==mon['monitor'])
check('inherited_place',commit['event']=='PLACE' and commit['after']['placed_count']==1 and commit['before']['placed_count']==0)
check('commit_to_ready',stages[7]['checkpoint']['state']==commit['after'])
check('committed_event_retained',any(all(x.get(k)==commit.get(k) for k in ('decision_id','before','after','action','proposed_action','monitor','selection','bundle','context','observation','event')) for x in cp['events']))
check('placed_preserved',state['placed_items']==commit['after']['placed_items'])
check('monitor_state_binding',commit['monitor']['binding']['state_digest']==digest(commit['before']))
check('monitor_result_digest',commit['monitor']['result_digest']==digest(commit['monitor']['result']))
check('monitor_decision_binding',commit['monitor']['binding']['decision_id']==commit['decision_id'])
chosen=next(x for x in commit['bundle']['selectable_candidates'] if x['candidate_id']==commit['selection']['selected_candidate_id'])
for key,value in {'action_digest':commit['proposed_action'],'bundle_digest':commit['bundle'],'candidate_digest':chosen,'config_digest':ex['config'],'context_digest':commit['context'],'selection_digest':commit['selection']}.items():
    check('prefix_monitor_binding_'+key,commit['monitor']['binding'][key]==digest(value))
check('prefix_action_committed',commit['action']==commit['proposed_action'] and commit['action']['candidate_id']==chosen['candidate_id'])
placed=commit['after']['placed_items'][-1]
check('prefix_placed_exact_geometry',placed['item_id']==chosen['pick_item_id'] and placed['pose']==chosen['pose'] and placed['oriented_size_mm']==chosen['oriented_size_mm'])
check('prefix_monitor_algorithm',commit['monitor']['result']['algorithm_identity']==ex['config']['stability_monitor']['algorithm_identity'])
check('prefix_monitor_runtime',commit['monitor']['binding']['runtime_identity']==ex['config']['runtime_identity'])
field('prefix_monitor',R+'/stages/000006.json','/checkpoint/pending_event/monitor',{'status':mon['monitor']['status'],'result_digest':mon['monitor']['result_digest'],'monitor_committed_flag':mon['monitor']['committed']},'monitor.committed=false is pre-commit observation; commit evidenced separately by stage7 PLACE/after, not inferred from monitor flag')
field('prefix_commit',R+'/stages/000007.json','/checkpoint/pending_event',{'decision_id':commit['decision_id'],'event':commit['event'],'after_digest':digest(commit['after']),'placed_ids':[x['item_id'] for x in state['placed_items']]},'stage7 -> stage8 READY -> stage10 inherited event')
field('area_load_ledger',p,'/checkpoint/state/placed_items',{'loads':[{'item_id':x['item_id'],'supported_load_kg':x['supported_load_kg'],'support_fractions':x['support_fractions'],'capacity':x['top_load_limit_kg_synthetic']} for x in state['placed_items']]},'area load stored in placed_items; no separate LP recomputation; retain attributes and support fractions')

pool=read(C+'/public/baseline_1/D0001/pool.json');prefix=read(C+'/public/baseline_1/D0001/prefix.json');ctxpath=R+'/ledger/contexts/'+e['decision_id']+'.json';ctx=read(ctxpath)
check('public_pool_exact_saved',pool==e['bundle']['selectable_candidates'])
check('context_exact_saved',ctx==e['context'])
check('pool_unique_complete',len(pool)==48 and len({x['candidate_id'] for x in pool})==48 and len(e['context']['display_mapping'])==48)
check('mapping_pool_ids',{x['candidate_id'] for x in e['context']['display_mapping'].values()}=={x['candidate_id'] for x in pool})
check('mapping_member_digests',all(any(x['candidate_id']==v['candidate_id'] and digest(x)==v['candidate_digest'] for x in pool) for v in e['context']['display_mapping'].values()))
check('public_prefix_ids',[x['item_id'] for x in prefix['buffer']]==[x['item']['item_id'] for x in state['pending_items']] and [x['item_id'] for x in prefix['placed_objects']]==[x['item_id'] for x in state['placed_items']])
sel=read(D+'/selected_pair.json')
exact_pool=read(C+'/public/baseline_1/D0001/pool.json',True)
selected=[]
for cid in ['E2_00986aa3a14df465','E2_2aeba209df8e7121']:
    ix=next(i for i,x in enumerate(pool) if x['candidate_id']==cid);x=exact_pool[ix]
    label=next(k for k,v in e['context']['display_mapping'].items() if v['candidate_id']==cid)
    selected.append({'candidate_id':cid,'pool_index':ix,'old_label':label,'pick_item_id':x['pick_item_id'],'pose':{k:str(v) for k,v in x['pose'].items()},'oriented_size_mm':[str(v) for v in x['oriented_size_mm']]})
for role,actual in zip(('A','B'),selected):
    old=sel['selected_candidates'][role]
    check('D1_exact_action_'+role,old['candidate_id']==actual['candidate_id'] and old['pick_item_id']==actual['pick_item_id'] and all(Decimal(old['pose'][k])==Decimal(v) for k,v in actual['pose'].items()) and all(Decimal(x)==Decimal(y) for x,y in zip(old['oriented_size_mm'],actual['oriented_size_mm'])))
check('fixed_pair_not_reselected',sel['pair']['point_id']=='P01_ffcfcc6e4af4' and sel['geometric_superset']=='A')
field('full_pool',C+'/public/baseline_1/D0001/pool.json','',{'count':48,'digest':digest(pool),'selected_bindings':selected},'same full pool, mapping labels are historical aliases only')
check('pair_exact_positions',selected[0]['pose']['x_mm']=='-300.0' and Decimal(selected[1]['pose']['x_mm'])==80)
# Pin all historical source bytes using the original declared entry Git snapshot;
# this is separate historical evidence, never an exception claiming current bytes match.
source=read(B+'/source_manifest.json'); history=[]; current=[]
for name, expected in source.items():
    path='semantic_pallet_planner/src/semantic_pallet_planner/'+name
    old=subprocess.run(['git','show','ad94605fdb51f8c099050f28f68783f3c8f67ed0:'+path],capture_output=True)
    history.append({'path':path,'expected':expected,'actual':sha(old.stdout) if old.returncode==0 else None,'match':old.returncode==0 and sha(old.stdout)==expected})
    now=Path(path)
    current.append({'path':path,'sha256':sha(now.read_bytes()) if now.exists() else None,'matches_historical':now.exists() and sha(now.read_bytes())==expected})
check('historical_source_manifest_identity',digest(source)==ex['identity']['source'])
check('historical_source_blob_bytes',all(x['match'] for x in history),'original C1 handoff entry HEAD ad94605f; source snapshot compared separately from current')
deps={}
for n in ('jsonschema','numpy','scipy'):
    try: deps[n]=version(n)
    except PackageNotFoundError: deps[n]='NOT_INSTALLED'
field('old_source_dependencies',R+'/activation.json','/execution/identity',ex['identity'],'historical declared environment; installed old packages not empirically recreated')
current_scope=json.loads((OUT/'source_read_scope.json').read_text())['source']
for name,expected in current_scope.items():
    if sha(Path('semantic_pallet_planner/src/semantic_pallet_planner',name).read_bytes())!=expected:
        raise ValueError('current source changed after scope freeze')
print(json.dumps({'current_source_identity':digest(current_scope),'historical_source_count':len(source),'current_source_count':len(current_scope),'version':'jm_d2a_audit_result_v1','checks':checks,'field_binding_matrix':fields,'actual_reads':reads,'selected_bindings':selected,'source_history':history,'current_source_comparison':current,'environment':{'historical':ex['identity'],'current_python':platform.python_version(),'current_dependencies':deps},'arithmetic':{'N':19,'placed_before':1,'forced_first':1,'proposed_sends_per_job':17,'proposed_jobs':4,'proposed_total':68,'authorized_sends':0},'failures':[x for x in checks if x['status']=='CONFLICT'],'not_run':['production validators','imports of production modules','geometry/stability solving','prefix replay','any jobs','new start construction']},ensure_ascii=False,indent=2))

raise SystemExit(1 if any(x['status']=='CONFLICT' for x in checks) else 0)
