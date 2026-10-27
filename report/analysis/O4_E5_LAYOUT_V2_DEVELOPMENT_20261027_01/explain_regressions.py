"""Compare saved paired trajectories without counterfactual order execution."""
import collections
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXP = ROOT/'semantic_pallet_planner/outputs/EXP_O4_E5_LAYOUT_V2_L2_20261027_01'


def read(path): return json.loads(path.read_text())


def action_candidate(event):
    action = event['action']
    if action is None: return None
    return next(c for c in event['candidates'] if c['candidate_id'] == action['candidate_id'])


def pose(candidate):
    if candidate is None: return None
    return [candidate['pick_item_id'], candidate['pose'], candidate['oriented_size_mm']]


def summary(event):
    return {'request_id': event['request']['request_id'], 'state_hash': event['request']['state_hash'],
            'arrived_ids': event['before']['arrived_ids'], 'action': action_candidate(event),
            'search': event['search_trace'], 'groups': [
                {'pick_item_id': g['pick_item_id'], 'candidate_generation': g['generation'],
                 'rank_explanation': g['trace'], 'allowed_count': len(g['evaluation']['allowed_ids'])} for g in event['groups']]}


def explain_pair(a, d):
    ae = [(i, e) for i, e in enumerate(a['events']) if e.get('groups')]
    de = [(i, e) for i, e in enumerate(d['events']) if e.get('groups')]
    first = None
    for step, ((ai, av), (di, dv)) in enumerate(zip(ae, de)):
        if pose(action_candidate(av)) == pose(action_candidate(dv)): continue
        old = action_candidate(av); new = action_candidate(dv)
        shared = av['before'] == dv['before']
        comparison = {'decision_index': step, 'A_event_index': ai, 'D_event_index': di, 'same_before_state': shared,
                      'A': summary(av), 'D': summary(dv)}
        if shared and old is not None:
            new_group = next((g for g in dv['groups'] if g['pick_item_id'] == old['pick_item_id']), None)
            same = next((c for c in new_group['candidates'] if pose(c) == pose(old)), None) if new_group else None
            if same is None:
                classification = 'candidate_retention'
            elif same['candidate_id'] not in new_group['evaluation']['allowed_ids']:
                classification = 'hard_filter'
            elif same['candidate_id'] not in new_group['trace']['eligible_labels']:
                classification = 'soft_budget'
            elif d['summary']['planner'] == 'buffer_search':
                classification = 'bounded_search_ranking_or_beam_pruning'
            else:
                classification = 'position_ranking'
            comparison['first_divergence_layer'] = classification
            comparison['legacy_action_in_D_topk'] = same
            if same is not None and classification == 'position_ranking':
                comparison['first_differing_rank_component'] = new_group['trace']['first_differing_rank_component'].get(same['candidate_id'])
                comparison['old_action_new_quality'] = new_group['trace']['qualities'].get(same['candidate_id'])
                comparison['new_action_quality'] = new_group['trace']['qualities'].get(new['candidate_id']) if new else None
        first = comparison; break
    terminal = []
    for name, result, events in [('A', a, ae), ('D', d, de)]:
        index, e = events[-1]
        rejected = collections.Counter(v.split(':')[0] for g in e['groups'] for r in g['evaluation']['evaluations'] for v in r['after']['violations'])
        terminal.append({'group': name, 'event_index': index, 'summary': result['summary'],
                         'stop_diagnostics': e['diagnostics'], 'topk_rejection_instances': dict(rejected),
                         'actual_action': e['action'], 'scope': 'own_terminal_state_not_a_shared_counterfactual'})
    return {'first_divergence': first, 'terminals': terminal,
            'causal_claim': 'first divergence and terminal restrictions identified; one early action is not proven sufficient to recover the order',
            'unresolved_for_user_review': ['search path-level choice versus beam-pruning contribution' ] if d['summary']['planner'] == 'buffer_search' else []}


records = []
for ap in sorted((EXP/'episodes').glob('L2_*_A_*.json')):
    dp = ap.with_name(ap.name.replace('_A_', '_D_'))
    if not dp.exists(): continue
    a, d = read(ap), read(dp)
    sa, sd = a['summary'], d['summary']
    count_loss = sd['placed_items']-sa['placed_items']
    volume_delta = sd['placed_volume_ratio']-sa['placed_volume_ratio']
    record = {'task_id': sa['task_id'], 'method': sa['planner'], 'count_delta': count_loss,
                    'volume_delta': volume_delta, 'hold': count_loss <= -2 or (sa['clean_completed'] and not sd['clean_completed']),
                    **explain_pair(a, d)}
    if volume_delta >= 0 and count_loss >= 0: record['unresolved_for_user_review'] = []
    records.append(record)
(HERE/'trajectory_explanations.json').write_text(json.dumps(records, ensure_ascii=False, indent=2)+'\n')
print('saved paired explanations:', len(records), 'severe regressions:', sum(r['hold'] for r in records))
