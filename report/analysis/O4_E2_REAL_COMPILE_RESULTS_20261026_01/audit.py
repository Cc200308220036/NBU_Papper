"""Offline audit only. Never calls ChatTransport.complete or modifies experiments."""
import json,hashlib
from collections import Counter
from pathlib import Path
from semantic_pallet_planner.o4.common import read,write,digest,O4Error
from semantic_pallet_planner.o4.extensions.e2.experiment import verify_seal,files
from semantic_pallet_planner.o4.extensions.e2.remote import parse_response,prompt
from semantic_pallet_planner.o4.extensions.e2.protocol import validate_observation,validate_response
from semantic_pallet_planner.o4.extensions.e2.reference import compare,audit
from semantic_pallet_planner.o4.extensions.e2.runtime import evaluate_candidates
from semantic_pallet_planner.o4.extensions.e2.visual import facts
from semantic_pallet_planner.o4.extensions.e2.visual_verify import verify
from semantic_pallet_planner.o4.remote.transport import ModelConfig,ChatTransport
BASE=Path('semantic_pallet_planner/outputs');results=[]
for kind in ('SMOKE','FIXED'):
 root=BASE/f'EXP_O4_E2_{kind}_REAL_20261025_01';planroot=BASE/f'PLAN_O4_E2_{kind}_READY_20261025_01'
 count=verify_seal(root);plan_count=verify_seal(planroot)
 report=read(root/'acceptance_report.json');plan=read(planroot/'plan.json');assert read(root/'plan.json')==plan
 assert files(Path(__import__('semantic_pallet_planner.o4.extensions.e2.remote',fromlist=['']).__file__).resolve().parents[3])==plan['source_files']
 cases=read(root/'private/cases.json');assert cases==read(planroot/'private/cases.json');bycase={c['case_id']:c for c in cases}
 rows=read(root/'metrics/records.json');ledger=read(root/'audit/attempts.json')
 assert len(rows)==len(cases)*4==report['planned_records']==report['recorded_records']
 assert len(ledger)==report['real_api_attempts'];assert [a['attempt_id'] for a in ledger]==list(range(1,len(ledger)+1))
 cfg=ModelConfig(**read(root/'model.snapshot.json'));assert cfg.snapshot()==read(planroot/'model.snapshot.json')
 transport=ChatTransport(cfg) # body() only: no network or credential lookup.
 records={p.stem:read(p) for p in sorted((root/'responses').glob('*.json'))}
 assert len(records)==2*len(cases)
 stats={b:Counter() for b in ('public_parser','remote_text','remote_image','oracle_ast')};repairs=[];seen=[];bodyparams={};groups={}
 for row in rows:
  c=bycase[row['case_id']];q=c['request'];validate_observation(q)
  response=row['response'];assert response is not None and row['status']=='valid'
  attached=q
  if row['compilation_id']:
   r=records[row['compilation_id']];seen.extend(a['attempt_id'] for a in r['attempts']);assert not r['test_double']
   assert r['source']==q and r['prompt_digest']==digest(prompt())
   attached=r['envelope']['public_request'];validate_observation(attached);assert response==r['response']
   assert r['condition']==('text' if row['backend']=='remote_text' else 'image')
   assert r['envelope']['visual_facts']==facts(q)
   assert len(attached['images'])==(r['condition']=='image')
   imagepath=f"public/images/{r['compilation_id']}.png"
   asset={'path':imagepath,'sha256':hashlib.sha256((root/imagepath).read_bytes()).hexdigest()}
   verify(q,root,asset)
   if attached['images']:assert attached['images']==[asset]
   diagnostic=None;successful=[]
   for i,a in enumerate(r['attempts']):
    assert a==ledger[a['attempt_id']-1] and a['repair']==(i==1)
    assert json.loads(a['raw_text'])==a['payload']
    body=transport.body(r['envelope'],root,prompt(),diagnostic);assert digest(body)==a['body_digest']
    bodyparams[(row['case_id'],row['backend'])]={k:v for k,v in body.items() if k!='messages'}
    try:
     parsed=parse_response(a['payload'],attached);status='valid';diagnostic=None;successful.append(parsed)
    except O4Error as exc:
     status=exc.code;diagnostic={'code':exc.code,'detail':str(exc),'repair_scope':'format/bindings only; no reference answer'}
    assert status==a['status'] and diagnostic==a['repair_diagnostic']
   assert len(r['attempts'])<=2 and successful[-1]==response
   assert r['first_valid']==(len(r['attempts'])==1) and r['repaired_valid']==(len(r['attempts'])==2)
   if r['repaired_valid']:
    first=json.loads(r['attempts'][0]['payload']['choices'][0]['message']['content']);last=response
    changed=[k for k in set(first)|set(last) if first.get(k)!=last.get(k)]
    repairs.append({'case_id':row['case_id'],'backend':row['backend'],'compilation_id':r['compilation_id'],
       'first_status':r['attempts'][0]['status'],'diagnostic':r['attempts'][0]['repair_diagnostic'],
       'changed_top_level_fields':changed,'policy_ast_unchanged':first['policy_ast']==last['policy_ast'],
       'initial_instruction_digest_length':len(first['instruction_digest']),'expected_instruction_digest_length':len(attached['instruction_digest'])})
   groups.setdefault(row['case_id'],{})[row['backend']]=r
  validate_response(response,attached)
  m=compare(response['policy_ast'],c['reference_policy'],q['placed_objects']+q['available_objects'])
  expected=audit(q,c['reference_policy'],c['candidates'])['allowed_ids']
  allowed=audit(q,response['policy_ast'],c['candidates'])['allowed_ids']
  assert evaluate_candidates(q,response['policy_ast'],c['candidates'])['allowed_ids']==allowed
  m.update(valid_ast=True,allowed_set_equal=allowed==expected,false_allow_ids=sorted(set(allowed)-set(expected)),false_reject_ids=sorted(set(expected)-set(allowed)))
  assert m==row['metrics'] and m['semantic_equal'] and m['allowed_set_equal']
  st=stats[row['backend']];st['records']+=1
  for key in ('valid_ast','semantic_equal','raw_ast_equal','allowed_set_equal'):st[key]+=bool(m[key])
  st['false_allow']+=len(m['false_allow_ids']);st['false_reject']+=len(m['false_reject_ids'])
 for caseid,g in groups.items():
  t=g['remote_text'];i=g['remote_image'];assert t['envelope']['visual_facts']==i['envelope']['visual_facts']
  assert bodyparams[(caseid,'remote_text')]==bodyparams[(caseid,'remote_image')]
  assert t['response']['state_hash']==i['response']['state_hash'] and t['response']['instruction_digest']==i['response']['instruction_digest']
 assert sorted(seen)==list(range(1,len(ledger)+1))
 assert len(repairs)==report['repaired_valid'] and sum(r['first_valid'] for r in records.values())==report['first_valid']
 result={'experiment':root.name,'status':'PASS','sealed_files_checked':count,'plan_files_checked':plan_count,'cases':len(cases),
  'records':len(rows),'real_api_attempts':len(ledger),'first_valid':report['first_valid'],'repaired_valid':len(repairs),
  'per_backend':stats,'repairs':repairs,'attempt_statuses':Counter(a['status'] for a in ledger),
  'model':cfg.model,'temperature':cfg.temperature,'thinking':cfg.thinking,
  'usage':{k:sum(a['usage'].get(k,0) for a in ledger) for k in ('prompt_tokens','completion_tokens','total_tokens')},
  'mean_latency_s':sum(a['latency_s'] for a in ledger)/len(ledger),
  'candidate_counts':Counter(len(c['candidates']) for c in cases),'observed_object_counts':Counter(len(c['request']['placed_objects'])+len(c['request']['available_objects']) for c in cases),
  'metrics_recomputed':True,'bindings_raw_response_ledger_png_body_digest_verified':True,
  'real_online_status':report['real_online_status'],'unseen_generalization':report['unseen_generalization'],'new_api_attempts':0}
 results.append(result)
write('report/analysis/O4_E2_REAL_COMPILE_RESULTS_20261026_01/audit.json',{'status':'PASS','experiments':results,'new_api_attempts':0})
print(json.dumps(results,ensure_ascii=False,indent=2))
