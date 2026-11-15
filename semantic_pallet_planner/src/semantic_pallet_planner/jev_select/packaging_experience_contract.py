"""JM2-B1 limited offline fact/expression contracts and closed admission gate.

No transport, prompt sending, trusted-review issuance, memory lifecycle or engine.
Real material can only be rejected here. Synthetic contract validity is never an
admission permit. Free prose is not certified by these deterministic checks.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import re
from functools import lru_cache
from .packaging_jev_sampling import _validate,digest,SamplingError
from . import packaging_t_projection as projection
from .packaging_versions import (JM_E_FACT_PACK,JM_E_GENERATION,JM_E_GATE,
                                JM_E_PROMPT,JM_E_RULES,JM_E_SCHEMAS)

class ContractError(ValueError):pass

def require(ok,code):
    if not ok:raise ContractError(code)

def schema_validate(value):
    require(type(value) is dict and value.get('version') in JM_E_SCHEMAS,'UNKNOWN_E_CONTRACT')
    schema=json.loads((Path(__file__).with_name('schemas')/(JM_E_SCHEMAS[value['version']]+'.schema.json')).read_text())
    try:digest(value);_validate(value,schema)
    except (SamplingError,ValueError,TypeError) as e:raise ContractError('E_CONTRACT_SCHEMA') from e
    return value

def at(value,pointer):
    require(type(pointer) is str and (not pointer or pointer.startswith('/')),'INVALID_POINTER')
    for token in pointer.split('/')[1:]:
        token=token.replace('~1','/').replace('~0','~')
        value=value[int(token)] if isinstance(value,list) else value[token]
    return value

def leaves(value,p=''):
    if isinstance(value,dict):
        for k,v in value.items():yield from leaves(v,p+'/'+k.replace('~','~0').replace('/','~1'))
    elif isinstance(value,list):
        for i,v in enumerate(value):yield from leaves(v,p+'/'+str(i))
    else:yield p,value

@lru_cache(maxsize=16)
def _parsed_json(raw):
    return json.loads(raw)

def checked_reference(repo,ref):
    require(type(ref) is dict and set(ref)=={'path','sha256','pointer'},'MISSING_SOURCE')
    root=Path(repo).resolve();relative=Path(ref['path'])
    require(not relative.is_absolute() and relative.as_posix().startswith('semantic_pallet_planner/outputs/') and relative.suffix=='.json','SOURCE_OUTSIDE_SAVED_JSON')
    require(not any(word in relative.as_posix().lower() for word in ('credentials','api_key','api key','.aws','.env')),'CREDENTIAL_SOURCE_FORBIDDEN')
    p=(root/relative).resolve()
    require(p.is_relative_to(root/'semantic_pallet_planner/outputs'),'SOURCE_OUTSIDE_SAVED_JSON')
    try:raw=p.read_bytes()
    except OSError as e:raise ContractError('SOURCE_NOT_AVAILABLE') from e
    require(hashlib.sha256(raw).hexdigest()==ref['sha256'],'EVIDENCE_IDENTITY_MISMATCH')
    try:return copy.deepcopy(at(_parsed_json(raw),ref['pointer']))
    except (ValueError,KeyError,IndexError,TypeError) as e:raise ContractError('INVALID_SOURCE_POINTER') from e

def build_fact_pack(repo,*,case_ref,review_ref,review_source_ref,denominator_ref,origin):
    """Bind a saved projection to exact leaf evidence; this issues no permit."""
    case=copy.deepcopy(checked_reference(repo,case_ref))
    facts=[]
    for i,(p,v) in enumerate(leaves(case),1):
        source=dict(case_ref,pointer=case_ref['pointer']+p)
        facts.append(dict(fact_id=f'F{i:04d}',case_pointer=p,value_digest=digest(v),evidence=[source]))
    pack=dict(version=JM_E_FACT_PACK,origin=origin,case=case,fact_claims=facts,
              review_ref=copy.deepcopy(review_ref),review_source_ref=copy.deepcopy(review_source_ref),
              denominator_ref=copy.deepcopy(denominator_ref),denominators=copy.deepcopy(checked_reference(repo,denominator_ref)))
    pack['pack_digest']=digest(pack)
    validate_pack(pack,repo)
    return pack

def validate_pack(pack,repo):
    schema_validate(pack);require(pack['version']==JM_E_FACT_PACK,'WRONG_PACK_VERSION')
    require(pack['pack_digest']==digest({k:v for k,v in pack.items() if k!='pack_digest'}),'PACK_IDENTITY_MISMATCH')
    try:projection.validate(pack['case'])
    except ValueError as e:raise ContractError('INCONSISTENT_CASE') from e
    expected=dict(leaves(pack['case']));facts=pack['fact_claims']
    require(len({f['fact_id'] for f in facts})==len(facts),'DUPLICATE_FACT_ID')
    require(len({f['case_pointer'] for f in facts})==len(facts) and {f['case_pointer'] for f in facts}==set(expected),'INCOMPLETE_FACTS_OR_COSTS')
    for f in facts:
        value=expected[f['case_pointer']]
        require(digest(value)==f['value_digest'],'FACT_VALUE_MISMATCH')
        refs=[checked_reference(repo,r) for r in f['evidence']]
        require(type(refs[0]) is type(value) and refs[0]==value,'FACT_EVIDENCE_MISMATCH')
    require(checked_reference(repo,pack['denominator_ref'])==pack['denominators'],'DENOMINATOR_EVIDENCE_MISMATCH')
    counts={k:0 for k in pack['denominators']['labels']}
    for row in pack['case']['observations']:counts[row['label']]+=1
    require(counts==pack['denominators']['labels'] and sum(counts.values())==pack['denominators']['registered_pairs'],'DENOMINATOR_COUNT_MISMATCH')
    if pack['origin']=='SYNTHETIC_FIXTURE':
        root_ref=dict(facts[0]['evidence'][0],pointer='')
        source_document=checked_reference(repo,root_ref)
        require(source_document.get('origin')=='SYNTHETIC_FIXTURE_NOT_RESEARCH_EVIDENCE','FIXTURE_ORIGIN_NOT_BOUND_TO_SOURCE')
    review=checked_reference(repo,pack['review_ref']);source=checked_reference(repo,pack['review_source_ref'])
    return review,source

def prerequisite_gate(pack,repo):
    reasons=[];pd=None
    try:
        if isinstance(pack,dict):
            if any(k not in pack for k in ('review_ref','review_source_ref','denominator_ref')):reasons.append('MISSING_SOURCE')
            for row in pack.get('case',{}).get('observations',[]):
                for r in ('A','B'):
                    if any(k not in row.get(r,{}) for k in ('elapsed_s','requests','input_tokens','output_tokens','model_cost_usd')):reasons.append('MISSING_COST')
        review,source=validate_pack(pack,repo);pd=pack['pack_digest']
        if review.get('disposition')=='ARCHIVE_ONLY':reasons.append('ARCHIVE_ONLY')
        if review.get('unknown_critical_conditions'):reasons.append('CRITICAL_CONDITION_UNKNOWN')
        if review.get('trusted_content_approval')!='APPROVED' or source.get('external_review_status')!='APPROVED':reasons.append('PENDING_CONTENT_REVIEW')
        if pack['origin']=='SYNTHETIC_FIXTURE':
            # Test-only shape contract is sufficient; source is deliberately not approval.
            reasons=['SYNTHETIC_FIXTURE_ONLY_NOT_REAL_APPROVAL']
            status='FIXTURE_CONTRACT_VALID'
        else:
            reasons.append('REAL_ADMISSION_CLOSED_IN_LIMITED_B1')
            status='NOT_READY'
    except (ContractError,ValueError,KeyError,TypeError,IndexError) as e:
        reasons.append(str(e) if isinstance(e,ContractError) else 'INVALID_EVIDENCE_OR_SCHEMA');status='NOT_READY'
    return schema_validate(dict(version=JM_E_GATE,status=status,qualified_generation_input=False,
                                execution_eligible=False,reasons=sorted(set(reasons)),pack_digest=pd))

def rules_contract():
    return dict(version=JM_E_RULES,real_admission='CLOSED_IN_THIS_LIMITED_UNIT',
        qualification='No code path issues a real generation permit, candidate memory or execution identity.',
        prerequisite_failures=['ARCHIVE_ONLY','CRITICAL_CONDITION_UNKNOWN','PENDING_CONTENT_REVIEW','MISSING_SOURCE','MISSING_COST','FACT_EVIDENCE_MISMATCH'],
        review_layers=['PROGRAM_FACT_AUDIT','OBSERVABLE_SCOPE_AND_EXPRESSION_STRUCTURE','TRUSTED_CONTENT_REVIEW_PENDING'],
        trust='Caller booleans and changed local review status cannot release this closed gate.',
        unknown_cost='Preserve UNKNOWN explicitly; never invent 0. UNKNOWN cost is disclosed, not hidden.',
        fixture='SYNTHETIC_FIXTURE validity is a contract test, never genuine content approval.',
        lifecycle='B2_NOT_IMPLEMENTED; no FACT_CASE→CANDIDATE_MEMORY→EXECUTION_ELIGIBLE upgrades')

def prompt_contract():
    return dict(version=JM_E_PROMPT,mode='OFFLINE_TEXT_CONTRACT_NOT_API_REQUEST',
        instruction=('Use only provided fact IDs and exact value digests. Separate observed facts, HYPOTHESIS, observable preconditions, exclusions, falsifiable support/refutation, results/costs and source/conflict denominators. '
        'Describe a concrete same-box pose/yaw or cross-box resource tradeoff under registered public predicates; state failure conditions. '
        'Never invent numbers, independent reviewers, unobserved causes, future boxes, PCT explanations, current absolute action answers, Cxx or rank shortcuts. '
        'Do not claim single-attribute causation when several attributes changed. Preserve all negative/neutral/conflicting evidence and UNKNOWN costs. '
        'Return INSUFFICIENT_EVIDENCE when material is inadequate. General reminders belong in a control or rejection, not a qualified rule. '
        'Structural validity is not trusted content approval; all free prose remains PENDING. No retries, repair or sends are implemented.'),
        fact_version=JM_E_FACT_PACK,generation_version=JM_E_GENERATION,rules_version=JM_E_RULES,
        real_qualified_inputs=0,model_calls_authorized=0)

def review_expression(candidate,pack,repo):
    """Check binding/structure and obvious shortcuts. Never approve free content."""
    gate=prerequisite_gate(pack,repo)
    result=dict(version='jev_jm_e_expression_check_v1',status='REJECTED',errors=[],
                content_review='PENDING',qualified_generation_input=False,execution_eligible=False)
    if gate['status']!='FIXTURE_CONTRACT_VALID':result['errors']=['PREREQUISITE_NOT_READY'];return result
    try:
        schema_validate(candidate);require(candidate['version']==JM_E_GENERATION,'WRONG_GENERATION_VERSION')
        require(candidate['pack_digest']==pack['pack_digest'],'GENERATION_PACK_MISMATCH')
        expected=[{k:f[k] for k in ('fact_id','value_digest')} for f in pack['fact_claims']]
        require(candidate['fact_claims']==expected,'FACTS_OR_COSTS_OMITTED_OR_CHANGED')
        if candidate['decision']=='INSUFFICIENT_EVIDENCE':
            require(candidate['proposal'] is None and bool(candidate['insufficient_reason']),'INVALID_INSUFFICIENT_FORM')
            result.update(status='INSUFFICIENT_EVIDENCE');return result
        require(candidate['proposal'] is not None and candidate['insufficient_reason'] is None,'INVALID_PROPOSE_FORM')
        p=candidate['proposal'];case=pack['case'];ids={f['fact_id'] for f in pack['fact_claims']}
        require(p['support_and_conflict']==pack['denominators'] and p['evidence_grade']==case['evidence_grade'] and p['continuation_identity']==case['continuation']['identity'],'EVIDENCE_SCOPE_CHANGED')
        require(p['observed_facts']==[f['fact_id'] for f in pack['fact_claims']],'RESULTS_OR_COSTS_OMITTED')
        require(p['decision_contrast']['intervention']==case['intervention'],'INTERVENTION_CHANGED')
        changed=[k for k,v in case['attribute_directions'].items() if v!='EQUAL']
        require(bool(set(p['decision_contrast']['distinguishing_attributes']) & set(changed)),'NO_OBSERVABLE_ACTION_DISTINCTION')
        refs=[]
        for node in [p['advice'],p['mechanism_hypothesis'],p['falsifiable_prediction']]:refs+=node['basis_refs']
        require(set(refs)<=ids,'UNKNOWN_FACT_REFERENCE')
        for pred in p['usage_scenario']['preconditions']+p['usage_scenario']['exclusions']:
            field=pred['field'].split('.')
            if field[0]=='features':
                require(case['features'][field[1]]['status']=='VALUE','UNOBSERVABLE_PREDICATE')
                value=case['features'][field[1]]['value']
            else:value=case['actions'][field[1]]['attributes'][field[2]]
            require(type(value) is type(pred['value']) or type(value) in (int,float) and type(pred['value']) in (int,float),'PREDICATE_TYPE_MISMATCH')
            target=pred['value'];op=pred['op']
            holds={'LT':lambda:value<target,'LE':lambda:value<=target,'EQ':lambda:value==target,'GE':lambda:value>=target,'GT':lambda:value>target}[op]()
            require(holds if pred in p['usage_scenario']['preconditions'] else not holds,'CONDITIONS_DO_NOT_DESCRIBE_FIXTURE')
        texts=[v for _,v in leaves(p) if isinstance(v,str)]
        text=' '.join(texts)
        require(not re.search(r'(?i)\bC\d{1,3}\b|\b(?:rank|candidate|option)\s*#?\s*\d+|第[一二三四五六七八九十0-9]+[名号个]|历史序号',text),'IDENTIFIER_OR_RANK_SHORTCUT')
        require(not any(x in text.lower() for x in ['综合考虑','consider everything','balance all factors']),'GENERIC_REMINDER_CONTROL_ONLY')
        result['status']='STRUCTURE_VALID_CONTENT_PENDING'
    except (ValueError,KeyError,TypeError) as e:result['errors']=[str(e) if isinstance(e,ContractError) else 'INVALID_GENERATION_SCHEMA']
    return result
