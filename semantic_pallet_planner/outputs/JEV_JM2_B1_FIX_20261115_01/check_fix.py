"""Focused B1 remediation checks. Only new-directory writes; no engine imports."""
import ast,copy,hashlib,importlib.metadata,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
BASE=ROOT/'semantic_pallet_planner/outputs';PARENT=BASE/'JEV_JM2_B1_LIMITED_20261115_01';QA=BASE/'JEV_JM2_B1_LIMITED_QA_20261115_01'
def read(p):return json.loads(Path(p).read_text())
def write(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p,pointer=''):return dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p),pointer=pointer)
PKG=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select'
write('import_review.json',dict(before_import=True,python=sys.version,executable=sys.executable,dependencies={n:importlib.metadata.version(n) for n in ['jsonschema']},imports=[dict(file=ref(PKG/n),imports=[ast.unparse(x) for x in ast.parse((PKG/n).read_text()).body if isinstance(x,(ast.Import,ast.ImportFrom))]) for n in ['packaging_experience_contract.py','packaging_t_projection.py','packaging_scenario_features.py','packaging_jev_sampling.py','packaging_versions.py']],side_effects='stdlib/pure helpers; no send or engine; harness writes own new directory only; no subprocess',install=False))
sys.path[:0]=[str(ROOT/'semantic_pallet_planner/src'),str(ROOT/'semantic_pallet_planner/tests/unit')]
import test_packaging_scenario_features as guards
from semantic_pallet_planner.jev_select import packaging_experience_contract as m

def seal(p):
 p=copy.deepcopy(p);p.pop('pack_digest',None);p['pack_digest']=m.digest(p);return p

