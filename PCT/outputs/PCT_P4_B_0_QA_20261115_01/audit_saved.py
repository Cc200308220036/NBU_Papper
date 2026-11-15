"""Independent stdlib saved-file/source-shape audit, no business dispatch."""
import ast
import hashlib
import json
from pathlib import Path
P=Path('PCT/outputs/PCT_P4_B_0_20261115_01')
Q=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
nav=[];manifest=read(P/'delivery_manifest.json')
for row in manifest['files']:
 p=Path(row['path'])
 if sha(p)!=row['sha256'] or p.stat().st_size!=row['bytes']:
  assert str(p) in ('PCT/README.md','PCT/docs/README.md'),str(p)
  nav.append(str(p))
protected=read(P/'protected_identity.json')['files']
for name,h in protected.items():assert sha(name)==h,name
identity=read(P/'identity.json')
for name,h in identity['files'].items():
 assert sha(name)==h and sha(P/'source_snapshot'/name)==h,name
 if name.endswith('.py'):ast.parse(Path(name).read_text())
assert read(P/'acceptance.json')['overall']=='PARTIAL'
assert read(P/'handoff.json')['formal_business_admission'] is False
assert 'FAILED' in (P/'tests_01_failed.log').read_text()
assert 'Ran 12 tests' in (P/'tests_final.log').read_text() and '\nOK\n' in (P/'tests_final.log').read_text()
assert 'Ran 7 tests' in (P/'p4a_regression.log').read_text()
executor=ast.parse(Path('PCT/src/pct_baseline/p4b_executor.py').read_text())
launch=next(n for n in ast.walk(executor) if isinstance(n,ast.FunctionDef) and n.name=='launch')
assert len(launch.body)==1 and isinstance(launch.body[0],ast.Expr)
runtime=ast.parse(Path('PCT/src/pct_baseline/p4b_runtime.py').read_text())
admit=next(n for n in ast.walk(runtime) if isinstance(n,ast.FunctionDef) and n.name=='admit_business')
assert isinstance(admit.body[-1],ast.Raise)
receipt={'status':'PASS_SAVED_FACTS_AND_STATIC_BOUNDARY','manifest_files':len(manifest['files']),
 'protected_files':len(protected),'source_snapshot_files':len(identity['files']),'navigation_differences':nav,
 'original_test_failure':'PRESERVED','formal_launch':'unconditional rejection after gates; no training loop',
 'archived_status':'PARTIAL','business_execution':'NONE','not_proven':['real model/Adam/RNG restore','actual stage hooks','collection/gradient execution','formal throughput/resources']}
(Q/'independent_saved_checks.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(receipt,ensure_ascii=False))
