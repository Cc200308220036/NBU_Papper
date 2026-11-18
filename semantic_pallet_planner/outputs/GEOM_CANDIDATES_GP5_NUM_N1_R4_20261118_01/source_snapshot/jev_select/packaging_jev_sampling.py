"""JM1-B1 offline public sampling. No business-engine imports or dispatch hooks.

Decimal preserves native numeric lexemes; Fraction performs gaps/quantiles without
Decimal-context rounding. Outputs are diagnostics, never sendable fork plans.
"""
from __future__ import annotations

import argparse
import base64
import copy
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re

from .packaging_versions import JM_SAMPLING_VERSION

POLICY_SHA256 = '4eb0d822b1fec051cebadcb2a378487e6099565130093e4d16364e8038fb63fb'
SCHEMA = Path(__file__).with_name('schemas') / 'jm_sampling_public_v1.schema.json'
CLAIM_SCOPE = ('Observed saved-native exact-top-tie / relative-near-top decisions only; '
               'not all decisions, high-confidence errors, causal confidence or generalization.')


class SamplingError(ValueError):
    """Stable machine-readable refusal code; never includes raw response text."""


def require(ok, code):
    if not ok:
        raise SamplingError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode())


def _pairs(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result, 'DUPLICATE_JSON_KEY')
        result[k] = v
    return result


class NativeNumber(str):
    """JSON number token, distinct from quoted JSON strings and booleans."""


def strict_load(raw, *, native=False):
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_float=NativeNumber if native else float,
                          parse_int=NativeNumber if native else int,
                          parse_constant=lambda _: (_ for _ in ()).throw(SamplingError('NONFINITE_OR_OUT_OF_RANGE')))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SamplingError('INVALID_JSON') from exc


def _validate(value, spec):
    """Validate the exact JSON-Schema subset used by this independent protocol.

    All keywords in our schema are handled; unknown keywords fail closed.
    This avoids importing the dependency-heavy historical contracts registry.
    """
    supported = {'$schema','title','type','properties','required','additionalProperties',
                 'items','minItems','maxItems','minLength','pattern','minimum',
                 'exclusiveMinimum','enum','const','anyOf'}
    require(not set(spec)-supported, 'UNSUPPORTED_SCHEMA_KEYWORD')
    if 'anyOf' in spec:
        for branch in spec['anyOf']:
            try:
                _validate(value, branch)
                return
            except SamplingError:
                pass
        raise SamplingError('PUBLIC_SCHEMA')
    if 'const' in spec:
        require(type(value) is type(spec['const']) and value == spec['const'], 'PUBLIC_SCHEMA')
    if 'enum' in spec:
        require(any(type(value) is type(v) and value == v for v in spec['enum']), 'PUBLIC_SCHEMA')
    kind = spec.get('type')
    if kind:
        types = {'object':dict,'array':list,'string':str,'integer':int,'boolean':bool,'null':type(None)}
        require((type(value) in (int,float) and math.isfinite(value)) if kind=='number'
                else type(value) is types[kind], 'PUBLIC_SCHEMA')
    if kind == 'object':
        require(set(spec['required']) <= set(value), 'PUBLIC_SCHEMA')
        require(spec['additionalProperties'] is False and not set(value)-set(spec['properties']), 'PUBLIC_SCHEMA')
        for k,v in value.items():
            _validate(v,spec['properties'][k])
    if kind == 'array':
        require(len(value)>=spec.get('minItems',0) and len(value)<=spec.get('maxItems',math.inf), 'PUBLIC_SCHEMA')
        for v in value:
            _validate(v,spec['items'])
    if kind == 'string':
        require(len(value)>=spec.get('minLength',0), 'PUBLIC_SCHEMA')
        if 'pattern' in spec:
            require(re.fullmatch(spec['pattern'],value) is not None, 'PUBLIC_SCHEMA')
    if kind in ('number','integer'):
        require(value>=spec.get('minimum',-math.inf) and value>spec.get('exclusiveMinimum',-math.inf), 'PUBLIC_SCHEMA')


def exact_action(candidate):
    # Numeric canonicalization makes 1, 1.0 and negative zero the same geometry.
    def canonical(v):
        if isinstance(v,dict):
            return {k:canonical(x) for k,x in v.items()}
        if isinstance(v,list):
            return [canonical(x) for x in v]
        if type(v) in (int,float):
            d=Decimal(str(v))
            return '0' if d == 0 else (format(d,'f').rstrip('0').rstrip('.') if '.' in format(d,'f') else format(d,'f'))
        return v
    return canonical({k:candidate[k] for k in ('pick_item_id','pose','oriented_size_mm')})


