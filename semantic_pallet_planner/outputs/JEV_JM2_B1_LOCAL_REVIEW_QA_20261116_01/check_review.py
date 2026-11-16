"""Independent stdlib saved-review audit; no production imports or dispatch."""
import json,hashlib,collections
from pathlib import Path
R=Path(__file__).resolve().parents[3];O=Path(__file__).resolve().parent;B=R/'semantic_pallet_planner/outputs'
def read(p):return json.loads(p.read_text())
def resolve(v):
 p=R/v['path'];assert hashlib.sha256(p.read_bytes()).hexdigest()==v['sha256'];x=read(p)
 for k in v['pointer'].split('/')[1:]:
  k=k.replace('~1','/').replace('~0','~');x=x[int(k)] if isinstance(x,list) else x[k]
 return x
review=read(B/'JEV_JM2_B1_LOCAL_CONTENT_REVIEW_20261116_01/per_card_content_review.json')['cards'];cards=read(B/'JEV_JM2_A2_20261115_01/case_snapshot_candidate.json')['cards'];idx=read(B/'JEV_JM2_A2_20261115_01/private_audit_index.json')['cards'];spec=read(B/'JEV_JM2_A1_20261115_01/scenario_feature_spec.json');counts=collections.Counter();branches=0;binding_count=0;rows=[]
assert len(review)==len(cards)==len(idx)==5
for i,(a,c,e) in enumerate(zip(review,cards,idx)):
 assert a['card_index']==i and resolve(a['card_ref'])==c
 costs=a['cost_and_counterevidence'];assert costs['observations']==c['observations'] and costs['continuation']==c['continuation']
 assert costs['grade']==c['evidence_grade'] and costs['repeat_conflict']==c['repeat_conflict']
 assert a['decision']=='ARCHIVE_ONLY' and not a['qualified_generation_input'] and not a['execution_eligible']
 assert a['review_status']=='COMPLETED_LOCAL_CONTENT_REVIEW' and a['causal_proof_required'] is False
 for binding in a['observable_preconditions']['bindings']:
  if binding['status']=='REGISTERED_OBSERVABLE_A_B_ATTRIBUTE':
   for role,value in binding['current_values'].items():assert value==c['actions'][role]['attributes'][binding['condition']]
   binding_count+=1
  if binding['status']=='REGISTERED_SCENARIO_FEATURE':
   assert binding['condition'] in spec['features'] and binding['value']==c['features'][binding['condition']];binding_count+=1
 for obs,pair in zip(c['observations'],e['pairs']):
  assert resolve(pair['comparison'])['evaluation']['label_v2']==obs['label'];counts[obs['label']]+=1
  for role in ['A','B']:
   b=resolve(pair['branches'][role]);assert all(b['metrics'][k]==v for k,v in obs[role].items());branches+=1
 rows.append(dict(card_index=i,evidence_grade=c['evidence_grade'],decision=a['decision'],comparisons=len(c['observations'])))
assert branches==18 and dict(counts)=={'improved':4,'degraded':3,'neutral':2}
result=dict(version='jm2_b1_local_review_qa_saved_v1',status='PASS',cards=rows,labels=dict(counts),branches=branches,registered_bindings=binding_count,scope='saved consistency only; independent judgement in QA report; not formal proof of applicability')
(O/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
