"""JN3-B contrast facts, restricted generated claims, independent review and E memory.

The LLM selects and composes a bounded claim graph. Numeric facts are references,
not regenerated prose. This first grammar deliberately cannot certify free prose.
"""
from __future__ import annotations
import copy
from datetime import datetime,timezone
from pathlib import Path
from .contracts import digest,canonical,validate_schema,Snapshot
from .ledger import read
from . import packaging_experience as trajectory
from .packaging_experience import require, sealed, verify_seal, sha, validate_evidence

VERSION='jev_packaging_contrast_v8'
METHOD='jev_with_contrast_experience'
RULE=copy.deepcopy(trajectory.RULE)
GRAMMAR={
 'version':'packaging_contrast_claim_grammar_v1',
 'directions':{
  'COMPARE_LOADING_AND_HEIGHT_TRADEOFF':'Hypothesis: in a similar currently observable setting, compare alternative box-and-position choices for potential loading opportunities while retaining the height cost; this historical result does not identify the best current action.',
  'COMPARE_STACKABILITY_AND_CAPACITY':'Hypothesis: compare observed size, mass, stackability and usable top-load capacity together when considering box-and-position alternatives; the causal contribution of any one attribute has not been established.'},
 'effects':{'MAY_CHANGE_FUTURE_LOADING':'HYPOTHESIS: different observed attribute and geometry tradeoffs may change later loading under a fixed continuation. This mechanism is unverified.',
            'UNRESOLVED_MECHANISM':'HYPOTHESIS: mechanism unresolved; independent review remains pending.'},
 'counterexamples':'No relevant counterexample was observed in the declared exact-observation/intervention-family group; this is not evidence of universal validity.',
 'relevance':'exact public observable_conditions digest and same-box-versus-cross-box intervention family; no source/id/outcome similarity used to decide membership',
 'review':'independent deterministic claim-graph rules; unsupported/free prose cannot be approved; no human or generator self-review claimed',
 'semantic_rule_version':'packaging_contrast_semantic_review_v1',
 'fact_rule_version':'packaging_contrast_fact_audit_v1',
 'limits':trajectory.LIMITATIONS+['restricted claim grammar; no free-form causal explanation certified','relevance is exact observed condition and intervention family; unrelated neutral evidence is not counted as support or refutation']}

class EMemoryView(trajectory.MemoryView):pass
class ESnapshot(Snapshot):pass


def family(o):
    return 'same_box' if o['reference_action']['item_attributes']==o['alternative_action']['item_attributes'] else 'cross_box'


