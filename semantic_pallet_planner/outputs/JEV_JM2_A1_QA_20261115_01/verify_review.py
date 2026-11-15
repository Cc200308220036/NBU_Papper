"""Pure saved data and guarded feature tests; no runtime, solver or credentials."""
import sys,json,hashlib,unittest,io,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'semantic_pallet_planner/src'),str(ROOT/'semantic_pallet_planner/tests/unit')]
import test_packaging_scenario_features as t
m=t.m
D=ROOT/'semantic_pallet_planner/outputs/JEV_JM2_A1_20261115_01'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
manifest=read(D/'delivery_manifest.json')
for r in manifest['files']:
 p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
source=read(D/'source_manifest.json');pkg=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
actual={p.relative_to(pkg).as_posix():sha(p) for p in pkg.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(pkg).parts)}
assert actual==source
old=read(ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01/source_manifest.json')
changed=[k for k,v in old.items() if actual.get(k)!=v];assert set(changed)=={'jev_select/contracts.py','jev_select/packaging_versions.py'}
for name in ('contracts.py','packaging_versions.py'):assert sha(D/'entry_source_bytes'/name)==old['jev_select/'+name]
excluded={'test_real_saved_and_current_share_function_and_entire_population':'Linux absolute paths; independently check archived normalized inputs below','test_central_schema_route_and_legacy_nonempty_guard':'jsonschema unavailable; static route and legacy guard review only'}
names=[n for n in unittest.defaultTestLoader.getTestCaseNames(t.ScenarioTests) if n not in excluded]
suite=unittest.TestSuite(t.ScenarioTests(n) for n in names);stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
(OUT/'tests.log').write_text(stream.getvalue());assert result.wasSuccessful()
def equivalent(a,b):
 if type(a) in (int,float) and type(b) in (int,float):return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-9)
 if isinstance(a,dict) and isinstance(b,dict):return set(a)==set(b) and all(k=='record_digest' or equivalent(a[k],b[k]) for k in a)
 if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(equivalent(x,y) for x,y in zip(a,b))
 return a==b
points=[]
for folder in sorted((D/'saved_public_checks').iterdir()):
 h=read(folder/'historical_input.json');c=read(folder/'current_input.json');hs=read(folder/'historical_signature.json');cs=read(folder/'current_signature.json');b=read(folder/'action_contrast_binding.json')
 assert equivalent(m.build_signature(h),hs) and equivalent(m.build_signature(c),cs) and equivalent(hs['features'],cs['features'])
 assert equivalent(m.bind_contrast(h,b['roles']['A']['exact_action']['candidate_id'],b['roles']['B']['exact_action']['candidate_id'],current=c),b)
 m.validate(hs);m.validate(cs);m.validate(b)
 assert not b['execution_eligible'] and b['ambiguity']
 # Independent full-pool mean, rectangle union for actual saved scene uses the source definition.
 for v,s in [(h,hs),(c,cs)]:
  pool=v['pool'];assert s['features']['candidate_count']['value']==len(pool)
  assert abs(s['features']['candidate_mean_top_mm']['value']-sum(x['pose']['z_base_mm']+x['oriented_size_mm'][2] for x in pool)/len(pool))<1e-9
 points.append(dict(point=folder.name,pool=len(h['pool']),pairs=len(b['correspondence_pairs'])))
origins=read(D/'field_origin_index.json');refs=0
for p in origins['points']:
 for f in p['features'].values():
  for r in f['historical']+f['current']+[f['output']]:
   q=Path(r['path']);q=q if q.is_absolute() else ROOT/q
   assert sha(q)==r['sha256'];v=read(q)
   for part in r['pointer'].lstrip('/').split('/') if r['pointer'] else []:
    key=part.replace('~1','/').replace('~0','~');v=v[int(key)] if isinstance(v,list) else v[key]
   refs+=1
assert len(points)==5 and sum(p['pool'] for p in points)==220
assert m.feature_spec()==read(D/'scenario_feature_spec.json')
r=dict(status='PASS',manifest_entries=len(manifest['files']),source_files=len(source),changed_old_files=changed,local_tests=result.testsRun,excluded_tests=excluded,points=points,field_references=refs,model_calls=0,orders=0,LP=0,scope='Guarded existing pure tests and saved normalized feature recomputation, not original Linux validator or current-state builder replay')
(OUT/'static_checks.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps(r,ensure_ascii=False))
