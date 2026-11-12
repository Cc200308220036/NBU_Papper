"""Stdlib saved facts and static transition-gap witnesses. Never imports runtime."""
import ast,base64,copy,hashlib,json,subprocess,xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
B=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_V13_ENGINEERING_20261112_01'
HEAD='90e0e488e880c3d2196627cc54a4999704dc0ff8'
def load(p):return json.loads(p.read_text())
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def sha(b):return hashlib.sha256(b).hexdigest()
def sealed(v):return v.get('record_digest')==digest({k:x for k,x in v.items() if k!='record_digest'})
result={'version':'jm_v13_independent_review_v1','head':HEAD}
m=load(B/'delivery_manifest.json')
for r in m['files']:
 raw=subprocess.check_output(['git','show',HEAD+':'+r['path']],cwd=ROOT) if r['path']=='docs/03_阶段产出分析/Jev/README.md' else (ROOT/r['path']).read_bytes()
 assert sha(raw)==r['sha256'] and len(raw)==r['bytes'],r['path']
result['delivery_files_checked']=len(m['files'])
snapshot=load(B/'source_manifest.json');package=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
actual={p.relative_to(package).as_posix():sha(p.read_bytes()) for p in sorted(package.rglob('*')) if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(package).parts)}
assert actual==snapshot;result['source_files_checked']=len(snapshot)
for r in load(B/'source_identity.json')['changed_or_new_files']:assert sha((ROOT/r['path']).read_bytes())==r['sha256']
history=load(B/'historical_protection.json')
def tree(ref):
 raw=subprocess.check_output(['git','ls-tree','-r','-z',ref],cwd=ROOT)
 return {entry.split(b'\t',1)[1].decode():entry.split(b'\t',1)[0].split()[2].decode() for entry in raw.split(b'\0') if entry}
old=tree(history['entry_head']);current=tree(HEAD)
for r in history['files']:assert r['entry_blob']==old[r['path']]==current[r['path']]==r['current_blob'] and r['unchanged']
result['historical_git_blob_rows_verified']=len(history['files'])
result['archived_junit']={}
for kind,expected in [('constructed',39),('legacy',131)]:
 root=ET.parse(B/f'accepted_{kind}_junit.xml').getroot();cases=root.findall('.//testcase')
 assert len(cases)==expected and not root.findall('.//failure') and not root.findall('.//error')
 result['archived_junit'][kind]={'tests':len(cases),'failures':0,'evidence':'ARCHIVED_NOT_CURRENT_RUN'}
roots=sorted((B/'accepted_constructed_evidence').rglob('activation.json'));phases=Counter();requests=0;raw_responses=0;negative_archive_observations=[]
for anchor in roots:
 activation=load(anchor);assert sealed(activation)
 ex=activation['execution'];assert sealed(ex)
 previous=digest(activation);cp=activation['initial_checkpoint'];assert sealed(cp)
 rows=sorted((anchor.parent/'stages').glob('*.json'))
 for seq,path in enumerate(rows,1):
  row=load(path);assert sealed(row) and row['sequence']==seq and row['previous_digest']==previous
  assert row['execution_digest']==digest(ex);cp=row['checkpoint'];assert sealed(cp)
  phases[cp['phase']]+=1;previous=digest(row)
 if rows:assert load(anchor.parent/'checkpoint_head.json')=={'sequence':len(rows),'digest':previous}
 ledger=anchor.parent/'ledger/requests.json'
 if ledger.exists():
  d=load(ledger);assert sealed(d);requests+=len(d['requests'])
  for row in d['requests']:
   context=load(anchor.parent/'ledger/contexts'/(row['decision_id']+'.json'))
   assert context['model_state']['memories']==[] and context['request_body']['state']['memories']==[]
   assert row['context_digest']==digest(context) and row['body_digest']==digest(context['request_body'])
   if row['transport'] is not None:
    t=row['transport'];assert row['transport_digest']==digest(t)
    if t.get('raw_body_b64') is not None:
     raw=base64.b64decode(t['raw_body_b64']);assert sha(raw)==t['raw_sha256'];raw_responses+=1
 counts=anchor.parent/'counts.json'
 if counts.exists():
  c=load(counts);expected_commits=sum(e['event']=='PLACE' for e in cp['events'])
  if c['commits']!=expected_commits:
   assert 'test_parent_saved_tampering_an' in str(anchor),str(anchor)
   assert c['commits']==expected_commits+1
   negative_archive_observations.append({'path':str(counts.relative_to(B)),'kind':'intentional counts tamper left by negative test','saved':c['commits'],'expected':expected_commits})
