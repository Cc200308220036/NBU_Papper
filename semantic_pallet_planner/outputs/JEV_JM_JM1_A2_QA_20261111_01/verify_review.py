"""JM1-A2 independent saved-fact review: stdlib, no business imports or dispatch."""
from pathlib import Path
import ast,collections,hashlib,importlib.util,json,subprocess,xml.etree.ElementTree as ET
R=Path(__file__).resolve().parents[3];O=Path(__file__).resolve().parent;B=R/'semantic_pallet_planner/outputs/JEV_JM1_A2_20261111_01'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dg(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def quantity(s):return (len(s['placed_items']),sum(__import__('math').prod(x['oriented_size_mm']) for x in s['placed_items']),sum(x['mass_kg'] for x in s['placed_items']))
manifest=read(B/'delivery_manifest.json');source=read(B/'source_identity.json');inputs=read(B/'input_evidence_index.json')
for p,h in manifest['files_sha256'].items():assert sha(R/p)==h,p
for p,h in inputs['files_sha256'].items():assert sha(R/p)==h,p
for p,h in source['runtime_package_source_sha256'].items():assert sha(R/p)==h,p
for p,h in source['changed_source_test_fixture_sha256'].items():assert sha(R/p)==h,p
junit={}
for name,expected in [('constructed_junit.xml',58),('public_regression_junit.xml',50)]:
 suites=list(ET.parse(B/name).getroot().iter('testsuite'))
 junit[name]={k:sum(int(s.attrib.get(k,0)) for s in suites) for k in ['tests','failures','errors','skipped']}
 assert junit[name]['tests']==expected and junit[name]['failures']==junit[name]['errors']==0
roots=[];request_count=0;histories=collections.Counter();statuses=collections.Counter();policies={}
for root in sorted((B/'constructed_evidence').glob('*/a2')):
 if root.parent.name.startswith('test_identity_tamper') or not(root/'episode.json').is_file():continue
 ep=read(root/'episode.json');counts=read(root/'counts.json');ex=read(root/'activation.json');ledger=read(root/'ledger/requests.json')
 assert read(root/'ledger/execution.json')==ex and ex['binding_digest']==dg(ex['binding']) and ex['policy_digest']==dg(ex['policy'])
 assert ex['scope']=='CONSTRUCTED_ONLY' and ex['policy']['memories']==[] and ex['policy']['retrieval']=='FORBIDDEN' and ex['policy']['retries']==0
 assert dg({k:v for k,v in ledger.items() if k!='record_digest'})==ledger['record_digest']
 events=[e for e in ep['events'] if e.get('selection')]
 assert sum(e['selection']['source']=='FORCED_FROM_FROZEN_POOL' for e in events)==counts['forced_actions']==1
 assert counts['constructed_requests']==sum(r['send_started'] for r in ledger['requests'])
 assert counts['singleton_actions']==sum(e['selection']['source']=='singleton' for e in events)
 assert counts['commits']==sum(e['event']=='PLACE' for e in ep['events']) and counts['real_model_calls']==0
 for row in ledger['requests']:
  request_count+=1;statuses[row['state']]+=1
  for h in row['history']:histories[h['state']]+=1
  ctx=read(root/'ledger/contexts'/f"{row['decision_id']}.json");res=read(root/'ledger/reservations'/f"{row['decision_id']}.json")
  assert row['context_digest']==dg(ctx) and row['body_digest']==dg(ctx['request_body']) and row['mapping_digest']==dg(ctx['display_mapping'])
  assert ctx['request_body']['state']==ctx['model_state'] and ctx['request_body']['state']['memories']==[]
  assert res['execution_digest']==dg(ex) and res['policy_digest']==ex['policy_digest']
  assert all(res[k]==row[k] for k in ['job_id','decision_id','body_digest','mapping_digest','context_digest'])
  assert row['origin']=='test_double'
  if row['transport'] is not None:assert row['transport_digest']==dg(row['transport'])
  if row['selection'] is not None:assert row['selection_digest']==dg(row['selection'])
 selected={};monitored={};stagecount=0
 for path in sorted((root/'stages').glob('*.json')):
  stagecount+=1;cp=read(path);assert cp['record_digest']==dg({k:v for k,v in cp.items() if k!='record_digest'})
  event=cp['pending_event']
  if event is None:continue
  did=event['decision_id']
  if cp['phase']=='SELECTED':assert event['monitor'] is None;selected[did]=event['selection']
  if cp['phase']=='MONITORED':assert selected[did]==event['selection'];monitored[did]=event['monitor']
  if cp['phase']=='COMMITTED':assert monitored[did]['status']=='STABLE'
 failed=[]
 for e in events:
  if e.get('monitor') and e['monitor']['status']!='STABLE':
   assert e['before']==e['after'] and e['action'] is None and quantity(e['before'])==quantity(e['after'])
   failed.append(e['monitor']['status'])
 if ep['checkpoint']['reason']=='UNKNOWN_IN_FLIGHT':assert any(r['state']=='UNKNOWN_SEND' for r in ledger['requests'])
 if root.parent.name.startswith('test_reference_and_alternative'):policies[root.parent.name]=ex['policy_digest']
 roots.append({'path':str(root.relative_to(R)),'reason':ep['checkpoint']['reason'],'requests':len(ledger['requests']),'request_states':[r['state'] for r in ledger['requests']],'counts':counts,'monitor_failure_statuses':failed,'saved_stages':stagecount})
assert len(roots)==20 and len(policies)==3 and len(set(policies.values()))==1
# Inspect, do not execute, production request/recovery methods.
pkg=R/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select'
tree=ast.parse((pkg/'packaging_jev_continuation.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ContinuationLedger')
methods={n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
inspect={'admit_request_line':methods['admit_request'].lineno,'admit_send_line':methods['admit_send'].lineno,'admit_send_reads_self_data':any(isinstance(n,ast.Attribute) and n.attr=='data' and isinstance(n.value,ast.Name) and n.value.id=='self' for n in ast.walk(methods['admit_send'])),'interpretation':'Existing INTENT can bypass new-request admit_request; admit_send has identity/origin checks but no ledger stopped-state guard. Recovery counterexample not executed in this review; A3 must gate and test before reopening INTENT recovery.'}
protected=['packaging_jev_forks.py','packaging_remote.py','execution.py','packaging_counterfactual.py','candidates.py','stability','configs/generator_v1.json']
diff=subprocess.check_output(['git','diff','--name-only','a11c2cf8','HEAD','--']+[str((pkg/p).relative_to(R)) for p in protected],cwd=R,text=True);assert not diff
result={'version':'jm1_a2_independent_saved_review_v1','head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),'delivery_script_this_turn':'PASS (stdlib read-only; before adding QA index row)','delivery_hashes_checked':len(manifest['files_sha256']),'input_hashes_checked':len(inputs['files_sha256']),'runtime_source_hashes_checked':len(source['runtime_package_source_sha256']),'changed_source_test_fixture_hashes_checked':len(source['changed_source_test_fixture_sha256']),'archived_junit':junit,'valid_saved_execution_roots':roots,'saved_request_rows_checked':request_count,'request_final_state_counts':dict(statuses),'request_history_state_counts':dict(histories),'three_intervention_shared_policy':policies,'intent_recovery_boundary_static_inspection':inspect,'protected_legacy_source_diff':diff,'available_python_dependencies':{n:importlib.util.find_spec(n)is not None for n in ['pytest','jsonschema','numpy','scipy']},'not_run':['pytest behavior tests','existing-INTENT recovery counterexample execution','business imports or execution','models/network/credentials','orders/forks/candidate reconstruction/solver','real v3 continuation'],'scope':'Saved positive execution roots checked; intentional identity-corruption negative fixture directories excluded from positive-run claims and retained as archive test evidence.'}
(O/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['delivery_hashes_checked','input_hashes_checked','runtime_source_hashes_checked','changed_source_test_fixture_hashes_checked','saved_request_rows_checked','request_final_state_counts','archived_junit','available_python_dependencies']},ensure_ascii=False))
