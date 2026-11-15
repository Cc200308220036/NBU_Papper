"""Stdlib immutable delivery verification only; no engine/model imports."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PACKAGE=ROOT/'PCT/outputs/PCT_P4_B_0_FIX_20261115_01'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    manifest=json.loads((PACKAGE/'delivery_manifest.json').read_text())
    for row in manifest['files']:
        path=ROOT/row['path']
        assert path.is_file() and sha(path)==row['sha256'] and path.stat().st_size==row['bytes'],row['path']
    protected=json.loads((PACKAGE/'historical_protection.json').read_text())
    for name,h in protected['unchanged'].items():assert sha(ROOT/name)==h,name
    for row in protected['authorized_live_drift']:
        assert sha(ROOT/row['path'])==row['current_sha256'],row['path']
    print(json.dumps({'status':'PASS_SAVED_ONLY','manifest_entries':len(manifest['files']),
                      'historical_unchanged':len(protected['unchanged']),
                      'authorized_live_drift':len(protected['authorized_live_drift'])}))


if __name__=='__main__':main()
