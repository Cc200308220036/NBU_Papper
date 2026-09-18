#!/usr/bin/env python3
"""对源代码快照和两份正式实验清单执行最终只读审计。"""
import argparse
import json
import sys
from pathlib import Path

PACKAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PACKAGE/'src'))
from semantic_pallet_planner.logging.artifacts import source_checksums,file_hash,dataset_checksums


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiments',nargs='+',required=True,help='formal 1A/1B experiment directories')
    args=parser.parse_args();reports=[]
    current=source_checksums()
    for value in args.experiments:
        root=Path(value);manifest=json.loads((root/'manifest.json').read_text())
        cfg=json.loads((root/'config.snapshot.json').read_text())
        failures=[]
        if manifest['source_checksums']!=current:failures.append('current code differs from experiment source snapshot')
        if manifest['dataset_checksums']!=dataset_checksums(cfg['dataset']):failures.append('dataset changed')
        for relative,expected in manifest['result_file_checksums'].items():
            path=root/relative
            if not path.is_file() or file_hash(path)!=expected:failures.append(f'artifact changed: {relative}')
        for relative in ['acceptance_report.json','replay_report.json','validation_report.json']:
            if json.loads((root/relative).read_text())['status']!='PASS':failures.append(relative)
        reports.append(dict(experiment=str(root),status='PASS' if not failures else 'FAIL',failures=failures))
    print(json.dumps(reports,ensure_ascii=False,indent=2))
    if any(r['status']!='PASS' for r in reports):raise SystemExit(1)

if __name__=='__main__':main()
