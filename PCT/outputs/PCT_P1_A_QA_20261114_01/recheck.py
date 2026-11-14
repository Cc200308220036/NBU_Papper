"""QA orchestration: saved hashes, reviewed construction tests and read-only data validation.
No pip installation, order/candidate-generation/LP/transport dispatch. Output QA only.
"""
import hashlib,json,os,subprocess
from pathlib import Path
Q=Path(__file__).parent
D=Path('PCT/outputs/PCT_P1_A_NBU_20261114_02')
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(n,x):(Q/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def main():
 identity=read(D/'identity.json');python=identity['environment']['executable']
 hashes={p:sha(p)==h for p,h in identity['source_configuration_schema_sha256'].items()}
 manifest=read(D/'delivery_manifest.json')
 delivery={r['path']:sha(r['path'])==r['sha256'] for r in manifest['files']}
 old=[]
 for folder in ('schemas','configs'):
  prefix='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/'+folder
  paths=subprocess.check_output(['git','ls-tree','-r','--name-only','2e4edb32',prefix],text=True).splitlines()
  for p in paths:old.append({'path':p,'same':Path(p).read_bytes()==subprocess.check_output(['git','show','2e4edb32:'+p])})
 save('saved_facts.json',dict(source_hashes=hashes,delivery_hashes=delivery,legacy_resources=old,interpreter_hash_matches=sha(python)==identity['environment']['executable_sha256'],head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()))
 assert all(hashes.values()) and all(delivery.values()) and all(r['same'] for r in old)
 env=dict(os.environ,PYTHONPATH='PCT/src:semantic_pallet_planner/src',PYTHONDONTWRITEBYTECODE='1')
 # Exact reviewed guard source retained in original receipt; constructors use temporary directories.
 guard=read(D/'dispatch_guard_source.json')['python_source']
 (Q/'reviewed_guard.py').write_text(guard)
 commands=[('tests.json',[python,str(Q/'reviewed_guard.py')],'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=PCT/src:semantic_pallet_planner/src "$NBU_PY" PCT/outputs/PCT_P1_A_QA_20261114_01/reviewed_guard.py'),('data.json',[python,'-m','pct_baseline.cli','validate-data','--dataset',str(D/'data'),'--full-schema'],'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=PCT/src:semantic_pallet_planner/src "$NBU_PY" -m pct_baseline.cli validate-data --dataset PCT/outputs/PCT_P1_A_NBU_20261114_02/data --full-schema')]
 records=[]
 for name,argv,display in commands:
  r=subprocess.run(argv,env=env,text=True,capture_output=True)
  row=dict(command=display,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr)
  save(name,row);records.append(row)
 save('commands_and_results.json',dict(commands=records,script_review='Developer aggregate not executed: writes new data, environment receipt hardcodes historical install success; only audited guard and read-only validator executed',boundary='No business dispatch; temporary test data only; no installs or credentials'))
 assert all(r['exit_code']==0 for r in records)
 print('PASS: source/delivery hashes, legacy bytes, guarded 20 tests, full data schema')
if __name__=='__main__':main()
