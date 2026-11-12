"""JM v13 delivery bytes verifier v1. No runtime import, Git/HEAD, replay or dispatch."""
import hashlib
import json
from pathlib import Path

VERSION='jm_v13_saved_delivery_verifier_v1'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def verify_source(repo,snapshot):
    package=repo/'semantic_pallet_planner/src/semantic_pallet_planner'
    actual={p.relative_to(package).as_posix():sha(p) for p in sorted(package.rglob('*'))
            if p.is_file() and p.suffix in ('.py','.json') and
            not {'tests','__pycache__'}.intersection(p.relative_to(package).parts)}
    if actual!=snapshot:raise ValueError('SOURCE_BYTES_OR_FILE_SET_DRIFT')

def verify(repo,delivery):
    manifest=json.loads((delivery/'delivery_manifest.json').read_text())
    identity=json.loads((delivery/'source_identity.json').read_text())
    if manifest['entry_head']!=identity['entry_head']:raise ValueError('ENTRY_HEAD_MISMATCH')
    for item in manifest['files']:
        p=repo/item['path']
        if not p.is_file() or sha(p)!=item['sha256'] or p.stat().st_size!=item['bytes']:
            raise ValueError('DELIVERY_BYTES_CHANGED:'+item['path'])
    verify_source(repo,json.loads((delivery/'source_manifest.json').read_text()))
    return {'version':VERSION,'status':'PASS_SAVED_BYTES','entry_head':manifest['entry_head'],
            'files_checked':len(manifest['files']),'current_head_used':False,'dispatches':0}

if __name__=='__main__':
    delivery=Path(__file__).resolve().parent
    print(json.dumps(verify(delivery.parents[2],delivery),sort_keys=True))
