"""JM1-A3 saved-byte evidence review, standard library only; never imports project."""
from pathlib import Path
import ast,collections,hashlib,importlib.util,json,subprocess,xml.etree.ElementTree as ET
R=Path(__file__).resolve().parents[3];O=Path(__file__).resolve().parent;B=R/'semantic_pallet_planner/outputs/JEV_JM1_A3_20261111_01'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dg(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def sealed(v):assert v['record_digest']==dg({k:x for k,x in v.items() if k!='record_digest'})
manifest=read(B/'delivery_manifest.json');source=read(B/'source_identity.json');inputs=read(B/'input_evidence_index.json')['inputs']
for row in manifest['files']:assert (R/row['path']).stat().st_size==row['bytes'] and sha(R/row['path'])==row['sha256']
for row in inputs:assert sha(R/row['path'])==row['sha256']
for p,h in source['source_manifest'].items():assert sha(R/'semantic_pallet_planner/src/semantic_pallet_planner'/p)==h
junit={}
for name,n in [('constructed',62),('legacy_constructed',58),('public_regression',50)]:
 suites=list(ET.parse(B/(name+'_junit.xml')).getroot().iter('testsuite'));junit[name]={k:sum(int(s.attrib.get(k,0)) for s in suites) for k in ['tests','errors','failures','skipped']}
 assert junit[name]['tests']==n and junit[name]['errors']==junit[name]['failures']==0
matrix=read(B/'recovery_matrix.json');observations=matrix['observations'];assert len(observations)==26
for obs in observations:
 actual=read(R/obs['evidence']);assert all(actual[k]==obs[k] for k in ['point','first','before_calls','after_calls','repeat_no_calls','terminal'])
 assert obs['repeat_no_calls'] and obs['after_calls']==([0,1,1] if obs['point']=='SENDING' else [3,4,4])
index=read(B/'constructed_evidence_index.json');roots=[];request_count=0
for name in index['valid_recovery_runs']:
 root=R/name;activation=read(root/'activation.json');sealed(activation);ex=activation['execution'];sealed(ex)
 previous=dg(activation);paths=sorted((root/'stages').glob('*.json'))
 for i,p in enumerate(paths,1):
  row=read(p);sealed(row);sealed(row['checkpoint']);assert p.name==f'{i:06d}.json' and row['sequence']==i and row['previous_digest']==previous and row['execution_digest']==dg(ex);previous=dg(row)
 assert read(root/'checkpoint_head.json')=={'sequence':len(paths),'digest':previous}
 cp=read(paths[-1])['checkpoint'];ep=read(root/'episode.json');assert ep['checkpoint']==cp and ep['events']==cp['events'] and ep['final_state']==cp['state']
 ledger=read(root/'ledger/requests.json');sealed(ledger);assert sum(x['send_started'] for x in ledger['requests'])<=ex['max_sends']
 for row in ledger['requests']:
  request_count+=1;c=read(root/'ledger/contexts'/(row['decision_id']+'.json'));res=read(root/'ledger/reservations'/(row['decision_id']+'.json'))
  assert c['request_body']['state']['memories']==[] and row['context_digest']==dg(c) and row['body_digest']==dg(c['request_body'])==res['body_digest'] and row['mapping_digest']==dg(c['display_mapping'])==res['mapping_digest']
  assert res['repeat_slot']==ex['repeat_slot'] and res['allocation_id']==ex['allocation_id']
  if row['transport'] is not None:assert row['transport_digest']==dg(row['transport'])
  if row['selection'] is not None:assert row['selection_digest']==dg(row['selection'])
 counts=read(root/'counts.json');assert counts['forced_actions']==sum(e.get('selection',{}).get('source')=='FORCED_FROM_FROZEN_POOL' for e in ep['events'] if e.get('selection'))==1
 assert counts['commits']==sum(e['event']=='PLACE' for e in cp['events']) and counts['constructed_requests']==sum(r['send_started'] for r in ledger['requests'])
 roots.append({'path':name,'stages':len(paths),'requests':len(ledger['requests']),'phase':cp['phase'],'reason':cp['reason']})
failures=[]
for p in (B/'constructed_evidence').glob('test_failure_recovery_no_res*/a3/slots/*/episode.json'):
 ep=read(p);last=next(e for e in reversed(ep['events']) if e.get('monitor'))
 assert last['monitor']['status'] in ['UNSTABLE','UNASSESSABLE','ERROR'] and last['before']==last['after'] and last['action'] is None
 failures.append({'path':str(p.relative_to(R)),'status':last['monitor']['status'],'placed_count':ep['final_state']['placed_count']})
assert len(failures)==12
isolated=[]
for p in (B/'constructed_evidence').glob('test_existing_intent_other_*/isolated/requests.json'):
 rows=read(p)['requests'];assert rows[0]['state']=='INTENT' and rows[0]['send_started'] is False and rows[1]['state'] in ['UNKNOWN_SEND','FAILED']
 isolated.append({'path':str(p.relative_to(R)),'states':[r['state'] for r in rows],'send_started':[r['send_started'] for r in rows]})
assert len(isolated)==2
repeat=read(B/'repeat_budget_evidence.json')
for row in repeat['slots']:assert read(R/row['path'])==row['counts']
assert len({r['counts']['allocation_id'] for r in repeat['slots']})==2 and sum(r['counts']['constructed_requests'] for r in repeat['slots'])==repeat['registered_total_max_sends']==3
pkg=R/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select';protected=['packaging_jev_forks.py','packaging_jev_continuation.py','packaging_remote.py','execution.py','candidates.py','stability','packaging_counterfactual.py']
diff=subprocess.check_output(['git','diff','--name-only','d48d7eef','HEAD','--']+[str((pkg/p).relative_to(R)) for p in protected],cwd=R,text=True);assert not diff
result={'version':'jm1_a3_independent_checks_v1','head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),'original_verify_delivery_current_run':'PASS_SAVED_FACTS_ONLY before QA index edit','delivery_file_hashes':len(manifest['files']),'input_hashes':len(inputs),'runtime_source_hashes':len(source['source_manifest']),'archived_junit':junit,'recovery_matrix_observations':len(observations),'matrix_points':sorted({x['point'] for x in observations}),'valid_saved_runs':roots,'saved_requests_checked':request_count,'failure_recovery_records':failures,'existing_INTENT_stop_records':isolated,'repeat_budget_summary':repeat,'protected_existing_source_diff':diff,'missing_journal_probe':read(O/'missing_journal_probe.json'),'available_python_dependencies':{n:importlib.util.find_spec(n)is not None for n in ['pytest','jsonschema','numpy','scipy']},'not_run_this_turn':['pytest','full production validate_saved_execution','run_repeat/run_episode/order/fork/commit/monitor','models/network/credentials','candidate rebuild/solver','real v3 execution'],'scope':'Raw hashes/journals/records/counts and archived tests only; exact source control-flow probe separately marked as precondition-adapted, not full runtime validation.'}
(O/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['delivery_file_hashes','input_hashes','runtime_source_hashes','archived_junit','recovery_matrix_observations','saved_requests_checked','available_python_dependencies']},ensure_ascii=False))
