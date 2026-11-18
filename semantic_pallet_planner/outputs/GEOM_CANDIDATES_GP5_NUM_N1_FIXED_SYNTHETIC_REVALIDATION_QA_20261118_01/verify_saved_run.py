import ast,collections,hashlib,json,struct,subprocess
from pathlib import Path
base=Path('semantic_pallet_planner/outputs')
r=base/'GEOM_CANDIDATES_GP5_NUM_N1_FIXED_SYNTHETIC_REVALIDATION_20261118_01'
f=base/'GEOM_CANDIDATES_GP5_NUM_N1_R6_20261118_01'
src=Path('semantic_pallet_planner/src/semantic_pallet_planner')
def read(p):return json.loads(p.read_bytes())
def sha(raw):return hashlib.sha256(raw).hexdigest()
def file_sha(p):return sha(p.read_bytes())
def digest(v):return sha(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())
def tree(p):return {str(x.relative_to(p)):file_sha(x) for x in p.rglob('*') if x.is_file()}
def same(a,b):
 if type(a) is not type(b):return False
 if type(a) is float:return struct.pack('>d',a)==struct.pack('>d',b)
 if type(a) is list:return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
 if type(a) is dict:return a.keys()==b.keys() and all(same(a[k],b[k]) for k in a)
 return a==b
m=read(r/'delivery_manifest.json')['files']; members={x['path'] for x in m}
assert len(m)==len(members)==1491
for x in m:
 p=Path(x['path'])
 raw=subprocess.check_output(['git','show',"b8134945f1b21a389d57cb9c8a436b04fd58fd8b"+':'+str(p)]) if p.name=='README.md' and not str(p).startswith(str(r)+'/') else p.read_bytes()
 assert (len(raw),sha(raw))==(x['size_bytes'],x['sha256']),str(p)
assert {str(p) for p in r.rglob('*') if p.is_file() and p.name!='delivery_manifest.json'}=={p for p in members if p.startswith(str(r)+'/')}
manifest=read(f/'source_manifest.json'); actual={str(p.relative_to(src)):file_sha(p) for p in src.rglob('*') if p.is_file() and p.suffix in {'.py','.json'} and not {'tests','__pycache__'}.intersection(p.relative_to(src).parts)}
assert actual==manifest['files'] and len(actual)==591 and digest(actual)==manifest['source_identity']
freeze=read(f/'frozen_identity.json')
assert len(freeze['files'])==1403
for path,expected in freeze['files'].items():assert file_sha(Path(path))==expected,path
for remote,members in read(r/'sealed_input_identity.json').items():assert tree(base/Path(remote).name)==members,remote
auth=read(r/'authorization_receipt.json'); assert auth==read(r/'execution_started.json')['authorization']
assert auth['input_freeze_sha256']==file_sha(f/'frozen_identity.json') and auth['validation_scope_sha256']==file_sha(f/'validation_scope.json')
assert auth['source_identity']==manifest['source_identity'] and Path(auth['run_root']).name==r.name
env=read(r/'environment_identity_preflight.json'); frozen_env=read(f/'environment_receipt.json')
assert env['observed_environment']==frozen_env['expected']==frozen_env['observed'] and env['dependencies']==frozen_env['dependencies'] and env['configs_preflighted']==8
rows=read(r/'case_results.json')['rows']; tally=collections.Counter((x['group'],x['status']) for x in rows)
want={('C','PASS'):6,('E','PASS'):8,('R','PASS'):2,('R','FAIL'):1,('R','NOT_RUN'):3,('X_H_ADMIN','NOT_RUN'):15}
assert len(rows)==len({x['id'] for x in rows})==35 and tally==want
assert all(x['attempts']==int(x['status']!='NOT_RUN') for x in rows)
for row in rows:
 if row['group']!='C':continue
 tag=row['id'].split('/')[1]; rec=read(r/'C'/(tag+'.json'))
 kind=tag[0]; vals={'I':[100,80,60],'F':[100.0,80.5,60.25],'M':[100,80.0,60]}[kind]
 if tag[1:]=='90': vals=[vals[1],vals[0],vals[2]]
 assert same(rec['target'],vals) and rec['case']==tag and all(v.startswith('PASS') for v in rec['requirements'].values())
 for node in rec['dependency_nodes']:
  assert node['digest']==digest({'domain':'geometry_native_shape_identity_r1/C_metadata/'+node['name']+'/v1','payload':node['payload']})
