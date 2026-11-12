"""JM v13 transition fix saved-byte verifier v1; no Git or runtime import."""
import hashlib
import json
from pathlib import Path

VERSION='jm_v13_transition_fix_saved_verifier_v1'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def source_check(repo,snapshot):
    package=repo/'semantic_pallet_planner/src/semantic_pallet_planner'
    current={p.relative_to(package).as_posix():sha(p) for p in sorted(package.rglob('*'))
             if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(package).parts)}
    if current!=snapshot:raise ValueError('SOURCE_BYTES_OR_FILE_SET_DRIFT')

def verify(repo,delivery):
    manifest=json.loads((delivery/'delivery_manifest.json').read_text())
    identity=json.loads((delivery/'source_identity.json').read_text())
    if manifest['entry_head']!=identity['entry_head']:raise ValueError('ENTRY_HEAD_CHANGED')
    for entry in manifest['files']:
        p=repo/entry['path']
        if not p.is_file() or sha(p)!=entry['sha256'] or p.stat().st_size!=entry['bytes']:
            raise ValueError('DELIVERY_BYTES_CHANGED:'+entry['path'])
    source_check(repo,json.loads((delivery/'source_manifest.json').read_text()))
    return {'version':VERSION,'status':'PASS_SAVED_BYTES','entry_head':identity['entry_head'],
            'files_checked':len(manifest['files']),'current_HEAD_used':False,'dispatches':0}

if __name__=='__main__':
    delivery=Path(__file__).resolve().parent
    print(json.dumps(verify(delivery.parents[2],delivery),sort_keys=True))
