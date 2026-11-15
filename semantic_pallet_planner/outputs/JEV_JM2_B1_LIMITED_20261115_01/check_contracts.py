"""B1 scoped offline checks, all writes in this new delivery directory."""
import ast,copy,hashlib,importlib.metadata,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
BASE=ROOT/'semantic_pallet_planner/outputs';A2=BASE/'JEV_JM2_A2_20261115_01';A3=BASE/'JEV_JM2_A3_20261115_01';QA=BASE/'JEV_JM2_A3_QA_20261115_01'
# Review imports before runtime import, and persist the review in this directory.
def write(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p,pointer=''):return dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p),pointer=pointer)
files=['packaging_experience_contract.py','packaging_t_projection.py','packaging_scenario_features.py','packaging_jev_sampling.py','packaging_versions.py']
PKG=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select'
write('import_side_effect_review.json',dict(before_runtime_import=True,files=[dict(file=ref(PKG/n),imports=[ast.unparse(x) for x in ast.parse((PKG/n).read_text()).body if isinstance(x,(ast.Import,ast.ImportFrom))]) for n in files],assessment='stdlib + pure A1/A2 helpers only; no old generation/transport/experiment imports; functions only write via this harness in own output',subprocess='NONE in verification process; separate finalizer uses read-only local Git commands',credential_reads='BLOCKED',python=sys.version,executable=sys.executable,dependencies={n:importlib.metadata.version(n) for n in ['jsonschema']},install=False))
sys.path[:0]=[str(ROOT/'semantic_pallet_planner/src'),str(ROOT/'semantic_pallet_planner/tests/unit')]
import test_packaging_scenario_features as guards
# Extend the existing side effect guard for the older generation routes.
forbidden=('semantic_pallet_planner.jev_select.packaging_contrast_generation','semantic_pallet_planner.jev_select.memory_generation','semantic_pallet_planner.jev_select.experiment')
class ExtraGuard(guards.NoDispatchImports):
 def find_spec(self,fullname,path=None,target=None):
  if any(fullname==p or fullname.startswith(p+'.') for p in forbidden):raise AssertionError('FORBIDDEN_IMPORT')
  return super().find_spec(fullname,path,target)
sys.meta_path.insert(0,ExtraGuard())
from semantic_pallet_planner.jev_select import packaging_experience_contract as m

def seal(pack):
 pack=copy.deepcopy(pack);pack.pop('pack_digest',None);pack['pack_digest']=m.digest(pack);return pack

def make_pack(case,origin,source,pointer,review_ref,review_source_ref,den,den_ref):
 pack=m.build_fact_pack(ROOT,case_ref=ref(source,pointer),review_ref=review_ref,review_source_ref=review_source_ref,denominator_ref=den_ref,origin=origin)
 assert pack['case']==case and pack['denominators']==den
 return pack

