"""Independent stdlib fix artifact/negative/positive audit. No runtime imports."""
import hashlib,json,subprocess,xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
B=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_V13_FIX_20261112_01';HEAD='92c024097111b700b859b5081c2adcb4467803ae'
def load(p):return json.loads(p.read_text())
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(v):return sha(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def seal_ok(v):return v['record_digest']==digest({k:x for k,x in v.items() if k!='record_digest'})
def check(rows):
 for r in rows:
  raw=subprocess.check_output(['git','show',HEAD+':'+r['path']],cwd=ROOT) if r['path']=='docs/03_阶段产出分析/Jev/README.md' else (ROOT/r['path']).read_bytes()
  assert sha(raw)==r['sha256'],r['path']
  if 'bytes' in r:assert len(raw)==r['bytes'],r['path']
 return len(rows)
r={'version':'jm_v13_fix_independent_checks_v1','head':HEAD}
r['delivery_files']=check(load(B/'delivery_manifest.json')['files'])
r['inputs']=check(load(B/'input_evidence_index.json')['files'])
identity=load(B/'source_identity.json');r['changed_new_source_test_files']=check(identity['changed_or_new_files'])
snapshot=load(B/'source_manifest.json');package=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
actual={p.relative_to(package).as_posix():sha(p.read_bytes()) for p in sorted(package.rglob('*')) if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(package).parts)}
assert actual==snapshot;r['full_runtime_source_files']=len(snapshot)
mods=subprocess.check_output(['git','-c','core.quotepath=false','diff','--name-only','--diff-filter=MD',identity['entry_head'],HEAD],cwd=ROOT,text=True).splitlines()
assert set(mods)=={'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_jev_v13.py','docs/03_阶段产出分析/Jev/README.md'},mods
r['modified_preexisting_paths']=mods
idx=load(B/'regression_evidence_index.json');r['archived_junit']={}
for k,n in [('targeted',2),('v13_regression',39),('legacy_regression',131)]:
 item=idx['results'][k];tree=ET.parse(B/item['junit']).getroot();assert len(tree.findall('.//testcase'))==n
 assert not tree.findall('.//failure') and not tree.findall('.//error')
 assert set(item['cases'])=={c.attrib['name'] for c in tree.findall('.//testcase')}
 r['archived_junit'][k]={'cases':n,'failures':0,'current_run':False}
pr=idx['production_rejections'];receipt=load(ROOT/pr['path']);assert sha((ROOT/pr['path']).read_bytes())==pr['sha256']
case_root=(ROOT/pr['path']).parent;baseline=case_root/'baseline';activation=load(baseline/'activation.json')
assert activation['execution']['identity']['source']==digest(snapshot)
errors=Counter();assert len(receipt['negative_cases'])==36
for c in receipt['negative_cases']:
 p=case_root/'negative_cases'/c['case']/'mutated_journal.json';raw=p.read_bytes();assert sha(raw)==c['mutated_sha256']
 j=json.loads(raw);assert seal_ok(j) and seal_ok(j['checkpoint'])
 original=baseline/c['original_journal'];assert sha(original.read_bytes())==c['original_sha256']
 assert j['execution_digest']==digest(activation['execution'])
 assert j['checkpoint']['task_digest']==digest(activation['execution']['task'])
 assert len(c['rejections'])==2 and {v['entry'] for v in c['rejections']}=={'validate_saved_execution','run_execution'}
 codes={v['error'] for v in c['rejections']};assert len(codes)==1
 code=next(iter(codes));assert code in {'jm13_saved_arrival_delta_changed','jm13_saved_place_delta_changed','buffer_invariant'}
 errors[code]+=1
 assert not any(c['dispatches'].values()) and c['mutated_and_other_saved_bytes_unchanged_by_both_entries']
assert receipt['original_unchanged'] and not any(receipt['dispatches'].values())
filemap={p.relative_to(baseline).as_posix():sha(p.read_bytes()) for p in baseline.rglob('*') if p.is_file()}
assert digest(filemap)==receipt['original_root_byte_identity']
assert set(receipt['positive_checkpoint_phases'])=={'READY','DECISION_READY','SELECTED','MONITORED','COMMITTED','TERMINATED'}
area=load(ROOT/idx['area_load_positive']['path']);assert area['legal_recursive_area_updates']=='PASS' and area['wrong_increment']=='REFUSED'
assert area['model_calls']==area['solver_calls']==area['saved_validator_commit_or_candidate_dispatch']==0
r['negative_cases']=36;r['production_rejections_archived']=72;r['case_refusal_counts']=dict(errors)
r['archived_guards']='zero dispatch and unchanged bytes in all receipts; original root byte map agrees'
r['legal_phases']=receipt['positive_checkpoint_phases'];r['area_positive']=area
r['current_behavior_tests']='NOT_RUN: missing pytest/jsonschema/numpy/scipy and reviewer execution restrictions; archive only'
r['historical_protection_note']='compact claimed19848 files; independently checked Git preexisting changes are only target module and shared navigation, no old data/report/schema updates'
r['status']='PASS_CURRENT_STDLIB_SAVED_EVIDENCE_REVIEW'
(OUT/'static_checks.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps(r,ensure_ascii=False))