result['intentional_negative_archive_observations']=negative_archive_observations
result['archived_v13_saved_roots']=len(roots);result['journal_phase_counts']=dict(phases)
result['archived_requests_checked']=requests;result['raw_response_hashes_checked']=raw_responses
# Save two static witnesses, not an invocation or substitute of production validation.
baseline=B/'accepted_constructed_evidence/test_baseline_public_export0/baseline'
receive=load(baseline/'stages/000001.json')['checkpoint'];assert receive['phase']=='READY' and len(receive['events'])==1
before=copy.deepcopy(receive);mut=copy.deepcopy(receive)
mut['events'][0]['after']['pending_items'][0]['item']['mass_kg']+=1
mut['state']=copy.deepcopy(mut['events'][0]['after']);mut['record_digest']=digest({k:v for k,v in mut.items() if k!='record_digest'})
assert sealed(mut) and mut['cursor']==before['cursor'] and mut['state']['arrived_ids']==before['state']['arrived_ids']
committed=next(load(p)['checkpoint'] for p in sorted((baseline/'stages').glob('*.json')) if load(p)['checkpoint']['phase']=='COMMITTED')
mut2=copy.deepcopy(committed);e=mut2['pending_event'];e['after']['placed_items'][-1]['pose']['x_mm']+=1
mut2['state']=copy.deepcopy(e['after']);mut2['record_digest']=digest({k:v for k,v in mut2.items() if k!='record_digest'})
assert sealed(mut2) and e['proposed_action']==committed['pending_event']['proposed_action']
assert e['after']['placed_count']==committed['pending_event']['after']['placed_count']
assert [p['item_id'] for p in e['after']['placed_items']]==[p['item_id'] for p in committed['pending_event']['after']['placed_items']]
(OUT/'static_transition_witnesses.json').write_text(json.dumps({'version':'jm_v13_static_transition_witnesses_v1','scope':'STATIC_ONLY_NOT_PRODUCTION_REPRODUCTION','cases':[{'id':'WAIT_RECEIVE_ITEM_MASS','source':'accepted_constructed_evidence/test_baseline_public_export0/baseline/stages/000001.json','modified_checkpoint':mut,'unchanged':'task/config execution identity, IDs/cursor/counts','missing_check':'arrival payload equality to frozen task; source lines 177,214,218'},{'id':'COMMITTED_PLACED_POSE','modified_checkpoint':mut2,'unchanged':'proposed action and monitor, counts and placed IDs','missing_check':'after placed geometry equality to selected candidate; lines203-211'}],'production_validator_run':'NOT_RUN: jsonschema/numpy/scipy unavailable; no substituted identity/schema/control-flow probe','original_files_modified':False},ensure_ascii=False,indent=2)+'\n')
result['static_findings']=['WAIT_RECEIVE/EOS payload transition under-validation','PLACE post-state geometry/payload under-validation']
result['current_behavior_tests']='NOT_RUN: prohibited episode/commit scope and missing pytest/jsonschema/numpy/scipy'
result['status']='SAVED_BYTES_AND_ARCHIVED_CHECKS_PASS_STATIC_TRANSITION_GAP_CONFIRMED'
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
