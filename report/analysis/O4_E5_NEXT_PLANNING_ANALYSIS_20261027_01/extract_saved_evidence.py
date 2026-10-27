"""Extract next-step evidence from saved episodes only; no planner execution."""
import collections
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
EPISODES = ROOT/'semantic_pallet_planner/outputs/EXP_O4_E5_LAYOUT_V2_L2_20261027_01/episodes'
hashes = {}


def load(path):
    data = path.read_bytes(); hashes[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return json.loads(data)


def decisions(result): return [(i,e) for i,e in enumerate(result['events']) if e.get('groups')]


def selected(event):
    return next((c for c in event['candidates'] if event['action'] and c['candidate_id']==event['action']['candidate_id']), None)


records = []; comparisons = []
for configuration in (0,1):
    saved = {}
    for group in 'ABCD':
        path = EPISODES/f'L2_E5_SRC04_C{configuration}_{group}_buffer_search_oracle_ast.json'
        result = load(path); events = decisions(result); saved[group] = events
        first_index, first = events[0]; last_index, last = events[-1]
        trace = first['search_trace']
        records.append({'configuration':configuration,'group':group,'summary':result['summary'],
                        'first_event_index':first_index,'first_state_hash':first['request']['state_hash'],
                        'first_action':selected(first), 'first_search':{
                            'evaluations':trace['evaluations'],'nodes_per_depth':dict(collections.Counter(n['depth'] for n in trace['nodes'])),
                            'candidate_counts_by_node':[n['candidate_count'] for n in trace['nodes']],
                            'search_truncated':trace['search_truncated'],'chosen_path':trace['chosen_path']},
                        'truncated_decisions':sum(e['search_trace']['search_truncated'] for _,e in events),
                        'last_decision_index':last_index,'last_event_type':last['event'],
                        'last_diagnostics':last['diagnostics']})
    a_index,a=saved['A'][1]; b_index,b=saved['B'][1]; b_action=selected(b)
    qualifications = {}
    for group,e in [('A',a),('B',b)]:
        candidate=next(c for c in e['candidates'] if c['pick_item_id']==b_action['pick_item_id'] and c['pose']==b_action['pose'])
        pool=next(g for g in e['groups'] if g['pick_item_id']==candidate['pick_item_id'])
        qualifications[group]={'present':True,'business_allowed':candidate['candidate_id'] in pool['evaluation']['allowed_ids'],
                               'soft_eligible':candidate['candidate_id'] in pool['trace']['eligible_labels']}
    comparisons.append({'configuration':configuration,'A_event_index':a_index,'B_event_index':b_index,
                         'same_before_state':a['before']==b['before'],'A_action':selected(a),'B_action':b_action,
                         'B_action_qualifications':qualifications,
                         'conclusion':'root chosen action exists and is eligible in both; descendant coverage, other eligible sets, beam exposure and budget remain to be separated'})

single=load(EPISODES/'L2_E5_SRC00_C0_D_single_oracle_ast.json'); index,event=decisions(single)[0]
group=event['groups'][0]; chosen=group['selected']; old_pose={'x_mm':0.,'y_mm':-55.,'z_base_mm':0.,'yaw_deg':90}
old=next(c for c in group['candidates'] if c['pose']==old_pose)
single_evidence={'event_index':index,'chosen_pose':chosen['pose'],'old_pose':old_pose,
                 'chosen_quality':group['trace']['qualities'][chosen['candidate_id']],
                 'old_quality':group['trace']['qualities'][old['candidate_id']],
                 'first_differing_rank_component':group['trace']['first_differing_rank_component'][old['candidate_id']],
                 'scope':'ranking explanation at shared empty state; not unique causal proof for full-order loss'}
for rel in ('semantic_pallet_planner/src/semantic_pallet_planner/o4/extensions/e5/layout_v2/planning.py',
            'semantic_pallet_planner/src/semantic_pallet_planner/o4/extensions/e5/layout_v2/quality.py',
            'semantic_pallet_planner/src/semantic_pallet_planner/o4/extensions/e5/layout_v2/candidates.py',
            'semantic_pallet_planner/src/semantic_pallet_planner/o4/extensions/e2/planning.py'):
    hashes[rel]=hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()
output=HERE/'saved_evidence.json'
if output.exists(): raise FileExistsError('Evidence exists; use a new report directory for another analysis version')
output.write_text(json.dumps({'source_sha256':hashes,'search_cases':records,'candidate_B_first_divergence':comparisons,
                             'single_first_decision':single_evidence,'new_planning_runs':0,'new_api_attempts':0,
                             'not_proven':['ranking versus pruning full causal attribution','single first action as sole cause','generalization']},
                            ensure_ascii=False,indent=2)+'\n')
print('saved evidence:',output)
