"""Seal new R6 test-layer inputs; no business execution or permit issuance."""
import ast,hashlib,json
from pathlib import Path
I=Path(__file__).resolve().parent;ROOT=Path.cwd();R5=I.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R5_20261118_01'
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,v):(I/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
assert not (I/'frozen_identity.json').exists(),'NO_OVERWRITE_OF_SEAL'
for f in I.glob('*.py'):ast.parse(f.read_bytes(),filename=str(f))
for rel,h in read(I/'archive_member_identity.json')['files'].items():assert sha(Path(rel))==h
for rel,h in read(R5/'frozen_identity.json')['files'].items():assert sha(Path(rel))==h
src=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner';current={str(f.relative_to(src)):sha(f) for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
assert current==read(I/'source_manifest.json')['files'] and len(current)==591
scope=read(I/'validation_scope.json');tree=ast.parse((I/'remaining_checks.py').read_bytes())
names={n.comparators[0].value for n in ast.walk(tree) if isinstance(n,ast.Compare) and isinstance(n.left,ast.Name) and n.left.id=='name' and len(n.comparators)==1 and isinstance(n.comparators[0],ast.Constant)}
assert names=={r['name'] for r in scope['X_H_names']} and len(names)==15
unchanged={n:sha(I/n) for n in ('run_state.py','negative_contract.py','remaining_checks.py','harness.py','expected_rejections.json')}
assert all(h==sha(R5/n) for n,h in unchanged.items())
write('guard_preservation.json',{'same_R5_bytes':unchanged,'separate_output_root':'PRESERVED','denominator_35_attempts_and_passes_separate':'PRESERVED','exact_expected_type_and_code':'PRESERVED','R5_guard_regression_methods':7,'status':'PASS'})
write('static_entrypoint_review.json',{'syntax':'PASS','fixed_C_E_R_X_H_ADMIN':[6,8,6,15],'original_X_H_names':sorted(names),'business_runtime':'NOT_RUN','new_functional_change':'F0 route-aware receipt + conditional request-field pairing only','necessary_wiring':'coverage reexport; R6 authorization unit and old R5/QA read-only protection','production_changes':0})
files=dict(read(R5/'frozen_identity.json')['files']);files.update(read(I/'archive_member_identity.json')['files'])
for row in read(I/'saved_f0_revalidation.json')['rows']:files.update(row['all_original_members'])
for f in I.iterdir():
 if f.suffix in ('.py','.json') and f.name not in ('frozen_identity.json','results.json','handoff.json','call_accounting.json','delivery_manifest.json'):files[str(f.relative_to(ROOT))]=sha(f)
write('frozen_identity.json',{'version':'geometry_num_n1_r6_input_freeze_v1','source_identity':read(I/'source_manifest.json')['source_identity'],'files':files,'scope_sha256':sha(I/'validation_scope.json'),'environment_receipt_sha256':sha(I/'environment_receipt.json'),'execution_authorized':False,'authorization_receipt':'ABSENT_PENDING_EXPLICIT_USER_ASSIGNMENT','output_root':'MUST_BE_EXPLICIT_NEW_SEPARATE_DIRECTORY','historical_identity_rewrite':False})
print('PASS R6 freeze',len(files),'identities; same591 production/environment; saved originals and R5 guards unchanged; no authorization issued')
