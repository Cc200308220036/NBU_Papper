"""Independent arithmetic and per-task audit of the new 96-record protocol."""
import ast
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[2]; OUT = ROOT/'semantic_pallet_planner/outputs'


def read(p): return json.loads(p.read_text())


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p,d):
    with p.open('x') as f: json.dump(d,f,ensure_ascii=False,indent=2);f.write('\n')


sp = OUT/'PLAN_O4_E5_CAPACITY_NEXT_SMALL_20261027_01'; sr = OUT/'EXP_O4_E5_CAPACITY_NEXT_SMALL_20261027_01'
fp = OUT/'PLAN_O4_E5_CAPACITY_NEXT_F_20261027_01'; er = OUT/'EXP_O4_E5_CAPACITY_NEXT_EXPANDED_20261027_01'
small, final = read(sp/'plan.json'), read(fp/'plan.json'); tasks = {t['task_id']:t for t in small['tasks']+final['tasks']}
assert len(tasks) == 24 and len({t['source_order_key'] for t in tasks.values()}) == 12
records = []
for row in small['reuse']:
    if row['group'] == 'A': records.append({**row,'record_path':row['path'],'phase':'small'})
for run, phase in ((sr,'small'),(er,'expanded')):
    jobs = read(run/'jobs.json'); assert all(j['status']=='PASS' for j in jobs)
    for j in jobs: records.append({**j,'group':'F' if j['group']=='B0' else j['group'],'record_path':str((run/'episodes'/f'{j["job_id"]}.json').relative_to(ROOT)), 'phase':phase})
assert len(records)==96 and len({(r['task_id'],r['method'],r['group']) for r in records})==96
rows=[]; event_rows=[]; checks=[]
for record in records:
    path=ROOT/record['record_path']; result=read(path); t=tasks[record['task_id']]; s=result['summary']; state=result['final_state']
    planned=sum(math.prod(i['dimensions_mm'].values()) for i in t['items']); volume=sum(math.prod(i['oriented_size_mm']) for i in state['placed_items'])
    assert s['placed_items']==len(state['placed_items']) and abs(s['placed_volume_ratio']-volume/planned)<1e-12
    assert len(t['items'])==s['planned_items'] and len(t['items'])<=12
    placed={i['item_id'] for i in state['placed_items']}; pending={i['item']['item_id'] for i in state['pending_items']}
    assert not placed & pending and placed|pending==set(state['arrived_ids'])
    assert not s['final_business_violations'] and not s['violating_steps'] and s['execution_status']=='PASS'
    for index,e in enumerate(result['events']):
        if 'search_trace' not in e:continue
        trace=e['search_trace']; assert trace['evaluations']<=256 and sum(len(g['candidates']) for g in e['groups'])<=48
        assert all(len(g['candidates'])<=16 for g in e['groups'])
        assert trace.get('max_depth',0)<=3 and trace.get('max_beam',0)<=8
        assert e.get('commit_error') is None
        if record['method']=='buffer_search':assert trace['before_real_state']==trace['after_real_state']
        if record['group']=='F' and record['method']=='buffer_search':
            for n in trace['nodes']:
                assert n['required']==16*(len(e['before']['pending_items'])-n['depth'])
                assert n['spent_after']-n['spent_before']==n['candidate_count']
                assert n['spent_after']<=256 and n['candidate_count']<=n['required']
        event_rows.append({'task_id':record['task_id'],'method':record['method'],'group':record['group'],'event_index':index,
                           'pending_count':len(e['before']['pending_items']),
                           'evaluations':trace['evaluations'],'max_depth':trace.get('max_depth',0),'max_beam':trace.get('max_beam',0),
                           'search_truncated':trace['search_truncated'],'layers':trace.get('layers'), 'nodes':trace.get('nodes',[]),
                           'seconds':trace.get('elapsed_seconds'), 'stop_reason':e.get('reason'),
                           'root_coverage':[{k:g['generation'].get(k) for k in ('coverage_gained','coverage_lost','retention','full_pool_quality_evaluations')} for g in e['groups']]})
    rows.append({**record,**s,'sha256':sha(path)})
