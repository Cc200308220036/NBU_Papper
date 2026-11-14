"""Offline data-only entry points. No selector/transport/LP/order imports."""
import argparse
import json
from .dataset import prepare, validate_data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare-data');p.add_argument('--spec',required=True);p.add_argument('--output',required=True);p.add_argument('--repo',default='.')
    p=commands.add_parser('validate-data');p.add_argument('--dataset',required=True);p.add_argument('--repo',default='.');p.add_argument('--full-schema',action='store_true')
    args=parser.parse_args()
    result=prepare(args.repo,args.spec,args.output) if args.command=='prepare-data' else validate_data(args.repo,args.dataset,full_schema=args.full_schema)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
