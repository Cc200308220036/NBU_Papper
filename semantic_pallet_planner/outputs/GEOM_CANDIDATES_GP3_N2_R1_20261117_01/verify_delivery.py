"""Read-only stdlib verification. No production imports or runtime behavior."""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--sealed',action='store_true');args=p.parse_args()
out=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N2_R1_20261117_01')
root=Path('semantic_pallet_planner/src/semantic_pallet_planner')
report=Path('docs/03_阶段产出分析/几何规划模块/几何候选器GP3-N2-R1配置交叉绑定最小整改交付_20261117_01.md')
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def hashed(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
s=read(out/'source_manifest.json')
assert len(s['files'])==534 and len(s['changed_existing'])==3
for n,h in s['files'].items():assert sha(root/n)==h,n
for n in s['changed_existing']:assert sha(out/'source_snapshot'/n)==s['files'][n]
assert sha(out/'test_geometry_binding_r1.py')==sha(Path('semantic_pallet_planner/tests/unit/test_geometry_binding_r1.py'))
before,after=read(out/'before_reproduction.json'),read(out/'after_same_input.json')
assert before['input_config_digest']==after['input_config_digest'] and before['bundle_config_digest']==after['bundle_config_digest']
assert all(r['result']=='ACCEPTED_MISMATCH_FAIL' for r in before['rows'])
assert all(r['result']=='REJECTED' and r['error'].startswith('geometry_config_bundle_mismatch:') for r in after['rows'])
rows=read(out/'consumer_matrix.json');assert len(rows)==170
assert sum(r['result']=='PASS' for r in rows)==2
assert sum(r['result']=='REJECTED' for r in rows)==168
for d in (out/'current_pairs').iterdir():
 cfg,b,a,ctx=map(read,[d/'config.json',d/'bundle.json',d/'audit.json',d/'context.json'])
 assert hashed(cfg)==a['backend_binding']['config_digest']==ctx['local_binding']['config_digest']
 assert cfg==a['config'] and cfg['candidate_backend']==b['candidate_backend']==d.name
 assert cfg['runtime_identity']['source_identity']==hashed(s['files'])
 assert hashed(a)==b['geometry_audit_digest']
for log,count in [('r1_tests_01.log',5),('geometry_public_n2.log',11),('geometry_runtime_n1.log',13),('space_candidates_gp2.log',13)]:
 t=(out/log).read_text();assert f'Ran {count} tests' in t and '\nOK\n' in t
# Historical manifests remain untouched. External source/navigation entries are
# verified against synchronized HEAD, never re-signed to match new code/index.
external_changed={str(root/n) for n in s['changed_existing']}|{str(report.parent/'README.md')}
old_members=0
for name in ('GEOM_CANDIDATES_GP3_N2_20261117_01','GEOM_CANDIDATES_GP3_N2_QA_20261117_01'):
 manifest=Path('semantic_pallet_planner/outputs')/name/'delivery_manifest.json'
 for r in read(manifest)['files']:
  q=Path(r['path'])
  revision='2b47a1fa550262761d3155e428f9a95b5ebf1611' if name=='GEOM_CANDIDATES_GP3_N2_20261117_01' else 'HEAD'
  data=subprocess.check_output(['git','show',revision+':'+q.as_posix()]) if q.as_posix() in external_changed else q.read_bytes()
  assert hashlib.sha256(data).hexdigest()==r['sha256'],q
  old_members+=1
for pth in (report,report.parent/'README.md'):
 for link in re.findall(r'\]\(([^)]+)\)',pth.read_text()):
  if '://' not in link:assert (pth.parent/link.split('#')[0]).exists(),link
if args.sealed:
 manifest=read(out/'delivery_manifest.json')
 expected={p.as_posix() for p in out.rglob('*') if p.is_file() and p.name not in ('delivery_manifest.json','seal_verification.log')}
 expected|={report.as_posix(),(report.parent/'README.md').as_posix(),'semantic_pallet_planner/tests/unit/test_geometry_binding_r1.py'}|{str(root/n) for n in s['changed_existing']}
 assert {r['path'] for r in manifest['files']}==expected
 for r in manifest['files']:
  q=Path(r['path']);assert sha(q)==r['sha256'] and q.stat().st_size==r['size_bytes'],q
print(json.dumps({'status':'PASS_SAVED_FILES_ONLY','sealed':args.sealed,'production_files':534,'changed':3,'historical_manifest_members_verified':old_members,'consumer_results':170,'original_FAIL_preserved':True,'production_calls':0,'checkpoint_restore':'NOT_RUN','parent_A03':'PARTIAL','GP4':'NOT_READY'}))