def build_fact_pack(case,repo,parent):
    root=Path(repo);parent=Path(parent);cid=case['provenance']['comparison_id']
    original=case['private_original'];obs=original['observable_conditions'];fragment=case['public_fragment']
    rows=[]
    for f in sorted((parent/'comparisons_v2').glob('*.json')):
        r=read(f);verify_seal(r,'record_digest')
        related=digest({k:v for k,v in r['observable_conditions'].items() if k not in ('reference_action','alternative_action')})==digest({k:v for k,v in obs.items() if k not in ('reference_action','alternative_action')}) and family(r['observable_conditions'])==family(obs)
        rows.append({'comparison_id':r['comparison_id'],'related':related,'label':r['evaluation']['label_v2'],
                     'membership_reason':'EXACT_OBSERVATION_AND_FAMILY' if related else 'DIFFERENT_OBSERVATION_OR_INTERVENTION_FAMILY',
                     'evidence':trajectory.evidence_reference(root,f.relative_to(root),'/evaluation')})
    counts={'support':sum(r['related'] and r['label']=='improved' for r in rows),
            'refutation':sum(r['related'] and r['label'] in ('degraded','trade_off') for r in rows),
            'neutral':sum(r['related'] and r['label']=='neutral' for r in rows),
            'invalid':sum(r['related'] and r['label']=='invalid' for r in rows),
            'unrelated_background':sum(not r['related'] for r in rows)}
    def compare(a):return {'box':a['box'],'size_over_container':a['size_over_container'],'on_floor':a['historical_center_over_container'][2]==0}
    vals={'F001':{'role':'OBSERVABLE_CONDITION','value':fragment['condition']},
          'F002':{'role':'OBSERVABLE_ATTRIBUTE_GEOMETRY_CONTRAST','value':{'historical_box_alpha':compare(fragment['historical_interventions']['original']),
                    'historical_box_beta':compare(fragment['historical_interventions']['alternative']),
                    'relationship':fragment['historical_interventions']['relationship'],'geometry_scope':'historical on-floor interventions; no coordinates are current actions'}},
          'F003':{'role':'OBSERVED_RESULT_AND_COST','value':fragment['historical_result']},
          'F004':{'role':'EVIDENCE_COUNTS','value':counts},
          'F005':{'role':'SCOPE_AND_LIMITATIONS','value':GRAMMAR['limits']}}
    refs=case['evidence']
    for fid,f in vals.items():
        f['fact_id']=fid;f['value_digest']=digest(f['value'])
        if fid=='F001':selected={k:v for k,v in refs.items() if '/observable_conditions/' in k and '/reference_action/' not in k and '/alternative_action/' not in k}
        elif fid=='F002':selected={k:v for k,v in refs.items() if '/reference_action/' in k or '/alternative_action/' in k}
        elif fid=='F003':selected={k:v for k,v in refs.items() if '/observable_conditions/' not in k}
        elif fid=='F004':selected={str(i):r['evidence'] for i,r in enumerate(rows)}
        else:selected={'limitations':trajectory.evidence_reference(root,(parent/'handoff.json').relative_to(root),'/limitations'),
                       'evaluation':trajectory.evidence_reference(root,(parent/'comparisons_v2'/f'{cid}.json').relative_to(root),'/evaluation')}
        f['evidence']=list(selected.values())
        f['derivation']='whitelist projection / exact relation arithmetic / frozen scope; raw values remain in source leaf evidence'
    return sealed({'version':'packaging_contrast_fact_pack_v1','facts':list(vals.values()),'provenance':case['provenance'],
          'case_digest':case['case_digest'],'retrieval_query':case['retrieval_query'],'fixture_only':case['fixture_only'],
          'background':rows,'relevance_rule':GRAMMAR['relevance'],'grammar_digest':digest(GRAMMAR)},'pack_digest')


def validate_fact_pack(pack,repo=None):
    validate_schema('packaging_contrast_fact_pack_v1',pack);verify_seal(pack,'pack_digest')
    require(pack['grammar_digest']==digest(GRAMMAR) and pack['relevance_rule']==GRAMMAR['relevance'],'contrast_fact_rules_changed')
    require([f['fact_id'] for f in pack['facts']]==['F001','F002','F003','F004','F005'],'contrast_fact_set_changed')
    for f in pack['facts']:
        require(f['value_digest']==digest(f['value']) and bool(f['evidence']),'contrast_fact_changed')
        if repo is not None:
            for ref in f['evidence']:validate_evidence(repo,ref)
    counts=fact_values(pack)['F004']
    expected={'support':sum(r['related'] and r['label']=='improved' for r in pack['background']),
              'refutation':sum(r['related'] and r['label'] in ('degraded','trade_off') for r in pack['background']),
              'neutral':sum(r['related'] and r['label']=='neutral' for r in pack['background']),
              'invalid':sum(r['related'] and r['label']=='invalid' for r in pack['background']),
              'unrelated_background':sum(not r['related'] for r in pack['background'])}
    require(counts==expected,'contrast_counts_changed')
    return pack


def fact_values(pack):return {f['fact_id']:f['value'] for f in pack['facts']}


