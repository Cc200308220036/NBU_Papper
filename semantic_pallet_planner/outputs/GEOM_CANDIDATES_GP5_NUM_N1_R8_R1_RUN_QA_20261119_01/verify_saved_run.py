import collections,hashlib,json,struct,subprocess
from pathlib import Path
b=Path('semantic_pallet_planner/outputs'); r=b/'GEOM_CANDIDATES_GP5_NUM_N1_R8_R1_RUN_20261119_01'; d=b/'GEOM_CANDIDATES_GP5_NUM_N1_R8_R1_20261119_01'
src=Path('semantic_pallet_planner/src/semantic_pallet_planner'); rev='45384dd1c3f976069fffee73a7180c5f2ef64bac'
def read(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def dg(v):return sha(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())
def hashes(p):return {str(f.relative_to(p)):sha(f.read_bytes()) for f in p.rglob('*') if f.is_file()}
def same(a,b):
 if type(a) is not type(b):return False
 if type(a) is float:return struct.pack('>d',a)==struct.pack('>d',b)
 if type(a) is dict:return a.keys()==b.keys() and all(same(a[k],b[k]) for k in a)
 if type(a) is list:return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
 return a==b
members=read(r/'delivery_manifest.json')['files']; assert len(members)==len({v['path'] for v in members})==974
for v in members:
 p=Path(v['path']); raw=subprocess.check_output(['git','show',rev+':'+str(p)]) if p.name=='README.md' and not str(p).startswith(str(r)+'/') else p.read_bytes()
 assert (len(raw),sha(raw))==(v['size_bytes'],v['sha256']),str(p)
assert {str(r/k) for k in hashes(r) if k!='delivery_manifest.json'}=={v['path'] for v in members if v['path'].startswith(str(r)+'/')}
f=read(d/'frozen_identity.json'); auth=read(r/'authorization_receipt.json'); start=read(r/'execution_started.json')
assert len(f['historical_members'])==2977 and len(f['current_members'])==699
for rows in (f['historical_members'],f['current_members']):
 for row in rows:
  p=Path(row['path']); raw=subprocess.check_output(['git','show',row['revision']+':'+str(p)]) if row['kind']=='git' else p.read_bytes()
  assert sha(raw)==row['sha256'],str(p)
for path,h in read(r/'sealed_input_identity.json').items():assert hashes(b/Path(path).name)==h,path
live={str(p.relative_to(src)):sha(p.read_bytes()) for p in src.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(src).parts)}
assert len(live)==591 and live==read(d/'source_manifest.json')['files'] and dg(live)==f['source_identity']==auth['source_identity']
assert auth==start['authorization'] and start['one_shot'] and auth['explicit_user_assignment'] and auth['independent_allowance_confirmed']
assert auth['limits']==f['limits'] and auth['allowed_jobs']==f['allowed_jobs'] and auth['input_freeze_sha256']==sha((d/'frozen_identity.json').read_bytes())
assert auth['run_root']==f['run_root']==str(r)
rows=read(r/'case_results.json')['rows']; counts=collections.Counter((x['group'],x['status']) for x in rows)
assert counts=={('C','PASS'):6,('E','PASS'):2,('R','PASS'):6,('X_H_ADMIN','PASS'):15,('E','NOT_RUN_OUT_OF_PROPOSED_MINIMUM_SCOPE'):6}
assert len({x['id'] for x in rows})==35 and all(x['attempts']==int(x['status']=='PASS') for x in rows)
assert sorted(x['id'] for x in rows if x['group']=='E' and x['status']=='PASS')==['E/J01','E/J03']
assert len(read(r/'C_results.json'))==6
for jid,backend in [('J01','e2_original_v1'),('J03','ems_surface_hybrid_v1')]:
 p=r/'E/jobs'/jid; ep=read(p/'episode.json'); m=read(p/'metrics.json')
 assert ep['summary']==m and m['candidate_backend']==backend and m['monitor_evidence']=='TEST_DOUBLE' and m['completed'] and m['termination_reason']=='ALL_ITEMS_PLACED' and m['placed_items']==2
 assert m['counts']=={'assessment_entries':0,'solver_calls':0,'test_double_assessments':2}
 assert read(p/'config.json')==read(d/'configs.json')[jid]
 events=[e for e in ep['events'] if e['event']=='PLACE']; assert len(events)==2
 assert [e['context']['route'] for e in events]==['CHOICE_REQUIRED','SINGLETON_BYPASS']
 for e in events:
  chosen=next(v for v in e['bundle']['physical_candidates'] if v['candidate_id']==e['selection']['selected_candidate_id'])
  item=next(v['item'] for v in e['before']['pending_items'] if v['item']['item_id']==chosen['pick_item_id'])
  placed=next(v for v in e['after']['placed_items'] if v['item_id']==chosen['pick_item_id'])
  dims=('length','width','height') if chosen['pose']['yaw_deg']==0 else ('width','length','height')
  assert same(chosen['oriented_size_mm'],[item['dimensions_mm'][a] for a in dims]) and same(placed['oriented_size_mm'],chosen['oriented_size_mm'])
  assert same(placed['pose'],chosen['pose']) and same(e['action'],e['proposed_action'])
  ref=e['geometry_ref']['sha256']; blob=(p/'blobs'/ref).read_bytes(); assert sha(blob)==ref
  for k,h in json.loads(blob)['audit']['publication']['blobs'].items():assert sha(bytes.fromhex(h))==k==sha((p/'blobs'/k).read_bytes())
 assert len(read(r/('E_f0_'+jid+'.json'))['production_saved_closure'])==2
