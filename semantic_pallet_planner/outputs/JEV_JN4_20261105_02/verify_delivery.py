"""Verify all bytes, nested manifests, source/test identity and parent protection."""
import argparse,hashlib,json,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--repo',default='.');a=p.parse_args()
repo=Path(a.repo);root=Path(a.output)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
m=load(root/'delivery_manifest.json')
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p!=root/'delivery_manifest.json'}
assert actual==set(m['files_sha256']),'file set changed'
for n,h in m['files_sha256'].items():
 p=(root/n).resolve();assert p.is_relative_to(root.resolve()) and sha(p)==h,n
for n,h in m['documentation_sha256'].items():
 assert sha(repo/n)==h,n
 for link in re.findall(r'\]\(([^)]+)\)',(repo/n).read_text()):
  if not link.startswith(('http:','https:','#')):assert ((repo/n).parent/link.split('#')[0]).exists(),(n,link)
package=repo/'semantic_pallet_planner/src/semantic_pallet_planner';source=load(root/'source_manifest.json')
current={p.relative_to(package).as_posix():sha(p) for p in package.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(package).parts)}
assert current==source
for n,h in source.items():assert sha(root/'code_snapshot'/n)==h,n
for n,h in load(root/'algorithm_archive_manifest.json').items():assert sha(root/'code_snapshot/jev_select/stability'/n)==h and sha(package/'jev_select/stability'/n)==h,n
for n,h in load(root/'test_manifest.json').items():assert sha(repo/n)==h and sha(root/'test_snapshot'/n)==h,n
for n,h in load(root/'protected_before.json').items():
 if n!='docs/03_阶段产出分析/Jev/README.md':assert sha(repo/n)==h,n
parent=repo/'semantic_pallet_planner/outputs/JEV_JN4_20261105_01';pm=load(parent/'delivery_manifest.json')
assert {p.relative_to(parent).as_posix() for p in parent.rglob('*') if p.is_file() and p!=parent/'delivery_manifest.json'}==set(pm['files_sha256'])
assert all(sha(parent/n)==h for n,h in pm['files_sha256'].items())
r=load(root/'evaluation_plan_receipt.json');assert r['six_method_engineering_complete'] and not r['data_ready'] and not r['formal_matrix_frozen'] and not r['JN4_B_admitted']
assert r['actual_model_api_calls']==r['actual_formal_test_jobs_executed']==0
print(json.dumps({'status':'PASS_STATIC_SUPPLEMENT','files':len(actual),'source_files':len(source),'parent_NOT_READY_unchanged':True,'JN4_B_admitted':False}))
