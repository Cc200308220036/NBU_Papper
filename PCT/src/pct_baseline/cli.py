"""Versioned data, recovery, and saved-only validation commands; imports are lazy."""
import argparse
import json
from .dataset import prepare, validate_data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare-data');p.add_argument('--spec',required=True);p.add_argument('--output',required=True);p.add_argument('--repo',default='.')
    p=commands.add_parser('validate-data');p.add_argument('--dataset',required=True);p.add_argument('--repo',default='.');p.add_argument('--full-schema',action='store_true')
    p=commands.add_parser('verify-saved');p.add_argument('--run',required=True)
    p=commands.add_parser('prepare-recovery');p.add_argument('--task',required=True);p.add_argument('--output',required=True)
    p=commands.add_parser('resume-recovery');p.add_argument('--run',required=True)
    args=parser.parse_args()
    if args.command=='verify-saved':
        from .saved import validate_job
        value=validate_job(args.run)
        print(json.dumps({k:value[k] for k in ('status','records','last_phase','business_dispatch')},ensure_ascii=False));return
    if args.command=='prepare-recovery':
        from .recovery import create_job
        from .contracts import read
        value=create_job(read(args.task),args.output)
        print(json.dumps({'status':'PREPARED_CONSTRUCTION_ONLY','header_digest':value['header_digest']}));return
    if args.command=='resume-recovery':
        from .recovery import run_job
        value=run_job(args.run)
        print(json.dumps({'status':value['checkpoint']['reason'],'loading':value['summary']['loading']},ensure_ascii=False));return
    result=prepare(args.repo,args.spec,args.output) if args.command=='prepare-data' else validate_data(args.repo,args.dataset,full_schema=args.full_schema)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
