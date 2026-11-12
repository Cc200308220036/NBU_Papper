"""Independent stdlib byte/source/provenance/selection/budget checks. No runtime imports."""
import hashlib,json,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
B=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_FORMAL_PREP_20261112_01';HEAD='c21d6b511e4c33e5ff0acfd4a51931c896edb60d'
def load(p):return json.loads(p.read_text())
def sha(v):return hashlib.sha256(v).hexdigest()
def digest(v):return sha(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def readref(r):
 raw=(ROOT/r['path']).read_bytes();assert sha(raw)==r['sha256'],r['path'];v=json.loads(raw)
 for part in r.get('pointer','').split('/')[1:]:
  part=part.replace('~1','/').replace('~0','~');v=v[int(part)] if isinstance(v,list) else v[part]
 return v
m=load(B/'delivery_manifest.json');result={'version':'jm_b2_formal_prep_independent_checks_v1','head':HEAD}
for r in m['files']:
 raw=(ROOT/r['path']).read_bytes();assert sha(raw)==r['sha256'] and len(raw)==r['bytes'],r['path']
result['delivery_files']=len(m['files'])
snapshot=load(B/'source_manifest.json');package=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
actual={p.relative_to(package).as_posix():sha(p.read_bytes()) for p in sorted(package.rglob('*')) if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(package).parts)}
assert actual==snapshot;result['runtime_source_files']=len(actual)
p=load(B/'materials/training_plan.json');assert p['plan_digest']==digest({k:v for k,v in p.items() if k!='plan_digest'})
assert p['runtime_identity']['source']==digest(snapshot)
for r in p['input_refs']:
 if r['path'].endswith('.md'):assert sha((ROOT/r['path']).read_bytes())==r['sha256']
 else:readref(r)
result['plan_input_refs']=len(p['input_refs'])
audit=readref(p['audit_ref']);catalog=readref(p['catalog_ref']);assert len(audit['rows'])==len(catalog['candidates'])==22
# Independently recover relation closure and deterministic train-only round robin.
components=[]
for row in catalog['candidates']:
 t=readref(row['material_ref']);s=readref(row['source_register_ref']);assert t['task_id']==row['existing_id']==s['id']
 assert len(t['items'])==row['audit_full_item_count']
 assert t['arrival_order']==[x['item_id'] for x in t['items']]
 assert s['file_sha256']==row['material_ref']['sha256'] and s['history']==row['history']
 merged={'tasks':{row['relation']['task_id']},'tokens':set(row['relation']['relation_tokens'])|{'SOURCE:'+row['relation']['source_group']}}
 while True:
  overlap=[c for c in components if c['tokens']&merged['tokens']]
  if not overlap:break
  for c in overlap:merged['tasks']|=c['tasks'];merged['tokens']|=c['tokens'];components.remove(c)
 components.append(merged)
computed=[{'tasks':sorted(c['tasks']),'tokens':sorted(c['tokens'])} for c in components];computed.sort(key=digest)
assert computed==audit['grouping']['material_components']
queues={}
for row in audit['rows']:
 if row['partition']=='train':queues.setdefault(row['component'],[]).append(row)
for q in queues.values():q.sort(key=lambda r:(r['task_ref']['sha256'],r['task_id']))
expected=[]
while len(expected)<6:
 for k in sorted(queues):
  if queues[k] and len(expected)<6:expected.append(queues[k].pop(0)['task_id'])
assert expected==[r['task_id'] for r in p['assignments']]
schedule=readref(p['schedule_ref']);executions=[];ns=[]
for i,r in enumerate(p['assignments']):
 t=readref(r['task_ref']);ex=readref(r['execution_ref']);rt=ex['task'];ns.append(len(t['items']));executions.append(ex)
 assert t['partition']=='train' and r['full_items']==ex['max_sends']==len(t['items'])
 assert r['wave']==1+i//3 and r['ordinal']==i+1 and r['slot_id']==f'W{1+i//3}S{1+i%3}'
 assert rt['frozen_task_digest']==digest(t) and rt['task_id']==t['task_id']
 for a,b in zip(rt['items'],t['items']):
  assert all(a[k]==b[k] for k in ('item_id','dimensions_mm','mass_kg','stackable','top_load_limit_kg_synthetic','fragile','weight_class'))
 assert r['runtime_task_digest']==digest(rt) and r['arrival_digest']==digest(rt['items'])
 assert ex['identity']==p['runtime_identity'] and ex['config']['jm_mode']=='REMOTE_INJECTED'
 assert ex['kind']=='BASELINE' and ex['repeat_slot']=='r0' and ex['record_digest']==digest({k:v for k,v in ex.items() if k!='record_digest'})
 assert ex['config']['runtime_identity']['data_identity']==r['data_identity']
 assert ex['config']['runtime_identity']['task_identity']==digest(rt)
 assert ex['config']['stability_monitor']['algorithm']=='pct_exact_pose_network_v3'