pairs=[]
for task in tasks:
    for method in ('single','buffer_search'):
        a,f=[next(r for r in rows if (r['task_id'],r['method'],r['group'])==(task,method,g)) for g in ('A','F')]
        pairs.append({'task_id':task,'source_order_key':tasks[task]['source_order_key'],'configuration':tasks[task]['configuration'],'method':method,
                      'A':a['placed_items'],'F_B0':f['placed_items'],'count_delta':f['placed_items']-a['placed_items'],
                      'A_volume':a['placed_volume_ratio'],'F_volume':f['placed_volume_ratio'],'volume_delta':f['placed_volume_ratio']-a['placed_volume_ratio'],
                      'A_clean':a['clean_completed'],'F_clean':f['clean_completed'],
                      'default_HOLD':f['placed_items']<a['placed_items']-1 or (a['clean_completed'] and not f['clean_completed'])})
aggregates=[]
for method in ('single','buffer_search'):
    subset=[p for p in pairs if p['method']==method]
    aggregates.append({'method':method,'tasks':len(subset),'planned_boxes':sum(len(t['items']) for t in tasks.values()),
        'A_count':sum(p['A'] for p in subset),'F_count':sum(p['F_B0'] for p in subset),
        'A_mean_volume':sum(p['A_volume'] for p in subset)/24,'F_mean_volume':sum(p['F_volume'] for p in subset)/24,
        'A_clean':sum(p['A_clean'] for p in subset),'F_clean':sum(p['F_clean'] for p in subset),
        'hold_tasks':[p['task_id'] for p in subset if p['default_HOLD']]})
noninferior=all(r['F_count']>=r['A_count'] and r['F_mean_volume']>=r['A_mean_volume']-1e-9 and r['F_clean']>=r['A_clean'] for r in aggregates)
gain=any(r['F_count']>=r['A_count']+1 and r['F_mean_volume']>=r['A_mean_volume']+.01 for r in aggregates)
old_source=OUT/'PLAN_O4_E5_LAYOUT_V2_20261027_01/code_snapshot/semantic_pallet_planner/o4/extensions/e5/planning.py'
new_source=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/o4/extensions/e5/planning.py'
old_choose=next(n for n in ast.parse(old_source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='choose')
new_choose=next(n for n in ast.parse(new_source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='choose')
assert ast.dump(ast.Module(body=new_choose.body[1:],type_ignores=[]))==ast.dump(ast.Module(body=old_choose.body,type_ignores=[]))
report={'engineering_status':'MAIN_96_EXECUTION_AND_ARITHMETIC_PASS','performance_status':'CAPACITY_GATE_PASS' if noninferior and gain else 'CAPACITY_GATE_FAILED',
        'default_replacement_status':'HOLD_TASK_REGRESSION' if any(p['default_HOLD'] for p in pairs) else 'PENDING_COST_AND_DELIVERY_AUDIT',
        'noninferior_both_methods':noninferior,'minimum_capacity_gain':gain,'aggregates':aggregates,
        'records':96,'tasks':24,'historical_development_sources':12,'new_episodes':84,'historical_A_reused':12,
        'planned_boxes_per_version_method':sum(len(t['items']) for t in tasks.values()),
        'planned_boxes_all_96_records':sum(len(tasks[r['task_id']]['items']) for r in rows),
        'actual_commits':sum(r['placed_items'] for r in rows if r['group']=='F' or r['phase']=='expanded'),
        'original_default_ast_unchanged':True,'F':'B0','old_D_L3':'NOT_RUN_NOT_RESUMED','new_api_attempts':0,
        'independent_generalization':'NOT_MEASURED','terminal_quality':'NOT_IMPLEMENTED','P3':'NOT_IMPLEMENTED','probe':'NOT_IMPLEMENTED'}
write(HERE/'main_rows.json',rows);write(HERE/'main_pairs.json',pairs);write(HERE/'main_decisions.json',event_rows);write(HERE/'main_audit.json',report)
print(json.dumps(report,ensure_ascii=False,indent=2))