jobs=read(f/'plan.json')['jobs']; frozen_cfg=read(f/'configs.json')
assert {v['status'] for v in read(r/'E/run.json')['rows']}=={'COMPLETE'}
for j in jobs:
 jid=j['job_id']; root=r/'E/jobs'/jid
 ep=read(root/'episode.json'); cfg=read(root/'config.json'); met=read(root/'metrics.json'); rec=read(r/('E_f0_'+jid+'.json'))
 assert cfg==frozen_cfg[jid] and met==ep['summary']
 placed=[e for e in ep['events'] if e['event']=='PLACE']
 assert len(placed)==met['placed_items']==2 and met['completed'] and met['monitor_evidence']=='TEST_DOUBLE'
 assert met['counts']=={'assessment_entries':0,'solver_calls':0,'test_double_assessments':2}
 assert len(rec['production_saved_closure'])==2
 assert [x['route'] for x in rec['f0']['contexts']]==['CHOICE_REQUIRED','SINGLETON_BYPASS']
 for e in placed:
  wanted=e['selection']['selected_candidate_id']
  selected=next(c for c in e['bundle']['physical_candidates'] if c['candidate_id']==wanted)
  source=next(x['item'] for x in e['before']['pending_items'] if x['item']['item_id']==selected['pick_item_id'])
  put=next(x for x in e['after']['placed_items'] if x['item_id']==selected['pick_item_id'])
  axes=('length','width','height') if selected['pose']['yaw_deg']==0 else ('width','length','height')
  expected=[source['dimensions_mm'][k] for k in axes]
  assert same(expected,selected['oriented_size_mm']) and same(expected,put['oriented_size_mm'])
  assert same(selected['pose'],put['pose']) and same(e['action'],e['proposed_action'])
  assert e['monitor']['status']=='STABLE' and e['monitor']['result']['diagnostics']['TEST_DOUBLE'] is True
  ref=e['geometry_ref']['sha256']; blob=root/'blobs'/ref
  assert file_sha(blob)==ref
  pub=read(blob)['audit']['publication']
  for k,content in pub['blobs'].items():assert sha(bytes.fromhex(content))==k and file_sha(root/'blobs'/k)==k
pairs=read(r/'E_f0_pairs.json')
assert len(pairs)==4 and len({(p['task_id'],p['method']) for p in pairs})==4
assert all(p['status']=='PASS_SAME_PROTOCOL_FIELD_CONTRACT' for p in pairs)
provenance=read(r/'R_snapshot_provenance.json')
assert len(provenance)==6
for row in provenance:
 label=row['job_id']+'_'+row['phase']; assert Path(row['root']).name==label
 p=r/'R_saved'/label; assert tree(p)==row['files'] and row['parent_prefix_unchanged']
 cp=read(p/'jobs'/row['job_id']/'checkpoint.json'); assert cp['phase']==row['phase']
 assert cp['state']['end_of_stream'] and len(cp['pending_event']['before']['placed_items'])==1
assert {p.name for p in (r/'R_recovery').iterdir()}=={'J01_SELECTED','J01_MONITORED','J01_COMMITTED'}
for phase,counts in [('SELECTED',(1,0,1)),('MONITORED',(0,1,1)),('COMMITTED',(0,0,0))]:
 p=r/'R_recovery'/('J01_'+phase); root=p/'jobs/J01'
 ac=read(root/'accounting.json'); inv=ac['invocations'][-1]; delta=inv['delta']
 cp=read(root/'checkpoint.json'); saved=read(r/'R_saved'/('J01_'+phase)/'jobs/J01/checkpoint.json')
 assert inv['resume_checkpoint_digest']==digest(saved) and inv['resume_phase']==phase
 assert tuple(delta[k] for k in ('monitor_entries','monitor_reuses','commit_successes'))==counts
 assert delta['selector_calls']==delta['singleton_executions']==0 and delta['commit_attempts']==delta['commit_successes']
 assert cp['phase']=='TERMINATED' and cp['reason']=='ALL_ITEMS_PLACED' and len(cp['state']['placed_items'])==2
 driver=next(x for x in read(p/'run.json')['rows'] if x['job_id']=='J01')
 if phase=='COMMITTED':
  assert inv['status']=='ERROR' and inv['result_checkpoint_digest'] is None and driver['status']=='TECHNICAL_FAILURE'
  assert not (root/'metrics.json').exists()
  recovery=cp
 else:assert inv['status']=='RETURNED' and inv['result_checkpoint_digest']==digest(cp) and driver['status']=='COMPLETE'
calls=read(r/'call_accounting.json'); assert collections.Counter(x['group'] for x in calls['dispatch_records'])=={'E':16,'R':1}
assert calls['cross_history_E']==calls['cross_history_E_max']==21 and calls['new_R_commits']==2 and calls['real_calls']==0
assert not (r/'X_H_admin_results.json').exists()
module=ast.parse((src/'jev_select/geometry_order_execution.py').read_bytes())
func=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='order_metrics')
loop=next(n for n in func.body if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='key')
assert loop.lineno==231 and ast.unparse(loop.body[0])=="timings.append({'segment': key, 'seconds': sum((e.get('timings', {}).get(key, 0) for e in events))})"
vals=[e['timings']['decision_wall_s'] for e in recovery['events'] if 'decision_wall_s' in e.get('timings',{})]
assert len(vals)==2 and type(vals[0]) is float and vals[1] is None
try:
 sum(e.get('timings',{}).get('decision_wall_s',0) for e in recovery['events'])
except TypeError as e:assert str(e)==read(r/'validation_stop.json')['detail']
else:raise AssertionError('Expected saved timing TypeError')
print('1491 archived entries; 1403 frozen hashes; 591 current source files; 5 protected roots verified via portable relative location')
print('C6/E8 + four F0 pairs; 16 exact logged placements; six unchanged saved copies; R attempts 3/pass 2; overall 16 PASS / 1 FAIL / 18 NOT_RUN')
print('E monitor 16, R monitor 1/commit 2; archived failed resume zero increment; timing values',vals,'; isolated summation reproduces original TypeError; no order replay')
