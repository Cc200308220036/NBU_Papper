"""Read-only source/evidence collection, fixed baseline revision; no loop calls."""
from pathlib import Path
import json,hashlib,shutil,subprocess
OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_R1_20261117_01')
ROOT=Path('semantic_pallet_planner/src/semantic_pallet_planner')
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
files={p.relative_to(ROOT).as_posix():sha(p) for p in ROOT.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(ROOT).parts)}
old=json.loads((OUT/'before_source_manifest.json').read_bytes())['files']
changed=sorted(n for n in old if files[n]!=old[n]);assert changed==['jev_select/episode.py','jev_select/geometry_execution.py']
assert files.keys()==old.keys()
save('source_manifest.json',{'files':files,'changed_existing':changed,'added':[],'production_files':len(files),'baseline_revision':json.loads((OUT/'baseline.json').read_bytes())['sync_head'],'validation_revision':'geometry_technical_failure_recovery_v1'})
for n in changed:
 p=OUT/'source_snapshot'/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/n,p)
for n in ('test_geometry_recovery_r1.py','test_geometry_execution_n3.py'):
 p=OUT/'test_snapshot'/n;p.parent.mkdir(exist_ok=True);shutil.copyfile(Path('semantic_pallet_planner/tests/unit')/n,p)
(OUT/'source_diff.patch').write_bytes(subprocess.check_output(['git','diff','--',str(ROOT)]))
print(json.dumps({'production_files':len(files),'changed_existing':changed,'unchanged':len(files)-len(changed),'old_schemas_unchanged':True}))
