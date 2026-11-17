"""Read-only stdlib file/saved-artifact verification. No production imports."""
import argparse
import hashlib
import json
from pathlib import Path
import re

args=argparse.ArgumentParser();args.add_argument('--sealed',action='store_true');args=args.parse_args()
OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N2_20261117_01')
PKG=Path('semantic_pallet_planner/src/semantic_pallet_planner')
REPORT=Path('docs/03_阶段产出分析/几何规划模块/几何候选器GP3-N2公共候选与F0构造接入开发交付_20261117_01.md')
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def encode(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(encode(v)).hexdigest()
def sealed(v):assert v['record_digest']==digest({k:x for k,x in v.items() if k!='record_digest'})

s=read(OUT/'source_manifest.json')
actual={p.relative_to(PKG).as_posix():sha(p) for p in PKG.rglob('*') if p.is_file()
        and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(PKG).parts)}
assert actual==s['files'] and len(actual)==534
prior=read(Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N1_20261117_01/source_manifest.json'))['files']
assert sorted(k for k in prior if actual.get(k)!=prior[k])==sorted(s['changed_existing'])
assert len(s['changed_existing'])==11 and len(s['added'])==4
assert all(n.startswith('jev_select/') or n=='planner/space_candidates/generator.py' for n in s['changed_existing'])
assert all(actual[k]==h for k,h in prior.items() if '/schemas/' in k)
for n in s['changed_existing']+s['added']:assert sha(OUT/'source_snapshot'/n)==actual[n]
for name in ('test_geometry_public_n2.py','test_geometry_runtime_n1.py','test_space_candidates_gp2.py'):
    assert sha(OUT/'test_snapshot'/name)==sha(Path('semantic_pallet_planner/tests/unit')/name)

groups={}
for path in (OUT/'cases').glob('*/*'):
    b,a,ctx,cfg=map(read,[path/'bundle.json',path/'audit.json',path/'context.json',path/'config.json'])
    n,g=path/'B_native.json',path/'B_geometry.json'
    common,adm,back=a['common_binding'],a['common_admission'],a['backend_binding']
    for record in (common,adm,back):sealed(record)
    assert sha(n)==common['native_snapshot_sha256'] and sha(g)==common['geometry_input_sha256']
    assert n.read_bytes().hex()==a['native_bytes_hex'] and g.read_bytes().hex()==a['geometry_bytes_hex']
    assert common['source_identity']==digest(actual)==cfg['runtime_identity']['source_identity']
    assert b['geometry_audit_digest']==digest(a)
    assert b['common_input_digest']==digest(common)==adm['common_input_digest']==back['common_input_digest']
    assert back['admission_digest']==digest(adm) and adm['status']=='PASS'
    assert b['backend_binding_digest']==digest(back)
    assert b['candidate_backend']==back['candidate_backend']==cfg['candidate_backend']
    assert b['generator_config_digest']==back['generator_config_digest']==cfg['generator_config_digest']
    assert back['config_digest']==digest(cfg)==ctx['local_binding']['config_digest']
    assert encode(b['physical_candidates'])==encode(b['selectable_candidates'])
    assert digest(b['physical_candidates'])==b['physical_digest']==b['selectable_digest']==a['final_candidates_digest']
    assert encode(b['generation_counts'])==encode(a['generation_counts'])
    assert ctx['local_binding']['common_input_digest']==digest(common)
    assert ctx['local_binding']['backend_binding_digest']==digest(back)
    body=read(path/'request.json');assert encode(body)==encode(ctx['request_body'])
    if body is not None:
        assert len(encode(body))<=96000
        text=encode(body).decode()
        assert all(word not in text for word in ('profile','host','geometry_audit','e2_original_v1','ems_surface_hybrid_v1','monitor'))
    stats=read(path/'telemetry.json')
    assert stats['backend']==cfg['candidate_backend']
    if stats['backend']=='ems_surface_hybrid_v1':
        assert stats['cache_supported'] is False and stats['cache_hits'] is None and stats['cache_misses'] is None
    else:assert stats['cache_supported'] is True and stats['cache_hits']+stats['cache_misses']==len(read(n)['current_state']['pending_items'])
    groups.setdefault(path.parent.name,[]).append((n.read_bytes(),g.read_bytes(),common,adm))
assert len(groups)==4
for rows in groups.values():assert len(rows)==2 and rows[0]==rows[1]
for p in (OUT/'failures').glob('*/*/error.json'):
    err=read(p);audit=read(p.parent/'audit.json')
    assert err['bundle_returned'] is False and err['fallback'] is False and err['state_unchanged'] is True
    if err['scope']=='COMMON_INPUT_ERROR':assert audit['backend_binding'] is None
    else:assert err['code']=='PHYSICAL_CHECK_DISAGREEMENT' and audit['common_admission']['status']=='PASS'
for name in ('empty','platform'):
    assert encode(read(OUT/'legacy'/f'{name}_reviewed.json'))==encode(read(OUT/'legacy'/f'{name}_current.json'))
links=0
for p in (REPORT,REPORT.parent/'README.md'):
    for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
        if '://' not in target:
            assert (p.parent/target.split('#')[0]).exists(),target
            links+=1
if args.sealed:
    manifest=read(OUT/'delivery_manifest.json')
    for r in manifest['files']:
        assert sha(Path(r['path']))==r['sha256'],r['path']
        assert Path(r['path']).stat().st_size==r['size_bytes']
    expected={p.as_posix() for p in OUT.rglob('*') if p.is_file() and p.name not in ('delivery_manifest.json','seal_verification.log')}
    expected|={REPORT.as_posix(),(REPORT.parent/'README.md').as_posix(),'semantic_pallet_planner/tests/unit/test_geometry_public_n2.py'}
    expected|={(PKG/n).as_posix() for n in s['changed_existing']+s['added']}
    assert {r['path'] for r in manifest['files']}==expected
print(json.dumps({'status':'PASS_SAVED_FILES_BYTES_AND_LINKS_ONLY','source_files':534,'unchanged_N1_files':519,
    'paired_hand_states':4,'saved_error_records':4,'links_checked':links,'sealed_manifest_verified':args.sealed,
    'production_imports':0,'candidate_calls':0,'run_episode_calls':0,'PCT_LP_calls':0,'model_calls':0,
    'checkpoint_restore':'NOT_RUN','parent_A03':'PARTIAL'},ensure_ascii=False))