def proposed_example(pack):
    """Shape example, also used only as an explicitly constructed fixture in tests."""
    return {'version':'packaging_contrast_generation_v1','decision':'PROPOSE',
      'fact_claims':[{'fact_id':f['fact_id'],'value_digest':f['value_digest']} for f in pack['facts']],
      'condition_refs':['F001','F002'],
      'advice':[{'type':'HYPOTHESIS','direction':'COMPARE_LOADING_AND_HEIGHT_TRADEOFF','basis_refs':['F001','F002','F003']}],
      'expected_effect':{'type':'HYPOTHESIS','code':'MAY_CHANGE_FUTURE_LOADING','basis_refs':['F003']},
      'counterexamples':{'status':'NO_RELEVANT_COUNTEREXAMPLE_OBSERVED','counts_ref':'F004','scope':'ONLY_DECLARED_RELEVANCE_GROUP'},
      'limitations_ref':'F005','insufficient_reason':None}


def generation_body(pack):
    validate_fact_pack(pack)
    from .contracts import schema_validator
    schema=schema_validator('packaging_contrast_generation_v1').schema
    prompt=('Produce one conditional contrast experience as strict JSON using only the supplied facts and claim grammar. '
      'Choose PROPOSE only if a cautious conditional direction is supported, otherwise INSUFFICIENT. '
      'Copy fact ids and their value_digest exactly, including the complete result/cost and limitations claims. '
      'All advice and expected mechanisms are HYPOTHESIS, never observed causation or a universally best action. '
      'Choose one or two allowed directions and appropriate basis_refs. Conditions must use F001 and F002. '
      'Do not write free prose, numeric guesses, identifiers, ranking advice, coordinates or stability explanations. '
      'The schema example illustrates format only, not a mandatory positive answer. There is no repair or retry.')
    public={'facts':[{k:f[k] for k in ('fact_id','role','value','value_digest')} for f in pack['facts']],
            'claim_grammar':GRAMMAR,'output_schema':schema,'format_example':proposed_example(pack),
            'insufficient_format':{'decision':'INSUFFICIENT','advice':[],'expected_effect':None,'insufficient_reason':'INSUFFICIENT_EVIDENCE'}}
    return {'model':'deepseek-v4-pro','messages':[{'role':'system','content':prompt},{'role':'user','content':canonical(public)}],
            'thinking':{'type':'disabled'},'temperature':0,'max_tokens':2048,'stream':False,'response_format':{'type':'json_object'}}


def fact_audit(candidate,pack):
    validate_fact_pack(pack);errors=[]
    try:validate_schema('packaging_contrast_generation_v1',candidate)
    except ValueError:
        return sealed({'version':GRAMMAR['fact_rule_version'],'candidate_digest':digest(candidate),'pack_digest':pack['pack_digest'],
           'status':'REJECTED','checks':{},'errors':['INVALID_GENERATION_SCHEMA'],'per_claim':[]},'audit_digest')
    claims=candidate.get('fact_claims',[]) if isinstance(candidate,dict) else []
    expected=[{'fact_id':f['fact_id'],'value_digest':f['value_digest']} for f in pack['facts']]
    checks={'all_claims_and_costs_exact':sorted(claims,key=lambda c:c.get('fact_id',''))==expected,
            'condition_refs_complete':candidate.get('condition_refs')==['F001','F002'] if isinstance(candidate,dict) else False,
            'limitations_retained':candidate.get('limitations_ref')=='F005' if isinstance(candidate,dict) else False}
    errors += [k for k,v in checks.items() if not v]
    return sealed({'version':GRAMMAR['fact_rule_version'],'candidate_digest':digest(candidate),'pack_digest':pack['pack_digest'],
       'status':'APPROVED' if not errors else 'REJECTED','checks':checks,'errors':errors,
       'per_claim':[{'claim':c,'evidence':[f['evidence'] for f in pack['facts'] if f['fact_id']==c.get('fact_id')]} for c in claims]},'audit_digest')


