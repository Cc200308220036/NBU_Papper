"""Read-only extraction of completed B/C evidence. No API calls or source edits."""
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = ROOT/'semantic_pallet_planner/outputs'
OLD = OUT/'EXP_OPT_O3_LAYOUT_VALIDATION_20261019_01'
RUNS = {k: OUT/f'EXP_OPT_O3_LAYOUT_FLASH_{v}_20261020_01'
        for k, v in [('B', 'SMOKE'), ('C', 'VALIDATION')]}


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def table(p):
    with p.open(encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def events(p):
    return [json.loads(s) for s in p.read_text().splitlines()]


def write(name, data):
    (HERE/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def main():
    baseline_manifest = read(OLD/'manifest.json')
    result = {}
    for stage, p in RUNS.items():
        manifest = read(p/'manifest.json')
        agreement = table(p/'metrics/parser_flash_agreement.csv')
        delivery = read(p/'delivery_manifest.json')
        bad = [n for n, h in delivery.items() if not (p/n).exists() or sha(p/n) != h]
        shared = set(baseline_manifest['source_sha256']) & set(manifest['source_sha256'])
        result[stage] = {
            'root': str(p.relative_to(ROOT)), 'acceptance': read(p/'acceptance_report.json'),
            'api_usage': read(p/'api_usage.json'), 'recorded_replay': read(p/'replay_report.json'),
            'summary': read(p/'metrics/summary.json'),
            'agreement_rows': len(agreement),
            'agreement_true': {k: sum(r[k] == 'True' for r in agreement)
                for k in ('ast_equal', 'same_state_action_equal', 'closed_loop_states_equal')},
            'delivery_files_checked': len(delivery), 'delivery_digest_failures': bad,
            'shared_source_files': len(shared),
            'shared_source_differences': sorted(n for n in shared if
                baseline_manifest['source_sha256'][n] != manifest['source_sha256'][n]),
            'review_replay': read(HERE/f'{stage}_replay.json'),
            'paired_comparisons': read(p/'metrics/paired_cluster_comparisons.json')}
        assert not bad
    before = {(r['mode'], r['variant'], r['episode_id']): r for r in table(OLD/'metrics/per_episode.csv')}
    summary_diff = []
    for r in table(RUNS['C']/'metrics/per_episode.csv'):
        if r['parser'] != 'public_parser':
            continue
        previous = before[r['mode'], r['variant'], r['episode_id']]
        changes = {k: {'old': previous[k], 'new': r[k]} for k in
            ('placed_items', 'completed', 'clean_completed', 'final_business_violation_count',
             'violating_steps', 'termination_reason') if previous[k] != r[k]}
        if changes:
            summary_diff.append({'mode': r['mode'], 'variant': r['variant'], 'episode_id': r['episode_id'],
                                 'changes': changes})
    divergences = []
    for failure in result['C']['recorded_replay']['failures']:
        location, reason = failure.split(':', 1)
        mode, variant, parser, episode = location.split('/')
        old = events(OLD/'episodes'/mode/variant/episode/'steps.jsonl')
        new = events(RUNS['C']/'episodes'/mode/variant/parser/episode/'steps.jsonl')
        for a, b in zip(old, new):
            if a['committed_label'] == b['committed_label'] and a['after_state_hash'] == b['after_state_hash']:
                continue
            labels = {a['committed_label'], b['committed_label']}
            divergences.append({'location': location, 'reason': reason, 'zero_based_step': a['step_index'],
                'same_before_state': a['before_state_hash'] == b['before_state_hash'],
                'exact_same_request': a['request'] == b['request'],
                'same_eligible_labels': a['trace'].get('eligible_labels') == b['trace'].get('eligible_labels'),
                'old_label': a['committed_label'], 'new_label': b['committed_label'],
                'old_scores': {k: v for k, v in a['trace']['layout_scores'].items() if k in labels},
                'new_scores': {k: v for k, v in b['trace']['layout_scores'].items() if k in labels}})
            break
    write('review_data.json', result)
    write('historical_summary_changes.json', summary_diff)
    write('first_divergences.json', divergences)
    features = divergences[0]['new_scores']['C11']['features']
    vector = [features[k] for k in ('support', 'capacity', 'height')]
    numeric = []
    for exe in [sys.executable, '/home/cyw/anaconda3/envs/pallet_vlm/bin/python']:
        process = subprocess.run([exe, '-c',
            'import json,sys; v=json.loads(sys.argv[1]); print(sys.version.split()[0],repr(sum(v)/len(v)))',
            json.dumps(vector)], capture_output=True, text=True, check=True)
        numeric.append({'executable': exe, 'version_and_result': process.stdout.strip()})
    write('numeric_reproduction.json', {'input_features': vector, 'results': numeric})
    names = ('manifest.json', 'acceptance_report.json', 'replay_report.json', 'api_usage.json',
             'metrics/summary.json', 'metrics/per_episode.csv', 'metrics/parser_flash_agreement.csv',
             'metrics/paired_cluster_comparisons.json', 'delivery_manifest.json')
    write('provenance.json', {'source_files': {str((p/n).relative_to(ROOT)): sha(p/n)
          for p in RUNS.values() for n in names}, 'analysis_script_sha256': sha(Path(__file__)),
          'new_api_calls': 0, 'source_experiments_modified': False})
    print('B:', result['B']['review_replay']['status'], 'C:', result['C']['review_replay']['status'],
          'historical divergence cases:', len(divergences))


if __name__ == '__main__':
    main()
