"""Independent E2 reference using projected vertices and ordered object pairs.

No compiler, normalizer, runtime, candidate generator or planner imports.
Only E1 rules are delegated to the frozen independent E1 reference.
"""
import copy
from decimal import Decimal
from collections import defaultdict
import json
from functools import lru_cache
from ...common import canonical,validate
from ...evaluator import _accept
from ...evaluation_v2 import _selector,_number
from ..reference import state as e1_state,signature as e1_signature,compare as e1_compare

VERSION='o4_e2_independent_evaluator_v1'


def projection(ast):
    return {'schema_version':'o4_e1_policy_v1','rules':[r for r in ast['rules'] if r['type']!='relative_position']}


def _canonical_relation(r):
    a,b=_selector(r['subject']),_selector(r['reference']);direction=r['relation']
    if direction in ('right_of','behind'):a,b=b,a
    return {'subject':a,'reference':b,'axis':'x' if direction in ('left_of','right_of') else 'y','min_gap_mm':_number(r['min_gap_mm']),'priority':_number(r['priority'])}


def signature(ast):
    validate('e2_policy',ast)
    return {'e1':e1_signature(projection(ast)),'relative':sorted([_canonical_relation(r) for r in ast['rules'] if r['type']=='relative_position'],key=canonical)}


def _compute_state(objects,ast,regions,eps=1e-6,pending_objects=(),end_of_stream=False):
    validate('e2_policy',ast)
    out=e1_state(objects,projection(ast),regions,eps)
    placed={o['object_id']:o for o in objects};observed=[*objects,*pending_objects]
    edges=[];waiting=[];statuses={};epsilon=Decimal(str(eps))
    for r in ast['rules']:
        if r['type']!='relative_position':continue
        left=[o for o in observed if _accept(o,r['subject'])];right=[o for o in observed if _accept(o,r['reference'])]
        out['applicable_objects'][r['rule_id']]={'subject':sorted(o['object_id'] for o in left),'reference':sorted(o['object_id'] for o in right)}
        evaluated=deferred_count=0
        for a in left:
            for b in right:
                ai,bi=a['object_id'],b['object_id']
                if ai==bi:continue
                if ai not in placed or bi not in placed:
                    deferred_count+=1;waiting.append({'rule_id':r['rule_id'],'subject_id':ai,'reference_id':bi,'status':'deferred'});continue
                axis=0 if r['relation'] in ('left_of','right_of') else 1;field=('x_mm','y_mm')[axis]
                av=[Decimal(str(a['pose'][field]))+sign*Decimal(str(a['oriented_size_mm'][axis]))/2 for sign in (-1,1)]
                bv=[Decimal(str(b['pose'][field]))+sign*Decimal(str(b['oriented_size_mm'][axis]))/2 for sign in (-1,1)]
                gap=Decimal(str(r['min_gap_mm']))
                if r['relation'] in ('left_of','front_of'):
                    valid=max(av)+gap<=min(bv)+epsilon;distance=min(bv)-max(av)
                else:
                    valid=min(av)>=max(bv)+gap-epsilon;distance=min(av)-max(bv)
                evaluated+=1
                edges.append({'rule_id':r['rule_id'],'subject_id':ai,'reference_id':bi,'relation':r['relation'],'min_gap_mm':r['min_gap_mm'],'clearance_mm':float(distance),'satisfied':valid})
                if not valid:out['violations'].append(f"relative:{r['rule_id']}:{ai}:{bi}")
        statuses[r['rule_id']]={'checked_pairs':evaluated,'deferred_pairs':deferred_count,'status':'deferred' if deferred_count or (not evaluated and not end_of_stream) else 'checked' if evaluated else 'not_applicable'}
    out.update(relation_instances=edges,deferred_relations=waiting,relation_status=statuses)
    out['violations'].sort();return out


@lru_cache(maxsize=1024)
def _cached_reference(serialized):
    return _compute_state(*json.loads(serialized))


def state(objects,ast,regions,eps=1e-6,pending_objects=(),end_of_stream=False):
    return copy.deepcopy(_cached_reference(canonical([objects,ast,regions,eps,list(pending_objects),end_of_stream])))


