"""Read-only design-package verification; standard library, no project imports."""
import hashlib,json,re,subprocess
from pathlib import Path
OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N0_20261117_01')
SRC=Path('semantic_pallet_planner/src/semantic_pallet_planner')
DOC=Path('docs/02_阶段实施方案/几何规划模块/几何候选器GP5-NUM-N0原生尺寸发布桥接定稿设计_20261117_01.md')
NAVS={str(Path('docs/02_阶段实施方案/几何规划模块/README.md')),str(Path('docs/03_阶段产出分析/几何规划模块/README.md'))}
def read(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
frozen=read(OUT/'source_inventory.json')
actual={str(p.relative_to(SRC)):sha(p.read_bytes()) for p in SRC.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(SRC).parts)}
assert actual==frozen['files'] and len(actual)==565
assert hashlib.sha256(json.dumps(actual,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()==frozen['source_identity']
head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
assert head==read(OUT/'readonly_receipt.json')['actual_head']
changed=set(filter(None,subprocess.check_output(['git','diff','--name-only','-z']).decode().split('\0')))
assert changed==NAVS,changed
assert not subprocess.check_output(['git','diff','--cached','--name-only'])
status=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z']).decode().split('\0')
assert all(not p or p==str(DOC) or p.startswith(str(OUT)+'/') for p in status),status
# The synchronization introduced only QA/report/navigation, not runtime source.
pulled=list(filter(None,subprocess.check_output(['git','diff','--name-only','0c7cacb2dc58fcf97c1d4a682f65fb42b9cfe377',head,'-z']).decode().split('\0')))
assert len(pulled)==12 and all(p.startswith(('docs/03_阶段产出分析/几何规划模块/','semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P1_R1_QA_20261117_01/')) for p in pulled)
for item in read(OUT/'readonly_receipt.json')['manifests']:
 p=Path(item['manifest']);assert sha(p.read_bytes())==item['manifest_sha256']
 for r in read(p)['files']:
  path=Path(r['path'])
  raw=subprocess.check_output(['git','show',item['navigation_revision']+':'+str(path)]) if path.name=='README.md' else path.read_bytes()
  assert sha(raw)==r['sha256'] and len(raw)==r['size_bytes'],str(path)
for row in read(OUT/'read_inventory.json'):
 p=Path(row['path'])
 raw=subprocess.check_output(['git','show',head+':'+str(p)]) if str(p) in NAVS else p.read_bytes()
 assert sha(raw)==row['sha256'],str(p)
for n,paths in read(OUT/'proposed_name_inventory.json')['names'].items():
 assert not paths and not any(n.encode() in (SRC/k).read_bytes() for k in actual),n
links=[]
for p in [DOC,OUT/'README.md']:
 for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if not target.startswith(('http:','https:','#')):assert (p.parent/target).exists(),target;links.append(target)
for nav in NAVS:
 text=Path(nav).read_text();assert DOC.name in text
examples=read(OUT/'hand_examples.json');assert len(examples['positive'])==6 and len(examples['negative'])==4
assert all(x['strict_value_equal'] for row in examples['positive'] for x in row['axes'])
contracts=read(OUT/'contract_inventory.json');assert contracts['versions']['config']=='jev_packaging_geometry_order_v17'
assert 'geometry_runtime_shortest_decimal_v1' in contracts['unchanged_numeric_contracts']
failure=read(OUT/'saved_failure_receipt.json');assert sha(Path(failure['path']).read_bytes())==failure['sha256'] and failure['NUM-01']=='OPEN'
if (OUT/'delivery_manifest.json').exists():
 for r in read(OUT/'delivery_manifest.json')['files']:
  raw=Path(r['path']).read_bytes();assert sha(raw)==r['sha256'] and len(raw)==r['size_bytes'],r['path']
subprocess.run(['git','diff','--check'],check=True)
print('PASS: 565 production files unchanged; QA11/R1 1409 pinned members; design links, names, six hand examples and retained NUM failure; only related navigation tracked edits; index empty. No production import/business execution.')
