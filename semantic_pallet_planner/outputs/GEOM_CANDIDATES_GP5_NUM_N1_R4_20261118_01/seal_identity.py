"""Stdlib freeze and saved-only checker; never imports suite or production."""
import hashlib,json,shutil
from pathlib import Path
O=Path(__file__).resolve().parent;ROOT=Path.cwd();SRC=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_bytes())
def write(n,v):(O/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
manifest=read(O/'source_manifest.json')
current={str(f.relative_to(SRC)):sha(f) for f in SRC.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(SRC).parts)}
assert current==manifest['files'] and len(current)==591
assert not (O/'frozen_identity.json').exists(),'NO_FREEZE_OVERWRITE'
files=[]
for rel in current:
 f=SRC/rel;dest=O/'source_snapshot'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dest);files.extend((f,dest))
for name in ('geometry_native_assertions_r2.py','test_geometry_order_p1.py','test_geometry_order_r1.py'):
 f=ROOT/'semantic_pallet_planner/tests/unit'/name;dest=O/'test_snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dest);files.extend((f,dest))
# Future ADMIN operations stay read/adapt/digest/reject only; freeze exact sources.
admin=[]
for tid in ('NEW_00100027_controlled_base','NEW_00100027_controlled_capacity_tight'):
 f=ROOT/'semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02/tasks'/(tid+'.json');files.append(f);admin.append({'path':str(f.relative_to(ROOT)),'sha256':sha(f),'usage':'ADMIN_READ_ADAPT_DIGEST_PRE_EPISODE_REFUSAL_ONLY','executed':False})
write('admin_input_identity.json',admin)
policy=O.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R3_20261118_01/policy_identity.json';shutil.copyfile(policy,O/'policy_identity.json')
files.append(ROOT/'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_20261117_01/cases/ems_surface_hybrid_v1_stable/config.json')
files.extend(f for f in O.iterdir() if f.suffix in ('.py','.json') and f.name not in ('frozen_identity.json','call_accounting.json','results.json','handoff.json','delivery_manifest.json'))
# Input authority, never navigation or later runtime outputs.
write('frozen_identity.json',{'version':'geometry_num_n1_r4_frozen_identity_v1','source_identity':manifest['source_identity'],'files':{str(f.relative_to(ROOT)):sha(f) for f in sorted(set(files))},'execution_authorized':False,'real_calls':0})
print('PASS frozen source591 snapshots, eight configs, plan, data, monitor, policy, deps and entrypoint identities')
