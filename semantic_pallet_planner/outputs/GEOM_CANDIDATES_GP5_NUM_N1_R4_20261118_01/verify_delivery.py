"""Read-only saved-byte verification; no production/suite imports."""
import ast,hashlib,json,re
from pathlib import Path
O=Path(__file__).resolve().parent
ROOT=Path.cwd();SRC=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for rel,h in read(O/'frozen_identity.json')['files'].items():assert sha(Path(rel))==h,rel
actual={str(f.relative_to(SRC)):sha(f) for f in SRC.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(SRC).parts)}
assert actual==read(O/'source_manifest.json')['files'] and len(actual)==591
assert len(read(O/'configs.json'))==8 and len(read(O/'results.json')['business_results'])==35
assert read(O/'environment_review.json')['differences']=={}
assert read(O/'call_accounting.json')['business_calls']==0
assert not any((O/n).exists() for n in ('E','R_saved','R_recovery','execution_started.json','validation_stop.json'))
for f in O.glob('*.py'):ast.parse(f.read_bytes(),filename=str(f))
for f in O.rglob('*.json'):read(f)
report=ROOT/'docs/03_阶段产出分析/几何规划模块/几何候选器GP5-NUM-N1-R4环境匹配与验证入口交付_20261118_01.md'
links=[]
for target in re.findall(r'\]\(([^)]+)\)',report.read_text()):
 assert (report.parent/target).exists(),target
 links.append(target)
manifest=O/'delivery_manifest.json'
if manifest.exists():
 for row in read(manifest)['files']:
  p=Path(row['path']);assert sha(p)==row['sha256'] and len(p.read_bytes())==row['size_bytes'],str(p)
print('PASS saved frozen identities,591 source set/bytes,8 configs,35 NOT_RUN entries,JSON/AST,report links; business calls0')
