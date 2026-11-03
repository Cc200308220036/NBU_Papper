"""E0/E2 closed public contract, bindings, and rule-family validation."""
import copy
import math
from functools import lru_cache
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from ....o4.common import O4Error, canonical, digest, validate, SCHEMAS, read
from ....o4.normalize import validate_policy as validate_legacy, validate_selector
from ....o4.buffer.buffer_state import observation as legacy_observation, ordered, invariant

CAPABILITY = 'o4_e2_v1'
POLICY = 'o4_e2_policy_v1'
STATE_KEYS = ('container', 'placed_objects', 'available_objects', 'regions',
              'buffer_context', 'capability_version', 'coordinate_convention',
              'placement_convention', 'rendering_version', 'spatial_eps_mm', 'sampling_grid_mm')
BINDINGS = ('request_id', 'state_hash', 'observation_digest', 'instruction_digest')


def fail(code, path, reason):
    raise O4Error(code, f'{path}: {reason}')


@lru_cache(maxsize=3)
def validator(name):
    return Draft202012Validator(read(SCHEMAS/f'o4_e2_{name}.schema.json'))


def check_schema(name, value, code='invalid_ast'):
    try:
        canonical(value)
    except (TypeError,ValueError) as exc:
        fail(code, '$', 'finite JSON values required')
    error=best_match(validator(name).iter_errors(value))
    if error is not None:
        detail={'path':'/'+ '/'.join(str(x) for x in error.absolute_path), 'reason':error.message[:240]}
        for key in ('enum','const','type','maxItems','required'):
            if key in error.schema:detail[key]=error.schema[key]
        raise O4Error(code, canonical(detail))
    return value


def old_policy(ast):
    return {'schema_version': 'o4_policy_v1', 'rules': copy.deepcopy([
        r for r in ast['rules'] if r['type'] not in ('inside_region','relative_position')])}


def validate_policy(ast, req=None):
    check_schema('policy', ast)
    known = None if req is None else {o['object_id'] for k in ('placed_objects', 'available_objects') for o in req[k]}
    ids = [r['rule_id'] for r in ast['rules']]
    if len(ids) != len(set(ids)):
        fail('invalid_ast', '$.rules', 'duplicate rule_id')
    lookup = {r['rule_id']: r for r in ast['rules']}
    for i, r in enumerate(ast['rules']):
        for key in ('target', 'left', 'right', 'subject', 'reference'):
            if key in r:
                try:
                    validate_selector(r[key], known)
                except O4Error as exc:
                    fail('invalid_ast', f'$.rules[{i}].{key}', str(exc))
        for j in r['overrides']:
            if j not in lookup or lookup[j]['type'] in ('inside_region','relative_position'):
                fail('invalid_ast', f'$.rules[{i}].overrides', 'load-family references only')
        if r['type'] == 'inside_region' and req is not None:
            if r['region_id'] not in {x['region_id'] for x in req['regions']}:
                fail('invalid_ast', f'$.rules[{i}].region_id', 'unknown region_id; use a public region')
    validate_legacy(old_policy(ast), req)
    return ast


def rebind(req):
    """Producer-side construction only; incoming responses are never rebound."""
    out = copy.deepcopy(req)
    try:
        canonical(out)
    except (TypeError,ValueError):
        fail('invalid_observation','$','finite JSON values required')
    out['state_hash'] = digest({k: out[k] for k in STATE_KEYS})
    out['instruction_digest'] = digest(out['instruction_text'])
    out['observation_digest'] = digest({k: v for k, v in out.items() if k not in ('request_id', 'observation_digest')})
    return validate_observation(out)


