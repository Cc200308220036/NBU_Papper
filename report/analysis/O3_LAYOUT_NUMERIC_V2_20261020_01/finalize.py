"""Verify frozen evidence and collect completed v2 offline/cross-runtime checks."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = ROOT/'semantic_pallet_planner/outputs'
A = OUT/'EXP_OPT_O3_LAYOUT_STABLE_V2_PY311_20261020_01'
B = OUT/'EXP_OPT_O3_LAYOUT_STABLE_V2_PY313_20261020_01'


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def inventory(p):
    return {str(f.relative_to(p)): sha(f) for f in sorted(p.rglob('*')) if f.is_file()}


def table(p):
    with p.open(encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def write(p, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def main():
    before = read(HERE/'protected_runs.before.json')
    after = {name: inventory(OUT/name) for name in before}
    changed = [name for name in before if before[name] != after[name]]
    write(HERE/'protected_runs.after.json', after)
    source = ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
    legacy = read(HERE/'legacy_source.before.json')
    source_changes = [n for n, h in legacy.items() if sha(source/n) != h]
    certificate = read(A/'cross_runtime_report.json')
    regression = {v: read(HERE/f'tests.{v}.json') for v in ('py311', 'py313')}
    matrix = {v: read(HERE/f'matrix.{v}.json') for v in ('py311', 'py313')}
    acceptance = {v: read(p/'acceptance_report.json') for v, p in [('py311', A), ('py313', B)]}
    api_calls = sum(read(p/'api_usage.json')['actual_attempts'] for p in (A, B))
    checks = {'old_experiments_unchanged': not changed, 'legacy_source_unchanged': not source_changes,
        'two_regression_suites_passed': all(v['exit_code'] == 0 for v in regression.values()),
        'both_120_episode_runs_accepted': all(v['exit_code'] == 0 for v in matrix.values())
            and all(v['status'] == 'PASS' and v['episodes'] == 120 for v in acceptance.values()),
        'cross_runtime_120_matches': certificate['status'] == 'PASS' and certificate['matched_episodes'] == 120,
        'saved_failure_requests_match': read(HERE/'saved_request_cross_runtime.json')['status'] == 'PASS',
        'no_api_calls': api_calls == 0,
        'old_B_pass_C_fail_retained': read(OUT/'EXP_OPT_O3_LAYOUT_FLASH_SMOKE_20261020_01/acceptance_report.json')['status'] == 'PASS'
            and read(OUT/'EXP_OPT_O3_LAYOUT_FLASH_VALIDATION_20261020_01/acceptance_report.json')['status'] == 'FAIL'}
    result = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
        'protected_files': sum(map(len, before.values())), 'protected_experiments': len(before),
        'changed_experiments': changed, 'changed_legacy_source': source_changes,
        'unique_logical_episodes': 120, 'independent_runtime_executions': 240,
        'cross_runtime_events': certificate['compared_events'], 'tests_per_runtime': 185,
        'real_api_calls': api_calls, 'api_experiments_delegated_to_user': True}
    write(HERE/'acceptance_report.json', result)
    write(HERE/'verification_report.json', {'regression': regression, 'offline_matrices': matrix,
        'ranking_certificate': certificate, 'package_source_sha256': read(A/'manifest.json')['source_sha256'],
        'extra_source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in [
            ROOT/'semantic_pallet_planner/scripts/check_layout_v2_cross_runtime.py',
            ROOT/'semantic_pallet_planner/scripts/compare_layout_v2_runs.py',
            ROOT/'semantic_pallet_planner/tests/unit/test_layout_preserving_v2.py',
            ROOT/'semantic_pallet_planner/tests/integration/test_layout_numeric_v2.py']}})
    keys = ('placed_items', 'completed', 'clean_completed', 'final_business_violation_count', 'violating_steps', 'termination_reason')
    changes = []
    current = table(A/'metrics/per_episode.csv')
    for label, old in [('legacy_layout', OUT/'EXP_OPT_O3_LAYOUT_VALIDATION_20261019_01'),
                       ('v1_flash_C', OUT/'EXP_OPT_O3_LAYOUT_FLASH_VALIDATION_20261020_01')]:
        previous = {(r['mode'], r['variant'], r['episode_id']): r for r in table(old/'metrics/per_episode.csv')
                    if r.get('parser', 'public_parser') == 'public_parser'}
        for row in current:
            prior = previous[row['mode'], row['variant'], row['episode_id']]
            delta = {key: {'old': prior[key], 'new': row[key]} for key in keys if row[key] != prior[key]}
            if delta:
                changes.append({'reference': label, 'mode': row['mode'], 'variant': row['variant'],
                                'episode_id': row['episode_id'], 'changes': delta})
    write(HERE/'version_metric_changes.json', changes)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
