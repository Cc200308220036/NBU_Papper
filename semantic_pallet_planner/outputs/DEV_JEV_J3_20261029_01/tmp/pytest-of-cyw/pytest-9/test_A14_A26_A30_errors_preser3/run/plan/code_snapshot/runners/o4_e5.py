"""E5 current-scope dedicated CLI. Real API is explicit and never implicit."""
import argparse
import json
from ..o4.extensions.e5.experiment import prepare,validate_plan,offline_run
from ..o4.extensions.e5.delivery import verify_experiment


def main(argv=None):
    p=argparse.ArgumentParser(description='O4 E5 0/90 mixed-order closure; E3 deferred, E4 out of scope')
    subs=p.add_subparsers(dest='command',required=True)
    s=subs.add_parser('prepare',help='freeze 24 source tasks, mixed gold/constructs, proofs and source');s.add_argument('--output',required=True);s.add_argument('--protection',required=True)
    s=subs.add_parser('validate-plan',help='validate sealed offline plan and frozen source');s.add_argument('--plan',required=True)
    s=subs.add_parser('offline-run',help='run 192 source+48 construct episodes, repeats, restores and audits');s.add_argument('--plan',required=True);s.add_argument('--output',required=True);s.add_argument('--resume',action='store_true');s.add_argument('--max-jobs',type=int)
    s=subs.add_parser('verify',help='read-only saved offline/real E5 recomputation, no API');s.add_argument('--experiment',required=True)
    s=subs.add_parser('remote-prepare',help='freeze real 240-job online plan after offline acceptance; no API');s.add_argument('--development-plan',required=True);s.add_argument('--offline-experiment',required=True);s.add_argument('--model-config',required=True);s.add_argument('--output',required=True)
    s=subs.add_parser('remote-run',help='explicit real online run/resume; one global API budget');s.add_argument('--plan',required=True);s.add_argument('--output',required=True);s.add_argument('--api-budget',required=True,type=int);s.add_argument('--remote',required=True,action='store_true');s.add_argument('--resume',action='store_true');s.add_argument('--max-jobs',type=int)
    args=p.parse_args(argv)
    if args.command=='prepare':result=prepare(args.output,args.protection)
    elif args.command=='validate-plan':
        plan,data,config=validate_plan(args.plan);result={'status':'PASS','planned_jobs':len(plan['jobs']),'new_api_attempts':0}
    elif args.command=='offline-run':result=offline_run(args.plan,args.output,resume=args.resume,max_jobs=args.max_jobs)
    elif args.command=='verify':result=verify_experiment(args.experiment)
    elif args.command=='remote-prepare':
        from ..o4.extensions.e5.online import prepare_remote
        result=prepare_remote(args.development_plan,args.offline_experiment,args.model_config,args.output)
    else:
        from ..o4.extensions.e5.online import remote_run
        result=remote_run(args.plan,args.output,args.api_budget,remote=args.remote,resume=args.resume,max_jobs=args.max_jobs)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result.get('status')=='FAIL':raise SystemExit(1)


if __name__=='__main__':main()
