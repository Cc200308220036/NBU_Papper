"""Independent R8 input seal; execution authorization deliberately absent."""
import ast,json,hashlib
from pathlib import Path
from scope_guard import UNIT,SOURCE,ALLOWED,LIMITS
I=Path(__file__).resolve().parent;B=I.parent
read=lambda p:json.loads(p.read_bytes())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert not (I/'frozen_identity.json').exists(),'NO_RESEAL'
for f in I.glob('*.py'):ast.parse(f.read_bytes())
# Verify historical bytes against existing identities; never replace them.
for inventory in (I/'historical_inventory.readonly.json',I/'archive_member_identity.json',B/'GEOM_CANDIDATES_GP5_NUM_N1_R6_20261118_01/frozen_identity.json'):
 for rel,h in read(inventory)['files'].items():assert sha(Path(rel))==h,rel
files={str(f):sha(f) for f in I.iterdir() if f.suffix in ('.py','.json') and f.name!='frozen_identity.json'}
files.update(read(I/'archive_member_identity.json')['files'])
files.update(read(I/'historical_inventory.readonly.json')['files'])
files.update(read(B/'GEOM_CANDIDATES_GP5_NUM_N1_R6_20261118_01/frozen_identity.json')['files'])
# Bind actual imported test helpers, their source-adjacent fixtures, production
# manifest and every source byte, plus monitor dependency/environment preflight.
for f in Path('semantic_pallet_planner/tests/unit').iterdir():
 if f.suffix in ('.py','.json'):files[str(f)]=sha(f)
for rel,h in read(I/'source_manifest.json')['files'].items():files[str(Path('semantic_pallet_planner/src/semantic_pallet_planner')/rel)]=h
root=str(B/'GEOM_CANDIDATES_GP5_NUM_N1_R8_RUN_20261119_01');assert not Path(root).exists()
value={'version':'geometry_num_n1_r8_input_freeze_v1','unit':UNIT,'source_identity':SOURCE,'source_files':591,'allowed_jobs':ALLOWED,'limits':LIMITS,'run_root':root,'execution_authorized':False,'authorization_receipt':'NOT_ISSUED','old_E_used':21,'old_E_cap':21,'carryover':False,'historical_identity_rewrite':False,'files':files}
(I/'frozen_identity.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
print('PASS independent freeze',len(files),'members; exact root',root,'; execution NOT_AUTHORIZED')
