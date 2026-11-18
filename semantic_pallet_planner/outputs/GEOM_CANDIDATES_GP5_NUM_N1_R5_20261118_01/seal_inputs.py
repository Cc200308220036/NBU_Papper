"""New input freeze; stdlib metadata only, no business authorization issued."""
import ast,hashlib,json
from pathlib import Path
I=Path(__file__).resolve().parent;ROOT=Path.cwd();R4=I.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R4_20261118_01'
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,v):(I/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
assert not (I/'frozen_identity.json').exists(),'DO_NOT_OVERWRITE_SEAL'
for f in I.glob('*.py'):ast.parse(f.read_bytes(),filename=str(f))
for rel,h in read(I/'archive_member_identity.json')['files'].items():assert sha(Path(rel))==h,rel
for rel,h in read(R4/'frozen_identity.json')['files'].items():assert sha(Path(rel))==h,rel
src=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
current={str(f.relative_to(src)):sha(f) for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
assert current==read(I/'source_manifest.json')['files'] and len(current)==591
scope=read(I/'validation_scope.json');tree=ast.parse((I/'remaining_checks.py').read_bytes())
names={n.comparators[0].value for n in ast.walk(tree) if isinstance(n,ast.Compare) and isinstance(n.left,ast.Name) and n.left.id=='name' and len(n.comparators)==1 and isinstance(n.comparators[0],ast.Constant)}
assert names=={r['name'] for r in scope['X_H_names']} and len(names)==15
write('static_entrypoint_review.json',{'AST_syntax':'PASS','original_X_H_admin_names':sorted(names),'X_H_admin_count':15,'C_E_R_denominators':[6,8,6],'runtime':'NOT_RUN','isolation':'sealed INPUTS -> explicit fresh output root; no default output in archive','C_coverage_receipts':'conversion_case + production_identity_contract_receipt','E_coverage_receipts':'saved full closure + f0_receipt + compare_f0','expected_exceptions':'exact per-case class/code; unexpected preserved; original completion test assertion context replaced with exact contract','business_authorization':'NOT_GRANTED'})
files={rel:h for rel,h in read(R4/'frozen_identity.json')['files'].items()}
files.update(read(I/'archive_member_identity.json')['files'])
# Freeze read-only saved snapshot fixture used by pure helper tests.
r=ROOT/'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01/E/jobs/J00';ep=read(r/'episode.json');ev=[x for x in ep['events'] if x.get('bundle')][-1]
for f in (r/'episode.json',r/'blobs'/ev['geometry_ref']['sha256']):files[str(f.relative_to(ROOT))]=sha(f)
for f in I.iterdir():
 if f.suffix in ('.py','.json') and f.name not in ('results.json','handoff.json','call_accounting.json','delivery_manifest.json','frozen_identity.json'):files[str(f.relative_to(ROOT))]=sha(f)
write('frozen_identity.json',{'version':'geometry_num_n1_r5_input_freeze_v1','source_identity':read(I/'source_manifest.json')['source_identity'],'files':files,'scope_sha256':sha(I/'validation_scope.json'),'environment_receipt_sha256':sha(I/'environment_receipt.json'),'execution_authorized':False,'authorization_receipt':'ABSENT_PENDING_EXPLICIT_USER_ASSIGNMENT','output_root':'MUST_BE_EXPLICIT_NEW_SEPARATE_DIRECTORY','historical_records':'PRESERVED_ORIGINAL_BYTES_NOT_RESIGNED'})
print('PASS new input freeze',len(files),'identities; production591 unchanged; original archives unchanged; no run root or authorization created')
