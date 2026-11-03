"""Local-only layout-v2 development entrypoint."""
import argparse
import json
from ..o4.extensions.e5.layout_v2.experiment import p0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local E5 layout-v2 diagnostics; no network operations')
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('p0', help='freeze and diagnose three historical case families')
    command.add_argument('--output', required=True)
    command = commands.add_parser('local-checks', help='record A/B/C/D choices on fixed decision states')
    command.add_argument('--output', required=True)
    command = commands.add_parser('prepare', help='freeze local L2 and conditional L3 plan')
    command.add_argument('--output', required=True); command.add_argument('--l0', required=True); command.add_argument('--l1-xml', required=True)
    command = commands.add_parser('run', help='execute/resume only the new local L2 jobs')
    command.add_argument('--plan', required=True); command.add_argument('--output', required=True)
    command.add_argument('--resume', action='store_true'); command.add_argument('--max-jobs', type=int)
    args = parser.parse_args(argv)
    if args.command == 'p0': result = p0(args.output)
    else:
        from ..o4.extensions.e5.layout_v2 import suite
        if args.command == 'local-checks': result = suite.local_checks(args.output)
        elif args.command == 'prepare': result = suite.prepare(args.output, args.l0, args.l1_xml)
        else: result = suite.run(args.plan, args.output, resume=args.resume, max_jobs=args.max_jobs)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
