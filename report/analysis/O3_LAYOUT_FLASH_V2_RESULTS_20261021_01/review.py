"""Read-only V2 real-run analysis. Never invokes a model or changes an experiment."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = ROOT/'semantic_pallet_planner/outputs'
BASELINE = OUT/'EXP_OPT_O3_LAYOUT_STABLE_V2_PY311_20261020_01'
RUNS = {'B': OUT/'EXP_OPT_O3_LAYOUT_FLASH_V2_SMOKE_20261020_01',
        'C': OUT/'EXP_OPT_O3_LAYOUT_FLASH_V2_VALIDATION_20261020_01'}


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def table(p):
    with p.open(encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def events(p):
    return [json.loads(s) for s in p.read_text().splitlines()]


def normalized(ast):
    result = json.loads(json.dumps(ast))
    if result['schema_version'] == 'pallet_policy_o1b_conditional_1':
        then, otherwise = normalized(result['then_policy']), normalized(result['else_policy'])
        if then == otherwise:
            return then
        result['then_policy'], result['else_policy'] = then, otherwise
        return result
    result['hard_constraints'].sort(key=lambda v: json.dumps(v, sort_keys=True))
    result['soft_priorities'].sort(key=lambda v: v['priority'])
    return result


def write(name, data):
    (HERE/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def main():
    output, provenance = {}, {}
    for stage, root in RUNS.items():
        manifest = read(root/'manifest.json')
        tasks = read(root/'data/tasks.private.json')
        rows = table(root/'metrics/per_episode.csv')
        agreement = table(root/'metrics/parser_flash_agreement.csv')
        delivery = read(root/'delivery_manifest.json')
        bad = [n for n, h in delivery.items() if not (root/n).exists() or sha(root/n) != h]
        assert not bad, bad
        paired, paired_steps, paired_ast, mismatches = 0, 0, 0, []
        conditional_ast_count = redundant_conditions = 0
        full_ast_semantic_mismatches = []
        for mode in manifest['modes']:
            for variant in manifest['variants']:
                for task in tasks:
                    path = root/'episodes'/mode/variant
                    a = events(path/'public_parser'/task['episode_id']/'steps.jsonl')
                    b = events(path/'flash'/task['episode_id']/'steps.jsonl')
                    if len(a) != len(b):
                        mismatches.append(f'{mode}/{variant}/{task["episode_id"]}:length')
                    for x, y in zip(a, b):
                        for field in ('request', 'before_state_hash', 'after_state_hash', 'after_placed',
                                      'proposed_label', 'committed_label', 'status'):
                            if x[field] != y[field]:
                                mismatches.append(f'{mode}/{variant}/{task["episode_id"]}/{x["step_index"]}:{field}')
                        if y['policy_ast'] is not None:
                            paired_ast += 1
                            if normalized(x['resolved_policy']) != normalized(y['resolved_policy']):
                                mismatches.append(f'{mode}/{variant}/{task["episode_id"]}/{x["step_index"]}:AST')
                            ast = y['policy_ast']
                            if ast['schema_version'] == 'pallet_policy_o1b_conditional_1':
                                conditional_ast_count += 1
                                redundant_conditions += normalized(ast['then_policy']) == normalized(ast['else_policy'])
                            if normalized(x['policy_ast']) != normalized(ast):
                                full_ast_semantic_mismatches.append(f'{mode}/{variant}/{task["episode_id"]}/{x["step_index"]}')
                        paired_steps += 1
                    paired += 1
        assert not mismatches, mismatches
        conditional = {}
        lookup = {(r['mode'], r['variant'], r['episode_id']): r for r in rows if r['parser'] == 'flash'}
        changes = []
        for mode in manifest['modes']:
            for variant in manifest['variants']:
                data = [r for r in rows if (r['mode'], r['variant'], r['parser']) == (mode, variant, 'flash')]
                completed = sum(r['completed'] == 'True' for r in data)
                clean = sum(r['clean_completed'] == 'True' for r in data)
                conditional[mode+'/'+variant] = {'completed_with_final_violations': completed-clean,
                    'completed_order_final_violation_rate': (completed-clean)/completed if completed else None,
                    'any_violating_step_episodes': sum(int(r['violating_steps']) > 0 for r in data),
                    'all_attempt_violation_rate': sum(int(r['violating_steps']) > 0 for r in data)/len(data),
                    'cohorts': {str(flag): {'episodes': sum((r['completed'] == 'True') == flag for r in data),
                        'placed_items': sum(int(r['placed_items']) for r in data if (r['completed'] == 'True') == flag),
                        'violating_steps': sum(int(r['violating_steps']) for r in data if (r['completed'] == 'True') == flag),
                        'final_instances': sum(int(r['final_business_violation_count']) for r in data if (r['completed'] == 'True') == flag)}
                        for flag in (True, False)},
                    'incomplete': [{k: r[k] for k in ('episode_id','planned_items','placed_items','termination_reason','final_business_violation_count')}
                                   for r in data if r['completed'] != 'True']}
                if variant == 'original':
                    continue
                gain, loss = [], []
                for r in data:
                    prior = lookup[mode, 'original', r['episode_id']]
                    if r['clean_completed'] != prior['clean_completed']:
                        (gain if r['clean_completed'] == 'True' else loss).append(r['episode_id'])
                changes.append({'mode': mode, 'variant': variant, 'clean_gains_vs_original': gain, 'clean_losses': loss})
        output[stage] = {'root': str(root.relative_to(ROOT)), 'acceptance': read(root/'acceptance_report.json'),
            'recorded_replay': read(root/'replay_report.json'), 'fresh_read_only_replay': read(HERE/f'{stage}_replay.json'),
            'api': read(root/'api_usage.json'), 'execution_checks': read(root/'audit/execution_checks.json'),
            'summary': read(root/'metrics/summary.json'), 'comparisons': read(root/'metrics/paired_cluster_comparisons.json'),
            'csv_agreement_rows': len(agreement), 'csv_agreement_true': {k: sum(r[k] == 'True' for r in agreement)
                for k in ('ast_equal','same_state_action_equal','closed_loop_states_equal')},
            'independent_episode_pairs': paired, 'independent_paired_events': paired_steps,
            'independent_paired_AST': paired_ast, 'independent_pair_mismatches': mismatches,
            'conditional_AST_count': conditional_ast_count, 'identical_branch_conditions': redundant_conditions,
            'full_AST_semantic_mismatches_after_identical_branch_reduction': full_ast_semantic_mismatches,
            'delivery_files_verified': len(delivery), 'delivery_failures': bad,
            'conditional_metrics': conditional, 'clean_gain_cases': changes,
            'ranking_version': manifest['ranking_version'], 'baseline_root': manifest['baseline_root'],
            'source_matches_baseline': manifest['source_sha256'] == read(BASELINE/'manifest.json')['source_sha256']}
        output[stage]['same_completed_observe_cohort_between_relaxed_variants'] = (
            {r['episode_id'] for r in rows if r['parser'] == 'flash' and r['mode'] == 'observe_business'
                and r['variant'] == 'relaxed_geometry' and r['completed'] == 'True'} ==
            {r['episode_id'] for r in rows if r['parser'] == 'flash' and r['mode'] == 'observe_business'
                and r['variant'] == 'relaxed_wo_floor' and r['completed'] == 'True'})
        for name in ('acceptance_report.json','manifest.json','replay_report.json','api_usage.json',
                     'metrics/summary.json','metrics/per_episode.csv','metrics/parser_flash_agreement.csv',
                     'metrics/paired_cluster_comparisons.json','delivery_manifest.json'):
            provenance[str((root/name).relative_to(ROOT))] = sha(root/name)
    write('review_data.json', output)
    write('provenance.json', {'source_files': provenance, 'review_script_sha256': sha(Path(__file__)),
                            'new_API_calls': 0, 'source_experiments_modified': False})
    print({k: {'acceptance': v['acceptance']['status'], 'fresh_replay': v['fresh_read_only_replay']['status'],
               'pairs': v['independent_episode_pairs'], 'AST': v['independent_paired_AST'],
               'delivery_files_verified': v['delivery_files_verified']} for k, v in output.items()})


if __name__ == '__main__':
    main()
