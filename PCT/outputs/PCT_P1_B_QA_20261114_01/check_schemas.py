"""Read-only saved JSON Schema/metadata/algorithm-byte checks. No runtime imports."""
import hashlib,importlib.metadata as metadata,json
from collections import Counter
from pathlib import Path
from jsonschema import Draft202012Validator
Q=Path(__file__).parent;D=Path('PCT/outputs/PCT_P1_B_20261114_01')
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 schemas={}
 for p in Path('PCT/src/pct_baseline/schemas').glob('*.schema.json'):
  doc=read(p);assert '$ref' not in json.dumps(doc),'unexpected reference; inspect before validation'
  Draft202012Validator.check_schema(doc);schemas[p.name.split('.')[0]]=Draft202012Validator(doc)
 count=Counter()
 def check(name,value):schemas[name].validate(value);count[name]+=1
 for record in read(D/'case_index.json')['rows']:
  ep_path=Path(record['path']);root=ep_path.parent;ep=read(ep_path)
  for name,file in [('task_b1_v1','task.json'),('config_b1_v1','config.json'),('constructed_execution_b1_v1','execution.json')]:check(name,read(root/file))
  for p in (root/'stages').glob('*.json'):check('checkpoint_b1_v1',read(p))
  check('checkpoint_b1_v1',ep['checkpoint'])
  for e in ep['events']:
   if e.get('selection'):check('selection_result_b1_v1',e['selection'])
 frozen=read(D/'final_verification/exact_freeze.json');alg=frozen['algorithm_identity']
 base=Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select/stability')
 mismatches=[n for n,h in alg['files_sha256'].items() if sha(base/n)!=h];assert not mismatches
 env=read(D/'final_verification/environment.json')
 package_versions={n:metadata.version(n) for n in env['dependencies']}
 assert package_versions==env['dependencies']
 assert sha(env['executable'])==env['executable_sha256'] and sha(env['highs_core_file'])==env['highs_core_sha256']
 result={'status':'PASS_SAVED_SCHEMA_METADATA_ONLY','schema_validations':dict(count),'algorithm_files_checked':len(alg['files_sha256']),'algorithm_mismatches':mismatches,'package_versions':package_versions,'interpreter_and_highs_binary_hashes':'MATCH','not_imported':['planner','numpy','scipy'],'not_run':['LP','orders','candidate generation']}
 (Q/'schema_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
