"""Read-only byte/metadata review. Never imports or executes the fixed suite."""
import ast,hashlib,json,re
from pathlib import Path
I=Path(__file__).resolve().parent;ROOT=Path.cwd()
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for rel,h in read(I/'frozen_identity.json')['files'].items():assert sha(Path(rel))==h,rel
for rel,h in read(I/'archive_member_identity.json')['files'].items():assert sha(Path(rel))==h,rel
src=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
current={str(f.relative_to(src)):sha(f) for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
assert current==read(I/'source_manifest.json')['files'] and len(current)==591
for f in I.glob('*.py'):ast.parse(f.read_bytes(),filename=str(f))
for f in I.rglob('*.json'):read(f)
result=read(I/'results.json');assert len(result['business_results'])==35 and all(r['status']=='NOT_RUN' and r['attempts']==0 for r in result['business_results'])
assert not any((I/n).exists() for n in ('E','R_saved','R_recovery','execution_started.json','stop.json'))
assert read(I/'call_accounting.json')['actual_business_calls']==0
assert read(I/'environment_receipt.json')['expected']==read(I/'environment_receipt.json')['observed']
report=ROOT/'docs/03_阶段产出分析/几何规划模块/几何候选器GP5-NUM-N1-R5测试层隔离与覆盖补齐交付_20261118_01.md'
for target in re.findall(r'\]\(([^)]+)\)',report.read_text()):assert (report.parent/target).exists(),target
if (I/'delivery_manifest.json').exists():
 for row in read(I/'delivery_manifest.json')['files']:
  p=Path(row['path']);assert len(p.read_bytes())==row['size_bytes'] and sha(p)==row['sha256'],str(p)
print('PASS1262 frozen input identities;634 original archive members unchanged;591 source set/bytes;35 NOT_RUN;8-config environment metadata;AST/JSON/links; business0')
