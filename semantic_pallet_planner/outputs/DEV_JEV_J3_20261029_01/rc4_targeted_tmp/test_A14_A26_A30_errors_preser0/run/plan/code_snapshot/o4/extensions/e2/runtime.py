"""Runtime all-pairs relative-position semantics; no private answers."""
from decimal import Decimal
import copy
import json
from functools import lru_cache
from ...common import canonical
from ...executor import transition
from ...normalize import matches
from ..runtime import evaluate_state as e1_state
from .protocol import validate_policy, validate_observation, validate_candidates


def e1_policy(ast):
    return {'schema_version':'o4_e1_policy_v1','rules':[r for r in ast['rules'] if r['type']!='relative_position']}


def _limits(obj):
    # JSON-decimal arithmetic avoids platform-dependent epsilon cancellation.
    x,y=(Decimal(str(obj['pose'][k])) for k in ('x_mm','y_mm'))
    l,w=(Decimal(str(v)) for v in obj['oriented_size_mm'][:2])
    return x-l/2,x+l/2,y-w/2,y+w/2


def _compute_state(objects, ast, regions, eps=1e-6, pending_objects=(), end_of_stream=False):
    validate_policy(ast)
    out=e1_state(objects,e1_policy(ast),regions,eps)
    observed=[*objects,*pending_objects];placed={o['object_id'] for o in objects}
    instances=[];deferred=[];statuses={};tolerance=Decimal(str(eps))
    for r in ast['rules']:
        if r['type']!='relative_position':continue
        subject=[o for o in observed if matches(o,r['subject'])]
        reference=[o for o in observed if matches(o,r['reference'])]
        out['applicable_objects'][r['rule_id']]={'subject':sorted(o['object_id'] for o in subject),'reference':sorted(o['object_id'] for o in reference)}
        checked=waiting=0;gap=Decimal(str(r['min_gap_mm']))
        for a in subject:
            for b in reference:
                ai,bi=a['object_id'],b['object_id']
                if ai==bi:continue
                if ai not in placed or bi not in placed:
                    deferred.append({'rule_id':r['rule_id'],'subject_id':ai,'reference_id':bi,'status':'deferred'});waiting+=1;continue
                aa,bb=_limits(a),_limits(b);relation=r['relation']
                if relation=='left_of':good=aa[1]+gap<=bb[0]+tolerance;clearance=bb[0]-aa[1]
                elif relation=='right_of':good=aa[0]>=bb[1]+gap-tolerance;clearance=aa[0]-bb[1]
                elif relation=='front_of':good=aa[3]+gap<=bb[2]+tolerance;clearance=bb[2]-aa[3]
                else:good=aa[2]>=bb[3]+gap-tolerance;clearance=aa[2]-bb[3]
                checked+=1
                instances.append({'rule_id':r['rule_id'],'subject_id':ai,'reference_id':bi,'relation':relation,'min_gap_mm':r['min_gap_mm'],'clearance_mm':float(clearance),'satisfied':good})
                if not good:out['violations'].append(f"relative:{r['rule_id']}:{ai}:{bi}")
        statuses[r['rule_id']]={'checked_pairs':checked,'deferred_pairs':waiting,'status':'deferred' if waiting or (not checked and not end_of_stream) else 'checked' if checked else 'not_applicable'}
    out.update(relation_instances=instances,deferred_relations=deferred,relation_status=statuses)
    out['violations'].sort();return out


@lru_cache(maxsize=1024)
def _cached_state(serialized):
    return _compute_state(*json.loads(serialized))


def evaluate_state(objects, ast, regions, eps=1e-6, pending_objects=(), end_of_stream=False):
    # Exact public-state memoization only, never a model-response cache. Copies
    # prevent search/client mutation from changing an independently reused node.
    return copy.deepcopy(_cached_state(canonical([objects,ast,regions,eps,list(pending_objects),end_of_stream])))


def evaluate_candidates(req, ast, candidates):
    validate_observation(req);validate_policy(ast,req);validate_candidates(req,candidates)
    args=(ast,req['regions'],req['spatial_eps_mm'])
    before=evaluate_state(req['placed_objects'],*args,pending_objects=req['available_objects'],end_of_stream=req['buffer_context']['end_of_stream'])
    rows=[]
    for c in candidates:
        pending=[o for o in req['available_objects'] if o['object_id']!=c['pick_item_id']]
        after=evaluate_state(transition(req,c),*args,pending_objects=pending,end_of_stream=req['buffer_context']['end_of_stream'])
        rows.append({'candidate_id':c['candidate_id'],'before':before,'after':after,'new_violations':sorted(set(after['violations'])-set(before['violations'])),'allowed':not after['violations']})
    return {'allowed_ids':sorted(r['candidate_id'] for r in rows if r['allowed']),'evaluations':rows}
