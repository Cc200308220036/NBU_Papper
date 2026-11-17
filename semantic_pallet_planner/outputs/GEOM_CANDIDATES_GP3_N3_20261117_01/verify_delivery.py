"""Read-only stdlib bytes/manifests check; no production imports or replay.

All historical Git revisions are explicit frozen identities, never HEAD.
"""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
args=argparse.ArgumentParser();args.add_argument('--sealed',action='store_true');args=args.parse_args()
OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_20261117_01')
ROOT=Path('semantic_pallet_planner/src/semantic_pallet_planner')
REPORT=Path('docs/03_阶段产出分析/几何规划模块/几何候选器GP3-N3公共执行持久化与恢复接入交付_20261117_01.md')
REVISIONS={
 'GEOM_CANDIDATES_GP3_N2_20261117_01':'2b47a1fa550262761d3155e428f9a95b5ebf1611',
 'GEOM_CANDIDATES_GP3_N2_QA_20261117_01':'ce67791e146a3660725ef734a568b4d7dee1c42b',
 'GEOM_CANDIDATES_GP3_N2_R1_20261117_01':'81a9a6ecb4023b2eaa7a8b0fe82d9e550b931f38',
 'GEOM_CANDIDATES_GP3_N2_R1_QA_20261117_01':'5a15186e537fc45d6dbea455e57b58a4995c0e1d'}
def read(p):return json.loads(p.read_bytes())
def rawsha(v):return hashlib.sha256(v).hexdigest()
def sha(p):return rawsha(p.read_bytes())
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return rawsha(canonical(v))
s=read(OUT/'source_manifest.json')
actual={p.relative_to(ROOT).as_posix():sha(p) for p in ROOT.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(ROOT).parts)}
assert actual==s['files'] and len(actual)==542
assert len(s['changed_existing'])==11 and len(s['added'])==8
for n in s['changed_existing']+s['added']:assert sha(OUT/'source_snapshot'/n)==actual[n]
for n in s['changed_existing']:
 raw=subprocess.check_output(['git','show',s['baseline_revision']+':'+str(ROOT/n)])
 assert (OUT/'baseline_source'/n).read_bytes()==raw
