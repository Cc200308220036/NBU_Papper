"""GP2 public bytes adapter. No checkpoint/private fields, no float recovery."""
import json
import math
from decimal import Decimal
from .contracts import require, number, text, digest, parse_input

VERSION = 'geometry_physical_input_v1'
ADAPTER = 'geometry_public_physical_adapter_v1'
ITEM = {'item_id','dimensions_mm','mass_kg','stackable','top_load_limit_kg_synthetic'}
PLACED = ITEM | {'pose','oriented_size_mm','supported_load_kg','support_fractions'}


def closed(obj, keys):
    require(type(obj) is dict and set(obj) == keys, 'closed fields: ' + ','.join(sorted(keys)))


def encode_exact(value):
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        return text(number(value))
    if isinstance(value, dict):
        return '{'+','.join(json.dumps(k)+':'+encode_exact(v) for k,v in sorted(value.items()))+'}'
    if isinstance(value, list):
        return '['+','.join(map(encode_exact,value))+']'
    return json.dumps(value, allow_nan=False)


def binary(value):
    if type(value) in (int, Decimal):
        f = float(value)
        require(math.isfinite(f), 'binary64 overflow')
        require(value == 0 or f != 0, 'binary64 underflow')
        return f
    if isinstance(value, dict):
        return {k:binary(v) for k,v in value.items()}
    if isinstance(value, list):
        return [binary(v) for v in value]
    return value


def adapt(raw):
    require(type(raw) is bytes, 'original public JSON bytes required')
    def pairs(items):
        out = {}
        for k,v in items:
            require(k not in out, 'duplicate key')
            out[k] = v
        return out
    def invalid(v):
        require(False, 'nonfinite JSON')
    value = json.loads(raw, parse_float=Decimal, object_pairs_hook=pairs, parse_constant=invalid)
    closed(value, {'version','container','placed_items','buffer_items'})
    require(value['version'] == VERSION, 'unregistered input version')
    closed(value['container'], {'length_mm','width_mm','max_height_mm','max_payload_kg'})
    require(all(number(v)>0 for v in value['container'].values()), 'positive container values')
    names = set()
    require(type(value['placed_items']) is list and type(value['buffer_items']) is list, 'item lists')
    require(len(value['buffer_items']) <= 3, 'buffer capacity 3')
    arrivals = set()
    for placed, records in ((True,value['placed_items']), (False,value['buffer_items'])):
        for item in records:
            closed(item, PLACED if placed else ITEM | {'arrival_index'})
            name = item['item_id']
            require(type(name) is str and bool(name) and name not in names, 'unique IDs')
            names.add(name)
            closed(item['dimensions_mm'], {'length','width','height'})
            require(all(number(v)>0 for v in item['dimensions_mm'].values()), 'positive dimensions')
            require(number(item['mass_kg'])>0 and number(item['top_load_limit_kg_synthetic'])>=0, 'mass/capacity')
            require(type(item['stackable']) is bool, 'stackable boolean')
            if placed:
                closed(item['pose'], {'x_mm','y_mm','z_base_mm','yaw_deg'})
                yaw=item['pose']['yaw_deg']
                require(type(yaw) is int and yaw in (0,90), 'yaw')
                dims=[item['dimensions_mm'][k] for k in ('length','width','height')]
                require(item['oriented_size_mm'] == (dims if yaw==0 else [dims[1],dims[0],dims[2]]), 'oriented dimensions')
                require(number(item['supported_load_kg'])>=0, 'saved load')
                require(type(item['support_fractions']) is list, 'saved supports')
                for edge in item['support_fractions']:
                    closed(edge, {'item_id','fraction'})
                    require(type(edge['item_id']) is str and 0<number(edge['fraction'])<=1, 'support edge')
            else:
                idx=item['arrival_index']
                require(type(idx) is int and idx>=0 and idx not in arrivals, 'unique arrival index')
                arrivals.add(idx)
    geometry={'version':'geometry_space_input_v1',
              'container':{k:value['container'][k] for k in ('length_mm','width_mm','max_height_mm')},
              'placed_items':[{k:p[k] for k in ('item_id','pose','oriented_size_mm')} for p in value['placed_items']]}
    geometry_bytes=encode_exact(geometry).encode()
    state=parse_input(geometry_bytes)
    physical=binary(value)
    # yaw is a protocol enum, retain integer identity at this boundary.
    for p in physical['placed_items']:
        p['pose']['yaw_deg']=int(p['pose']['yaw_deg'])
    identity=digest({'adapter':ADAPTER,'public_input':json.loads(encode_exact(value),parse_float=str)})
    return value, physical, state, geometry_bytes, identity