def main():
 parents=[]
 for parent in [QA,A3,A2]:
  man=read(parent/'delivery_manifest.json')
  for e in man['files']:
   p=ROOT/e['path']
   if p.stat().st_size!=e['bytes'] or sha(p)!=e['sha256']:
    assert e['path'] in ['semantic_pallet_planner/src/semantic_pallet_planner/jev_select/contracts.py','semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_versions.py']
    original=OUT/'entry_source_bytes'/p.name
    assert original.stat().st_size==e['bytes'] and sha(original)==e['sha256']
  parents.append(dict(manifest=ref(parent/'delivery_manifest.json'),files=len(man['files']),status='PASS_ARCHIVED_BYTES_WITH_EXPLICIT_NEW_REGISTRY_IDENTITY'))
 reviews=read(A3/'projection_sufficiency_review.json');review_source=read(A3/'review_source.json');cards=read(A2/'case_snapshot_candidate.json')['cards'];private=read(A2/'private_audit_index.json')['cards'];field=read(A2/'field_and_claim_evidence.json')
 # Freeze local copies of small per-card denominator projections, with explicit parents.
 dens=[]
 for c,e in zip(cards,private):
  labels={k:0 for k in ['improved','degraded','neutral','trade_off','invalid','not_run']}
  for row in c['observations']:labels[row['label']]+=1
  f=e['family'];dens.append(dict(labels=labels,registered_pairs=f['registered_pairs'],starts=f['covered_starts'],source_components=len(f['covered_source_components']),cross_start_support=f['cross_start_support'],independent_unseen_sources=0,coverage='PARTIAL'))
 write('input_denominators.json',dict(denominators=dens,parents=[ref(A2/'private_audit_index.json','/cards'),ref(A3/'inherited_boundaries.json')],interpretation='label counts describe outcomes only, not general mechanism support'))
 packs=[];real=[]
 for i,(c,e) in enumerate(zip(cards,private)):
  p=make_pack(c,'REAL_ARCHIVE_NEGATIVE',A2/'case_snapshot_candidate.json','/cards/'+str(i),ref(A3/'projection_sufficiency_review.json','/cards/'+str(i)),ref(A3/'review_source.json'),dens[i],ref(OUT/'input_denominators.json','/denominators/'+str(i)))
  r=m.prerequisite_gate(p,ROOT)
  assert r['status']=='NOT_READY' and not r['qualified_generation_input']
  assert {'ARCHIVE_ONLY','CRITICAL_CONDITION_UNKNOWN','PENDING_CONTENT_REVIEW','REAL_ADMISSION_CLOSED_IN_LIMITED_B1'}<=set(r['reasons'])
  packs.append(p);real.append(dict(point_id=e['point_id'],origin='REAL_ARCHIVE_NEGATIVE',gate=r,review_ref=p['review_ref']))
 write('real_negative_fact_packs.json',dict(version='jm2_b1_real_negative_packs_v1',scope='PRIVATE_AUDIT_ONLY_REJECTION_CASES_NOT_GENERATION_INPUT',packs=packs))
 write('real_card_rejections.json',dict(cases=real,qualified_cards=0))
 # A wholly synthetic case, never a real card relabelled as an approved example.
 h=guards.fixture();s=m.projection
 metric={k:0 for k in s.METRICS};metric.update(placed_items=2,placed_volume_mm3=4000,placed_volume_ratio=.1,placed_item_ratio=.5,placed_mass_kg=2,placed_mass_ratio=.2,fixed_container_utilization=.0005,actual_height_mm=20,envelope_utilization=.1,elapsed_s=1,requests=1,input_tokens=100,output_tokens=10)
 a=metric|dict(model_cost_usd='UNKNOWN',stable_complete=False,category='EMPTY_POOL');b=copy.deepcopy(a);b.update(placed_volume_mm3=5000,placed_volume_ratio=.125)
 obs=dict(A=a,B=b,label='improved',delta_B_minus_A={k:b[k]-a[k] for k in s.METRICS})
 case=s.project_case(h,'a0','a1',observations=[obs],continuation=dict(policy='jev_no_memory / memories=[]',identity='0'*64,stochastic_choices_fixed=False),evidence_grade='PROVISIONAL_CASE',repeat_conflict=False)
 den=dict(labels=dict(improved=1,degraded=0,neutral=0,trade_off=0,invalid=0,not_run=0),registered_pairs=1,starts=1,source_components=1,cross_start_support=0,independent_unseen_sources=0,coverage='SYNTHETIC_FIXTURE')
 fixture=dict(origin='SYNTHETIC_FIXTURE_NOT_RESEARCH_EVIDENCE',case=case,denominators=den,review=dict(disposition='SYNTHETIC_CONTRACT_TEST_ONLY',unknown_critical_conditions=[],trusted_content_approval='PENDING'),review_source=dict(actual_author='test harness',external_review_status='SYNTHETIC_NOT_REVIEWED',human_signature=None,independent_reviewer=None))
 write('synthetic_fixture_input.json',fixture)
 fp=make_pack(case,'SYNTHETIC_FIXTURE',OUT/'synthetic_fixture_input.json','/case',ref(OUT/'synthetic_fixture_input.json','/review'),ref(OUT/'synthetic_fixture_input.json','/review_source'),den,ref(OUT/'synthetic_fixture_input.json','/denominators'))
 fg=m.prerequisite_gate(fp,ROOT);assert fg['status']=='FIXTURE_CONTRACT_VALID' and not fg['qualified_generation_input']
 ids=[f['fact_id'] for f in fp['fact_claims']];basis=[next(f['fact_id'] for f in fp['fact_claims'] if f['case_pointer']==pointer) for pointer in ['/actions/B/attributes/x_over_length','/observations/0/B/placed_volume_mm3','/observations/0/B/elapsed_s']]
 p=dict(usage_scenario=dict(description='Synthetic same-box horizontal translation under observed nonempty structure.',preconditions=[dict(field='features.placed_count',op='GE',value=2),dict(field='actions.B.x_over_length',op='GT',value=0)],exclusions=[dict(field='actions.B.yaw_deg',op='EQ',value=90)]),decision_contrast=dict(intervention='SAME_BOX_TRANSLATION',distinguishing_attributes=['x_over_length']),advice=dict(status='CONDITIONAL_HYPOTHESIS',preferred_role='B',resource_tradeoff='Under these synthetic conditions compare the translated pose for loading volume while retaining its observed elapsed time and height costs.',failure_conditions='Exclude rotated interventions and changed support structure; no universal preference.',basis_refs=basis),observed_facts=ids,mechanism_hypothesis=dict(status='HYPOTHESIS',text='The pose may alter subsequent packing opportunities; synthetic hypothesis only.',basis_refs=basis),falsifiable_prediction=dict(text='In a separately registered synthetic comparison this preference may fail.',support_observation='A further controlled comparison has larger loaded volume with the same continuation.',refuting_observation='A matched comparison has lower loaded volume or unacceptable cost.',basis_refs=basis),evidence_grade=case['evidence_grade'],continuation_identity=case['continuation']['identity'],support_and_conflict=den,limitations=['SYNTHETIC_FIXTURE_ONLY','No trusted content approval or execution permission'],review=dict(type='PROGRAM_STRUCTURE_ONLY',status='PENDING',human_signature=None,independent_reviewer=None))
 candidate=dict(version=m.JM_E_GENERATION,origin='SYNTHETIC_FIXTURE',pack_digest=fp['pack_digest'],decision='PROPOSE',fact_claims=[{k:f[k] for k in ['fact_id','value_digest']} for f in fp['fact_claims']],proposal=p,insufficient_reason=None)
 result=m.review_expression(candidate,fp,ROOT);assert result['status']=='STRUCTURE_VALID_CONTENT_PENDING',result
 write('synthetic_positive_contract.json',dict(origin='SYNTHETIC_FIXTURE_ONLY',fact_pack=fp,candidate=candidate,gate=fg,result=result))
 cases=[]
 def check(name,pack=None,cand=None,expected=None,reason=None):
  r=m.prerequisite_gate(pack,ROOT) if pack is not None else m.review_expression(cand,fp,ROOT)
  assert r['status']==expected,(name,r)
  if reason:assert reason in r.get('reasons',r.get('errors',[])),(name,r)
  cases.append(dict(name=name,origin='CONSTRUCTED_FIXTURE_OR_MUTATED_NEGATIVE',result=r))
 bad=copy.deepcopy(packs[0]);bad['review_ref']['sha256']='f'*64;check('changed_reference_digest',pack=seal(bad),expected='NOT_READY',reason='EVIDENCE_IDENTITY_MISMATCH')
 bad=copy.deepcopy(packs[0]);del bad['review_source_ref'];check('missing_review_source',pack=seal(bad),expected='NOT_READY',reason='MISSING_SOURCE')
 bad=copy.deepcopy(packs[0]);del bad['case']['observations'][0]['A']['elapsed_s'];check('missing_cost',pack=seal(bad),expected='NOT_READY',reason='MISSING_COST')
 bad=copy.deepcopy(packs[0]);bad['fact_claims'][0]['value_digest']='f'*64;check('wrong_fact',pack=seal(bad),expected='NOT_READY',reason='FACT_VALUE_MISMATCH')
 bad=copy.deepcopy(packs[0]);bad['review_ref']['path']='semantic_pallet_planner/outputs/missing.json';check('missing_source_file',pack=seal(bad),expected='NOT_READY',reason='SOURCE_NOT_AVAILABLE')
 bad=copy.deepcopy(packs[0]);bad['self_approved']=True;check('self_signed_boolean',pack=seal(bad),expected='NOT_READY')
 for name,text,code in [('fixed_Cxx','Choose C02','IDENTIFIER_OR_RANK_SHORTCUT'),('historical_rank','Choose candidate 2','IDENTIFIER_OR_RANK_SHORTCUT'),('generic_reminder','综合考虑','GENERIC_REMINDER_CONTROL_ONLY')]:
  bad=copy.deepcopy(candidate);bad['proposal']['advice']['resource_tradeoff']=text;check(name,cand=bad,expected='REJECTED',reason=code)
 bad=copy.deepcopy(candidate);bad['proposal']['usage_scenario']['preconditions'][0]['field']='future.best_box';check('unobservable_predicate',cand=bad,expected='REJECTED')
 bad=copy.deepcopy(candidate);bad['proposal']['decision_contrast']['intervention']='CROSS_BOX_SELECTION';check('wrong_intervention',cand=bad,expected='REJECTED',reason='INTERVENTION_CHANGED')
 bad=copy.deepcopy(candidate);bad['proposal']['decision_contrast']['distinguishing_attributes']=['mass_kg'];check('unchanged_attribute_not_contrast',cand=bad,expected='REJECTED',reason='NO_OBSERVABLE_ACTION_DISTINCTION')
 bad=copy.deepcopy(candidate);bad['fact_claims'].pop();check('omitted_fact_or_cost',cand=bad,expected='REJECTED',reason='FACTS_OR_COSTS_OMITTED_OR_CHANGED')
 bad=copy.deepcopy(candidate);bad['proposal']['mechanism_hypothesis']['status']='PROVEN_CAUSE';check('causal_claim_as_fact',cand=bad,expected='REJECTED')
 bad=copy.deepcopy(candidate);bad['proposal']['support_and_conflict']['labels']['neutral']=1;check('invented_counterexample',cand=bad,expected='REJECTED',reason='EVIDENCE_SCOPE_CHANGED')
 bad=copy.deepcopy(candidate);bad['proposal']['review']['human_signature']='invented';check('fabricated_signature',cand=bad,expected='REJECTED')
 bad=copy.deepcopy(candidate);bad.update(decision='INSUFFICIENT_EVIDENCE',proposal=None,insufficient_reason='No sufficient observable explanatory material.');check('explicit_generation_decline',cand=bad,expected='INSUFFICIENT_EVIDENCE')
 # Even a newly saved false approval source cannot release the real gate.
 write('forged_approval_negative.json',dict(review=dict(disposition='APPROVED',unknown_critical_conditions=[],trusted_content_approval='APPROVED'),source=dict(external_review_status='APPROVED',trusted_independent_approval=True),origin='CONSTRUCTED_FORGERY_NEGATIVE_NOT_REVIEW'))
 bad=copy.deepcopy(packs[0]);bad['review_ref']=ref(OUT/'forged_approval_negative.json','/review');bad['review_source_ref']=ref(OUT/'forged_approval_negative.json','/source');check('new_digest_self_approval_does_not_release',pack=seal(bad),expected='NOT_READY',reason='REAL_ADMISSION_CLOSED_IN_LIMITED_B1')
 bad=copy.deepcopy(packs[0]);bad['origin']='SYNTHETIC_FIXTURE';check('real_card_cannot_be_relabelled_fixture',pack=seal(bad),expected='NOT_READY',reason='FIXTURE_ORIGIN_NOT_BOUND_TO_SOURCE')
 copied=m.checked_reference(ROOT,packs[0]['review_ref']);copied['disposition']='APPROVED'
 assert m.checked_reference(ROOT,packs[0]['review_ref'])['disposition']=='ARCHIVE_ONLY'
 cases.append(dict(name='reference_cache_cannot_be_mutated_by_caller',origin='CONSTRUCTED_CHECK',result=dict(status='PASS_IMMUTABLE_SOURCE_VIEW')))
 # Explicit central schema routes are available here; old schemas remain unchanged.
 from semantic_pallet_planner.jev_select.contracts import schema_validator
 for name,value in [('jm_e_fact_pack_v1',fp),('jm_e_generation_v1',candidate),('jm_e_gate_v1',fg)]:schema_validator(name).validate(value)
 assert not any(any(n==b or n.startswith(b+'.') for b in guards.BLOCKED+forbidden) for n in sys.modules)
 write('constructed_validation.json',dict(version='jm2_b1_constructed_validation_v1',cases=cases,positive_expression='STRUCTURE_VALID_CONTENT_PENDING_SYNTHETIC_ONLY',central_schema_routes='PASS',forbidden_imports_absent=True))
 write('prompt_contract.json',m.prompt_contract());write('prerequisite_rules.json',m.rules_contract())
 write('parent_checks.json',dict(parents=parents,A3_qualified_cards=reviews['summary']['approved_sufficient'],A3_M21_07=reviews['M21_07'],A3_review_source=ref(A3/'review_source.json'),A2_field_evidence=ref(A2/'field_and_claim_evidence.json'),read_materials=[ref(A3/'handoff.json'),ref(QA/'handoff.json'),ref(QA/'quality_review.json'),ref(QA/'next_stage_admission.json'),ref(QA/'static_checks.json'),ref(QA/'check_attempts.json')]))
 print('PASS_LIMITED_B1',len(real),'REAL_REJECTIONS;',len(cases),'CONSTRUCTED_CHECKS; SYNTHETIC_SHAPE_ONLY; QUALIFIED_REAL=0')
if __name__=='__main__':main()
