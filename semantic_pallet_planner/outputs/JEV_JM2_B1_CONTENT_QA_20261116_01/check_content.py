"""Independent saved comparison/binding check; no production imports."""
import json,hashlib,collections
from pathlib import Path
R=Path(__file__).resolve().parents[3];O=Path(__file__).resolve().parent;B=R/'semantic_pallet_planner/outputs'
def read(p):return json.loads(p.read_text())
def ref(v):
 p=R/v['path'];assert hashlib.sha256(p.read_bytes()).hexdigest()==v['sha256'];x=read(p)
 for k in v['pointer'].split('/')[1:]:
  k=k.replace('~1','/').replace('~0','~');x=x[int(k)] if isinstance(x,list) else x[k]
 return x
m=read(B/'JEV_JM2_B1_CONTENT_CHECK_20261116_01/per_card_supplement_matrix.json')['cards'];c=read(B/'JEV_JM2_A2_20261115_01/case_snapshot_candidate.json')['cards'];idx=read(B/'JEV_JM2_A2_20261115_01/private_audit_index.json')['cards'];spec=read(B/'JEV_JM2_A1_20261115_01/scenario_feature_spec.json');labels=collections.Counter();rows=[];branches=0;bindings=0
assert len(m)==len(c)==len(idx)==5
for i,(a,card,e) in enumerate(zip(m,c,idx)):
 assert a['card_index']==i and a['point_id']==e['point_id']
 assert a['tradeoff']['intervention']==card['intervention']
 assert a['tradeoff']['changed']=={k:v for k,v in card['attribute_directions'].items() if v!='EQUAL'}
 assert a['result_and_counterevidence']['observations']==card['observations']
 assert a['result_and_counterevidence']['continuation']==card['continuation']
 assert a['result_and_counterevidence']['evidence_grade']==card['evidence_grade']
 assert a['result_and_counterevidence']['repeat_conflict']==card['repeat_conflict']
 for binding in a['necessary_observable_conditions']['bindings']:
  if binding['status']=='REGISTERED_OBSERVABLE_A_B_ATTRIBUTE':
   for role,value in binding['current_values'].items():assert card['actions'][role]['attributes'][binding['condition']]==value
   bindings+=1
  if binding['status']=='REGISTERED_SCENARIO_FEATURE':
   assert binding['condition'] in spec['features'] and binding['value']==card['features'][binding['condition']];bindings+=1
 for obs,pair in zip(card['observations'],e['pairs']):
  comp=ref(pair['comparison']);assert obs['label']==comp['evaluation']['label_v2'];labels[obs['label']]+=1
  for role in ['A','B']:
   b=ref(pair['branches'][role]);assert all(b['metrics'][k]==v for k,v in obs[role].items());branches+=1
 assert not a['disposition']['generation_input_eligible'] and not a['disposition']['execution_eligible']
 rows.append(dict(point=e['point_id'],comparisons=len(card['observations']),height_deltas=[x['delta_B_minus_A']['actual_height_mm'] for x in card['observations']]))
assert branches==18 and dict(labels)=={'improved':4,'degraded':3,'neutral':2}
result=dict(version='jm2_b1_content_qa_saved_check_v1',status='PASS',cards=rows,labels=dict(labels),branches=branches,registered_bindings=bindings,scope='exact saved records; content necessity and trusted approval not mechanically established')
(O/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
