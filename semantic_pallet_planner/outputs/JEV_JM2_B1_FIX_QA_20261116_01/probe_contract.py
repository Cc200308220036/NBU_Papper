"""Read-only contract probes; in-memory mutations; writes only own QA result."""
import sys,json,copy,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
BASE=ROOT/'semantic_pallet_planner/outputs/JEV_JM2_B1_LIMITED_20261115_01'
sys.path[:0]=[str(ROOT/'semantic_pallet_planner/src'),str(ROOT/'semantic_pallet_planner/tests/unit')]
import test_packaging_scenario_features as guards
from semantic_pallet_planner.jev_select import packaging_experience_contract as m

def read(n):return json.loads((BASE/n).read_text())
def seal(p):
 p=copy.deepcopy(p);p.pop('pack_digest');p['pack_digest']=m.digest(p);return p
packs=read('real_negative_fact_packs.json')['packs'];fixture=read('synthetic_positive_contract.json')
assert len(packs)==5
positive=m.review_expression(fixture['candidate'],fixture['fact_pack'],ROOT)
assert positive['status']=='STRUCTURE_VALID_CONTENT_PENDING'
results=[]
for p in packs:
 g=m.prerequisite_gate(p,ROOT);assert g['status']=='NOT_READY' and not g['qualified_generation_input'];results.append(g)
baseline_checks=[]
for name,change,expected in [
 ('fixed_Cxx',lambda c:c['proposal']['advice'].update(resource_tradeoff='Choose C02'),'REJECTED'),
 ('generic_reminder',lambda c:c['proposal']['advice'].update(resource_tradeoff='综合考虑'),'REJECTED'),
 ('omitted_fact',lambda c:c['fact_claims'].pop(),'REJECTED'),
 ('explicit_insufficient',lambda c:c.update(decision='INSUFFICIENT_EVIDENCE',proposal=None,insufficient_reason='Insufficient evidence'),'INSUFFICIENT_EVIDENCE')]:
 c=copy.deepcopy(fixture['candidate']);change(c);actual=m.review_expression(c,fixture['fact_pack'],ROOT)
 assert actual['status']==expected
 baseline_checks.append(dict(name=name,result=actual))
probes=[]
for field,pointer in [('review_ref','/cards'),('review_source_ref','/review_basis')]:
 p=copy.deepcopy(packs[0]);p[field]['pointer']=pointer
 if field=='review_source_ref':
  q=BASE/'forged_approval_negative.json'
  p['review_ref']=dict(path=q.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(q.read_bytes()).hexdigest(),pointer='/review')
 p=seal(p)
 try:
  actual=m.prerequisite_gate(p,ROOT);probes.append(dict(name=field+'_list_reference',result=actual))
 except Exception as e:
  probes.append(dict(name=field+'_list_reference',exception=type(e).__name__,message=str(e)))
# Valid schema and SHA; point P01 pack to P02 review without modifying any source.
p=copy.deepcopy(packs[0]);p['review_ref']=copy.deepcopy(packs[1]['review_ref']);p=seal(p)
try:
 review,source=m.validate_pack(p,ROOT)
 probes.append(dict(name='cross_card_review_binding',validation='ACCEPTED',pack_point_index=0,review_card_index=review['card_index'],gate=m.prerequisite_gate(p,ROOT)))
except Exception as e:probes.append(dict(name='cross_card_review_binding',exception=type(e).__name__,message=str(e)))
c=copy.deepcopy(fixture['candidate']);c['proposal']['decision_contrast']['distinguishing_attributes'].append('mass_kg')
probes.append(dict(name='unchanged_extra_distinguishing_attribute',result=m.review_expression(c,fixture['fact_pack'],ROOT)))
assert probes[0]['result']['reasons']==['INVALID_REVIEW_TYPE']
assert probes[1]['result']['reasons']==['INVALID_REVIEW_SOURCE_TYPE']
assert probes[2]['exception']=='ContractError' and probes[2]['message']=='REVIEW_CASE_MISMATCH'
assert probes[3]['result']['status']=='REJECTED'
extra=[]
f=ROOT/'semantic_pallet_planner/outputs/JEV_JM2_B1_FIX_20261115_01/typed_negative_inputs.json'
for field,code in [('review_ref','INVALID_REVIEW_TYPE'),('review_source_ref','INVALID_REVIEW_SOURCE_TYPE')]:
 for kind in ['list','null','number','string','boolean']:
  p=copy.deepcopy(packs[0]);p[field]=dict(path=f.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(f.read_bytes()).hexdigest(),pointer='/'+kind)
  g=m.prerequisite_gate(seal(p),ROOT);assert g['status']=='NOT_READY' and code in g['reasons']
  extra.append(dict(field=field,kind=kind,result=g))
result=dict(version='jm2_b1_qa_probe_v1',python=sys.version,positive_fixture=positive,real_rejections=results,baseline_checks=baseline_checks,probes=probes,extra_type_checks=extra,scope='actual new contract functions; in-memory pack_digest reseal for mutation consistency only, original identities unchanged; no production generation/service/LP')
(OUT/'probe_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
for p in probes:print(json.dumps(p,ensure_ascii=False))
