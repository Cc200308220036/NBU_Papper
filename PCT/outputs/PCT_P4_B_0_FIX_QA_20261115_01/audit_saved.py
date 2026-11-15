"""Stdlib saved identity audit. No planner/model imports."""
import ast
import hashlib
import json
from pathlib import Path
P=Path('PCT/outputs/PCT_P4_B_0_FIX_20261115_01');Q=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
manifest=read(P/'delivery_manifest.json');nav=[]
for row in manifest['files']:
 path=Path(row['path'])
 if sha(path)!=row['sha256'] or path.stat().st_size!=row['bytes']:
  assert str(path) in ('PCT/README.md','PCT/docs/README.md'),str(path)
  nav.append(str(path))
history=read(P/'historical_protection.json')
for n,h in history['unchanged'].items():assert sha(n)==h,n
for row in history['authorized_live_drift']:assert sha(row['path'])==row['current_sha256']
files=list(Path('PCT/src/pct_baseline').glob('p4b_*.py'))
for path in files:ast.parse(path.read_text())
for method in ('training_plan.json','evaluation_template.json'):
 value=read(Path('PCT/outputs/PCT_P4_A_20261115_01/build_01')/method)
 assert value['execution_admitted'] is False and value['sending_admitted'] is False
identity=read(P/'identity.json')['execution_identity']['source']
for name,h in identity.items():
 path=Path('PCT/src')/name if name.startswith('pct_baseline/') else Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select')/name
 assert sha(path)==h,str(path)
result={'status':'PASS_SAVED_HASHES','manifest_entries':len(manifest['files']),'historical_unchanged':len(history['unchanged']),
        'registered_live_drift':len(history['authorized_live_drift']),'execution_source_files':len(identity),
        'navigation_differences':nav,'business_execution':'NONE','limit':'hashes do not validate training/recovery correctness; separate RNG probe required'}
(Q/'independent_saved_checks.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
