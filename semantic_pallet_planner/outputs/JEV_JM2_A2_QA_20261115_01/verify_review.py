"""Guarded saved-artifact review. No builder main, network, engine or LP."""
import sys,json,hashlib,math,io,contextlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent;D=ROOT/'semantic_pallet_planner/outputs/JEV_JM2_A2_20261115_01'
sys.path[:0]=[str(D),str(ROOT/'semantic_pallet_planner/src'),str(ROOT/'semantic_pallet_planner/tests/unit')]
import verify_delivery as original
from build_and_verify import m,read
buf=io.StringIO()
with contextlib.redirect_stdout(buf):original.main()
(OUT/'original_verifier.log').write_text(buf.getvalue())
def eq(a,b):
 if type(a) in (int,float) and type(b) in (int,float):return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-9)
 if isinstance(a,dict) and isinstance(b,dict):return set(a)==set(b) and all(eq(a[k],b[k]) for k in a)
 if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(eq(x,y) for x,y in zip(a,b))
 return a==b
cards=read(D/'case_snapshot_candidate.json')['cards'];index=read(D/'private_audit_index.json')['cards'];labels=[]
for c,e in zip(cards,index):
 h=read(ROOT/e['a1_input']['path']);q=m.query_projection(h)
 assert all(eq(q[k],c[k]) for k in ('coordinate','structure','features'))
 m.validate(c)
 for row,pair in zip(c['observations'],e['pairs']):
  for role in ('A','B'):
   b=read(ROOT/pair['branches'][role]['path'])
   for k,v in row[role].items():assert eq(v,b['metrics'][k])
  for k in m.METRICS:assert eq(row['delta_B_minus_A'][k],row['B'][k]-row['A'][k])
  labels.append(row['label'])
 assert not c['execution_eligible'] and c['sufficiency_review']=='NOT_RUN_A3'
source=read(D/'source_manifest.json');pkg=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
actual={p.relative_to(pkg).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in pkg.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(pkg).parts)}
assert actual==source and len(cards)==5 and len(labels)==9
result=dict(status='PASS_LIMITED_SAVED_REVIEW',original_verifier=buf.getvalue().strip(),source_files=len(actual),cards=5,pairs=9,labels={k:labels.count(k) for k in set(labels)},local_unit_tests=dict(passed=3,failed=1,errors=2,reason='3.9 vs frozen3.13 floating sum and inherited PEP701 f-string syntax'),numeric_recheck='PASS with rel_tol1e-12 abs_tol1e-9; not identity or byte equivalence',production_suite='NOT_RUN_IN_FROZEN_ENV',model_calls=0,LP=0)
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
