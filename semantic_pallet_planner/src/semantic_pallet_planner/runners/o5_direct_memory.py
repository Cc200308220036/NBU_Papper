"""O5 S0/S1 independent offline CLI. No API key or remote flag is accepted."""
import argparse
import json
from ..o5 import data, experiment


def main(argv=None):
    p = argparse.ArgumentParser(description='O5 S0/S1 offline physical candidate-selection research')
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('prepare-data')
    s.add_argument('--output', required=True)
    s.add_argument('--config')
    s.add_argument('--rule-plan', required=True)
    s = sub.add_parser('freeze-data-rule', help='freeze approved geometric quantile rule before sampling')
    s.add_argument('--audit-data', required=True)
    s.add_argument('--output', required=True)
    s.add_argument('--config')
    s = sub.add_parser('prepare')
    s.add_argument('--dataset', required=True)
    s.add_argument('--output', required=True)
    s.add_argument('--config')
    s.add_argument('--count', type=int, default=2)
    s.add_argument('--stub-policy', choices=('first', 'stop'), default='first')
    s = sub.add_parser('prepare-fixture', help='synthetic protocol fixtures only; never a research dataset')
    s.add_argument('--output', required=True)
    s.add_argument('--stub-policy', choices=('first', 'stop'), default='first')
    s = sub.add_parser('run')
    s.add_argument('--plan', required=True)
    s.add_argument('--output', required=True)
    s.add_argument('--resume', action='store_true')
    s.add_argument('--max-jobs', type=int)
    s.add_argument('--stop-after', type=int)
    s = sub.add_parser('verify')
    s.add_argument('--experiment', required=True)
    s = sub.add_parser('pilot-draft')
    s.add_argument('--dataset', required=True)
    s.add_argument('--output', required=True)
    s = sub.add_parser('report', help='render saved committed states, without replanning')
    s.add_argument('--experiment', required=True)
    s.add_argument('--output', required=True)
    args = p.parse_args(argv)
    if args.command == 'prepare-data':
        result = data.prepare(args.output, args.config, rule_plan=args.rule_plan)
        result = {k: result[k] for k in ('status', 'short_orders', 'eligible_source_clusters', 'iid_available', 'ood_available', 'split_counts', 'new_api_attempts')}
    elif args.command == 'freeze-data-rule':
        rule = data.freeze_rule(args.audit_data, args.output, args.config)
        result = {k: rule[k] for k in ('population_clusters', 'threshold', 'id_pool', 'ood_pool', 'frozen_before_sampling', 'new_api_attempts')}
    elif args.command == 'prepare':
        result = experiment.prepare(args.dataset, args.output, args.config, count=args.count, stub_policy=args.stub_policy)
    elif args.command == 'prepare-fixture':
        result = experiment.prepare(None, args.output, stub_policy=args.stub_policy, fixture=True)
    elif args.command == 'run':
        result = experiment.execute(args.plan, args.output, resume=args.resume, max_jobs=args.max_jobs, stop_after=args.stop_after)
    elif args.command == 'verify':
        result = experiment.verify(args.experiment)
    elif args.command == 'report':
        from ..o5.report import export
        result = export(args.experiment, args.output)
    else:
        result = experiment.pilot_draft(args.dataset, args.output)
        result = {k: result[k] for k in ('status', 'data_status', 'tasks', 'maximum_selection_attempts',
                                        'cost_status', 'model_multimodal_preflight', 'new_api_attempts')}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get('status') in ('FAIL', 'BLOCKED_DATA'):
        raise SystemExit(1)


if __name__ == '__main__':
    from ..o5.common import offline_guard
    with offline_guard():
        main()
