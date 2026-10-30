"""Frozen V2 policy evaluator. Hidden AST supplied only by evaluation callers."""
import json
import math
from pathlib import Path
from jsonschema import Draft202012Validator
from .attribute_metrics_v2 import transition, raw_metrics, face_contact, TOL_MM

EPS = 1e-6
SCHEMA = Path(__file__).resolve().parents[1]/'schemas/policy_v2.schema.json'


def validate_policy(policy):
    Draft202012Validator(json.loads(SCHEMA.read_text())).validate(policy)
    if [p['priority'] for p in policy['soft_priorities']] != list(range(1, len(policy['soft_priorities'])+1)):
        raise ValueError('priorities must be unique and consecutive')
    if len({p['metric'] for p in policy['soft_priorities']}) != len(policy['soft_priorities']):
        raise ValueError('duplicate soft metric')
    return policy


def matches(item, selector):
    return all(item.get(k) == v for k, v in selector.items())


def violations(placed, policy):
    instances, applicable = [], []
    for ri, rule in enumerate(policy['hard_constraints']):
        if rule['type'] == 'fragile_load_limit':
            targets = [p for p in placed if matches(p, rule['selector'])]
            applicable.append(bool(targets))
            for p in targets:
                if p['supported_load_kg'] > rule['threshold_kg']+EPS:
                    instances.append(f"r{ri}:load:{p['item_id']}")
        else:
            pairs = []
            for i, a in enumerate(placed):
                for b in placed[i+1:]:
                    if (matches(a, rule['left']) and matches(b, rule['right'])) or (matches(b, rule['left']) and matches(a, rule['right'])):
                        pairs.append((a, b))
            applicable.append(bool(pairs))
            for a, b in pairs:
                if face_contact(a, b):
                    instances.append(f"r{ri}:contact:{':'.join(sorted([a['item_id'], b['item_id']]))}")
    return sorted(set(instances)), applicable


def soft_quality(placed, policy, container):
    raw = raw_metrics(placed)
    scale = {'heavy_low': container['max_height_mm'],
             'heavy_center': math.hypot(container['length_mm']/2, container['width_mm']/2)}
    field = {'heavy_low': 'heavy_mass_weighted_z_mm', 'heavy_center': 'heavy_center_distance_mm'}
    return [None if raw[field[p['metric']]] is None else max(0., 1.-raw[field[p['metric']]]/scale[p['metric']])
            for p in policy['soft_priorities']]


def evaluate(case, candidate, policy, container):
    validate_policy(policy)
    before, after = transition(case, candidate)
    bv, ba = violations(before, policy)
    av, aa = violations(after, policy)
    applicable = any(aa)
    def load_excess(records):
        return {f"r{ri}:load:{p['item_id']}": max(0., p['supported_load_kg']-rule['threshold_kg'])
                for ri, rule in enumerate(policy['hard_constraints']) if rule['type']=='fragile_load_limit'
                for p in records if matches(p, rule['selector'])}
    before_excess, after_excess = load_excess(before), load_excess(after)
    worsened = [i for i in bv if i in after_excess and after_excess[i]>before_excess.get(i,0.)+EPS]
    return {'business_hard_applicable': applicable,
            'business_hard_satisfied': not av if applicable else None,
            'before_violation_instances': bv, 'after_violation_instances': av,
            'new_violation_instances': sorted(set(av)-set(bv)),
            'before_business_violation_count': len(bv), 'post_business_violation_count': len(av),
            'new_business_violation_count': len(set(av)-set(bv)),
            'worsened_existing_violation_instances': worsened,
            'worsened_existing_violation_count': len(worsened),
            'before_load_excess_by_instance_kg': before_excess, 'after_load_excess_by_instance_kg': after_excess,
            'hard_rule_applicability': aa, 'soft_quality': soft_quality(after, policy, container)}


def optimal_set(evaluations, epsilon=EPS):
    feasible = [i for i, e in enumerate(evaluations) if not e['after_violation_instances']]
    equivalent = list(feasible)
    stage_best = []
    n = len(evaluations[0]['soft_quality']) if evaluations else 0
    for priority in range(n):
        vals = [evaluations[i]['soft_quality'][priority] for i in equivalent]
        best = max((v for v in vals if v is not None), default=None)
        stage_best.append(best)
        if best is not None:
            equivalent = [i for i in equivalent if evaluations[i]['soft_quality'][priority] is not None and evaluations[i]['soft_quality'][priority] >= best-epsilon]
    return {'feasible_indices': feasible, 'equivalent_indices': equivalent, 'stage_best': stage_best,
            'soft_applicable': any(v is not None for e in evaluations for v in e['soft_quality'])}


def priority_regret(evaluation, optimum):
    """Later regret N/A unless selected candidate survives all earlier stages."""
    eligible = not evaluation['after_violation_instances']
    out = []
    for q, best in zip(evaluation['soft_quality'], optimum['stage_best']):
        value = max(0., best-q) if eligible and q is not None and best is not None else None
        out.append(value)
        if value is not None and value > EPS:
            eligible = False
    return out