def audit(req,ast,candidates):
    before=state(req['placed_objects'],ast,req['regions'],req['spatial_eps_mm'],req['available_objects'],req['buffer_context']['end_of_stream']);rows=[]
    for c in candidates:
        item=copy.deepcopy(next(o for o in req['available_objects'] if o['object_id']==c['pick_item_id']))
        item.update(pose=copy.deepcopy(c['pose']),oriented_size_mm=list(c['oriented_size_mm']))
        pending=[o for o in req['available_objects'] if o['object_id']!=c['pick_item_id']]
        after=state([*req['placed_objects'],item],ast,req['regions'],req['spatial_eps_mm'],pending,req['buffer_context']['end_of_stream'])
        rows.append({'candidate_id':c['candidate_id'],'before':before,'after':after,'allowed':not after['violations'],'new_violations':sorted(set(after['violations'])-set(before['violations']))})
    return {'allowed_ids':sorted(r['candidate_id'] for r in rows if r['allowed']),'evaluations':rows}


def compare(actual,expected,objects):
    base=e1_compare(projection(actual),projection(expected),objects)
    def groups(ast):
        out=defaultdict(list)
        for r in ast['rules']:
            if r['type']=='relative_position':out[canonical(sorted([_selector(r['subject']),_selector(r['reference'])],key=canonical))].append(r)
        return out
    a,b=groups(actual),groups(expected);equal={k:len(v) for k,v in a.items()}=={k:len(v) for k,v in b.items()};unique=equal and all(len(v)==1 for v in a.values())
    def endpoints(ast):
        return sorted([sorted([sorted(o['object_id'] for o in objects if _accept(o,r[role])) for role in ('subject','reference')]) for r in ast['rules'] if r['type']=='relative_position'])
    def direction(r):
        v=_canonical_relation(r);return {k:v[k] for k in ('subject','reference','axis')}
    directions=all(direction(a[k][0])==direction(b[k][0]) for k in a) if unique and a else None
    gaps=all(_number(a[k][0]['min_gap_mm'])==_number(b[k][0]['min_gap_mm']) for k in a) if unique and a else None
    priorities=all(_number(a[k][0]['priority'])==_number(b[k][0]['priority']) for k in a) if unique else None
    def detail(ast):
        return [{'rule_id':r['rule_id'],'subject_selector':r['subject'],'reference_selector':r['reference'],
                 'subject_object_ids':sorted(o['object_id'] for o in objects if _accept(o,r['subject'])),
                 'reference_object_ids':sorted(o['object_id'] for o in objects if _accept(o,r['reference']))}
                for r in ast['rules'] if r['type']=='relative_position']
    return {**base,'evaluator_version':VERSION,'raw_ast_equal':actual==expected,'semantic_equal':signature(actual)==signature(expected),
            'rule_count_equal':len(actual['rules'])==len(expected['rules']),'selector_structure_equal':base['selector_structure_equal'] and equal,
            'applicable_objects_equal':base['applicable_objects_equal'] and endpoints(actual)==endpoints(expected),'conditions_exceptions_equal':base['conditions_exceptions_equal'] and equal,
            'priority_equal':None if priorities is None or base['priority_equal'] is None else priorities and base['priority_equal'],
            'relation_endpoint_selectors_equal':equal,'relation_endpoint_sets_equal':endpoints(actual)==endpoints(expected),
            'relation_direction_equal':directions,'relation_gap_equal':gaps,
            'raw_subject_selectors_equal':all(_selector(a[k][0]['subject'])==_selector(b[k][0]['subject']) for k in a) if unique and a else None,
            'raw_reference_selectors_equal':all(_selector(a[k][0]['reference'])==_selector(b[k][0]['reference']) for k in a) if unique and a else None,
            'actual_relation_endpoints':detail(actual),'reference_relation_endpoints':detail(expected),
            'relation_component_alignment':'UNIQUE' if unique else 'AMBIGUOUS' if equal else 'SCOPE_MISMATCH'}
