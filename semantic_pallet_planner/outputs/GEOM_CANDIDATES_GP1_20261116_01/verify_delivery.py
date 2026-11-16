"""Read-only GP1 archive verification; never imports or runs space algorithms."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

ROOT=Path.cwd()
OUT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(),parse_float=Decimal)
def check_ref(r):
    p=ROOT/r['path'];assert p.is_file() and sha(p)==r['sha256'],r
    return p

manifest=load(OUT/'delivery_manifest.json')
assert 'delivery_manifest.json' not in manifest['package_files']
actual={p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*') if p.is_file() and p.name!='delivery_manifest.json'}
assert actual==manifest['package_files']
for path,h in manifest['external_delivery_files'].items():assert sha(ROOT/path)==h,path
sources=load(OUT/'source_manifest.json')
pkg=ROOT/sources['package_root']
current={p.relative_to(pkg).as_posix():sha(p) for p in pkg.rglob('*') if p.is_file() and p.suffix in ('.py','.json')
         and not {'tests','__pycache__'}.intersection(p.relative_to(pkg).parts)}
assert current==sources['files']
assert len(sources['new_production_files'])==4
for r in sources['protected_artifacts']:check_ref(r)
for r in sources['entry_documents']:check_ref(r)
old=load(check_ref(sources['gp0_source_manifest']))
assert all(current[k]==v for k,v in old['files'].items())
assert sorted(set(current)-set(old['files']))==sorted(sources['new_production_files'])
configs=load(OUT/'config_snapshot.json');assert configs['budgets']==load(check_ref(configs['gp0_config']))['new_generator_draft']['budgets']
assert configs['stage']=='GP1' and configs['authorization']['model_calls']==configs['authorization']['candidate_generations']==0
checks=load(OUT/'checks.json')
assert checks['A01']['status']=='PASS_DEVELOPER_SELF_CHECK_PENDING_INDEPENDENT_QA'
assert all(checks['other_acceptance'][k]=='NOT_RUN' for k in ('A02','A03','A04','A05','A06'))
for c in checks['commands']:
    if 'stdout' in c:assert (OUT/c['stdout']).is_file()
    if 'stderr' in c:assert (OUT/c['stderr']).is_file()
assert checks['test_methods']==12

space_counts={}
for p in sorted((OUT/'constructed').glob('*_input.json')):
    value=load(p);name=p.name.removesuffix('_input.json')
    r=load(OUT/'constructed'/f'{name}_index.json')
    assert r['status'] in ('OK','OK_EMPTY')
    assert (r['status']=='OK_EMPTY')==(r['spaces']==[])
    c=value['container'];occupied=[]
    for o in value['placed_items']:
        l,w,h=map(Decimal,o['oriented_size_mm']);x,y,z=(Decimal(o['pose'][k]) for k in ('x_mm','y_mm','z_base_mm'))
        occupied.append((x-l/2,y-w/2,z,x+l/2,y+w/2,z+h))
    seen=set()
    for s in r['spaces']:
        b=tuple(map(Decimal,s['bounds_mm']));assert b not in seen;seen.add(b)
        assert all(b[d]<b[d+3] for d in range(3))
        assert -Decimal(c['length_mm'])/2<=b[0]<b[3]<=Decimal(c['length_mm'])/2
        assert -Decimal(c['width_mm'])/2<=b[1]<b[4]<=Decimal(c['width_mm'])/2
        assert 0<=b[2]<b[5]<=c['max_height_mm']
        assert not any(all(min(b[d+3],o[d+3])>max(b[d],o[d]) for d in range(3)) for o in occupied)
        assert set(s['source_types'])<=set(('EMS_STYLE_3D','SURFACE_CORNER'))
        assert s['space_id']=='space_'+hashlib.sha256(json.dumps(s['bounds_mm'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    for k,v in r['budget_usage']['used'].items():assert v<=configs['budgets'][k]
    for seed in r['surface']['seeds']:
        for expansion in seed['expansions']:assert expansion['space_id'] in {s['space_id'] for s in r['spaces']}
    space_counts[name]=len(r['spaces'])
assert len(space_counts)==6
for fault in load(OUT/'budget_fault_injections.json'):
    r=fault['result'];assert fault['test_double'] and r['status']=='ERROR' and r['spaces']==[] and r['surface'] is None
    assert r['error']['code']=='GEOMETRY_BUDGET_EXCEEDED'
handoff=load(OUT/'handoff.json');assert handoff['stop'] and handoff['next_stage_admission']=='INDEPENDENT_QA_ONLY'
for f in [ROOT/handoff['report'], ROOT/'docs/03_阶段产出分析/几何规划模块/README.md']:
    for link in re.findall(r'\]\(([^)]+)\)',f.read_text()):
        if not link.startswith(('https://','http://','#')):assert (f.parent/link).exists(),link
print(json.dumps(dict(status='PASS_READ_ONLY_DELIVERY',source_files=len(current),old_files_unchanged=len(old['files']),
                      constructed_space_counts=space_counts,scope='hashes, archived geometric properties, budget receipts and links; no algorithm rerun'),indent=2))
