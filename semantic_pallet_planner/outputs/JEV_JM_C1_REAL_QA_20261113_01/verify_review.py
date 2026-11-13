"""Saved facts and stdlib public sampler only. No credentials, dispatch, candidates or LP.
Linux paths are mapped solely to locate archived bytes; no runtime identity is substituted.
"""
import base64,hashlib,json,math,subprocess,sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'semantic_pallet_planner/src'))
from semantic_pallet_planner.jev_select import packaging_jev_sampling as s,packaging_jev_training_template as t
B=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_C1_REAL_BASELINES_20261112_01'
F=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01'
def path(p,base=ROOT):
 p=str(p);prefix='/home/cyw/NBU_Papper/'
 return ROOT/p[len(prefix):] if p.startswith(prefix) else (Path(p) if Path(p).is_absolute() else base/p)
def load(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def seal(v):assert v['record_digest']==s.digest({k:x for k,x in v.items() if k!='record_digest'})
def ref(v,base=ROOT):
 p=path(v['path'],base);assert sha(p)==v['sha256'],str(p)
 return p
m=load(B/'delivery_manifest.json')
for r in m['files']:
 p=path(r['path']);assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],str(p)
source=load(F/'source_manifest.json');pkg=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
actual={p.relative_to(pkg).as_posix():sha(p) for p in pkg.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(pkg).parts)}
assert actual==source and len(actual)==505
f=load(F/'formal_freeze.json');plan=load(F/'materials/training_plan.json');baseline=load(B/'baseline_receipt.json')
assert s.digest({k:v for k,v in f.items() if k!='receipt_digest'})==f['receipt_digest']
assert s.digest({k:v for k,v in plan.items() if k!='plan_digest'})==plan['plan_digest']==f['preparation_digest']
auth=load(B/'authorization_receipt.json');assert auth['baseline_send_upper']==103 and auth['suffix_authorized']==0
assert auth['authority']=='USER_EXPLICIT_CURRENT_TURN'
public=[];event_lookup={};checkpoints={};requests=commits=stages=kernel_calls=input_tokens=output_tokens=0;job_summary=[]
for i,(j,b) in enumerate(zip(f['jobs'],baseline['jobs']),1):
 ex=load(ref(j['execution_ref']));seal(ex);root=path(j['storage_root']);activation=load(root/'activation.json');seal(activation)
 assert activation['execution']==ex==load(root/'ledger/execution.json')
 permit=load(ref(activation['send_permit_ref']))
 assert permit==dict(version='jev_jm_v13_send_permit_v1',execution_digest=s.digest(ex),allocation_id=ex['allocation_id'],max_sends=ex['max_sends'],authorized=True)
 cp=activation['initial_checkpoint'];seal(cp);prev=s.digest(activation)
 journal=sorted((root/'stages').glob('*.json'));phases=[]
 allowed={'READY':{'READY','DECISION_READY','TERMINATED'},'DECISION_READY':{'DECISION_READY','SELECTED','TERMINATED'},'SELECTED':{'MONITORED','TERMINATED'},'MONITORED':{'COMMITTED','TERMINATED'},'COMMITTED':{'READY','TERMINATED'},'TERMINATED':{'TERMINATED'}}
 for no,p in enumerate(journal,1):
  row=load(p);seal(row);nxt=row['checkpoint'];seal(nxt)
  assert row['sequence']==no and p.name==f'{no:06d}.json' and row['previous_digest']==prev and row['execution_digest']==s.digest(ex)
  assert nxt['phase'] in allowed[cp['phase']] and nxt['events'][:len(cp['events'])]==cp['events']
  phases.append(nxt['phase']);cp=nxt;prev=s.digest(row)
 assert load(root/'checkpoint_head.json')==dict(sequence=len(journal),digest=prev)
 ep=load(root/'episode.json');assert ep['checkpoint']==cp and ep['events']==cp['events'] and ep['final_state']==cp['state']
 assert cp['phase']=='TERMINATED' and cp['pending_event'] is None and cp['reason']=='STOP_NO_PHYSICAL_CANDIDATE'
 assert cp['runtime_identity']==ex['config']['runtime_identity'] and cp['task_digest']==s.digest(ex['task']) and cp['config_digest']==s.digest(ex['config'])
 rows=load(root/'ledger/requests.json')['requests'];rowmap={r['decision_id']:r for r in rows};assert len(rows)==len(rowmap)
 count=0;state=activation['initial_checkpoint']['state'];placed=[]
 for e in cp['events']:
  assert e['before']==state
  if e.get('context'):
   did=e['decision_id'];ctx=e['context'];event_lookup[did]=e;checkpoints[did]=(ex,root,journal[-1])
   assert ctx['request_body'] is None or ctx['request_body']['state']['memories']==[]
   assert ctx['model_state']['memories']==[]
   if e['event']=='PLACE':
    sel=e['selection'];r=rowmap[did];candidate=next(c for c in e['bundle']['selectable_candidates'] if c['candidate_id']==sel['selected_candidate_id'])
    assert sel==r['selection'] and sel['source']=='jev' and sel['status']=='selected'
    assert load(root/'ledger/contexts'/(did+'.json'))==ctx
    reservation=load(root/'ledger/reservations'/(did+'.json'))
    assert reservation['allocation_id']==ex['allocation_id'] and reservation['execution_digest']==s.digest(ex)
    assert r['state']=='SELECTION_SAVED' and r['send_started'] and r['origin']=='jev'
    assert [h['state'] for h in r['history']]==['INTENT','SENDING','RESPONSE_SAVED','SELECTION_SAVED']
    tr=r['transport'];raw=base64.b64decode(tr['raw_body_b64'],validate=True)
    assert hashlib.sha256(raw).hexdigest()==tr['raw_sha256']==sel['raw_response_digest']
    assert s.digest(tr)==r['transport_digest'] and s.digest(sel)==r['selection_digest']
    assert tr['network_attempted'] and tr['http_status']==200 and sel['requested_model']==sel['served_model']=='jev-1.14.0'
    parsed=json.loads(raw);assert parsed['usage']==sel['usage']
    mon=e['monitor'];assert mon['status']==mon['result']['status']=='STABLE' and mon['attempted']
    assert mon['result_digest']==s.digest(mon['result']) and mon['credential_digest']==s.digest({k:v for k,v in mon.items() if k!='credential_digest'})
    bind=mon['binding'];assert bind['action_digest']==s.digest(e['proposed_action']) and bind['bundle_digest']==s.digest(e['bundle']) and bind['runtime_identity']==ex['config']['runtime_identity']
    assert bind['state_digest']==s.digest(e['before']) and bind['candidate_digest']==s.digest(candidate) and bind['selection_digest']==s.digest(sel) and bind['context_digest']==s.digest(ctx)
    assert mon['result']['algorithm_identity']==ex['config']['stability_monitor']['algorithm_identity']
    assert e['action']==e['proposed_action'] and e['after']['placed_count']==e['before']['placed_count']+1
    assert phases.count('SELECTED')==phases.count('MONITORED')==phases.count('COMMITTED')==len(rows)
    placed_id=candidate['pick_item_id'];assert placed_id not in placed;placed.append(placed_id)
    new=next(x for x in e['after']['placed_items'] if x['item_id']==placed_id)
    assert new['pose']==candidate['pose'] and new['oriented_size_mm']==candidate['oriented_size_mm']
    assert placed_id not in [x['item']['item_id'] for x in e['after']['pending_items']]
    count+=1;kernel_calls+=mon['result']['kernel_calls'];input_tokens+=sel['usage']['input_tokens'];output_tokens+=sel['usage']['output_tokens']
   else:
    assert e['event']=='STOP' and e['after']==e['before'] and e['action'] is None and not e['bundle']['selectable_candidates'] and e['monitor'] is None
  state=e['after']
 assert state==cp['state'] and count==len(rows)==b['requests']==b['placed_items']<=j['max_sends']
 assert count==load(root/'counts.json')['commits']==load(root/'counts.json')['requests']
 assert len(placed)==len(set(placed))==cp['state']['placed_count'] and not b['completed']
 assert set(placed)=={x['item_id'] for x in cp['state']['placed_items']}
 job_receipt=load(B/f'job_{i}_receipt.json');assert job_receipt['technical_valid'] and job_receipt['counts']==load(root/'counts.json')
 export=B/'public'/f'baseline_{i}';idx=load(export/'index.json');exported=0
 for ent in idx['decisions']:
  if ent['status']=='PUBLIC_SAVED':
   p=load(ref(ent['public_ref'],export));s.validate_saved_evidence(p,root=export);public.append(p);exported+=1
   e=event_lookup[p['decision_id']];pool=e['bundle']['selectable_candidates']
   assert [c['frozen_candidate'] for c in p['pool']]==pool and len(p['public_state']['placed_objects'])==e['before']['placed_count']
   assert [x['item_id'] for x in p['public_state']['buffer']]==[x['item']['item_id'] for x in e['before']['pending_items']]
   assert p['original']['label']==e['selection']['selected_display_id'] and p['original']['candidate_id']==e['selection']['selected_candidate_id']
   assert p['probability_evidence']['raw_base64']==rowmap[p['decision_id']]['transport']['raw_body_b64']
 assert exported==count and len(idx['decisions'])==count+1
 assert idx['decisions'][-1]['status']=='NO_SAVED_VALID_SELECTION' and idx['decisions'][-1]['candidate_count']==0
 requests+=len(rows);commits+=count;stages+=len(journal)
 job_summary.append(dict(ordinal=i,requests=count,placed=count,planned=len(ex['task']['items']),stages=len(journal),reason=cp['reason']))
