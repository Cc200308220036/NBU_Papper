"""White-list ideal observations; never accept a scenario or truth AST."""
import copy
from .common import CATEGORIES, O4Error, digest, validate


def derive_attributes(item, scenario_id, seed=20261021):
    token = digest([seed, scenario_id, item['item_id']])
    value = int(token[:16], 16)
    return {
        'object_id': item['item_id'],
        'cargo_category': 'electronics' if item['product_category']=='electronics' else ('food','glassware','household_cleaner','general')[value % 4],
        'packaging': {'reinforced': bool((value >> 3) & 1)},
        'labels': {'no_top_load': bool((value >> 5) & 1),
                   'max_top_load_kg': float((0,1,2,3,5,8)[(value >> 7) % 6])},
        'physical_top_load_limit_kg': item['top_load_limit_kg_synthetic'],
    }


def public_object(item, attributes, placed=False):
    if attributes['object_id'] != item['item_id'] or attributes['physical_top_load_limit_kg'] != item['top_load_limit_kg_synthetic']:
        raise O4Error('invalid_observation', 'attribute identity/physical limit mismatch')
    out = {key: copy.deepcopy(item[key]) for key in ('mass_kg','dimensions_mm','stackable','fragile','weight_class')}
    out.update(copy.deepcopy(attributes))
    if placed:
        out.update({key:copy.deepcopy(item[key]) for key in ('pose','oriented_size_mm')})
    return out


def build_observation(state, attributes, instruction_text, images=()):
    """state contains only the actual placed and available objects."""
    placed = [public_object(i, attributes[i['item_id']], True) for i in state['placed_items']]
    available = [public_object(i, attributes[i['item_id']]) for i in state['available_items']]
    req = {'schema_version':'o4_request_v1','request_id':state['request_id'],
           'units':{'length':'mm','mass':'kg'},'container':copy.deepcopy(state['container']),
           'placed_objects':placed,'available_objects':available,'instruction_text':instruction_text,
           'images':list(copy.deepcopy(images))}
    req['state_hash'] = digest({k:req[k] for k in ('container','placed_objects','available_objects')})
    req['instruction_digest'] = digest(instruction_text)
    req['observation_digest'] = digest({k:v for k,v in req.items() if k!='request_id'})
    return validate_observation(req)


def validate_observation(req):
    validate('observation', req, 'invalid_observation')
    objects = req['placed_objects'] + req['available_objects']
    ids = [i['object_id'] for i in objects]
    if len(ids) != len(set(ids)):
        raise O4Error('invalid_observation','duplicate object')
    for item in req['placed_objects']:
        dims = item['dimensions_mm']
        expected = [dims[k] for k in ('length','width','height')]
        if item['pose']['yaw_deg']==90:
            expected[0],expected[1]=expected[1],expected[0]
        if expected != item['oriented_size_mm']:
            raise O4Error('invalid_observation','orientation mismatch')
    expected_state = digest({k:req[k] for k in ('container','placed_objects','available_objects')})
    payload = {k:v for k,v in req.items() if k not in ('observation_digest','request_id')}
    if req['state_hash']!=expected_state or req['instruction_digest']!=digest(req['instruction_text']) or req['observation_digest']!=digest(payload):
        raise O4Error('invalid_binding','observation digest mismatch')
    return req


def rebind(req):
    """Useful for explicit counterfactual observations; no truth is accepted."""
    req=copy.deepcopy(req)
    req['state_hash']=digest({k:req[k] for k in ('container','placed_objects','available_objects')})
    req['instruction_digest']=digest(req['instruction_text'])
    req['observation_digest']=digest({k:v for k,v in req.items() if k not in ('observation_digest','request_id')})
    return validate_observation(req)