def semantic_review(candidate,pack,audit):
    """A separate deterministic reviewer; it never trusts generator approval fields."""
    require(audit==fact_audit(candidate,pack),'contrast_fact_audit_changed')
    checks={};pending=[]
    if audit['status']!='APPROVED':status='REJECTED';checks={'facts_approved':False}
    elif candidate['decision']=='INSUFFICIENT':status='REJECTED';checks={'generator_declined':True}
    else:
        vals=fact_values(pack);d=vals['F003']['delta'];counts=vals['F004'];contrast=vals['F002']
        checks={'observable_conditions':candidate['condition_refs']==['F001','F002'],
                'conditional_hypotheses_only':all(a['type']=='HYPOTHESIS' for a in candidate['advice']) and candidate['expected_effect']['type']=='HYPOTHESIS',
                'complete_scope_and_cost':candidate['limitations_ref']=='F005' and d['actual_height_mm']>0,
                'no_identifier_or_rank_or_coordinate_advice':True, # closed codes; no free textual field exists
                'counterexample_scope':candidate['counterexamples']=={'status':'NO_RELEVANT_COUNTEREXAMPLE_OBSERVED','counts_ref':'F004','scope':'ONLY_DECLARED_RELEVANCE_GROUP'} and counts['refutation']==0,
                'positive_evidence_only_in_declared_scope':counts['support']>=1 and d['placed_volume_ratio']>0}
        statements=[]
        for a in candidate['advice']:
            linked=set(a['basis_refs'])=={'F001','F002','F003'}
            if a['direction']=='COMPARE_LOADING_AND_HEIGHT_TRADEOFF':supported=d['placed_volume_ratio']>0 and d['actual_height_mm']>0
            else:supported=contrast['historical_box_alpha']['box']!=contrast['historical_box_beta']['box']
            statements.append(linked and supported)
        checks['each_advice_grounded']=bool(statements) and all(statements)
        checks['effect_grounded']=candidate['expected_effect']['basis_refs']==['F003']
        if candidate['expected_effect']['code']=='UNRESOLVED_MECHANISM':pending.append('mechanism_not_certifiable_by_frozen_grammar')
        status='REJECTED' if not all(checks.values()) else 'PENDING_REVIEW' if pending else 'APPROVED'
    return sealed({'version':GRAMMAR['semantic_rule_version'],'reviewer':'independent deterministic claim graph; no human approval or generator self-evaluation',
        'candidate_digest':digest(candidate),'fact_audit_digest':audit['audit_digest'],'rule_digest':digest(GRAMMAR),
        'status':status,'checks':checks,'pending_reasons':pending,'unsupported_free_prose_policy':'PENDING_REVIEW; never activate'},'review_digest')


def render(candidate,pack,audit,review):
    require(audit['status']=='APPROVED' and review['status']=='APPROVED','contrast_unapproved_render')
    v=fact_values(pack)
    return {'kind':'E','notice':'Conditional historical contrast experience; not a current action or established causal rule.',
        'observable_conditions':v['F001'],'historical_attribute_geometry_contrast':v['F002'],
        'advice':[{'type':'HYPOTHESIS','direction':a['direction'],'text':GRAMMAR['directions'][a['direction']]} for a in candidate['advice']],
        'expected_effect':{'type':'HYPOTHESIS','text':GRAMMAR['effects'][candidate['expected_effect']['code']]},
        'historical_result':v['F003'],'evidence_counts':v['F004'],'counterexamples':GRAMMAR['counterexamples'],
        'evaluation_rule':'jev_branch_comparison_rule_v2','fixed_followup':'local_geometry_test_double','limitations':v['F005']}


def make_card(candidate,pack,attempt):
    audit=fact_audit(candidate,pack);review=semantic_review(candidate,pack,audit)
    require(review['status']=='APPROVED','contrast_card_not_approved')
    fragment=render(candidate,pack,audit,review)
    return sealed({'version':'packaging_contrast_card_v1','kind':'E','fixture_only':pack['fixture_only'] or attempt['origin']!='deepseek',
       'review_status':'APPROVED','candidate':candidate,'fact_pack':pack,'fact_audit':audit,'semantic_review':review,
       'generation':attempt,'public_fragment':fragment,'public_digest':digest(fragment),'retrieval_query':pack['retrieval_query'],
       'provenance':pack['provenance']},'case_digest')


