"""Independent JM1-A3 fix saved-evidence review; stdlib only, no project imports."""
from pathlib import Path
import ast,collections,hashlib,importlib.util,json,subprocess,xml.etree.ElementTree as ET
R=Path(__file__).resolve().parents[3];O=Path(__file__).resolve().parent;B=R/'semantic_pallet_planner/outputs/JEV_JM1_A3_FIX_20261111_01'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dg(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
manifest=read(B/'delivery_manifest.json');source=read(B/'source_identity.json');inputs=read(B/'input_evidence_index.json')['files']
for row in manifest['files']:assert sha(R/row['path'])==row['sha256'] and (R/row['path']).stat().st_size==row['bytes'],row['path']
for row in inputs:assert sha(R/row['path'])==row['sha256'],row['path']
for p,h in source['source_manifest'].items():assert sha(R/'semantic_pallet_planner/src/semantic_pallet_planner'/p)==h,p
junit={}
for n,num in [('targeted',11),('regression',62),('legacy',58)]:
 suites=list(ET.parse(B/(n+'_junit.xml')).getroot().iter('testsuite'));junit[n]={k:sum(int(s.attrib.get(k,0)) for s in suites) for k in ['tests','errors','failures','skipped']}
 assert junit[n]['tests']==num and junit[n]['errors']==junit[n]['failures']==junit[n]['skipped']==0
cases=[];rejections=0
for case in read(B/'production_negative_evidence.json')['cases']:
 receipt=read(R/case['receipt']);assert receipt['production_validator'] and not receipt['identities_or_schemas_substituted']
 assert receipt['remaining_files_before']==receipt['remaining_files_after']
 assert [e['entry'] for e in receipt['rejections']]==['validate_saved_execution','run_repeat']
 for row in receipt['rejections']:
  assert row['remaining_files_unchanged'] and all(v==0 for v in row['dispatch_counts'].values());rejections+=1
 root=R/case.get('copy_root',case['source_root'])
 ledger=read(root/'ledger/requests.json');actual_states=[r['state'] for r in ledger['requests']];assert actual_states==case['request_states']
 if case['kind']=='joint_loss':
  assert not(root/'stages').exists() and not(root/'checkpoint_head.json').exists() and not(root/'episode.json').exists()
  original=R/case['source_root'];assert not(original/'episode.json').exists()
  assert all(sha(p)==sha(original/p.relative_to(root)) for p in root.rglob('*') if p.is_file())
 for relative,h in receipt['remaining_files_after'].items():
  # Receipt snapshot root is the copied/original schedule root, two levels up.
  schedule_root=root.parents[1]
  assert sha(schedule_root/relative)==h,relative
 cases.append({'kind':case['kind'],'receipt':case['receipt'],'states':actual_states,'errors':[e['error_code'] for e in receipt['rejections']],'zero_dispatch':True,'remaining_bytes_unchanged':True})
assert len(cases)==8 and rejections==16
legal=[]
for p in (B/'targeted_evidence').glob('test_current_decision_ready_*/legal_response_receipt.json'):
 d=read(p);assert d['saved_phase']=='DECISION_READY' and d['completed'] and d['saved_validation_readonly'] and d['final_sends']==3;legal.append(d)
assert len(legal)==2
reg=read(B/'regression_evidence_index.json')['recovery_observations'];assert len(reg)==26
requests_checked=0
for item in reg:
 root=(R/item['path']).parent
 activation=read(root/'activation.json');ex=activation['execution'];previous=dg(activation);paths=sorted((root/'stages').glob('*.json'))
 for i,path in enumerate(paths,1):
  v=read(path);assert v['record_digest']==dg({k:x for k,x in v.items() if k!='record_digest'})
  assert v['sequence']==i and v['previous_digest']==previous and v['execution_digest']==dg(ex);previous=dg(v)
 assert read(root/'checkpoint_head.json')=={'sequence':len(paths),'digest':previous}
 cp=read(paths[-1])['checkpoint'];episode=read(root/'episode.json');assert episode['checkpoint']==cp and episode['events']==cp['events'] and episode['final_state']==cp['state']
 ledger=read(root/'ledger/requests.json');assert ledger['record_digest']==dg({k:x for k,x in ledger.items() if k!='record_digest'})
 for row in ledger['requests']:
  requests_checked+=1;c=read(root/'ledger/contexts'/(row['decision_id']+'.json'));res=read(root/'ledger/reservations'/(row['decision_id']+'.json'))
  assert row['context_digest']==dg(c) and row['body_digest']==dg(c['request_body'])==res['body_digest'] and row['mapping_digest']==dg(c['display_mapping'])==res['mapping_digest']
  assert c['request_body']['state']['memories']==[] and res['allocation_id']==ex['allocation_id'] and res['repeat_slot']==ex['repeat_slot']
 counts=read(root/'counts.json');assert counts['forced_actions']==1 and counts['commits']==sum(e['event']=='PLACE' for e in cp['events']) and counts['constructed_requests']==sum(r['send_started'] for r in ledger['requests'])
for item in reg:
 if isinstance(item,str):r=read(R/item)
 elif 'path' in item:
  r=read(R/item['path']);assert r==item['observation']
 elif 'evidence' in item:r=read(R/item['evidence'])
 else:r=item
 assert r['repeat_no_calls'] and r['after_calls']==([0,1,1] if r['point']=='SENDING' else [3,4,4])
module=R/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_jev_recovery.py';tree=ast.parse(module.read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='validate_saved_execution')
code=ast.get_source_segment(module.read_text(),fn)
assert 'set(contexts) <= set(choice_events)' in code and "choice_events.get(row['decision_id'])" in code and "'jm_A3_request_ahead_of_checkpoint'" in code and "'jev_jm_saved_recovery_check_v2'" in code
paths=subprocess.check_output(['git','diff','--name-only','43caa1e43','HEAD','--','semantic_pallet_planner/src','semantic_pallet_planner/tests'],cwd=R,text=True).splitlines()
assert set(paths)=={'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_jev_recovery.py','semantic_pallet_planner/tests/unit/test_packaging_jev_recovery_progress.py'}
result={'version':'jm1_a3_fix_independent_review_checks_v1','head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),'original_verify_delivery_current_run':'PASS_SAVED_FACTS_ONLY before adding new QA index','delivery_hashes':len(manifest['files']),'input_hashes':len(inputs),'runtime_source_hashes':len(source['source_manifest']),'changed_source_test_files':paths,'archived_junit':junit,'negative_cases':cases,'zero_dispatch_rejections':rejections,'legal_current_DECISION_READY_receipts':legal,'normal_recovery_observations':len(reg),'regression_saved_requests_checked':requests_checked,'saved_validation_version':'jev_jm_saved_recovery_check_v2','old_QA_issue_closure':'QA-JM1A3-01 closed in constructed scope by source fix plus same-source archived production-validator tests; full local behavior rerun NOT_RUN','available_python_dependencies':{n:importlib.util.find_spec(n)is not None for n in ['pytest','jsonschema','numpy','scipy']},'not_run_this_turn':['pytest and full production-validator rerun','run_repeat/run_episode/selector/transport/monitor/commit','network/credentials/models','orders/forks/candidate generation/solver','formal baseline task freeze or real v3 runtime'],'scope':'Saved hashes, raw negative receipts and unchanged copy bytes, legal receipts/JUnit, source diff/AST and recovery observations only; production negative tests are archive evidence, no substituted validation in those tests.'}
(O/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['delivery_hashes','input_hashes','runtime_source_hashes','archived_junit','zero_dispatch_rejections','normal_recovery_observations','available_python_dependencies']},ensure_ascii=False))
