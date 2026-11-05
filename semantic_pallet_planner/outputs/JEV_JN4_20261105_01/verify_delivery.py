"""Static byte/identity validation only. No reruns or model imports."""
import argparse
from pathlib import Path
import json
import hashlib

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--repo',default='.')
a=p.parse_args();root=Path(a.output);repo=Path(a.repo)
m=json.loads((root/'delivery_manifest.json').read_text())
actual={x.relative_to(root).as_posix() for x in root.rglob('*') if x.is_file() and x.name!='delivery_manifest.json'}
assert actual==set(m['files_sha256']),'delivery file set changed'
for n,h in m['files_sha256'].items():
 q=(root/n).resolve();assert q.is_relative_to(root.resolve()) and sha(q)==h,n
for n,h in m['documentation_sha256'].items():assert sha(repo/n)==h,n
source=json.loads((root/'source_manifest.json').read_text())
package=repo/'semantic_pallet_planner/src/semantic_pallet_planner'
actual_source={q.relative_to(package).as_posix():sha(q) for q in package.rglob('*') if q.is_file() and q.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(q.relative_to(package).parts)}
assert actual_source==source,'production file set/identity changed'
for n,h in source.items():
 assert sha(package/n)==h,n
 assert sha(root/'plan/code_snapshot'/n)==h,n
for n,h in json.loads((root/'algorithm_auxiliary_manifest.json').read_text()).items():
 assert sha(package/n)==h and sha(root/'plan/code_snapshot'/n)==h,n
for n,h in json.loads((root/'test_manifest.json').read_text()).items():
 assert sha(repo/n)==h and sha(root/'test_snapshot'/Path(n).name)==h,n
before=json.loads((root/'protected_before.json').read_text())
for n,h in before.items():
 if n=='docs/03_阶段产出分析/Jev/README.md':continue # Explicitly updated index.
 assert sha(repo/n)==h,n
for n,h in json.loads((root/'history_inventory.json').read_text())['files'].items():assert sha(repo/n)==h,n
receipt=json.loads((root/'evaluation_plan_receipt.json').read_text())
assert receipt['JN4_B_admitted'] is False and receipt['actual_model_api_calls']==0 and receipt['actual_formal_test_jobs_executed']==0
assert receipt['status']=='NOT_READY'
print(json.dumps({'status':'PASS_STATIC_BLOCKED_DELIVERY','files':len(actual),'production_files':len(source),'JN4_B_admitted':False}))
