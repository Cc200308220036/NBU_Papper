"""O5 S2-A offline engineering CLI; real preflight/pilot execution is not authorized here."""
import argparse
import copy
import json
import sys
from ..o5.common import O5Error, atomic, read, offline_guard
from ..o5.remote_config import TEMPLATE,amount_policy,pricing_ready
from ..o5 import remote_experiment as experiment


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('profile-template');p.add_argument('--output',required=True)
    for name in ('prepare-preflight','prepare-pilot'):
        p=sub.add_parser(name);p.add_argument('--dataset');p.add_argument('--output',required=True)
        p.add_argument('--provider-config')
        if name=='prepare-pilot':p.add_argument('--preflight')
    for name in ('preflight','run-pilot'):
        p=sub.add_parser(name);p.add_argument('--plan',required=True);p.add_argument('--output',required=True)
        p.add_argument('--authorization',required=True);p.add_argument('--resume',action='store_true')
    p=sub.add_parser('prepare-fixture');p.add_argument('--output',required=True)
    p=sub.add_parser('run-fixture');p.add_argument('--plan',required=True);p.add_argument('--output',required=True)
    p.add_argument('--resume',action='store_true');p.add_argument('--stop-after',type=int);p.add_argument('--max-jobs',type=int)
    p=sub.add_parser('verify');p.add_argument('--experiment',required=True)
    p=sub.add_parser('report');p.add_argument('--experiment',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('validate-plan');p.add_argument('--plan',required=True)
    args=parser.parse_args(argv)
    if args.command=='profile-template':
        from pathlib import Path
        path=Path(args.output)
        # Exclusive create: a template cannot overwrite existing configuration.
        with path.open('x') as stream:json.dump(TEMPLATE,stream,ensure_ascii=False,indent=2);stream.write('\n')
        result={'status':'DRAFT_NOT_EXECUTABLE','amount_policy':TEMPLATE['amount_policy'],'real_api_attempts':0}
    elif args.command in ('preflight','run-pilot'):
        from ..o5.remote_authorized import preflight,run_pilot
        result=(preflight if args.command=='preflight' else run_pilot)(args.plan,args.output,args.authorization,resume=args.resume)
    elif args.command=='prepare-pilot' and args.preflight:
        from ..o5.remote_authorized import prepare_pilot_from_preflight
        result=prepare_pilot_from_preflight(args.preflight,args.output)
    elif args.command.startswith('prepare-'):
        fixture=args.command=='prepare-fixture'
        if not fixture and not args.dataset:parser.error('--dataset is required for a draft plan')
        profile=experiment.fixture_profile() if fixture else (read(args.provider_config) if args.provider_config else copy.deepcopy(TEMPLATE))
        result=experiment.prepare(None if fixture else args.dataset,args.output,profile,
                                 stage='preflight' if args.command=='prepare-preflight' else 'pilot',fixture=fixture)
    elif args.command=='run-fixture':
        result=experiment.execute_fixture(args.plan,args.output,resume=args.resume,stop_after=args.stop_after,max_jobs=args.max_jobs)
    elif args.command=='verify':
        result=experiment.verify(args.experiment)
        result={k:v for k,v in result.items() if k!='results'}
    elif args.command=='report':result=experiment.report(args.experiment,args.output)
    else:
        plan,tasks=experiment.validate_plan(args.plan)
        result={'status':plan['status'],'gaps':plan['gaps'],'planned_jobs':len(plan['jobs']),
                'amount_policy':amount_policy(plan['profile']),
                'cost_estimate_status':'ESTIMATABLE' if pricing_ready(plan['profile']) else 'UNKNOWN',
                'maximum_selection_attempts':plan['maximum_selection_attempts'],'real_api_attempts':0}
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1] in ('preflight','run-pilot'):
        main()  # Explicit remote commands still require a frozen profile and matching authorization.
    else:
        with offline_guard():main()
