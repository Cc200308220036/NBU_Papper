"""Derived descriptive tables. Does not edit the sealed experiment."""
import json
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path('/home/cyw/NBU_Papper')
EXP = BASE/'semantic_pallet_planner/outputs/EXP_O4_E5_090_OFFLINE_20261026_06'
OUT = BASE/'report/analysis/O4_E5_DEVELOPMENT_20261026_01'

def read(path):
    return json.loads(path.read_text())

groups = defaultdict(list)
sources = []
activity = defaultdict(Counter)
for job in read(EXP/'audit/jobs.json'):
    if job['status'] != 'PASS':
        continue
    result = read(EXP/f"episodes/{job['job_id']}.json")
    summary = result['summary']
    groups[(summary['source_kind'], summary['backend'], summary['planner'])].append(summary)
    sources.append({'job_id': job['job_id'], **summary})
    for rule in summary['task_rule_presence']:
        row = activity[(summary['source_kind'], rule['type'])]
        row['planned_occurrences'] += 1
        row['planned_without_targets_NA'] += not rule['has_targets_in_planned_order']
    for event in result['events']:
        for rule in event.get('rule_activity', []):
            row = activity[(summary['source_kind'], rule['type'])]
            row['checked_rule_steps'] += rule['checked_instances'] > 0
            row['checked_instances'] += rule['checked_instances']
            row['deferred_rule_steps'] += rule['deferred']
            row['overridden_rule_steps'] += rule['status'] == 'overridden'

rows = []
for (kind, backend, planner), runs in sorted(groups.items()):
    n = len(runs)
    placed = sum(s['placed_items'] for s in runs)
    violations = sum(s['violating_steps'] for s in runs)
    rows.append({
        'source_kind': kind, 'backend': backend, 'planner': planner,
        'episodes': n, 'completed': sum(s['completed'] for s in runs),
        'completed_without_any_violating_step': sum(s['completed'] and not s['final_business_violations'] and s['violating_steps'] == 0 for s in runs),
        'planned_items': sum(s['planned_items'] for s in runs), 'placed_items': placed,
        'mean_item_ratio': sum(s['placed_item_ratio'] for s in runs)/n,
        'mean_volume_ratio': sum(s['placed_volume_ratio'] for s in runs)/n,
        'violating_steps': violations, 'business_violation_step_rate': violations/placed if placed else None,
        'termination_reasons': dict(Counter(s['termination_reason'] for s in runs)),
    })
payload = {'scope': 'descriptive derived tables; not additional experimental samples',
           'recorded_jobs': len(sources), 'groups': rows,
           'rule_activity': [{'source_kind': k[0], 'rule_type': k[1], **v} for k, v in sorted(activity.items())]}
(OUT/'descriptive_summary.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
(OUT/'per_job_summaries.json').write_text(json.dumps(sources, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({'recorded_jobs': len(sources), 'groups': rows}, ensure_ascii=False, indent=2))

# The final watcher calls this only after authoritative full-matrix audits.
if (OUT/'evidence.json').is_file():
    import contextlib
    import io
    import runpy
    document_log=io.StringIO()
    with contextlib.redirect_stdout(document_log):
        runpy.run_path(str(OUT/'document_delivery.py'),run_name='__main__')
    (OUT/'document_delivery_stdout.txt').write_text(document_log.getvalue())
