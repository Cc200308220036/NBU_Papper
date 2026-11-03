"""Separate compilation, policy, completion, N/A and full planned denominators."""
from collections import defaultdict, Counter


def group_key(row):
    return row['source_kind'], str(row['configuration']), row['backend'], row['planner']


def aggregate(results, jobs):
    groups = defaultdict(list)
    planned = defaultdict(list)
    recorded = 0
    for job in jobs:
        if all(k in job for k in ('source_kind', 'configuration', 'backend', 'planner')):
            planned[group_key(job)].append(job)
    for result in results:
        recorded += 1
        groups[group_key(result['summary'])].append(result)
    rows = []
    for key in sorted(groups.keys() | planned.keys()):
        kind, configuration, backend, planner = key
        runs = groups[key]
        group_jobs = planned.get(key, [])
        total = len(group_jobs) if group_jobs else len(runs)
        decisions = [e for r in runs for e in r['events'] if 'compilation' in e]
        compilations = [e['compilation'] for e in decisions]
        # Failed/invalid compilations have no semantic comparison. They remain
        # in the compilation denominator and are never silently counted valid.
        events = [e for r in runs for e in r['events'] if 'compilation_metrics' in e]
        components = {}
        keys = sorted({k for e in events for k, v in e['compilation_metrics'].items()
                       if isinstance(v, bool) or v is None})
        for name in keys:
            values = [e['compilation_metrics'].get(name) for e in events]
            components[name] = {'correct': sum(v is True for v in values),
                                'comparable': sum(v is not None for v in values),
                                'not_comparable': sum(v is None for v in values)}
        applicability = defaultdict(Counter)
        for result in runs:
            for rule in result['summary']['task_rule_presence']:
                counts = applicability[rule['type']]
                counts['planned_rule_occurrences'] += 1
                counts['planned_without_targets_NA'] += not rule['has_targets_in_planned_order']
        for event in events:
            for rule in event['rule_activity']:
                counts = applicability[rule['type']]
                counts['checked_rule_steps'] += rule['checked_instances'] > 0
                counts['checked_instances'] += rule['checked_instances']
                counts['deferred_rule_steps'] += rule['deferred']
                counts['no_placed_target_or_pair_steps'] += rule['status'] in ('no_placed_target', 'no_placed_pair', 'not_applicable')
                counts['overridden_rule_steps'] += rule['status'] == 'overridden'
        summaries = [r['summary'] for r in runs]
        recorded_planned_items = sum(s['planned_items'] for s in summaries)
        planned_items = sum(j['planned_items'] for j in group_jobs) if group_jobs and all('planned_items' in j for j in group_jobs) else recorded_planned_items
        placed = sum(s['placed_items'] for s in summaries)
        completed = sum(s['completed'] for s in summaries)
        clean = sum(s['clean_completed'] for s in summaries)
        violating = sum(s['violating_steps'] for s in summaries)
        final_valid = sum(c['status'] == 'valid' for c in compilations)
        first_valid = sum(c['first_valid'] for c in compilations)
        rows.append({
            'source_kind': kind, 'configuration': configuration, 'backend': backend, 'planner': planner,
            'planned_episodes': total, 'recorded_episodes': len(runs), 'unrecorded_episodes': total-len(runs),
            'measurement_complete': len(runs) == total,
            'independent_sources': len({s['source_order_key'] for s in summaries}) if kind != 'constructed' else 0,
            'planned_independent_sources': len({j['source_order_key'] for j in group_jobs}) if kind != 'constructed' else 0,
            'execution_pass': sum(s['execution_status'] == 'PASS' for s in summaries),
            'completed': completed, 'clean_completed': clean,
            'completed_over_planned': completed/total if total else None,
            'clean_completed_over_planned': clean/total if total else None,
            'planned_items': planned_items, 'planned_items_in_recorded_episodes': recorded_planned_items,
            'placed_item_ratio_over_planned': placed/planned_items if planned_items else None,
            'placed_items': placed,
            'mean_placed_item_ratio': sum(s['placed_item_ratio'] for s in summaries)/len(runs) if runs else None,
            'mean_placed_volume_ratio': sum(s['placed_volume_ratio'] for s in summaries)/len(runs) if runs else None,
            'violating_steps': violating, 'business_violation_step_rate': violating/placed if placed else None,
            'submitted_violation_instances': sum(len(e['reference_after']['violations']) for e in events
                                                 if e.get('action') or e.get('submitted')),
            'commit_failures': sum(e['event'] == 'COMMIT_FAILURE' for e in decisions),
            'physical_commit_rejections': sum((e.get('commit_error') or {}).get('code') in
                                              ('physical_rejection', 'physical_violation') for e in decisions),
            'termination_reasons': dict(Counter(s['termination_reason'] for s in summaries)),
            'compilation': {'decisions': len(compilations), 'first_valid': first_valid,
                            'repaired_valid': sum(c['repaired_valid'] for c in compilations),
                            'final_valid': final_valid, 'final_invalid_or_failed': len(compilations)-final_valid,
                            'first_valid_rate': first_valid/len(compilations) if compilations else None,
                            'final_valid_rate': final_valid/len(compilations) if compilations else None},
            'components': components,
            'component_scope': 'symbolic AST comparisons on valid-AST decisions, including rejected commits; comparability is not physical applicability',
            'invalid_compilation_semantics': 'not scored; failures remain in compilation and full job denominators',
            'rule_activity': {k: dict(v) for k, v in applicability.items()},
            'false_allow': sum(len(e['compilation_metrics']['false_allow_ids']) for e in events),
            'false_reject': sum(len(e['compilation_metrics']['false_reject_ids']) for e in events),
            'rule_applicability_states': dict(Counter(v['status'] for e in events for v in e['reference_after']['relation_status'].values()))})
    return {'planned_jobs': len(jobs), 'recorded_episodes': recorded,
            'job_statuses': dict(Counter(j['status'] for j in jobs)), 'groups': rows,
            'interpretation': 'constructed orders and source/configuration repeats are not new independent sources; group means describe recorded episodes and measurement_complete marks missing jobs'}
