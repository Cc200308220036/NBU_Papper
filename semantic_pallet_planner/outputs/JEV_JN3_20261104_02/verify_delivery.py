"""Static byte/inventory verifier; no application imports or execution."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--repo',default='.')
a=p.parse_args();root=Path(a.output);repo=Path(a.repo)
m=json.loads((root/'delivery_manifest.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
actual={f.relative_to(root).as_posix():sha(f) for f in sorted(root.rglob('*')) if f.is_file() and f.name!='delivery_manifest.json'}
assert actual==m['files_sha256'],'delivery file bytes or inventory changed'
assert all(sha(repo/n)==h for n,h in m['documentation_sha256'].items()),'documentation changed'
s=json.loads((root/'source_manifest.json').read_text());package=repo/'semantic_pallet_planner/src/semantic_pallet_planner'
assert all(sha(root/'code_snapshot'/n)==h for n,h in s.items()),'archive changed'
assert all(sha(package/n)==h for n,h in s.items()),'current source changed; use frozen validator for evolved code'
old=json.loads((root/'protected_before.json').read_text())
assert all((repo/n).is_file() and sha(repo/n)==h for n,h in old.items()),'parent changed'
print(json.dumps({'status':'PASS','delivery_files':len(actual),'source_files':len(s),'protected_files':len(old),'source_archive_current_match':True}))
