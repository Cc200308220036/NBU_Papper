"""Dedicated O4-E2 CLI. No implicit old-runner upgrades or network calls."""
import argparse
import json
from pathlib import Path
from ..o4.extensions.e2.experiment import prepare, run, verify_experiment, validate_plan


def main(argv=None):
    p=argparse.ArgumentParser(description='O4 E2 upright top-label spatial development')
    subs=p.add_subparsers(dest='command',required=True)
    s=subs.add_parser('prepare',help='build/validate fixtures and freeze source/data/config plan');s.add_argument('--output',required=True)
    s=subs.add_parser('validate-plan',help='verify sealed plan, input counts and source snapshot');s.add_argument('--plan',required=True)
    s=subs.add_parser('run',help='run full offline E2 matrix, repeats, restore and audit');s.add_argument('--plan',required=True);s.add_argument('--output',required=True);s.add_argument('--protection',required=True,help='pre-development SHA256 manifest')
    s=subs.add_parser('verify',help='read-only recomputation of NEW E2 experiment, without APIs');s.add_argument('--experiment',required=True)
    s=subs.add_parser('remote-prepare',help='freeze E2 real compile smoke/fixed plan; no network');s.add_argument('--development-plan',required=True);s.add_argument('--profile',choices=('compile-smoke','fixed'),required=True);s.add_argument('--model-config',required=True);s.add_argument('--output',required=True)
    s=subs.add_parser('remote-run',help='explicit real E2 compile run, no online-order claim');s.add_argument('--plan',required=True);s.add_argument('--output',required=True);s.add_argument('--api-budget',required=True,type=int);s.add_argument('--remote',action='store_true',required=True)
    args=p.parse_args(argv)
    if args.command=='prepare':result=prepare(args.output)
    elif args.command=='validate-plan':
        plan,data,config=validate_plan(args.plan);result={'status':'PASS','jobs':len(plan['jobs']),'new_api_attempts':0}
    elif args.command=='run':result=run(args.plan,args.output,args.protection)
    elif args.command=='remote-prepare':
        from ..o4.extensions.e2.remote import prepare_remote
        result=prepare_remote(args.development_plan,args.output,args.profile,args.model_config)
    elif args.command=='remote-run':
        from ..o4.extensions.e2.remote import run_remote
        result=run_remote(args.plan,args.output,args.api_budget,args.remote)
    else:result=verify_experiment(args.experiment)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result.get('status')!='PASS':raise SystemExit(1)


if __name__=='__main__':main()