for p in (OUT/'test_snapshot').iterdir():assert sha(p)==sha(Path('semantic_pallet_planner/tests/unit')/p.name)
prior=read(Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N2_R1_20261117_01/source_manifest.json'))['files']
assert all(actual[n]==h for n,h in prior.items() if '/schemas/' in n)
# Only declared external production files/index may be different now. Package
# members always read current bytes; never hide a changed historical package.
changed_external={str(ROOT/n) for n in s['changed_existing']}|{str(REPORT.parent/'README.md')}
historical=0
for name,revision in REVISIONS.items():
 for r in read(Path('semantic_pallet_planner/outputs')/name/'delivery_manifest.json')['files']:
  p=Path(r['path'])
  raw=subprocess.check_output(['git','show',revision+':'+str(p)]) if str(p) in changed_external else p.read_bytes()
  assert rawsha(raw)==r['sha256'],(name,str(p))
  historical+=1
cases=0;blob_copies=0;test_double_rows=0
for p in sorted((OUT/'cases').iterdir()):
 cfg,task,result=map(read,[p/'config.json',p/'task.json',p/'result.json'])
 assert cfg['version']=='jev_packaging_geometry_run_v15' and cfg['construction_only'] is False
 assert cfg['runtime_identity']['source_identity']==digest(actual)
 assert cfg['fixture_task_digest']==digest(task)==cfg['runtime_identity']['task_identity']
 assert task['version']=='jev_geometry_fixture_task_v1' and task['fixture_only'] is True
 cp=result['checkpoint']
 assert read(p/'durable/checkpoint.json')==cp
 assert cp['record_digest']==digest({k:v for k,v in cp.items() if k!='record_digest'})
 assert cp['config_digest']==digest(cfg) and cp['execution_binding']['config_digest']==digest(cfg)
 def get(ref):
  raw=(p/'durable/blobs'/ref['sha256']).read_bytes();assert rawsha(raw)==ref['sha256'];return raw
 def obj(ref):return json.loads(get(ref))
 for blob in (p/'durable/blobs').iterdir():assert sha(blob)==blob.name;blob_copies+=1
 for e in cp['events']:
  if e.get('geometry_ref'):
   a=obj(e['geometry_ref'])
   if a['version']=='geometry_durable_decision_v1':
    assert canonical(a['bundle'])==canonical(e['bundle'])
    assert canonical(a['audit']['config'])==canonical(cfg)
    assert digest(a['audit'])==e['bundle']['geometry_audit_digest']
    i=obj(a['input']);n,g=get(i['native']),get(i['geometry'])
    assert rawsha(n)==i['binding']['native_snapshot_sha256'] and rawsha(g)==i['binding']['geometry_input_sha256']
    assert a['audit']['native_bytes_hex']==n.hex() and a['audit']['geometry_bytes_hex']==g.hex()
    assert digest(i['binding'])==e['bundle']['common_input_digest']
   else:assert a['version']=='geometry_generation_failure_v1' and a['audit']['TEST_DOUBLE'] is True
  if e.get('context') is not None:
   body=e['context']['request_body']
   if body is not None:
    assert len(canonical(body))<=96000
    text=canonical(body).decode()
    assert not any(word in text for word in ('e2_original_v1','ems_surface_hybrid_v1','numerical_profile','geometry_runtime','geometry_audit','host','monitor'))
  row=e.get('monitor')
  if row is not None:
   assert row['binding']['state_digest']==digest(e['before'])
   assert row['binding']['action_digest']==digest(e['proposed_action'])
   assert row['credential_digest']==digest({k:v for k,v in row.items() if k!='credential_digest'})
   if row['result'] is not None:
    assert row['result']['diagnostics']['TEST_DOUBLE'] is True and row['result']['kernel_calls']==0
    test_double_rows+=1
   if row['status']!='STABLE':assert e['before']==e['after'] and e['action'] is None
  if e['event']=='PLACE':assert row is not None and row['status']=='STABLE'
 cases+=1
assert cases==13
for name,count in [('n3_tests_final.log',10),('test_geometry_binding_r1.log',5),('test_geometry_public_n2.log',11),('test_geometry_runtime_n1.log',13),('test_space_candidates_gp2.log',13)]:
 text=(OUT/name).read_text();assert f'Ran {count} tests' in text and '\nOK\n' in text
assert '3 passed' in (OUT/'legacy_runtime.log').read_text()
for p in (REPORT,REPORT.parent/'README.md'):
 for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),target
if args.sealed:
 m=read(OUT/'delivery_manifest.json')
 paths={p.as_posix() for p in OUT.rglob('*') if p.is_file() and p.name not in ('delivery_manifest.json','seal_verification.log')}
 paths|={REPORT.as_posix(),(REPORT.parent/'README.md').as_posix(),'semantic_pallet_planner/tests/unit/test_geometry_execution_n3.py'}|{str(ROOT/n) for n in s['changed_existing']+s['added']}
 assert paths=={r['path'] for r in m['files']}
 for r in m['files']:
  p=Path(r['path']);assert sha(p)==r['sha256'] and p.stat().st_size==r['size_bytes'],str(p)
print(json.dumps({'status':'PASS_SAVED_BYTES_AND_FIXED_HISTORICAL_REVISIONS_ONLY','sealed':args.sealed,'production_files':542,'saved_cases':cases,'blob_file_copies':blob_copies,'test_double_monitor_rows':test_double_rows,'historical_manifest_members':historical,'production_imports':0,'runtime_calls':0,'real_PCT_LP_calls':0,'model_calls':0,'real_kernel_E2E':'NOT_RUN','A03':'PARTIAL','GP4':'NOT_READY'}))
