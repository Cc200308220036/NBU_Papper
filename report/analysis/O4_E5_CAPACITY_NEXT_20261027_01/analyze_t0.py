"""Read-only interpretation of the predeclared T0 calls; never imports a planner."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
T0 = ROOT/'semantic_pallet_planner/outputs/EXP_O4_E5_CAPACITY_NEXT_T0_20261027_01'
EP = ROOT/'semantic_pallet_planner/outputs/EXP_O4_E5_LAYOUT_V2_L2_20261027_01/episodes'


def read(p): return json.loads(p.read_text())


def pose(c):
    p = c['pose']
    return [c['pick_item_id'], [p['x_mm'], p['y_mm'], p['z_base_mm'], p['yaw_deg']]]


def sets(n):
    return {g['pick']: {'poses': sorted([c['pose'] for c in g['candidates']]),
                       'eligible': sorted([c['pose'] for c in g['candidates'] if c['status'] == 'eligible'])} for g in n['groups']}


results = {p.stem: read(p) for p in (T0/'calls').glob('*.json') if not p.name.endswith('.started.json')}
assert len(results) == 12
checks = {}; ranking = []; candidate = []
for q in (1, 2):
    rows = []
    for u in range(4):
        r = results[f'Q{q}_U{u}']
        rows.append({'variant': f'U{u}', 'selected': r['selected'], 'chosen_path': r['chosen_path'],
                     'depths': r['expanded_depth_distribution'], 'evaluations': r['evaluations'], 'tree_digest': r['tree_digest']})
    ranking.append({'q': f'Q{q}', 'rows': rows,
                    'leaf_only_changed_action_with_legacy_beam': rows[0]['selected'] != rows[1]['selected'],
                    'beam_only_changed_action_with_legacy_leaf': rows[0]['selected'] != rows[2]['selected'],
                    'leaf_only_changed_action_with_v2_beam': rows[2]['selected'] != rows[3]['selected']})
    for u, group in ((0, 'B'), (3, 'D')):
        saved = read(EP/f'L2_E5_SRC04_C{q-1}_{group}_buffer_search_oracle_ast.json')['events'][3]
        chosen = next(c for c in saved['candidates'] if c['candidate_id'] == saved['action']['candidate_id'])
        checks[f'Q{q}_U{u}_saved_action'] = results[f'Q{q}_U{u}']['selected'] == pose(chosen)
for q in (3, 4):
    a, b = [results[f'Q{q}_{g}'] for g in ('legacy', 'B')]
    shared = {n['path_digest']: n for n in a['nodes']}
    different_descendants = []
    for n in b['nodes']:
        old = shared.get(n['path_digest'])
        if old is not None and n['depth'] and sets(old) != sets(n):
            different_descendants.append({'path': n['path'], 'state_equal': old['state_digest'] == n['state_digest'],
                                           'A': sets(old), 'B': sets(n), 'spent_A': old['spent_after'], 'spent_B': n['spent_after']})
    beam_differences = []
    for la, lb in zip(a['levels'], b['levels']):
        sa, sb = [[c['path'] for c in l['children'] if c['status'] == 'survived'] for l in (la, lb)]
        if sa != sb: beam_differences.append({'depth': la['depth'], 'A': sa, 'B': sb})
    qualification = {}
    branch_exposure = {}
    for group, r in [('A', a), ('B', b)]:
        matched = [c for g in r['nodes'][0]['groups'] for c in g['candidates'] if c['pose'] == b['selected']]
        qualification[group] = [c['status'] for c in matched]
        branch_exposure[group] = {'expanded': [{'path': n['path'], 'cost': n['candidate_count']} for n in r['nodes'] if n['path'] and n['path'][0] == b['selected']],
                                 'budget_refused': [n['path'] for n in r['budget_refusals'] if n['path'][0] == b['selected']],
                                 'beam_positions': [{'depth': l['depth'], 'status': c['status'], 'path': c['path']} for l in r['levels'] for c in l['children'] if c['path'][0] == b['selected']]}
    candidate.append({'q': f'Q{q}', 'A_selected': a['selected'], 'B_selected': b['selected'],
                      'B_action_root_qualification': qualification, 'root_A': sets(a['nodes'][0]), 'root_B': sets(b['nodes'][0]),
                      'first_different_shared_descendant': different_descendants[0] if different_descendants else None,
                      'first_beam_difference': beam_differences[0] if beam_differences else None,
                      'first_budget_refusal_A': a['budget_refusals'][0] if a['budget_refusals'] else None,
                      'first_budget_refusal_B': b['budget_refusals'][0] if b['budget_refusals'] else None,
                      'B_action_branch_exposure': branch_exposure})
    for g, r in [('A', a), ('B', b)]:
        saved = read(EP/f'L2_E5_SRC04_C{q-3}_{g}_buffer_search_oracle_ast.json')['events'][5]
        chosen = next(c for c in saved['candidates'] if c['candidate_id'] == saved['action']['candidate_id'])
        checks[f'Q{q}_{g}_saved_action'] = r['selected'] == pose(chosen)
        old_groups = {g['pick_item_id']: g for g in saved['groups']}
        checks[f'Q{q}_{g}_root_poses_and_eligible'] = all(
            sorted(c['pose'] for c in n['candidates']) == sorted(pose(c) for c in old_groups[n['pick']]['candidates']) and
            sorted(c['pose'] for c in n['candidates'] if c['status'] == 'eligible') == sorted(pose(c) for c in old_groups[n['pick']]['eligible'])
            for n in r['nodes'][0]['groups'])
checks.update(budget_all_256_or_less=all(r['evaluations'] <= 256 for r in results.values()),
              beam_all_eight_or_less=all(r['max_beam_observed'] <= 8 for r in results.values()),
              roots_unchanged=all(r['root_unchanged'] for r in results.values()))
output = {'checks': checks, 'ranking_decomposition': ranking, 'candidate_mechanism': candidate,
          'search_calls': 12, 'additional_search_calls': 0, 'new_api_attempts': 0,
          'scope': 'fixed states and generated frontier only; not global optimality or full-order causal isolation'}
dest = Path(__file__).with_name('t0_interpretation.json')
with dest.open('x') as f: json.dump(output, f, ensure_ascii=False, indent=2); f.write('\n')
print(json.dumps({'checks': checks, 'ranking': ranking, 'candidate': [
    {'q': c['q'], 'A': c['A_selected'], 'B': c['B_selected'], 'common_descendant_difference': c['first_different_shared_descendant'] is not None,
     'first_beam_difference_depth': c['first_beam_difference']['depth'] if c['first_beam_difference'] else None,
     'branch_expanded_nodes': {g: len(v['expanded']) for g,v in c['B_action_branch_exposure'].items()}} for c in candidate]}, ensure_ascii=False, indent=2))
assert all(checks.values()), checks
