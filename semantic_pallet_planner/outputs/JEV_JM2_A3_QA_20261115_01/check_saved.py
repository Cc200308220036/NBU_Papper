"""Independent stdlib saved-record check; writes only its own QA result."""
import json,hashlib,collections
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
BASE=ROOT/'semantic_pallet_planner/outputs'
A3=BASE/'JEV_JM2_A3_20261115_01'; A2=BASE/'JEV_JM2_A2_20261115_01'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def resolve(r):
 p=(ROOT/r['path']).resolve();assert p.is_relative_to(ROOT)
 assert sha(p)==r['sha256'];v=read(p)
 for k in r.get('pointer','').split('/')[1:]:
  k=k.replace('~1','/').replace('~0','~');v=v[int(k)] if isinstance(v,list) else v[k]
 return v
cards=read(A2/'case_snapshot_candidate.json')['cards']; index=read(A2/'private_audit_index.json')['cards']; review=read(A3/'projection_sufficiency_review.json')['cards']
assert len(cards)==len(index)==len(review)==5
labels=collections.Counter(); rows=[]; branches=0;fieldrefs=0
for i,(c,e,r) in enumerate(zip(cards,index,review)):
 assert r['card_index']==i and resolve(r['card_ref'])==c
 h=resolve(e['a1_input']);state=resolve(e['public_prefix']);pool=resolve(e['full_pool']);binding=resolve(e['role_binding_diagnostic'])
 assert state==h['state'] and [{k:x[k] for k in h['pool'][0]} for x in pool]==h['pool'] and len(pool)==c['features']['candidate_count']['value']
 for key,prefix in [('buffer','box_'),('placed_objects','placed_')]:
  expected=[]
  for j,b in enumerate(state[key]):
   b=dict(b);b.pop('item_id');b['box_role']=prefix+str(j+1);expected.append(b)
  assert expected==c['structure'][key]
 assert len(c['observations'])==len(e['pairs'])==len(r['pair_checks'])
 for obs,pair in zip(c['observations'],e['pairs']):
  comp=resolve(pair['comparison']);assert comp['evaluation']['label_v2']==obs['label'];labels[obs['label']]+=1
  assert comp['delta_direction']=='alternative_minus_reference' and comp['same_prefix_pool_task_follow']
  assert not comp['baseline_whole_trajectory_used_as_benefit_reference']
  for role in ['A','B']:
   b=resolve(pair['branches'][role]);ex=resolve(pair['executions'][role]);trajectory=resolve(pair['trajectories'][role]);branches+=1
   frozen=next(x for x in pool if x['candidate_id']==b['candidate_id'])
   assert b['frozen_candidate']==frozen
   assert b['exact_action']['pick_item_id']==frozen['pick_item_id']
   assert all(Decimal(str(v))==Decimal(str(frozen['pose'][k])) for k,v in b['exact_action']['pose'].items())
   assert list(map(Decimal,b['exact_action']['oriented_size_mm']))==list(map(lambda x:Decimal(str(x)),frozen['oriented_size_mm']))
   assert b['candidate_id']==binding['roles'][role]['exact_action']['candidate_id']
   for k in ['pose','oriented_size_mm']:assert c['actions'][role][k]==frozen[k]
   assert c['actions'][role]['box_role']==binding['roles'][role]['box_role']
   assert ex['config']['selector']=='jev_no_memory' and ex['config']['memory_mode']=='none'
   assert ex['config']['runtime_identity']['strategy_identity']==c['continuation']['identity']
   for k,v in obs[role].items():assert v==b['metrics'][k]
   assert len(trajectory['requests'])==obs[role]['requests']
  for k,v in obs['delta_B_minus_A'].items():assert v==obs['B'][k]-obs['A'][k]
 assert len(r['dimensions'])==6 and r['unknown_critical_conditions'] and not r['execution_eligible']
 assert r['disposition']=='ARCHIVE_ONLY' and r['trusted_content_approval']=='PENDING'
 assert not c['execution_eligible'] and c['cross_start_support']==0
 rows.append(dict(point=e['point_id'],pool=len(pool),comparisons=len(e['pairs']),disposition=r['disposition'],unknowns=r['unknown_critical_conditions'],height_deltas=[o['delta_B_minus_A']['actual_height_mm'] for o in c['observations']]))
for card in read(A2/'field_and_claim_evidence.json')['cards']:
 for row in card['fields']:
  for ref in row['sources']:resolve(ref);fieldrefs+=1
assert dict(labels)=={'improved':4,'degraded':3,'neutral':2} and branches==18
assert rows[0]['height_deltas'][0]<0<rows[0]['height_deltas'][1]
assert cards[3]['evidence_grade']=='PROVISIONAL_CASE' and len(cards[3]['observations'])==1
source=read(A3/'review_source.json');assert not source['trusted_independent_approval'] and source['independent_reviewer'] is None and source['human_signature'] is None
result=dict(version='jm2_a3_independent_saved_check_v1',status='PASS',cards=rows,branches=branches,labels=dict(labels),field_source_references=fieldrefs,scope='saved facts only; no signature recomputation, order, candidate reconstruction, LP or model',tolerance_used=False)
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('PASS independent saved facts:',len(rows),'cards;',branches,'branches;',fieldrefs,'field refs;',dict(labels))
