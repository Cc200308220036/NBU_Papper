"""Preserve the new negative cases using saved records only. No planner import."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]


def read(p):return json.loads(p.read_text())


def pose(c):return None if c is None else {'pick':c['pick_item_id'],'pose':c['pose']}


def selected(e):return next((c for c in e['candidates'] if e.get('action') and e['action']['candidate_id']==c['candidate_id']),None)


def qualification(e,c):
    found=[]
    for g in e['groups']:
        for p in g['candidates']:
            if pose(p)==pose(c):found.append({'present':True,'allowed':p['candidate_id'] in g['evaluation']['allowed_ids'],'eligible':p['candidate_id'] in g['trace']['eligible_labels']})
    return found or [{'present':False,'allowed':None,'eligible':None}]


rows=read(HERE/'main_rows.json');pairs=read(HERE/'main_pairs.json');cases=[]
for p in pairs:
    if p['count_delta']>=0 and p['volume_delta']>=-1e-9:continue
    records=[next(r for r in rows if (r['task_id'],r['method'],r['group'])==(p['task_id'],p['method'],g)) for g in ('A','F')]
    episodes=[read(ROOT/r['record_path']) for r in records]
    decisions=[[(i,e) for i,e in enumerate(ep['events']) if 'search_trace' in e] for ep in episodes]
    first=None
    for (ai,a),(fi,f) in zip(*decisions):
        ac,fc=selected(a),selected(f)
        if pose(ac)!=pose(fc):
            first={'A_event':ai,'F_event':fi,'before_equal':a['before']==f['before'],'A_action':ac,'F_action':fc,
                   'A_action_qualification_in_A':qualification(a,ac),'A_action_qualification_in_F':qualification(f,ac),
                   'F_action_qualification_in_A':qualification(a,fc),'F_action_qualification_in_F':qualification(f,fc),
                   'input_A':a['request'],'input_F':f['request'],'AST_A':a['response']['policy_ast'],'AST_F':f['response']['policy_ast'],
                   'A_search':a['search_trace'],'F_search':f['search_trace']}
            break
    cases.append({'pair':p,'sources':[{'path':r['record_path'],'sha256':r['sha256']} for r in records],
                  'first_divergence':first,'last_decisions':[{'event_index':d[-1][0],'event':d[-1][1]['event'],'diagnostics':d[-1][1].get('diagnostics')} for d in decisions],
                  'causal_status':'REVIEW_REQUIRED_FOR_UNIQUE_FULL_ORDER_CAUSE','followup_searches':0,
                  'scope':'negative result retained; first common-state action divergence and sampled STOP evidence only, no unique full-order counterfactual proof'})
with (HERE/'regression_cases.json').open('x') as f:json.dump({'cases':cases,'new_planning_runs':0,'new_api_attempts':0,'F_changed':False},f,ensure_ascii=False,indent=2)
print(json.dumps([{'task':c['pair']['task_id'],'method':c['pair']['method'],'delta':c['pair']['count_delta'],
 'before_equal':c['first_divergence']['before_equal'],'A_action_in_F':c['first_divergence']['A_action_qualification_in_F'],
 'F_action_in_A':c['first_divergence']['F_action_qualification_in_A'],'status':c['causal_status']} for c in cases],ensure_ascii=False,indent=2))