def main():
 packs=read(PARENT/'real_negative_fact_packs.json')['packs'];fixture=read(PARENT/'synthetic_positive_contract.json');fp=fixture['fact_pack'];candidate=fixture['candidate'];rows=[]
 def gate(name,pack,code=None,issue='QA-JM2B1-01'):
  value=m.prerequisite_gate(pack,ROOT)
  assert value['status']=='NOT_READY' and value['qualified_generation_input'] is False and value['execution_eligible'] is False,(name,value)
  if code:assert code in value['reasons'],(name,value)
  rows.append(dict(name=name,issue=issue,result=value))
 for i,p in enumerate(packs):
  m.validate_pack(p,ROOT);gate('valid_real_archive_'+str(i),p,'REAL_ADMISSION_CLOSED_IN_LIMITED_B1','BASELINE')
 positive=m.review_expression(candidate,fp,ROOT);assert positive['status']=='STRUCTURE_VALID_CONTENT_PENDING' and not positive['qualified_generation_input'] and not positive['execution_eligible']
 rows.append(dict(name='unchanged_saved_synthetic_positive',issue='BASELINE',result=positive))
 # Existing valid references pointing to the wrong semantic type.
 for field,pointer,code in [('review_ref','/cards','INVALID_REVIEW_TYPE'),('review_source_ref','/review_basis','INVALID_REVIEW_SOURCE_TYPE')]:
  p=copy.deepcopy(packs[0]);p[field]['pointer']=pointer;gate(field+'_original_list_probe',seal(p),code)
 payload=dict(list=[],null=None,number=1,string='bad',boolean=True,empty={},review=m.checked_reference(ROOT,packs[0]['review_ref']),source=m.checked_reference(ROOT,packs[0]['review_source_ref']))
 write('typed_negative_inputs.json',payload)
 for target,code in [('review_ref','INVALID_REVIEW_TYPE'),('review_source_ref','INVALID_REVIEW_SOURCE_TYPE')]:
  for kind in ['list','null','number','string','boolean']:
   p=copy.deepcopy(packs[0]);p[target]=ref(OUT/'typed_negative_inputs.json','/'+kind);gate(target+'_'+kind,seal(p),code)
 for target,code in [('review_ref','INVALID_REVIEW_FIELDS'),('review_source_ref','INVALID_REVIEW_SOURCE_FIELDS')]:
  p=copy.deepcopy(packs[0]);p[target]=ref(OUT/'typed_negative_inputs.json','/empty');gate(target+'_missing_fields',seal(p),code)
 # Remove each common required semantic field independently, retaining valid SHA.
 for target,obj,keys,code in [('review_ref',payload['review'],['disposition','unknown_critical_conditions','trusted_content_approval'],'INVALID_REVIEW_FIELDS'),('review_source_ref',payload['source'],['actual_author','external_review_status','human_signature','independent_reviewer'],'INVALID_REVIEW_SOURCE_FIELDS')]:
  for key in keys:
   data=copy.deepcopy(obj);del data[key];name=target+'_missing_'+key;write(name+'.json',data)
   p=copy.deepcopy(packs[0]);p[target]=ref(OUT/(name+'.json'));gate(name,seal(p),code)
 nested=[('pack_null',None,'INVALID_PACK_TYPE'),('case_list',dict(packs[0],case=[]),'INVALID_CASE_TYPE'),('case_null',dict(packs[0],case=None),'INVALID_CASE_TYPE')]
 for value in [None,{},1,'bad']:
  p=copy.deepcopy(packs[0]);p['case']['observations']=value;nested.append(('observations_'+type(value).__name__,p,'INVALID_OBSERVATIONS_TYPE'))
 p=copy.deepcopy(packs[0]);p['case']['observations']=[None];nested.append(('row_null',p,'INVALID_OBSERVATION_TYPE'))
 p=copy.deepcopy(packs[0]);p['case']['observations'][0]['A']=[];nested.append(('outcome_list',p,'INVALID_OUTCOME_TYPE'))
 for name,p,code in nested:gate(name,p,code)
 p=copy.deepcopy(packs[0]);p['review_ref']=copy.deepcopy(packs[1]['review_ref']);p=seal(p)
 try:m.validate_pack(p,ROOT)
 except m.ContractError as ex:assert str(ex)=='REVIEW_CASE_MISMATCH'
 else:raise AssertionError('cross-card validate_pack accepted')
 gate('P01_with_P02_review',p,'REVIEW_CASE_MISMATCH','QA-JM2B1-02')
 # Same values in another saved source do not substitute for declared identity.
 write('wrong_source_copy.json',payload['source']);p=copy.deepcopy(packs[0]);p['review_source_ref']=ref(OUT/'wrong_source_copy.json');gate('equal_content_wrong_source_identity',seal(p),'REVIEW_SOURCE_MISMATCH','QA-JM2B1-02')
 for key in ['card_ref','content_assessment_source','card_index','point_id']:
  data=copy.deepcopy(payload['review']);del data[key];name='missing_binding_'+key;write(name+'.json',data)
  p=copy.deepcopy(packs[0]);p['review_ref']=ref(OUT/(name+'.json'));gate(name,seal(p),'INVALID_REVIEW_BINDING_FIELDS','QA-JM2B1-02')
 data=copy.deepcopy(payload['review']);data['content_assessment_source']=ref(OUT/'wrong_source_copy.json');write('wrong_declared_source.json',data)
 p=copy.deepcopy(packs[0]);p['review_ref']=ref(OUT/'wrong_declared_source.json');gate('declared_source_does_not_match_pack',seal(p),'REVIEW_SOURCE_MISMATCH','QA-JM2B1-02')
 # Synthetic links bind the existing named sections, without synthetic approval.
 p=copy.deepcopy(fp);p['review_source_ref']=packs[0]['review_source_ref'];gate('fixture_wrong_source',seal(p),'FIXTURE_REVIEW_BINDING_MISMATCH','QA-JM2B1-02')
 # Original expression paths preserved and mixed true/false distinction refused.
 for name,mut,expected,code in [
  ('Cxx',lambda c:c['proposal']['advice'].update(resource_tradeoff='Choose C02'),'REJECTED','IDENTIFIER_OR_RANK_SHORTCUT'),
  ('generic',lambda c:c['proposal']['advice'].update(resource_tradeoff='综合考虑'),'REJECTED','GENERIC_REMINDER_CONTROL_ONLY'),
  ('omitted_fact',lambda c:c['fact_claims'].pop(),'REJECTED','FACTS_OR_COSTS_OMITTED_OR_CHANGED'),
  ('insufficient',lambda c:c.update(decision='INSUFFICIENT_EVIDENCE',proposal=None,insufficient_reason='insufficient material'),'INSUFFICIENT_EVIDENCE',None),
  ('mixed_distinctions',lambda c:c['proposal']['decision_contrast']['distinguishing_attributes'].append('mass_kg'),'REJECTED','NO_OBSERVABLE_ACTION_DISTINCTION'),
  ('empty_distinctions',lambda c:c['proposal']['decision_contrast'].update(distinguishing_attributes=[]),'REJECTED',None)]:
  c=copy.deepcopy(candidate);mut(c);r=m.review_expression(c,fp,ROOT);assert r['status']==expected,(name,r)
  if code:assert code in r['errors'],(name,r)
  rows.append(dict(name=name,issue='QA-JM2B1-03' if 'distinctions' in name else 'BASELINE',result=r))
 p=copy.deepcopy(packs[0]);del p['case']['observations'][0]['A']['elapsed_s'];gate('missing_cost_preserved',seal(p),'MISSING_COST','BASELINE')
 assert not any(any(n==k or n.startswith(k+'.') for k in guards.BLOCKED) for n in sys.modules)
 write('focused_results.json',dict(version='jm2_b1_fix_results_v1',validation_revision=m.JM_E_VALIDATION_REVISION,cases=rows,unexpected_exceptions=[],actual_operations={k:0 for k in ['credentials_read','model_calls','orders','forks','candidate_reconstruction','prefix_replay','stability_solves','subagents']},all_privileges_false=True,real_qualified_cards=0))
 write('validation_contract.json',m.validation_contract())
 print('PASS_FOCUSED_REMEDIATION',len(rows),'CASES; REAL_ARCHIVES_VALID_5; FIXTURE_PENDING; ALL_PRIVILEGES_FALSE')
if __name__=='__main__':main()