(pair,)=read(r/'E_f0_pairs.json'); assert set(pair['backends'])=={'e2_original_v1','ems_surface_hybrid_v1'} and pair['status']=='PASS_SAME_PROTOCOL_FIELD_CONTRACT'
provenance=read(r/'R_snapshot_provenance.json'); assert len(provenance)==6
seen=set(); partial={}
for p in provenance:
 jid,phase=p['job_id'],p['phase']; label=jid+'_'+phase; seen.add(label)
 saved=r/'R_saved'/label; assert hashes(saved)==p['files'] and p['parent_prefix_unchanged'] and p['new_business_dispatches']==0
 c=read(saved/'jobs'/jid/'checkpoint.json'); assert c['phase']==phase
 recovered=r/'R_recovery'/label/'jobs'/jid; cp=read(recovered/'checkpoint.json'); m=read(recovered/'metrics.json')
 assert cp['phase']=='TERMINATED' and cp['reason']=='ALL_ITEMS_PLACED' and m['completed'] and m['placed_items']==2
 ac=read(recovered/'accounting.json')['invocations']; assert len(ac)==2
 last=ac[-1]; delta=last['delta']; assert last['status']=='RETURNED' and last['resume_checkpoint_digest']==dg(c) and last['result_checkpoint_digest']==dg(cp)
 assert (delta['monitor_entries'],delta['monitor_reuses'],delta['commit_attempts'],delta['commit_successes'])=={'SELECTED':(1,0,1,1),'MONITORED':(0,1,1,1),'COMMITTED':(0,0,0,0)}[phase]
 assert delta['selector_calls']==delta['singleton_executions']==0
 t=read(r/'R_timing'/(label+'.json')); assert t['status']=='PASS' and t['phase']==phase
 if phase=='COMMITTED':
  vals=[e['timings'].get('decision_wall_s') for e in cp['events'] if e.get('decision_id') or e.get('timings')]
  results={x['segment']:x['seconds'] for x in m['timings']}
  assert len(vals)==2 and isinstance(vals[0],(int,float)) and vals[1] is None
  assert 'decision_wall_s' not in results and results['measured_partial/decision_wall_s']==vals[0]==t['expected_from_events']['measured_partial/decision_wall_s']
  partial[jid]=vals[0]
assert seen=={j+'_'+p for j in ('J01','J03') for p in ('SELECTED','MONITORED','COMMITTED')}
x=read(r/'X_H_admin_results.json'); assert [v['name'] for v in x]==[v['name'] for v in read(d/'validation_scope.json')['X_H_names']]
expected=read(d/'expected_rejections.json')
for case in x:
 name=case['name']; assert case['status']=='PASS'
 details=case['details'] if name!='H_strong_completion_missing_duplicate_error_no_commit' else read(r/'X_contracts/completion_contract.json')['strict_exception_receipts']
 observed={v['case']:{'type':v['exception_type'],'code':v['code']} for v in details if v.get('status')=='EXPECTED_REJECTION'}
 assert observed==expected.get(name,{}),(name,observed)
assert not (r/'ADMIN_MUST_NOT_EXIST').exists()
h=read(r/'H_v16/jobs/J02/metrics.json'); assert h['termination_reason']=='RUNTIME_INPUT_INVALID' and h['placed_items']==1 and h['counts']['test_double_assessments']==1
a=read(r/'call_accounting.json'); assert collections.Counter((v['group'],v['job_id']) for v in a['dispatch_records'])=={('E','J01'):2,('E','J03'):2,('R','J01'):1,('R','J03'):1,('X_H','H_v16'):1}
assert a['R_resumes_attempted']==a['R_resumes_passed']==6 and a['R_commit_dispatch_attempts']==a['new_R_commits']==4 and a['real_calls']==0
assert a['historical_E_used']==21 and a['old_E_remaining']==0
assert read(r/'command_receipts.json')['retries']==0 and not (r/'validation_stop.json').exists()
print('974 delivery entries; 2977 historical / 699 current frozen members; 591 live production files; authorized receipt matched.')
print('C6/E2/R6/X_H_ADMIN15 passed in archive; 6 out of scope; both backends 2/2, exact actions and F0 pair checked.')
print('Both COMMITTED partial totals:',partial,'; monitor E4/R2/XH1, R commits 4, real calls 0; no replay.')
