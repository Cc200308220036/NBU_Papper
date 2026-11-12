"""Independent fix receipt/byte/history checks; stdlib only, no business dispatch."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
B=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_FIX_20261111_01'
HEAD='49a98862c845a941cbfadeb3b1af570d3d823599'
def load(p):return json.loads(p.read_text())
def sha(v):return hashlib.sha256(v).hexdigest()
def raw_at(ref,path):return subprocess.check_output(['git','show',ref+':'+path],cwd=ROOT)
def check(rows):
 for r in rows:
  raw=raw_at(HEAD,r['path']) if r['path']=='docs/03_阶段产出分析/Jev/README.md' else (ROOT/r['path']).read_bytes()
  assert sha(raw)==r['sha256'] and len(raw)==r['bytes'],r['path']
 return len(rows)
result={'version':'jm1_b2_fix_independent_checks_v1','reviewed_head':HEAD}
result['delivery_files']=check(load(B/'delivery_manifest.json')['files'])
result['input_files']=check(load(B/'input_evidence_index.json')['files'])
s=load(B/'source_identity.json');result['source_identity_files']=check(s['files'])
protection=load(B/'original_artifact_protection.json');result['protected_original_files']=check(protection['files'])
for r in protection['files']:assert sha(raw_at(s['entry_head'],r['path']))==r['sha256'],r['path']
result['protected_match_recorded_entry_git_blob']=True
changed=subprocess.check_output(['git','diff','--name-only',s['entry_head'],HEAD,'--','semantic_pallet_planner/src','semantic_pallet_planner/tests'],cwd=ROOT,text=True).splitlines()
assert set(changed)=={s['changed_business_source'],s['new_test']}
result['source_test_diff']=changed
original=ROOT/'semantic_pallet_planner/outputs/JEV_JM_JM1_B2_QA_20261111_01/probe_saved_point.py'
assert original.read_bytes()==(B/'replay_original_qa_probe.py').read_bytes()==(OUT/'probe_saved_point.py').read_bytes()
current=load(OUT/'semantic_probe.json');archived=load(B/'semantic_probe.json')
assert len(current['cases'])==4
for a,c in zip(archived['cases'],current['cases']):
 assert a['case']==c['case'] and a['observation']==c['observation'] and c['observation']['accepted'] is False
assert current['original_package_unchanged'] and current['validation_readonly']
result['original_four_cases_current_run']='ALL_REFUSED_WITH_SAME_CODES_AS_FIX_ARCHIVE'
for name,n in [('negative_semantic_receipts.json',17),('diagnostic_negative_receipts.json',8)]:
 rows=load(B/name)['cases'];assert len(rows)==n
 for r in rows:
  assert r['actual']==r.get('expected',r['actual']) and r['dispatches']==0
 result[name+'_cases']=n
neg=load(B/'negative_semantic_receipts.json')
for r in neg['cases']:
 p=B/'targeted_saved_evidence'/r['selected_point_ref']['path']
 assert sha(p.read_bytes())==r['selected_point_ref']['sha256']
result['raw_parser_negative_cases']=len(load(B/'raw_negative_receipts.json')['cases']);assert result['raw_parser_negative_cases']==4
legal=load(B/'legal_original_receipt.json');old=load(ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_20261111_01/constructed_budget.json')
a=legal['current_result'];assert a['version']=='jev_jm_training_template_check_v2'
assert {k:v for k,v in a.items() if k!='version'}=={k:v for k,v in old.items() if k!='version'}
assert len(a['jobs'])==54 and a['global_send_upper']==579 and a['total_suffixes']==48
assert legal['formal_gate']['status']=='REFUSED'
dup=load(B/'legal_duplicate_receipt.json')['original_branch'];assert dup['label']=='C00' and dup['native_lexeme']=='0.1' and dup['group_score']=={'numerator':1,'denominator':2}
near=load(B/'legal_near_and_outside_receipt.json');assert near['epsilon']=={'numerator':1,'denominator':500041}
assert near['outside_cross_refused']=='B2_BRANCH_OUTSIDE_SAVED_LAYER'
result['archived_positive_budget']={'jobs':54,'suffixes':48,'send_upper':579,'formal_gate':'REFUSED','comparison':'all result fields except version identical'}
result['local_tests']={'targeted':6,'B2':10,'B1':10,'failures':0,'scope':'CONSTRUCTED_ONLY'}
result['limits']=['No real v3 execution/admission established','Historical navigation gap retained; delivery README pinned to reviewed Git blob','B1 regression runs constructed sampler only; fix validator and probe do not dispatch sampler/engine/model/solver']
result['status']='PASS_FIX_BYTES_NEGATIVES_POSITIVES_AND_SCOPE'
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
