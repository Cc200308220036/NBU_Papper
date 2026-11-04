"""Recheck historical bytes and output directory inventories without mutation."""
import argparse
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--receipt',required=True);args=p.parse_args()
base=Path(__file__).resolve().parent
before=json.loads((base/'protected_before.json').read_text())
roots=sorted({str(Path(*Path(n).parts[:3])) for n in before if n.startswith('semantic_pallet_planner/outputs/')})
files={str(p) for root in roots for p in Path(root).rglob('*') if p.is_file()}
files.update(n for n in before if not n.startswith('semantic_pallet_planner/outputs/'))
after={n:hashlib.sha256(Path(n).read_bytes()).hexdigest() for n in sorted(files) if Path(n).is_file()}
changed=[n for n in before if n in after and before[n]!=after[n]]
missing=sorted(set(before)-set(after));added=sorted(set(after)-set(before))
result={'status':'PASS' if not (changed or missing or added) else 'FAIL',
        'files':len(before),'changed':changed,'missing':missing,'added':added,
        'roots':roots,'before_sha256':hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),
        'after_sha256':hashlib.sha256(json.dumps(after,sort_keys=True).encode()).hexdigest(),
        'scope':'all original output files, original Jev reports except authorized index, and AGENTS; new report/indices/main-spec changes excluded by authorization'}
Path(args.receipt).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
assert result['status']=='PASS'