def freeze_snapshot(cards,*,frozen_at=None):
    for card in cards:validate_card(card)
    s=sealed({'version':'packaging_contrast_snapshot_v1','mode':'E','cards':cards,'review_status':'APPROVED',
      'source_groups':sorted({c['provenance']['source_group'] for c in cards}),
      'retrieval_rule':RULE,'grammar':GRAMMAR,'render_version':'packaging_contrast_render_v1',
      'frozen_at':frozen_at or datetime.now(timezone.utc).isoformat()},'snapshot_digest')
    validate_snapshot(s);return ESnapshot.from_dict(s)


def validate_card(card):
    validate_schema('packaging_contrast_card_v1',card);verify_seal(card,'case_digest')
    require(card['review_status']=='APPROVED' and card['kind']=='E','contrast_unapproved_card')
    pack=validate_fact_pack(card['fact_pack']);candidate=card['candidate']
    a=fact_audit(candidate,pack);r=semantic_review(candidate,pack,a)
    require(a==card['fact_audit'] and r==card['semantic_review'] and r['status']=='APPROVED','contrast_review_changed')
    require(card['public_fragment']==render(candidate,pack,a,r) and card['public_digest']==digest(card['public_fragment']),'contrast_render_changed')
    require(card['provenance']==pack['provenance'] and card['retrieval_query']==pack['retrieval_query'],'contrast_source_changed')
    require(card['generation']['origin'] in ('fixture','deepseek') and card['fixture_only']==(pack['fixture_only'] or card['generation']['origin']!='deepseek'),'contrast_fixture_identity_changed')
    require(card['generation']['candidate_digest']==digest(candidate) and card['generation']['pack_digest']==pack['pack_digest'],'contrast_generation_binding_changed')
    validate_schema('packaging_contrast_public_v1',card['public_fragment']);return card


def validate_snapshot(s,expected=None):
    if isinstance(s,Snapshot):s=s.data
    validate_schema('packaging_contrast_snapshot_v1',s);verify_seal(s,'snapshot_digest')
    require(s['mode']=='E' and s['review_status']=='APPROVED' and s['grammar']==GRAMMAR and s['retrieval_rule']==RULE,'contrast_snapshot_contract_changed')
    require(expected is None or expected==s['snapshot_digest'],'contrast_snapshot_changed')
    for c in s['cards']:validate_card(c)
    require(s['source_groups']==sorted({c['provenance']['source_group'] for c in s['cards']}),'contrast_groups_changed')
    return s


def empty_view(snapshot_digest,query_digest=None):
    v=trajectory.empty_view(snapshot_digest,query_digest).data;v.update(version='packaging_contrast_view_v1',mode='E')
    return EMemoryView.from_dict(sealed({k:x for k,x in v.items() if k!='view_digest'},'view_digest'))


def validate_view(view,expected=None):
    require(isinstance(view,EMemoryView),'contrast_explicit_E_view_required')
    v=view.data;validate_schema('packaging_contrast_view_v1',v);verify_seal(v,'view_digest')
    require(v['mode']=='E' and (expected is None or v['snapshot_digest']==expected),'contrast_view_snapshot_changed')
    for entry in v['entries']:validate_schema('packaging_contrast_public_v1',entry)
    text=canonical(v['entries']);require(len(text)==v['injected_chars'] and len(text.encode())==v['injected_utf8_bytes'],'contrast_length_changed')
    require(len(v['entries'])<=RULE['max_entries'] and len(text)<=RULE['max_chars'] and len(text.encode())<=RULE['max_utf8_bytes'],'contrast_budget_exceeded')
    return v


def retrieve(query,snapshot,*,excluded_source_groups=(),excluded_fork_digests=(),rule=None):
    s=validate_snapshot(snapshot);trajectory.validate_query(query)
    rule=RULE if rule is None else rule;require(rule==RULE,'contrast_retrieval_rule_changed')
    return trajectory._retrieve_validated(query,{'cases':s['cards'],'snapshot_digest':s['snapshot_digest']},rule,
       excluded_source_groups,excluded_fork_digests,view_class=EMemoryView,view_version='packaging_contrast_view_v1',mode='E',view_validator=validate_view)