def exact_digest(candidate):
    return digest(exact_action(candidate))


def validate_public(public):
    require(isinstance(public,dict) and public.get('version') == JM_SAMPLING_VERSION, 'UNKNOWN_PROTOCOL')
    e=public.get('probability_evidence')
    if isinstance(e,dict):
        require(e.get('protocol')=='jev_systemone_choice_native_v1','UNKNOWN_PROBABILITY_PROTOCOL')
    _validate(public, json.loads(SCHEMA.read_text()))
    pool=public['pool']; mapping=public['display_mapping']
    ids={c['candidate_id']:c for c in pool}
    require(len(ids)==len(pool) and len(mapping)==len(pool), 'INCOMPLETE_MAP')
    require(len({r['label'] for r in mapping})==len(mapping) and
            {r['candidate_id'] for r in mapping}==set(ids), 'INCOMPLETE_MAP')
    for c in pool:
        frozen=c['frozen_candidate']
        require(c['candidate_digest']==digest(frozen) and
                all(c[k]==frozen[k] for k in ('candidate_id','pick_item_id','pose','oriented_size_mm')),
                'FROZEN_CANDIDATE_CHANGED')
    for r in mapping:
        require(r['candidate_digest']==ids[r['candidate_id']]['candidate_digest'], 'INCOMPLETE_MAP')
    original=public['original']
    require(any(r['label']==original['label'] and r['candidate_id']==original['candidate_id'] for r in mapping), 'INCOMPLETE_MAP')
    require(original['exact_action_digest']==exact_digest(ids[original['candidate_id']]), 'ORIGINAL_ACTION_CHANGED')
    state=public['public_state']
    current=state['buffer']+state['placed_objects']
    require(len({x['item_id'] for x in current})==len(current), 'DUPLICATE_PUBLIC_ITEM')
    buffer={x['item_id']:x for x in state['buffer']}
    for c in pool:
        require(c['pick_item_id'] in buffer, 'ACTION_OUTSIDE_CURRENT_BUFFER')
        size=buffer[c['pick_item_id']]['size_mm']
        expected=size if c['pose']['yaw_deg']==0 else [size[1],size[0],size[2]]
        require(c['oriented_size_mm']==expected, 'ORIENTED_SIZE_MISMATCH')
    if public['probability_evidence']:
        require(public['evidence_scope']!='CONSTRUCTED_ONLY' or
                public['probability_evidence']['origin']=='CONSTRUCTED_ONLY', 'CONSTRUCTED_SCOPE_MISMATCH')
    return public


def project_public(saved_public, *, private_audit=None):
    """Copy a closed *already public* envelope; private audit is never inspected.

    Not a historical order/context reconstruction adapter. Unknown nested fields
    are rejected rather than copied; audit remains the caller's independent data.
    """
    validate_public(saved_public)
    return copy.deepcopy(saved_public)


def parse_probabilities(public):
    validate_public(public)
    evidence=public['probability_evidence']
    require(evidence is not None, 'MISSING_NATIVE_PROBABILITIES')
    require(evidence['protocol']=='jev_systemone_choice_native_v1', 'UNKNOWN_PROBABILITY_PROTOCOL')
    try:
        raw=base64.b64decode(evidence['raw_base64'],validate=True)
    except ValueError as exc:
        raise SamplingError('INVALID_RAW_ENCODING') from exc
    require(sha(raw)==evidence['raw_sha256'], 'RAW_IDENTITY_CHANGED')
    body=strict_load(raw,native=True)
    require(isinstance(body,dict) and set(body)<={'model','answers','usage'} and
            isinstance(body.get('model'),str), 'UNKNOWN_RESPONSE_PROTOCOL')
    answers=body.get('answers')
    require(isinstance(answers,dict) and set(answers)=={'next_action'}, 'UNKNOWN_RESPONSE_PROTOCOL')
    answer=answers['next_action']
    require(isinstance(answer,dict) and set(answer)=={'type','choice','probabilities','confidence'} and
            answer['type']=='choice', 'UNKNOWN_RESPONSE_PROTOCOL')
    if 'usage' in body:
        usage=body['usage']
        require(isinstance(usage,dict) and set(usage)=={'input_tokens','output_tokens'} and
                all(type(v) is NativeNumber and re.fullmatch(r'[0-9]+',v) for v in usage.values()),
                'UNKNOWN_RESPONSE_PROTOCOL')
    values=answer['probabilities']
    require(isinstance(values,dict), 'MISSING_NATIVE_PROBABILITIES')
    require(set(values)=={r['label'] for r in public['display_mapping']}, 'INCOMPLETE_MAP')
    require(answer['choice']==public['original']['label'], 'ORIGINAL_CHOICE_CHANGED')
    for v in [*values.values(),answer['confidence']]:
        require(type(v) is NativeNumber, 'NONFINITE_OR_OUT_OF_RANGE')
        d=Decimal(v)
        require(d.is_finite() and 0<=d<=1, 'NONFINITE_OR_OUT_OF_RANGE')
    return {'raw_sha256':sha(raw), 'bytes':len(raw), 'lexemes':{k:str(v) for k,v in values.items()},
            'values':{k:Fraction(Decimal(v)) for k,v in values.items()},
            'provider_internal_precision':'UNKNOWN','provider_tie_rule':'UNKNOWN'}