def validate_observation(req):
    check_schema('observation', req, 'invalid_observation')
    canonical(req)
    objects = req['placed_objects'] + req['available_objects']
    ids = [o['object_id'] for o in objects]
    if len(ids) != len(set(ids)):
        fail('invalid_observation', '$', 'duplicate object_id')
    for o in req['placed_objects']:
        dims = [o['dimensions_mm'][k] for k in ('length', 'width', 'height')]
        if o['pose']['yaw_deg'] == 90:
            dims[0], dims[1] = dims[1], dims[0]
        if o['oriented_size_mm'] != dims:
            fail('invalid_observation', '$.placed_objects', 'yaw/dimensions mismatch')
    c = req['container']
    regions = req['regions']
    if len({r['region_id'] for r in regions}) != len(regions):
        fail('invalid_observation', '$.regions', 'duplicate region_id')
    for i, r in enumerate(regions):
        if not (-c['length_mm']/2 <= r['x_min_mm'] < r['x_max_mm'] <= c['length_mm']/2
                and -c['width_mm']/2 <= r['y_min_mm'] < r['y_max_mm'] <= c['width_mm']/2):
            fail('invalid_observation', f'$.regions[{i}]', 'positive rectangle inside pallet required')
    b = req['buffer_context']; pending = b['pending']
    if (len(pending) > b['capacity'] or {x['object_id'] for x in pending} != {o['object_id'] for o in req['available_objects']}
            or len({x['object_id'] for x in pending}) != len(pending)
            or len({x['slot'] for x in pending}) != len(pending)
            or len({x['arrival_index'] for x in pending}) != len(pending)
            or any(x['slot'] >= b['capacity'] for x in pending)):
        fail('invalid_observation', '$.buffer_context', 'pending identity/capacity/slot mismatch')
    expected = digest({k: req[k] for k in STATE_KEYS})
    obs = digest({k: v for k, v in req.items() if k not in ('request_id', 'observation_digest')})
    if req['state_hash'] != expected or req['instruction_digest'] != digest(req['instruction_text']) or req['observation_digest'] != obs:
        fail('invalid_binding', '$', 'state/instruction/observation digest mismatch')
    return req


def observation(state, text, regions, images=()):
    invariant(state)
    req = legacy_observation(state, text)
    req.update(schema_version='o4_e2_request_v1', capability_version=CAPABILITY,
               coordinate_convention='bottom_center_x_right_y_back_z_up_v1',
               placement_convention='upright_label_pos_z_v1', rendering_version='o4_e2_top_label_render_v1',
               spatial_eps_mm=1e-6, sampling_grid_mm=[0,50,100], regions=copy.deepcopy(regions), images=copy.deepcopy(list(images)),
               buffer_context={'capacity': state['buffer_capacity'], 'event_index': state['event_index'],
                               'end_of_stream': state['end_of_stream'], 'pending': [
                                   {'object_id': p['item']['item_id'], 'slot': p['slot'], 'arrival_index': p['arrival_index']}
                                   for p in ordered(state)]})
    return rebind(req)


def response_for(req, ast):
    validate_observation(req)
    return validate_response({'schema_version': 'o4_e2_response_v1',
                              **{k: req[k] for k in BINDINGS}, 'policy_ast': copy.deepcopy(ast)}, req)


def validate_candidates(req, candidates):
    """Reject tilted/forged pose structures before any simulated transition."""
    if not isinstance(candidates,list) or len(candidates)>48:
        fail('invalid_candidate','$.candidates','at most 48 joint candidates')
    ids=set();counts={};known={o['object_id'] for o in req['available_objects']}
    for i,c in enumerate(candidates):
        path=f'$.candidates[{i}]'
        if not isinstance(c,dict) or not isinstance(c.get('candidate_id'),str) or not c['candidate_id'] or c['candidate_id'] in ids:
            fail('invalid_candidate',path,'unique nonempty candidate ID required')
        ids.add(c['candidate_id']);pick=c.get('pick_item_id')
        if pick not in known:fail('invalid_candidate',path+'.pick_item_id','currently pending object required')
        counts[pick]=counts.get(pick,0)+1
        if counts[pick]>16:fail('invalid_candidate',path,'per-object Top-K exceeds16')
        p=c.get('pose')
        if not isinstance(p,dict) or set(p)!= {'x_mm','y_mm','z_base_mm','yaw_deg'}:
            fail('invalid_candidate',path+'.pose','upright x/y/z/yaw only; roll/pitch unsupported')
        if type(p['yaw_deg']) is not int or p['yaw_deg'] not in (0,90):
            fail('invalid_candidate',path+'.pose.yaw_deg','E2 allowed angles:0,90')
        if any(type(p[k]) not in (int,float) or not math.isfinite(p[k]) for k in ('x_mm','y_mm','z_base_mm')):
            fail('invalid_candidate',path+'.pose','finite numeric coordinates required')
        size=c.get('oriented_size_mm')
        if not isinstance(size,list) or len(size)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in size):
            fail('invalid_candidate',path+'.oriented_size_mm','three finite positive lengths required')
    return candidates


def validate_response(response, req):
    validate_observation(req)
    check_schema('response', response, 'invalid_ast')
    for k in BINDINGS:
        if response[k] != req[k]:
            fail('invalid_binding', '$.' + k, 'response belongs to a different request/state')
    validate_policy(response['policy_ast'], req)
    return response
