"""Read-only final bytes/receipts verifier; no suite or order imports."""
import ast,hashlib,json,re
from pathlib import Path
I=Path(__file__).resolve().parent;ROOT=Path.cwd()
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
freeze=read(I/'frozen_identity.json')
for rel,h in freeze['files'].items():assert sha(Path(rel))==h,rel
for rel,h in read(I/'archive_member_identity.json')['files'].items():assert sha(Path(rel))==h,rel
src=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner';actual={str(f.relative_to(src)):sha(f) for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
assert actual==read(I/'source_manifest.json')['files'] and len(actual)==591
for row in read(I/'saved_f0_revalidation.json')['rows']:
 for rel,h in row['all_original_members'].items():assert sha(Path(rel))==h,rel
 r=read(I/row['receipt']);assert len(r['contexts'])==r['context_count']==2
 assert [c['route'] for c in r['contexts']]==['CHOICE_REQUIRED','SINGLETON_BYPASS']
 assert r['contexts'][1]['request_body_is_null'] and r['contexts'][1]['request_fields'] is None
 assert r['contexts_dropped']==0 and r['request_constructed'] is False
for f in I.glob('*.py'):ast.parse(f.read_bytes(),filename=str(f))
for f in I.rglob('*.json'):read(f)
rows=read(I/'results.json')['business_results'];assert len(rows)==35 and all(r['status']=='NOT_RUN' and r['attempts']==0 for r in rows)
assert read(I/'call_accounting.json')['actual_business_calls']==0
assert read(I/'environment_receipt.json')['expected']==read(I/'environment_receipt.json')['observed']
assert not any((I/n).exists() for n in ('E','R_saved','R_recovery','execution_started.json','stop.json'))
report=ROOT/'docs/03_阶段产出分析/几何规划模块/几何候选器GP5-NUM-N1-R6单候选F0收据修复交付_20261118_01.md'
for target in re.findall(r'\]\(([^)]+)\)',report.read_text()):assert (report.parent/target).exists(),target
if (I/'delivery_manifest.json').exists():
 for row in read(I/'delivery_manifest.json')['files']:
  p=Path(row['path']);assert len(p.read_bytes())==row['size_bytes'] and sha(p)==row['sha256'],str(p)
print('PASS1403 frozen identities;591 production set/bytes; original archives and full J00/J01 unchanged; both mixed-route receipts PASS;35 NOT_RUN;AST/JSON/links; business0')