def _ratio(v):
    return {'numerator':v.numerator,'denominator':v.denominator}


def _groups(public, probabilities):
    by_id={c['candidate_id']:c for c in public['pool']}; groups={}
    for r in public['display_mapping']:
        c=by_id[r['candidate_id']]; key=exact_digest(c)
        member={'label':r['label'],'candidate_id':c['candidate_id'],
                'candidate_digest':c['candidate_digest'],'native_lexeme':probabilities['lexemes'][r['label']]}
        if key not in groups:
            groups[key]={'exact_action_digest':key,'action':exact_action(c),'members':[], 'score':Fraction(-1)}
        groups[key]['members'].append(member)
        groups[key]['score']=max(groups[key]['score'],probabilities['values'][r['label']])
    for group in groups.values():
        group['members'].sort(key=lambda m:(m['candidate_digest'],m['candidate_id'],m['label']))
    return groups


def inspect_decision(public):
    """All decisions, including rejected records, produce one denominator row."""
    row={'projection_digest':digest(public),'status':'REJECTED','reason':None,
         'probability_complete':False,'stage':None,'multi_candidate':False}
    try:
        validate_public(public)
        row.update(task_id=public['task_id'],source_group=public['source_group'],
                   decision_id=public['decision_id'],decision_ordinal=public['decision_ordinal'],
                   stage='NONEMPTY' if public['public_state']['placed_objects'] else 'OPENING',
                   multi_candidate=len(public['pool'])>1, candidate_count=len(public['pool']),
                   pool_ref=public['pool_ref'],prefix_ref=public['prefix_ref'],
                   pool_digest=digest(public['pool']),original=public['original'],
                   probability_evidence_identity=(None if public['probability_evidence'] is None else
                       {k:public['probability_evidence'][k] for k in ('protocol','origin','raw_sha256')}))
        p=parse_probabilities(public); groups=_groups(public,p)
        row.update(probability_complete=True,raw_sha256=p['raw_sha256'],native_lexemes=p['lexemes'],
                   exact_action_count=len(groups),duplicate_exact_actions=len(public['pool'])-len(groups),
                   groups=[{k:v for k,v in g.items() if k!='score'}|{'score':_ratio(g['score'])}
                           for _,g in sorted(groups.items())])
        require(len(groups)>1,'NO_ALTERNATIVE_CLASS')
        pmax=max(g['score'] for g in groups.values())
        require(pmax>0,'NONPOSITIVE_MAX')
        gaps={k:(pmax-g['score'])/pmax for k,g in groups.items()}
        positives=[g for g in gaps.values() if g>0]
        row.update(status='PARSED',reason=None,exact_top_tie=sum(g==0 for g in gaps.values())>1,
                   min_positive_gap=_ratio(min(positives)) if positives else None,
                   gaps={k:_ratio(v) for k,v in sorted(gaps.items())})
    except SamplingError as exc:
        row['reason']=str(exc)
    return row


def _fraction(r):
    return Fraction(r['numerator'],r['denominator'])


