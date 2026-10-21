"""Execute the same saved failure requests under two interpreters; never call API."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT/'semantic_pallet_planner/outputs/EXP_OPT_O3_LAYOUT_VALIDATION_20261019_01'
CASES = [('safe', '0053', 'P0', 4), ('safe', '0053', 'P1', 6),
         ('observe_business', '0053', 'P0', 4), ('observe_business', '0053', 'P1', 6),
         ('observe_business', '0056', 'P1', 9)]


def worker():
    import socket
    def forbidden(*args, **kwargs):
        raise RuntimeError('network forbidden in cross-runtime regression')
    socket.create_connection = forbidden
    from semantic_pallet_planner.selectors.layout_preserving_v2 import select_layout, VERSION
    from semantic_pallet_planner.selectors.instruction_parser_o1b import resolved_public_policy
    rows = []
    for mode, source, policy_id, index in CASES:
        name = f'O3_SCN_{source}_{policy_id}'
        path = BASELINE/'episodes'/mode/'relaxed_wo_floor'/name/'steps.jsonl'
        event = json.loads(path.read_text().splitlines()[index])
        req = event['request']
        policy = resolved_public_policy(req['instruction_text'], req)
        for variant in ('original', 'relaxed_geometry', 'relaxed_wo_floor'):
            label, trace = select_layout(req, policy, variant, allow_business_violation=mode == 'observe_business')
            rows.append({'case': f'{mode}/{name}/{index}', 'variant': variant,
                         'selected_label': label, 'trace': trace})
    return {'python': sys.version, 'executable': sys.executable, 'ranking_version': VERSION,
            'network_calls': 0, 'cases': rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--worker', action='store_true')
    ap.add_argument('--python', nargs=2)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    if args.worker:
        print(json.dumps(worker(), ensure_ascii=False))
        return
    if not args.python or not args.output:
        ap.error('--python EXE1 EXE2 and --output are required')
    if args.output.exists():
        raise FileExistsError(args.output)
    result = []
    for exe in args.python:
        completed = subprocess.run([exe, str(Path(__file__).resolve()), '--worker'], cwd=ROOT,
            env=dict(os.environ, PYTHONPATH=str(ROOT/'semantic_pallet_planner/src')),
            capture_output=True, text=True, check=True)
        result.append(json.loads(completed.stdout))
    sys.path.insert(0, str(ROOT/'semantic_pallet_planner/src'))
    from semantic_pallet_planner.evaluation.replay_values_v2 import replay_values_equal
    failures = []
    for a, b in zip(result[0]['cases'], result[1]['cases']):
        if not replay_values_equal(a, b):
            failures.append(a['case']+'/'+a['variant'])
    if len(result[0]['cases']) != len(result[1]['cases']):
        failures.append('case count')
    report = {'status': 'FAIL' if failures else 'PASS', 'compared_cases': len(result[0]['cases']),
              'failures': failures, 'runtimes': result, 'real_api_calls': 0}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'runtimes'}))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