assert schedule['executions']==executions and schedule['global_max_sends']==sum(ns)==103
initial=sum(3*(n-1)+3*max(0,n-2) for n in ns);repeat=sum(sorted([3*max(0,n-z-1) for n in ns for z in (0,1)],reverse=True)[:4])
b=p['budget'];assert (initial,repeat,initial+repeat,sum(ns)+initial+repeat)==(564,210,774,877)
assert (b['baseline_send_upper'],b['initial_suffix_send_upper'],b['repeat_suffix_send_upper'],b['suffix_send_upper'],b['global_send_upper'])==(103,564,210,774,877)
assert (b['point_cap'],b['initial_suffix_cap'],b['repeat_suffix_cap'],b['total_suffix_cap'])==(12,36,12,48)
assert not p['formal_frozen'] and not p['execution_authorized'];assert p['qa_refs']==[] and len(p['missing_qa'])==5
result['historically_missing_parent_files_now_present']=[v for v in p['missing_qa'] if (ROOT/v).is_file()];assert len(result['historically_missing_parent_files_now_present'])==5
parent=ROOT/'semantic_pallet_planner/outputs/JEV_JM_V13_FIX_QA_20261112_01'
parent_manifest=load(parent/'delivery_manifest.json');nav_gap=[]
for row in parent_manifest['files']:
 raw=(ROOT/row['path']).read_bytes()
 if sha(raw)!=row['sha256'] and row['path']=='docs/03_阶段产出分析/Jev/README.md':
  for commit in subprocess.check_output(['git','log','-20','--format=%H','--',row['path']],cwd=ROOT,text=True).splitlines():
   old=subprocess.check_output(['git','show',commit+':'+row['path']],cwd=ROOT)
   if sha(old)==row['sha256']:raw=old;break
  if sha(raw)!=row['sha256']:nav_gap.append(row['path']);continue
 assert sha(raw)==row['sha256'],row['path']
result['parent_QA_navigation_only_gaps']=nav_gap
h=load(B/'historical_protection.json')
for r in h['files']:
 current=(ROOT/r['path']).read_bytes()
 if r['comparison']=='EXACT':assert sha(current)==r['entry_sha256']
 else:
  old=subprocess.check_output(['git','show',h['entry_head']+':'+r['path']],cwd=ROOT)
  assert sha(old)==r['entry_sha256'] and current.startswith(old)
result['protected_files']=len(h['files'])
assert not subprocess.check_output(['git','diff','e7646132',HEAD,'--','semantic_pallet_planner/src','semantic_pallet_planner/tests'],cwd=ROOT)
junit=ET.parse(B/'constructed_junit.xml').getroot();assert len(junit.findall('.//testcase'))==18 and not junit.findall('.//failure') and not junit.findall('.//error')
roles=load(B/'role_reservations.json');assert roles['selected_order']==expected
chosen={r['component'] for r in p['assignments']}
assert len(chosen)==3 and len({r['relation']['source_group'] for r in p['assignments']})==4
for c in roles['components']:assert c['reserved_role']==('training' if c['component'] in chosen else 'DEFER_NOT_ASSIGNED')
assert not (B/'materials/future_runs').exists()
result.update(material_tasks=22,selected_tasks=expected,full_items=ns,source_groups=4,conservative_components=3,budget={'baseline':103,'initial':564,'repeat':210,'suffix':774,'global':877},formal_frozen=False,execution_authorized=False,archived_tests=18,current_behavior='NOT_RUN: missing dependencies; no identity/schema substitution',root_binding={'frozen':schedule['storage_root'],'local_review_root':str(ROOT),'portable':False},original_verifier='NOT_RUN: imports missing dependencies and writes original delivery_checks.json; independent read-only check used',status='PASS_OFFLINE_SAVED_FACTS_WITH_FORMAL_FREEZE_DEFER')
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