def sample(public_decisions, *, task_order):
    """Fixed-policy diagnostic computation, including constructed epsilon only.

    No B2 matrix or C1 frozen epsilon is issued. Task order is caller-supplied
    public order, not sorted by outcomes. All supplied decisions remain in rows.
    """
    require(len(task_order)==len(set(task_order))<=6, 'TASK_CAP_OR_DUPLICATE')
    rows=[inspect_decision(p) for p in public_decisions]
    require(all(r.get('task_id') in task_order for r in rows if r.get('task_id')), 'UNREGISTERED_TASK')
    keys=[(r.get('task_id'),r.get('decision_id')) for r in rows if r.get('task_id')]
    ordinals=[(r.get('task_id'),r.get('decision_ordinal')) for r in rows if r.get('task_id')]
    require(len(set(keys))==len(keys) and len(set(ordinals))==len(ordinals), 'DUPLICATE_DECISION')
    positives=sorted(_fraction(r['min_positive_gap']) for r in rows if r.get('min_positive_gap'))
    epsilon=min(positives[(len(positives)+3)//4-1],Fraction(1,10)) if positives else Fraction(0)
    for r in rows:
        r['selected']=False
        if r['status']!='PARSED':
            continue
        groups=r['groups']; gaps={k:_fraction(v) for k,v in r['gaps'].items()}
        layer={k for k,v in gaps.items() if v<=epsilon}
        original=r['original']['exact_action_digest']
        r['registered_layer']=sorted(layer)
        r['near_top']=any(0<gaps[k]<=epsilon for k in layer)
        r['stratum']='OBSERVED_EXACT_TOP_TIE' if r['exact_top_tie'] and gaps[original]==0 else 'RELATIVE_NEAR_TOP'
        original_item=next(g['action']['pick_item_id'] for g in groups if g['exact_action_digest']==original)
        same=[g for g in groups if g['exact_action_digest'] in layer and
              g['exact_action_digest']!=original and g['action']['pick_item_id']==original_item]
        cross=[g for g in groups if g['exact_action_digest'] in layer and g['action']['pick_item_id']!=original_item]
        r.update(same_box_available=bool(same),cross_box_available=bool(cross),
                 missing_classes=[k for k,v in [('SAME_BOX',same),('CROSS_BOX',cross)] if not v])
        if original not in layer:
            r.update(status='REJECTED',reason='ORIGINAL_OUTSIDE_LAYER');continue
        if not same and not cross:
            r.update(status='REJECTED',reason='NO_ALTERNATIVE_CLASS');continue
        def branch(g, kind):
            # Original keeps its saved candidate/label even if a duplicate scored higher.
            m=(next(m for m in g['members'] if m['candidate_id']==r['original']['candidate_id'])
               if kind=='ORIGINAL_ACTION_REFERENCE' else
               min(g['members'],key=lambda m:(-Fraction(Decimal(m['native_lexeme'])),
                                              m['candidate_digest'],m['candidate_id'],m['label'])))
            return {'kind':kind,**m,'exact_action_digest':g['exact_action_digest'],
                    'action':g['action'],'members':g['members'],'group_score':g['score'],
                    'relative_gap':r['gaps'][g['exact_action_digest']],
                    'layer':'EXACT_TOP' if gaps[g['exact_action_digest']]==0 else 'RELATIVE_NEAR_TOP'}
        reference=next(g for g in groups if g['exact_action_digest']==original)
        branches=[branch(reference,'ORIGINAL_ACTION_REFERENCE')]
        for candidates,kind in [(same,'SAME_BOX_DIFFERENT_POSE'),(cross,'CROSS_BOX_SELECTION')]:
            if candidates:
                g=min(candidates,key=lambda g:(-_fraction(g['score']),g['exact_action_digest']))
                b=branch(g,kind)
                if kind=='SAME_BOX_DIFFERENT_POSE':
                    p=reference['action']['pose'];q=g['action']['pose']
                    b['position_changed']=any(p[k]!=q[k] for k in ('x_mm','y_mm','z_base_mm'))
                    b['orientation_changed']=p['yaw_deg']!=q['yaw_deg']
                else:
                    public=next(p for p in public_decisions if digest(p)==r['projection_digest'])
                    attrs={x['item_id']:x for x in public['public_state']['buffer']}
                    b['public_attribute_contrast']={'original':attrs[original_item], 'alternative':attrs[g['action']['pick_item_id']]}
                branches.append(b)
        r.update(status='ELIGIBLE',reason='STAGE_PRIORITY_NOT_SELECTED',branches=branches)
    selected=[]; gaps=[]
    for task in task_order:
        for stage in ('OPENING','NONEMPTY'):
            eligible=[r for r in rows if r.get('task_id')==task and r['stage']==stage and r['status']=='ELIGIBLE']
            if not eligible:
                gaps.append({'task_id':task,'stage':stage,'reason':'NO_ELIGIBLE_POINT'});continue
            r=min(eligible,key=lambda r:(0 if r['same_box_available'] and r['cross_box_available'] else
                                        1 if r['same_box_available'] else 2,
                                        0 if r['stratum']=='OBSERVED_EXACT_TOP_TIE' else 1,
                                        r['decision_ordinal'],r['pool_digest'],r['original']['exact_action_digest']))
            r.update(selected=True,reason='SELECTED_BY_FROZEN_POLICY')
            selected.append({'task_id':task,'decision_id':r['decision_id'],'projection_digest':r['projection_digest'],
                             'stage':stage,'stratum':r['stratum'],'pool_ref':r['pool_ref'],
                             'prefix_ref':r['prefix_ref'],'raw_sha256':r['raw_sha256'],'branches':r['branches']})
    coverage=[]
    for task in task_order:
        subset=[r for r in rows if r.get('task_id')==task]
        coverage.append({'task_id':task,'all_decisions':len(subset),
            'multi_candidate':sum(r['multi_candidate'] for r in subset),
            'probability_complete':sum(r['probability_complete'] for r in subset),
            'probability_missing_or_invalid':sum(not r['probability_complete'] for r in subset),
            'exact_top_tie':sum(r.get('exact_top_tie',False) for r in subset),
            'near_top':sum(r.get('near_top',False) for r in subset),
            'same_box_eligible':sum(r.get('same_box_available',False) and r['status']=='ELIGIBLE' for r in subset),
            'cross_box_eligible':sum(r.get('cross_box_available',False) and r['status']=='ELIGIBLE' for r in subset),
            'stages':{stage:sum(r['stage']==stage for r in subset) for stage in ('OPENING','NONEMPTY')},
            'selected':sum(r['selected'] for r in subset),
            'reasons':{reason:sum(r['reason']==reason for r in subset) for reason in sorted({r['reason'] for r in subset})}})
    return {'version':'jev_jm_sampling_diagnostic_v1','execution_authorized':False,
            'scope':'CONSTRUCTED_ONLY' if all(p.get('evidence_scope')=='CONSTRUCTED_ONLY' for p in public_decisions)
                    else 'OFFLINE_SAVED_PUBLIC_DIAGNOSTIC_ONLY',
            'policy_sha256':POLICY_SHA256,'epsilon_status':'DIAGNOSTIC_NOT_FORMAL_FROZEN_VALUE',
            'diagnostic_epsilon':_ratio(epsilon),'positive_gap_denominator':len(positives),
            'real_epsilon':'NOT_MATERIALIZED_DEFER_C1','provider_internal_precision':'UNKNOWN',
            'provider_tie_rule':'UNKNOWN','claim_scope':CLAIM_SCOPE,'rows':rows,'selected_points':selected,
            'coverage_gaps':gaps,'per_task_coverage':coverage,'counts':{'all_supplied_decisions':len(rows),
                'multi_candidate_decisions':sum(r['multi_candidate'] for r in rows),
                'probability_complete':sum(r['probability_complete'] for r in rows),
                'probability_missing_or_invalid':sum(not r['probability_complete'] for r in rows),
                'selected_points':len(selected)},'stop':True}


def validate_saved_evidence(public, *, root):
    """Read-only binding check against saved public artifacts; no regeneration.

    pool_ref points to the entire original frozen public candidate array, prefix_ref to public_state.
    An audit-side adapter must separately bind these projections to source receipts.
    """
    validate_public(public); root=Path(root).resolve()
    for field,expected in [('pool_ref',[c['frozen_candidate'] for c in public['pool']]),('prefix_ref',public['public_state'])]:
        ref=public[field];path=(root/ref['path']).resolve()
        require(not Path(ref['path']).is_absolute() and path.is_relative_to(root),'EVIDENCE_PATH_ESCAPE')
        raw=path.read_bytes();require(sha(raw)==ref['sha256'],'SAVED_IDENTITY_CHANGED')
        value=strict_load(raw);pointer=ref['pointer']
        require(pointer=='' or pointer.startswith('/'),'INVALID_POINTER')
        try:
            for part in pointer.split('/')[1:]:
                part=part.replace('~1','/').replace('~0','~')
                value=value[int(part)] if isinstance(value,list) else value[part]
        except (KeyError,ValueError,IndexError,TypeError) as exc:
            raise SamplingError('INVALID_POINTER') from exc
        require(value==expected,'SAVED_PROJECTION_CHANGED')
    return {'version':'jev_jm_sampling_saved_check_v1','status':'PASS_SAVED_PUBLIC_ONLY',
            'projection_digest':digest(public),'dispatches':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',help='closed JSON {version, task_order, decisions}; never a task/order file')
    parser.add_argument('output',help='new diagnostic JSON path (exclusive creation)')
    args=parser.parse_args()
    data=strict_load(Path(args.input).read_bytes())
    require(set(data)=={'version','task_order','decisions'} and data['version']=='jev_jm_sampling_batch_v1','UNKNOWN_BATCH_PROTOCOL')
    result=sample(data['decisions'],task_order=data['task_order'])
    with Path(args.output).open('x') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')


if __name__=='__main__':
    main()
