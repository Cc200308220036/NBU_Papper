"""Independent E1 reference: corner containment, independent selector interpreter.

No runtime, normalizer, compiler, generator or planner imports. Uses independent
legacy reference only on the legacy-rule projection, never on spatial rules.
"""
import copy
from ..common import canonical, validate, O4Error
from ..evaluator import reference_state as old_state, _accept
from ..evaluation_v2 import normalized_signature, compare_policies as old_compare, _selector

VERSION = 'o4_e1_independent_evaluator_v1'


def projection(ast):
    return {'schema_version': 'o4_policy_v1', 'rules': [r for r in ast['rules'] if r['type'] != 'inside_region']}


def signature(ast):
    validate('e1_policy', ast)
    old = normalized_signature(projection(ast))
    spatial = [{'target': _selector(r['target']), 'region_id': r['region_id'], 'priority': r['priority']}
               for r in ast['rules'] if r['type'] == 'inside_region']
    return {'legacy': old, 'spatial': sorted(spatial, key=canonical)}


def state(objects, ast, regions, eps=1e-6):
    out = old_state(objects, projection(ast))
    spatial = []
    for r in ast['rules']:
        if r['type'] != 'inside_region':
            continue
        region = next(g for g in regions if g['region_id'] == r['region_id'])
        matches = []
        for o in objects:
            if not _accept(o, r['target']):
                continue
            matches.append(o['object_id'])
            x, y = o['pose']['x_mm'], o['pose']['y_mm']
            w, h = o['oriented_size_mm'][:2]
            corners = [(x+sx*w/2, y+sy*h/2) for sx in (-1, 1) for sy in (-1, 1)]
            good = all(region['x_min_mm']-eps <= a <= region['x_max_mm']+eps
                       and region['y_min_mm']-eps <= b <= region['y_max_mm']+eps for a, b in corners)
            spatial.append({'rule_id': r['rule_id'], 'object_id': o['object_id'], 'region_id': r['region_id'], 'inside': good})
            if not good:
                out['violations'].append(f"region:{r['rule_id']}:{o['object_id']}")
        out['applicable_objects'][r['rule_id']] = sorted(matches)
    out['region_instances'] = spatial
    out['violations'].sort()
    return out


def audit(req, ast, candidates):
    rows = []
    before = state(req['placed_objects'], ast, req['regions'], req['spatial_eps_mm'])
    for c in candidates:
        obj = copy.deepcopy(next(o for o in req['available_objects'] if o['object_id'] == c['pick_item_id']))
        obj.update(pose=copy.deepcopy(c['pose']), oriented_size_mm=list(c['oriented_size_mm']))
        after = state([*req['placed_objects'], obj], ast, req['regions'], req['spatial_eps_mm'])
        rows.append({'candidate_id': c['candidate_id'], 'before': before, 'after': after,
                     'allowed': not after['violations'], 'new_violations': sorted(set(after['violations'])-set(before['violations']))})
    return {'allowed_ids': sorted(r['candidate_id'] for r in rows if r['allowed']), 'evaluations': rows}


def compare(actual, expected, objects):
    base = old_compare(projection(actual), projection(expected), objects)
    def targets(ast):
        return sorted([sorted(o['object_id'] for o in objects if _accept(o, r['target']))
                       for r in ast['rules'] if r['type'] == 'inside_region'])
    def selectors(ast):
        return sorted([canonical(_selector(r['target'])) for r in ast['rules'] if r['type'] == 'inside_region'])
    def grouped(ast):
        out={}
        for r in ast['rules']:
            if r['type']=='inside_region':out.setdefault(canonical(_selector(r['target'])),[]).append(r)
        return out
    a,b=grouped(actual),grouped(expected)
    scopes_equal={k:len(v) for k,v in a.items()}=={k:len(v) for k,v in b.items()}
    unique=scopes_equal and all(len(v)==1 for v in a.values())
    region_equal=all(a[k][0]['region_id']==b[k][0]['region_id'] for k in a) if unique else None
    priority=all(a[k][0]['priority']==b[k][0]['priority'] for k in a) if unique else None
    return {**base, 'evaluator_version': VERSION, 'raw_ast_equal': actual == expected,
            'semantic_equal': signature(actual) == signature(expected),
            'rule_count_equal':len(actual['rules'])==len(expected['rules']),
            'applicable_objects_equal': base['applicable_objects_equal'] and targets(actual) == targets(expected),
            'selector_structure_equal': base['selector_structure_equal'] and selectors(actual) == selectors(expected),
            'conditions_exceptions_equal':base['conditions_exceptions_equal'] and scopes_equal,
            'priority_equal':None if priority is None or base['priority_equal'] is None else priority and base['priority_equal'],
            'spatial_component_alignment':'UNIQUE' if unique else 'AMBIGUOUS' if scopes_equal else 'SCOPE_MISMATCH',
            'region_references_equal':region_equal}
