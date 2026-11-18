"""Runtime E1 business decisions; no reference answers or state mutation."""
from ..executor import evaluate_state as legacy_state, transition, bounds
from ..normalize import matches
from .protocol import old_policy, validate_policy, validate_observation, validate_candidates


def evaluate_state(objects, ast, regions, eps=1e-6):
    validate_policy(ast)
    out = legacy_state(objects, old_policy(ast))
    by_id = {r['region_id']: r for r in regions}
    details = []
    for rule in ast['rules']:
        if rule['type'] != 'inside_region':
            continue
        region = by_id[rule['region_id']]
        selected = [o for o in objects if matches(o, rule['target'])]
        out['applicable_objects'][rule['rule_id']] = sorted(o['object_id'] for o in selected)
        for o in selected:
            b = bounds(o)
            amounts = {'left': max(0., region['x_min_mm']-b[0]), 'right': max(0., b[1]-region['x_max_mm']),
                       'front': max(0., region['y_min_mm']-b[2]), 'back': max(0., b[3]-region['y_max_mm'])}
            bad = [side for side, invalid in (
                ('left',b[0] < region['x_min_mm']-eps), ('right',b[1] > region['x_max_mm']+eps),
                ('front',b[2] < region['y_min_mm']-eps), ('back',b[3] > region['y_max_mm']+eps)) if invalid]
            details.append({'rule_id': rule['rule_id'], 'object_id': o['object_id'],
                            'region_id': region['region_id'], 'outside_mm': amounts, 'violating_sides': bad})
            if bad:
                out['violations'].append(f"region:{rule['rule_id']}:{o['object_id']}")
    out['region_instances'] = details
    out['violations'].sort()
    return out


def evaluate_candidates(req, ast, candidates):
    validate_observation(req)
    validate_policy(ast, req)
    validate_candidates(req,candidates)
    before = evaluate_state(req['placed_objects'], ast, req['regions'], req['spatial_eps_mm'])
    rows = []
    for c in candidates:
        after = evaluate_state(transition(req, c), ast, req['regions'], req['spatial_eps_mm'])
        rows.append({'candidate_id': c['candidate_id'], 'before': before, 'after': after,
                     'new_violations': sorted(set(after['violations'])-set(before['violations'])),
                     'allowed': not after['violations']})
    return {'allowed_ids': sorted(r['candidate_id'] for r in rows if r['allowed']), 'evaluations': rows}
