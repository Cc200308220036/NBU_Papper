"""GP1-only constructed evidence. No saved orders or production entrypoints.

One-time output writer; refuses overwrites. Run from repository root.
Source/test import and network/subprocess/credential guards cover constructions.
"""
import ast
import hashlib
import importlib.abc
import json
from pathlib import Path
import runpy
import sys
import time

ROOT=Path.cwd()
OUT=Path(__file__).resolve().parent
PACKAGE=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
TEST=ROOT/'semantic_pallet_planner/tests/unit/test_space_geometry_gp1.py'


class ImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith('semantic_pallet_planner.') and fullname not in (
            'semantic_pallet_planner.planner','semantic_pallet_planner.planner.space_candidates',
            'semantic_pallet_planner.planner.space_candidates.contracts',
            'semantic_pallet_planner.planner.space_candidates.empty_spaces',
            'semantic_pallet_planner.planner.space_candidates.surface_spaces'):
            raise AssertionError('forbidden project import '+fullname)
        if fullname.split('.')[0] in ('numpy','scipy','torch','requests','httpx'):
            raise AssertionError('forbidden external import '+fullname)


def audit(event,args):
    if event.startswith(('socket.','subprocess.')) or event in ('os.system','os.fork','os.posix_spawn'):
        raise AssertionError('forbidden operation '+event)
    if event=='open':
        path=str(args[0]).lower()
        if any(t in path for t in ('credentials','secrets.json','api_key','.pem','.env')):
            raise AssertionError('forbidden credential access')


sys.meta_path.insert(0,ImportGuard())
sys.addaudithook(audit)
ns=runpy.run_path(str(TEST),run_name='gp1_evidence_fixtures')
build,encode=ns['build_space_index'],ns['encode']
from semantic_pallet_planner.planner.space_candidates.contracts import Budget,DEFAULT_LIMITS
from semantic_pallet_planner.planner.space_candidates import _build_space_index


def write(path,value):
    p=OUT/path;p.parent.mkdir(exist_ok=True,parents=True)
    with p.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')


summary=[]
for name,scene in ns['SCENES'].items():
    raw=encode(scene);started=time.perf_counter();r=build(raw);elapsed=time.perf_counter()-started
    assert r['status']!='ERROR',r
    write('constructed/'+name+'_input.json',scene)
    write('constructed/'+name+'_index.json',r)
    summary.append(dict(scene=name,status=r['status'],space_count=len(r['spaces']),budget_usage=r['budget_usage'],
                        observation_wall_s=elapsed,semantic_digest=r['semantic_digest']))

failures=[]
for key in ('active_spaces','space_containment_comparisons','surface_event_cells','surface_expansion_cell_checks'):
    limits=dict(DEFAULT_LIMITS);limits[key]=0
    r=_build_space_index(encode(ns['SCENES']['overhead_cavity']),Budget(limits))
    assert r['status']=='ERROR' and r['spaces']==[] and r['surface'] is None
    failures.append(dict(test_double=True,lowered_limit=key,result=r))
write('budget_fault_injections.json',failures)
write('constructed_summary.json',summary)

# Small code-native SVG cross sections; float conversion is DISPLAY ONLY.
for name in ('same_height_platform','steps','overhead_cavity'):
    scene=ns['SCENES'][name]
    r=json.loads((OUT/('constructed/'+name+'_index.json')).read_text())
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="780" height="420" viewBox="0 0 780 420">',
         '<rect width="780" height="420" fill="white"/>',
         '<text x="25" y="24" font-size="16">'+name+' : x-z slice, y=0 (display only)</text>']
    def rect(a,color,opacity,width):
        x0,y0,z0,x1,y1,z1=map(float,a)
        if not y0<=0<=y1:return
        svg.append(f'<rect x="{45+(x0+5)*65}" y="{365-z1*30}" width="{(x1-x0)*65}" height="{(z1-z0)*30}" fill="{color}" fill-opacity="{opacity}" stroke="{color}" stroke-width="{width}"/>')
    for s in r['spaces']:
        rect(s['bounds_mm'],'#2477b5' if s['source_types']==['EMS_STYLE_3D'] else '#26955d',0.035,1)
    for b in scene['placed_items']:
        p=b['pose'];sx,sy,sz=b['oriented_size_mm'];x,y,z=p['x_mm'],p['y_mm'],p['z_base_mm']
        rect([x-sx/2,y-sy/2,z,x+sx/2,y+sy/2,z+sz],'#454545',0.8,2)
    svg.extend(['<text x="25" y="402" font-size="13">Blue: EMS-only; green: surface/merged; grey: occupied. Overlapping spaces are proposals.</text>','</svg>'])
    p=OUT/('figures/'+name+'.svg');p.parent.mkdir(exist_ok=True)
    with p.open('x') as f:f.write('\n'.join(svg)+'\n')

newfiles=sorted((PACKAGE/'planner/space_candidates').glob('*.py'))
for p in newfiles:
    tree=ast.parse(p.read_text())
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom) and node.level==0:
            assert node.module.split('.')[0] in ('dataclasses','decimal','fractions','collections')
        if isinstance(node,ast.Import):
            assert all(n.name in ('hashlib','json') for n in node.names)
write('execution_guards.json',dict(scope='constructed evidence process: guard installed before all project imports',
    project_modules=[k for k in sys.modules if k.startswith('semantic_pallet_planner')],
    allowed_code_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in newfiles},
    network='DENIED_BY_AUDIT_HOOK',subprocess='DENIED_BY_AUDIT_HOOK',credential_paths='DENIED_BY_AUDIT_HOOK',
    forbidden_dependencies='DENIED_BY_IMPORT_FINDER',production_entrypoints='DENIED_BY_IMPORT_FINDER',
    guard_triggered=False,physical_admission='NOT_RUN',orders='NOT_RUN',models='NOT_RUN',LP='NOT_RUN'))
print(json.dumps(dict(status='PASS_CONSTRUCTED_GP1_ONLY',scenes=summary),ensure_ascii=False,indent=2))
