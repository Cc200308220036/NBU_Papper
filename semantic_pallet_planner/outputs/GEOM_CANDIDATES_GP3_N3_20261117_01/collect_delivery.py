"""Snapshot current source, existing results and fixed baseline; no runtime calls."""
from pathlib import Path
import json,hashlib,subprocess,shutil
out=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_20261117_01')
root=Path('semantic_pallet_planner/src/semantic_pallet_planner')
revision=json.loads((out/'baseline.json').read_bytes())['sync_head']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(n,v):(out/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
prior=json.loads(Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N2_R1_20261117_01/source_manifest.json').read_bytes())['files']
files={p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(root).parts)}
changed=sorted(n for n,h in prior.items() if files[n]!=h);added=sorted(set(files)-set(prior))
assert all(files[n]==h for n,h in prior.items() if '/schemas/' in n)
for n in changed+added:
 p=out/'source_snapshot'/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/n,p)
for n in changed:
 p=out/'baseline_source'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(subprocess.check_output(['git','show',revision+':'+str(root/n)]))
save('source_manifest.json',{'version':'geometry_n3_source_v1','files':files,'changed_existing':changed,'added':added,'production_files':len(files),'baseline_revision':revision,'old_schemas_unchanged':True})
for name in ('test_geometry_execution_n3.py','test_geometry_binding_r1.py','test_geometry_public_n2.py','test_geometry_runtime_n1.py','test_space_candidates_gp2.py'):
 p=out/'test_snapshot'/name;p.parent.mkdir(exist_ok=True);shutil.copyfile(Path('semantic_pallet_planner/tests/unit')/name,p)
(out/'source_diff.patch').write_bytes(subprocess.check_output(['git','diff','--',str(root)]))
cases=[]
for p in sorted((out/'cases').iterdir()):
 r=json.loads((p/'result.json').read_bytes());c=json.loads((p/'config.json').read_bytes())
 cases.append({'case':p.name,'backend':c['candidate_backend'],'method':c['selector'],'placed':r['summary']['placed_items'],'termination':r['summary']['termination_reason'],'monitor_evidence':r['summary']['monitor_evidence'],'phases':list(dict.fromkeys(cp['phase'] for cp in json.loads((p/'phases.json').read_bytes()))),'config_digest':hashlib.sha256(json.dumps(c,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()})
save('case_summary.json',{'cases':cases,'scope':'manual one-box fixtures only; not GP4 state comparisons or real-source orders','real_PCT_LP_calls':0,'model_calls':0})
print(json.dumps({'production_files':len(files),'changed':changed,'added':added,'saved_cases':len(cases)},ensure_ascii=False))