assert requests==commits==baseline['actual_requests']==44 and [j['requests'] for j in job_summary]==[6,9,7,5,11,6]
# Independent exact-rational epsilon from native JSON tokens, grouping identical actions.
positive=[]
for record in public:
 raw=json.loads(base64.b64decode(record['probability_evidence']['raw_base64']),parse_float=Fraction,parse_int=Fraction)
 probs=raw['answers']['next_action']['probabilities'];scores={}
 for member in record['display_mapping']:
  candidate=next(c for c in record['pool'] if c['candidate_id']==member['candidate_id'])
  action=s.exact_digest(candidate);scores[action]=max(scores.get(action,Fraction(0)),probs[member['label']])
 top=max(scores.values());gaps=[(top-x)/top for x in scores.values() if x<top]
 if gaps:positive.append(min(gaps))
positive.sort();independent_epsilon=min(positive[(len(positive)+3)//4-1],Fraction(1,10))
assert len(positive)==44 and independent_epsilon==Fraction(1,10)
diag=s.sample(public,task_order=[j['task_id'] for j in f['jobs']]);assert diag==load(B/'sampling_diagnostic.json')
eps=load(B/'epsilon_receipt.json');assert eps['epsilon']==diag['diagnostic_epsilon']==dict(numerator=1,denominator=10) and eps['positive_gap_denominator']==44
fp=load(B/'fork_plan.json');assert fp['artifact_digest']==s.digest({k:v for k,v in fp.items() if k!='artifact_digest'}) and not fp['suffix_execution_authorized'] and fp['suffix_sends']==0
assert len(fp['points'])==len(diag['selected_points'])==5
repeat=load(B/'repeat_plan.json');assert repeat['selected_point_ids']==t.repeat_priority(repeat['metadata'],task_order=fp['task_order']) and len(repeat['selected_point_ids'])==4
for point,dp in zip(fp['points'],diag['selected_points']):
 assert all(point[k]==v for k,v in dp.items())
 assert point['public_projection'] in public and s.digest(point['public_projection'])==point['projection_digest']
 assert point['stage']=='NONEMPTY' and point['branches'][0]['kind']=='ORIGINAL_ACTION_REFERENCE'
for j in fp['jobs']:
 point=next(p for p in fp['points'] if p['point_id']==j['point_id']);branch=next(b for b in point['branches'] if b['label']==j['forced_label'])
 ex=load(ref(j['execution_ref']));seal(ex);parent,root,last=checkpoints[point['decision_id']];start=ex['start']
 assert ex['kind']=='FORK' and ex['config']==parent['config'] and ex['task']==parent['task']
 assert load(ref(start['activation_ref']))==load(root/'activation.json') and ref(start['checkpoint_ref'])==last and start['decision_id']==point['decision_id']
 e=event_lookup[start['decision_id']];candidate=next(c for c in e['bundle']['selectable_candidates'] if c['candidate_id']==branch['candidate_id'])
 assert e['context']['display_mapping'][ex['forced_label']]['candidate_id']==j['candidate_id']==candidate['candidate_id']
 assert j['frozen_candidate']==candidate and j['candidate_digest']==s.digest(candidate)==branch['candidate_digest']
 assert j['exact_action_digest']==s.exact_digest(candidate)==branch['exact_action_digest'] and j['exact_action']==branch['action']
 base_job=ex['job_id'].rsplit('_',1)[0]
 assert ex['allocation_id']==s.digest(dict(job_id=base_job,repeat_slot=ex['repeat_slot'],task=s.digest(ex['task']),start=ex['start'],forced_label=ex['forced_label'],root=ex['storage_root']))
 assert ex['allocation_id']==j['allocation_id'] and ex['storage_root']==j['storage_root'] and ex['job_id']==j['job_id']
 assert j['max_sends']==ex['max_sends']==len(ex['task']['items'])-e['before']['placed_count']-1
 assert j['status']=='NOT_RUN_NOT_AUTHORIZED' and not path(j['storage_root']).exists()
 assert (j['repeat_slot']=='r1') is (ex['repeat_slot']=='r1')
 assert j['repeat_slot']=='r0' or j['point_id'] in repeat['selected_point_ids']
 assert not path(j['storage_root']).exists()
budget=load(B/'concrete_budget_receipt.json');assert len(fp['jobs'])==18 and sum(j['max_sends'] for j in fp['jobs'])==budget['suffix_send_upper']==242
assert sum(j['max_sends'] for j in fp['jobs'] if j['repeat_slot']=='r0')==130 and sum(j['max_sends'] for j in fp['jobs'] if j['repeat_slot']=='r1')==112
coverage=load(B/'sampling_coverage_receipt.json');assert coverage['counts']==diag['counts'] and coverage['tasks']==diag['per_task_coverage'] and coverage['gaps']==diag['coverage_gaps']
assert len(coverage['gaps'])==7 and input_tokens==505125 and output_tokens==16495
assert len({j['allocation_id'] for j in fp['jobs']})==18
for point in fp['points']:
 jobs=[j for j in fp['jobs'] if j['point_id']==point['point_id']]
 for branch in point['branches']:
  slots={j['repeat_slot'] for j in jobs if j['forced_label']==branch['label']}
  assert slots==({'r0','r1'} if point['point_id'] in repeat['selected_point_ids'] else {'r0'})
assert not subprocess.check_output(['git','diff','ad94605f','HEAD','--','semantic_pallet_planner/src','semantic_pallet_planner/tests'],cwd=ROOT)
result=dict(version='jm_c1_real_independent_saved_review_v1',head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),status='PASS',manifest_files=len(m['files']),runtime_files=len(actual),jobs=job_summary,requests=requests,commits=commits,journal_stages=stages,archived_kernel_calls=kernel_calls,public_records=len(public),deterministic_sampling='PASS_UNCHANGED_STDLIB_SAMPLER',repeat_priority='PASS',points=5,suffix_jobs=18,suffix_bound=242,coverage_gaps=7,input_tokens=input_tokens,output_tokens=output_tokens,cost='UNKNOWN',authorization_evidence='ARCHIVED_USER_QUOTE_ONLY_NOT_NEW_AUTHORIZATION',current_calls=0,current_orders=0,current_LP=0,full_production_validator='NOT_RUN_ON_MAC',limits='saved JSON seals/bindings and public deterministic computation, no regenerated candidates, physics, LP or schema/runtime identity substitution')
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
