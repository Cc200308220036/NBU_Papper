"""Local capacity protocol; no API or historical replay entry points."""
import argparse
import json
from ..o4.extensions.e5.layout_v3 import suite


def main():
    p = argparse.ArgumentParser(); sub = p.add_subparsers(dest='action', required=True)
    prepare = sub.add_parser('prepare-small'); prepare.add_argument('--test-xml', required=True)
    for name in ('run-small', 'run-expanded'):
        run = sub.add_parser(name); run.add_argument('--resume', action='store_true'); run.add_argument('--max-jobs', type=int)
    sub.add_parser('small-gate'); sub.add_parser('prepare-final')
    a = p.parse_args()
    if a.action == 'prepare-small': r = suite.prepare_small(a.test_xml)
    elif a.action == 'small-gate': r = suite.small_gate()
    elif a.action == 'prepare-final': r = suite.prepare_final()
    else: r = suite.run(expanded=a.action == 'run-expanded', resume=a.resume, max_jobs=a.max_jobs)
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
