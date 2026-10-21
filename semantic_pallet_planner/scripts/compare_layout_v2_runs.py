"""Certify all stable-v2 offline trajectories; discrete actions/hashes stay exact."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from semantic_pallet_planner.runners.attribute_pilot_v2 import read_json, sha, write_json
from semantic_pallet_planner.runners.layout_ablation import inventory
from semantic_pallet_planner.runners.layout_flash_validation_v2 import events_at, VERSION, RANKING_VERSION
from semantic_pallet_planner.evaluation.replay_values_v2 import replay_values_equal


def compare(baseline, peer):
    baseline, peer = Path(baseline).resolve(), Path(peer).resolve()
    a, b = read_json(baseline/'manifest.json'), read_json(peer/'manifest.json')
    failures = []
    for key in ('version', 'ranking_version', 'ranking_epsilon', 'task_digest', 'config_digest',
                'variants', 'modes', 'parsers', 'source_sha256', 'dataset_sha256', 'planned_episodes'):
        if a[key] != b[key]:
            failures.append('manifest:'+key)
    if a['version'] != VERSION or a['ranking_version'] != RANKING_VERSION or a['remote'] or b['remote']:
        failures.append('not stable offline v2')
    if b['baseline_root'] != str(baseline):
        failures.append('peer reference binding')
    for path in (baseline, peer):
        if read_json(path/'acceptance_report.json')['status'] != 'PASS' or read_json(path/'replay_report.json')['status'] != 'PASS':
            failures.append(str(path)+':not accepted')
        if read_json(path/'api_usage.json')['actual_attempts'] != 0:
            failures.append(str(path)+':unexpected API calls')
    runtimes = [read_json(p/'environment.json')['python'] for p in (baseline, peer)]
    minors = ['.'.join(v.split()[0].split('.')[:2]) for v in runtimes]
    if len(set(minors)) != 2:
        failures.append('not two distinct Python minor versions')
    tasks = read_json(baseline/'data/tasks.private.json')
    count = steps = 0
    per_variant = {}
    for mode in a['modes']:
        for variant in a['variants']:
            for task in tasks:
                prefix = f'{mode}/{variant}/{task["episode_id"]}'
                ad, ae = events_at(baseline, mode, variant, 'public_parser', task)
                bd, be = events_at(peer, mode, variant, 'public_parser', task)
                if len(ae) != len(be):
                    failures.append(prefix+':event count')
                for index, (x, y) in enumerate(zip(ae, be)):
                    # Each local replay separately verifies these digest bindings.
                    # Cross-version raw candidate floats can legitimately differ at 1e-16.
                    xx = {k: v for k, v in x.items() if k != 'candidate_set_digest'}
                    yy = {k: v for k, v in y.items() if k != 'candidate_set_digest'}
                    if not replay_values_equal(xx, yy):
                        failures.append(prefix+f':event {index}')
                    steps += 1
                if not replay_values_equal(read_json(ad/'episode.json')['summary'], read_json(bd/'episode.json')['summary']):
                    failures.append(prefix+':summary')
                count += 1
                per_variant[mode+'/'+variant] = per_variant.get(mode+'/'+variant, 0)+1
    if count != a['planned_episodes'] or count != b['planned_episodes']:
        failures.append('matrix incomplete')
    if not replay_values_equal(read_json(baseline/'metrics/summary.json'), read_json(peer/'metrics/summary.json')):
        failures.append('aggregate metrics')
    return {'status': 'FAIL' if failures else 'PASS', 'baseline_root': str(baseline), 'peer_root': str(peer),
        'baseline_manifest_sha256': sha(baseline/'manifest.json'), 'peer_manifest_sha256': sha(peer/'manifest.json'),
        'python_versions': runtimes, 'python_minor_versions': minors, 'matched_episodes': count if not failures else 0,
        'compared_episodes': count, 'compared_events': steps, 'per_variant': per_variant,
        'discrete_action_and_state_hash_comparison': 'EXACT', 'finite_float_abs_tolerance': 1e-9,
        'excluded_cross_runtime_fields': ['candidate_set_digest (each runtime independently verified)'],
        'failures': failures, 'real_api_calls': 0, 'ranking_version': RANKING_VERSION}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--peer', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--certify', action='store_true', help='also save certificate in accepted baseline')
    args = ap.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = compare(args.baseline, args.peer)
    write_json(args.output, result)
    if args.certify and result['status'] == 'PASS':
        destination = args.baseline/'cross_runtime_report.json'
        if destination.exists():
            raise FileExistsError(destination)
        write_json(destination, result)
        contents = inventory(args.baseline)
        contents.pop('delivery_manifest.json', None)
        write_json(args.baseline/'delivery_manifest.json', contents)
    print(json.dumps({k: v for k, v in result.items() if k not in ('python_versions', 'per_variant')}, indent=2))
    if result['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
