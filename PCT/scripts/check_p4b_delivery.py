"""Stdlib read-only integrity checker; no business execution or re-sealing."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
PACKAGE=ROOT/'PCT/outputs/PCT_P4_B_0_20261115_01'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest=json.loads((PACKAGE/'delivery_manifest.json').read_text())
    for row in manifest['files']:
        path=ROOT/row['path']
        assert path.is_file() and path.stat().st_size==row['bytes'] and sha(path)==row['sha256'],row['path']
    protected=json.loads((PACKAGE/'protected_identity.json').read_text())
    for name,h in protected['files'].items():assert sha(ROOT/name)==h,name
    print(json.dumps({'status':'PASS_SAVED_BYTES_ONLY','manifest_files':len(manifest['files']),
                      'protected_files':len(protected['files']),'business_calls':0}))


if __name__=='__main__':main()
