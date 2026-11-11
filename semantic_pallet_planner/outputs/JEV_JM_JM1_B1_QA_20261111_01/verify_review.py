"""Independent stdlib saved-byte review; no business module imports or dispatch."""
import ast, base64, hashlib, json, re, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
B=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B1_20261111_01'
def load(p):return json.loads(p.read_text())
def sha(v):return hashlib.sha256(v).hexdigest()
def check(rows):
 for r in rows:
  ref=r.get('git_ref')
  if r['path']=='docs/03_阶段产出分析/Jev/README.md':ref=ref or '11790ca4e7af9d2affe0a2980dc1158a774d9900'
  raw=subprocess.check_output(['git','show',ref+':'+r['path']],cwd=ROOT) if ref else (ROOT/r['path']).read_bytes()
  assert sha(raw)==r['sha256'],r['path']
 return len(rows)
result={'version':'jm1_b1_independent_static_checks_v1','head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
result['delivery_files']=check(load(B/'delivery_manifest.json')['files'])
result['input_files']=check(load(B/'input_evidence_index.json')['files'])
result['source_files']=check(load(B/'source_identity.json')['source_files'])
result['material_files']=check(load(B/'material_candidates.json')['files'])
entry=load(B/'source_identity.json')['entry_head']
registry='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_versions.py'
old=subprocess.check_output(['git','show',entry+':'+registry],cwd=ROOT)
new=(ROOT/registry).read_bytes()
assert new.startswith(old) and b'JM_SAMPLING_PROTOCOLS' in new[len(old):]
result['registry_append_against_recorded_entry']='PASS'
changed=subprocess.check_output(['git','diff','--name-only',entry,'HEAD','--','semantic_pallet_planner/src','semantic_pallet_planner/tests'],cwd=ROOT,text=True).splitlines()
assert set(changed)=={r['path'] for r in load(B/'source_identity.json')['source_files']}
result['source_test_change_scope']=changed
module=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_jev_sampling.py'
tree=ast.parse(module.read_text())
imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.level]
assert imports==['packaging_versions']
result['relative_imports']=imports
pairs=[(load(B/'constructed_public.json'),load(B/'constructed_diagnostic.json'))]
pairs.extend((p,load(B/'cap_coverage.json')) for p in load(B/'cap_batch.json')['decisions'])
dup=load(B/'duplicate_actions.json');pairs.append((dup['input'],dup['result']))
actions=0
for p,d in pairs:
 e=p['probability_evidence'];assert sha(base64.b64decode(e['raw_base64'],validate=True))==e['raw_sha256']
 for field,expected in [('pool_ref',[c['frozen_candidate'] for c in p['pool']]),('prefix_ref',p['public_state'])]:
  r=p[field];raw=(ROOT/r['path']).read_bytes();assert sha(raw)==r['sha256'] and r['pointer']==''
  assert json.loads(raw)==expected
 for point in d['selected_points']:
  if (point['task_id'],point['decision_id'])!=(p['task_id'],p['decision_id']):continue
  for branch in point['branches']:
   c=next(c for c in p['pool'] if c['candidate_id']==branch['candidate_id'])
   assert c['candidate_digest']==branch['candidate_digest']
   assert any(m['label']==branch['label'] and m['candidate_id']==c['candidate_id'] for m in p['display_mapping'])
   actions+=1
result['archived_action_references']=actions
neg=load(B/'negative_cases.json')
assert len(neg)==13
for n in neg:
 d=n['diagnostic'];assert not d['selected_points'] and d['counts']['all_supplied_decisions']==1
 assert d['rows'][0]['status']=='REJECTED' and d['rows'][0]['reason']
cap=load(B/'cap_coverage.json');assert len(cap['rows'])==24 and len(cap['selected_points'])==12
assert sum(r['reason']=='STAGE_PRIORITY_NOT_SELECTED' for r in cap['rows'])==12
result['archived_negative_records']=len(neg)
result['archived_cap']={'decisions':24,'selected':12,'priority_unselected':12}
for path in [ROOT/load(B/'handoff.json')['report'], B/'input_adapter_notes.md']:
 for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
  if '://' not in target and not target.startswith('#'):assert (path.parent/target.split('#')[0]).exists(),target
result['status']='PASS_INDEPENDENT_SAVED_BYTES_AND_STATIC_CHECKS'
result['original_verifier']='FAIL_AT_LINE_39_HEAD_RELATIVE_CHECK_AFTER_COMMIT'
result['local_behavior_tests']='10/10 PASS; see local_tests.log; constructed only'
result['business_dispatches']=0
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
