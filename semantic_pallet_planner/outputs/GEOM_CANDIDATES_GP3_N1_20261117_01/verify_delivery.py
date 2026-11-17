"""Read-only N1 file/byte/audit identity check; no production imports or calls."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

parser=argparse.ArgumentParser()
parser.add_argument('--sealed',action='store_true')
args=parser.parse_args()
OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N1_20261117_01')
PKG=Path('semantic_pallet_planner/src/semantic_pallet_planner')
REPORT=Path('docs/03_阶段产出分析/几何规划模块/几何候选器GP3-N1运行时快照与共享生成核心开发交付_20261117_01.md')


def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


manifest=read(OUT/'source_manifest.json')
actual={p.relative_to(PKG).as_posix():sha(p) for p in sorted(PKG.rglob('*'))
        if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(PKG).parts)}
assert actual==manifest['files'] and len(actual)==530
for name in manifest['changed_existing']+manifest['added']:
    assert sha(OUT/'source_snapshot'/name)==actual[name]
old=read(Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP2_20261117_01/source_manifest.json'))['files']
assert [n for n in old if actual.get(n)!=old[n]]==['planner/space_candidates/generator.py']
assert len(set(actual)-set(old))==3
for name in ('test_geometry_runtime_n1.py','test_space_candidates_gp2.py'):
    assert sha(OUT/'test_snapshot'/name)==sha(Path('semantic_pallet_planner/tests/unit')/name)
for case in (OUT/'cases').iterdir():
    n,g,b=case/'B_native.json',case/'B_geometry.json',read(case/'binding.json')
    assert sha(n)==b['native_snapshot_sha256'] and sha(g)==b['geometry_input_sha256']
    assert b['record_digest']==digest({k:v for k,v in b.items() if k!='record_digest'})
    assert b['source_manifest_digest']==digest(actual)
    assert b['config_digest']==digest(read(OUT/'config_snapshot.json'))
    geometry=read(g)
    assert geometry['native_snapshot_sha256']==sha(n)
    assert b['geometry_values_digest']==digest(geometry['payload'])
    assert b['effective_state_digest']==geometry['effective_state_digest']
    r=read(case/'result.json');a=r['audit']
    assert a['semantic_digest']==digest({k:v for k,v in a.items() if k!='semantic_digest'})
    assert a['binding']==b
    if r['status']=='ERROR':assert r['candidates']==[]
native=read(OUT/'cases/native_identity/B_native.json')
assert struct.pack('>d',native['current_state']['placed_items'][0]['pose']['x_mm']).hex()=='8000000000000000'
assert read(OUT/'cases/native_identity/B_geometry.json')['payload']['placed_items'][0]['pose']['x_mm']=='0'
for p in (OUT/'faults').glob('*/result.json'):
    r=read(p)
    assert r['status']=='ERROR' and r['candidates']==[]
for entry in read(OUT/'case_summary.json')['legacy_regression']:
    assert sha(Path(entry['input_path']))==entry['input_sha256']
    expected=Path(entry['input_path'].replace('_input.json','_result.json'))
    assert sha(expected)==entry['saved_result_sha256']
    assert digest(read(OUT/'legacy_regression'/f"{entry['case']}_actual.json"))==digest(read(expected))
links=0
for doc in (REPORT,REPORT.parent/'README.md'):
    for target in re.findall(r'\]\(([^)]+)\)',doc.read_text()):
        if '://' not in target:
            assert (doc.parent/target.split('#')[0]).exists(),target
            links+=1
if args.sealed:
    delivery=read(OUT/'delivery_manifest.json')
    for r in delivery['files']:
        assert sha(Path(r['path']))==r['sha256'],r['path']
        assert Path(r['path']).stat().st_size==r['size_bytes']
    expected={p.as_posix() for p in OUT.rglob('*') if p.is_file() and
              p.name not in ('delivery_manifest.json','seal_verification.log')}
    expected|={REPORT.as_posix(),(REPORT.parent/'README.md').as_posix(),
               'semantic_pallet_planner/tests/unit/test_geometry_runtime_n1.py'}
    expected|={(PKG/n).as_posix() for n in manifest['changed_existing']+manifest['added']}
    assert {r['path'] for r in delivery['files']}==expected,'unlisted/extra delivery members'
print(json.dumps({'status':'PASS_FILE_BYTE_AND_AUDIT_IDENTITIES','source_files':530,'old_unchanged':526,
      'native_geometry_fixtures':7,'links_checked':links,'manifest_verified':args.sealed,
      'production_imports':0,'candidate_calls':0,'orders':0,'PCT_calls':0,
      'checkpoint_resume':'NOT_RUN','parent_A03':'PARTIAL'},ensure_ascii=False))
