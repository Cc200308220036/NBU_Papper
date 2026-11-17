"""N1 current-public snapshots. No task argument, persistence, selector or monitor.

Capture returns immutable original bytes. Validation consumes those same bytes;
it never repairs a binding or re-signs saved snapshots. This is not resume logic.
"""
import copy
from decimal import Decimal
from pathlib import Path

from . import geometry_runtime_contracts as c
from .contracts import digest
from ..planner.space_candidates.contracts import GeometryError, parse_input
from ..planner.space_candidates.input_adapter import ITEM, PLACED, encode_exact


def runtime_config():
    from ..planner.space_candidates.generator import CONFIG
    return {'version': 'geometry_runtime_generator_config_v1', 'profile': c.PROFILE,
            'generator': copy.deepcopy(CONFIG)}


def _integer(value, *, maximum=None):
    c.require(type(value) is int and value >= 0 and (maximum is None or value <= maximum),
              'nonnegative integer/enum required')


def _item(obj, placed):
    c.closed(obj, c.PLACED_KEYS if placed else c.ITEM_KEYS)
    c.require(type(obj['item_id']) is str and bool(obj['item_id']), 'item ID required')
    c.closed(obj['dimensions_mm'], {'length','width','height'})
    for v in obj['dimensions_mm'].values():
        c.require(c.native_number(v) > 0, 'positive dimensions')
    c.require(c.native_number(obj['mass_kg']) > 0 and
              c.native_number(obj['top_load_limit_kg_synthetic']) >= 0, 'mass/capacity')
    c.require(type(obj['stackable']) is bool and type(obj['fragile']) is bool, 'boolean flags')
    c.require(obj['weight_class'] in ('light','medium','heavy') and
              type(obj['product_category']) is str, 'legacy public aliases')
    if not placed:
        return
    c.closed(obj['pose'], {'x_mm','y_mm','z_base_mm','yaw_deg'})
    yaw = obj['pose']['yaw_deg']
    c.require(type(yaw) is int and yaw in (0,90), 'yaw 0/90 int')
    for k in ('x_mm','y_mm','z_base_mm'):
        c.native_number(obj['pose'][k])
    c.require(obj['pose']['z_base_mm'] >= 0, 'negative base height')
    dims = [obj['dimensions_mm'][k] for k in ('length','width','height')]
    expected = dims if yaw == 0 else [dims[1],dims[0],dims[2]]
    c.require(type(obj['oriented_size_mm']) is list and
              c.same_native(obj['oriented_size_mm'], expected), 'oriented size/type mismatch')
    c.require(c.native_number(obj['supported_load_kg']) >= 0, 'negative saved load')
    c.require(type(obj['support_fractions']) is list, 'support list required')
    ids = set()
    for edge in obj['support_fractions']:
        c.closed(edge, {'item_id','fraction'})
        c.require(type(edge['item_id']) is str and edge['item_id'] not in ids and
                  0 < c.native_number(edge['fraction']) <= 1, 'support ID/fraction')
        ids.add(edge['item_id'])


def _public(state, observation, *, project):
    from ..o4.buffer.buffer_state import invariant
    from ..o4.extensions.e2.protocol import observation as rebuild, validate_observation
    from .packaging_runtime import INSTRUCTION
    c.require(type(state) is dict, 'state required')
    # Capture discards environment metadata; decoding a saved envelope is closed.
    c.require(c.STATE_KEYS <= state.keys(), 'missing state fields', 'RUNTIME_INPUT_MISSING_FIELD')
    s = {k: copy.deepcopy(state[k]) for k in c.STATE_KEYS} if project else copy.deepcopy(state)
    c.closed(s, c.STATE_KEYS)
    c.closed(s['container'], c.CONTAINER_KEYS)
    for k in ('length_mm','width_mm','max_height_mm','max_payload_kg'):
        c.require(c.native_number(s['container'][k]) > 0, 'positive container values')
    c.require(s['buffer_capacity'] == 3 and type(s['buffer_capacity']) is int, 'capacity 3')
    for k in ('event_index','arrival_count','placed_count'):
        _integer(s[k])
    c.require(type(s['end_of_stream']) is bool and type(s['arrived_ids']) is list and
              all(type(x) is str and bool(x) for x in s['arrived_ids']), 'public metadata')
    c.require(type(s['pending_items']) is list and type(s['placed_items']) is list and
              type(s['attributes']) is dict, 'state collections')
    for p in s['placed_items']:
        if project:
            c.require(type(p) is dict and c.PLACED_KEYS <= p.keys(), 'missing placed field', 'RUNTIME_INPUT_MISSING_FIELD')
            for k in set(p) - c.PLACED_KEYS:
                del p[k]
        _item(p, True)
    for pending in s['pending_items']:
        c.closed(pending, {'item','slot','arrival_index'})
        if project:
            obj = pending['item']
            c.require(type(obj) is dict and c.ITEM_KEYS <= obj.keys(), 'missing item field', 'RUNTIME_INPUT_MISSING_FIELD')
            pending['item'] = {k: obj[k] for k in c.ITEM_KEYS}
        _item(pending['item'], False)
        _integer(pending['slot'], maximum=2)
        _integer(pending['arrival_index'])
    all_items = s['placed_items'] + [p['item'] for p in s['pending_items']]
    ids = {p['item_id'] for p in all_items}
    for p in s['placed_items']:
        c.require(all(e['item_id'] in {q['item_id'] for q in s['placed_items']}
                      and e['item_id'] != p['item_id'] for e in p['support_fractions']), 'unknown/self support ID')
    c.require(set(s['attributes']) == ids, 'attribute IDs changed')
    for obj in all_items:
        attrs = s['attributes'][obj['item_id']]
        c.closed(attrs, {'object_id','cargo_category','packaging','labels','physical_top_load_limit_kg'})
        c.closed(attrs['packaging'], {'reinforced'})
        c.closed(attrs['labels'], {'no_top_load','max_top_load_kg'})
        c.require(attrs['object_id'] == obj['item_id'] and
                  c.same_native(attrs['physical_top_load_limit_kg'], obj['top_load_limit_kg_synthetic']),
                  'physical alias type/value changed', 'RUNTIME_SNAPSHOT_MISMATCH')
    c.check_native_tree(s)
    c.check_native_tree(observation)
    try:
        invariant(s)
        validate_observation(observation)
        c.require(observation['instruction_text'] == INSTRUCTION and
                  observation['regions'] == [] and observation['images'] == [], 'physical-only public observation required')
        expected = rebuild(s, INSTRUCTION, [])
    except (ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, GeometryError):
            raise
        raise GeometryError('RUNTIME_INPUT_INVALID', 'public observation/invariant: ' + str(exc)) from exc
    c.require(c.same_native(expected, observation), 'stale observation or native leaf/type/bit drift',
              'RUNTIME_SNAPSHOT_MISMATCH')
    return s


def _payload(state):
    def convert(value, key=''):
        if type(value) in (int, float):
            return value if key in ('yaw_deg','arrival_index') else c.numeric_text(value)
        if type(value) is dict:
            return {k: convert(v,k) for k,v in value.items()}
        if type(value) is list:
            return [convert(v,key) for v in value]
        return value
    payload = {'container': {k: state['container'][k] for k in
                            ('length_mm','width_mm','max_height_mm','max_payload_kg')},
               'placed_items': [{k: p[k] for k in PLACED} for p in state['placed_items']],
               'buffer_items': [{**{k:p['item'][k] for k in ITEM}, 'arrival_index': p['arrival_index']}
                                for p in sorted(state['pending_items'], key=lambda p:p['arrival_index'])]}
    return convert(payload)


def _exact(payload):
    def convert(value, key=''):
        if type(value) is str and key != 'item_id':
            # Values are already checked against the unique native derivation.
            return Decimal(value)
        if type(value) is dict:
            return {k: convert(v,k) for k,v in value.items()}
        if type(value) is list:
            return [convert(v,key) for v in value]
        return value
    return convert(payload)


def _effective(state):
    return {**{k: copy.deepcopy(state[k]) for k in ('buffer_capacity','arrived_ids','event_index',
             'arrival_count','placed_count','end_of_stream')},
            'payload': _native_payload(state),
            'pending_slots': [{'item_id':p['item']['item_id'],'slot':p['slot'],'arrival_index':p['arrival_index']}
                              for p in sorted(state['pending_items'],key=lambda p:p['arrival_index'])]}


def _native_payload(state):
    return {'container': {k: state['container'][k] for k in
                          ('length_mm','width_mm','max_height_mm','max_payload_kg')},
            'placed_items': [{k: copy.deepcopy(p[k]) for k in PLACED} for p in state['placed_items']],
            'buffer_items': [{**{k:copy.deepcopy(p['item'][k]) for k in ITEM}, 'arrival_index':p['arrival_index']}
                             for p in sorted(state['pending_items'],key=lambda p:p['arrival_index'])]}


def local_identity(config):
    from .experiment import source_manifest
    from .packaging_runtime import physical_manifest
    c.require(c.same_native(config, runtime_config()), 'unsupported runtime configuration/profile')
    return {'adapter_source_digest': digest({p.name: c.sha(p.read_bytes()) for p in
            (Path(__file__), Path(c.__file__))}),
            'source_manifest_digest': digest(source_manifest()), 'config_digest':digest(config),
            'physical_identity':digest(physical_manifest()), 'environment_digest':digest(c.environment())}


def _identities(identities):
    c.closed(identities, c.IDENTITY_KEYS)
    for v in identities.values():
        c.hash_string(v)


def _binding(native_raw, geometry_raw, native, geo, config, identities):
    _identities(identities)
    local = local_identity(config)
    row = {'version': c.BINDING, 'native_snapshot_sha256': c.sha(native_raw),
           'geometry_input_sha256':c.sha(geometry_raw), 'effective_state_digest':geo['effective_state_digest'],
           'geometry_values_digest':digest(geo['payload']), 'observation_digest':native['observation']['observation_digest'],
           'profile':c.PROFILE, 'adapter_version':c.ADAPTER, 'serializer_version':c.SERIALIZER,
           'backend':config['generator']['backend'], **local, **identities}
    row['record_digest'] = digest(row)
    return row


def capture_current_public_snapshot_v1(state, observation, *, profile, identities, config=None):
    c.require(profile == c.PROFILE, 'unsupported numeric profile')
    config = runtime_config() if config is None else config
    s = _public(state, observation, project=True)
    native = {'version':c.NATIVE, 'current_state':s, 'observation':copy.deepcopy(observation)}
    native_raw = c.encode(native)
    c.require(c.same_native(native, c.decode(native_raw)), 'native type/bit roundtrip failed',
              'RUNTIME_SNAPSHOT_MISMATCH')
    geo = {'version':c.INPUT, 'profile':c.PROFILE, 'adapter':c.ADAPTER,
           'native_snapshot_sha256':c.sha(native_raw), 'effective_state_digest':digest(_effective(s)),
           'observation_digest':observation['observation_digest'], 'payload':_payload(s)}
    geometry_raw = c.encode(geo)
    binding = _binding(native_raw, geometry_raw, native, geo, config, identities)
    validate_runtime_snapshot_v1(native_raw, geometry_raw, binding, identities=identities,
                                 current_state=state, observation=observation, config=config)
    return native_raw, geometry_raw, binding


def validate_runtime_snapshot_v1(native_raw, geometry_raw, binding, *, identities,
                                 current_state=None, observation=None, config=None):
    """Return separate exact/native views. No IO, reconstruction or candidate calls.

    Without an external current_state/observation pair this checks the saved
    artifacts only, not live freshness. A saved binding must be caller-trusted.
    """
    config = runtime_config() if config is None else config
    native, geo = c.decode(native_raw), c.decode(geometry_raw)
    c.closed(native, {'version','current_state','observation'})
    c.require(native['version'] == c.NATIVE, 'unregistered native version')
    s = _public(native['current_state'], native['observation'], project=False)
    c.closed(geo, {'version','profile','adapter','native_snapshot_sha256','effective_state_digest',
                   'observation_digest','payload'})
    c.require(geo['version'] == c.INPUT and geo['profile'] == c.PROFILE and geo['adapter'] == c.ADAPTER,
              'unregistered geometry version/profile/adapter')
    expected = {'version':c.INPUT, 'profile':c.PROFILE, 'adapter':c.ADAPTER,
                'native_snapshot_sha256':c.sha(native_raw), 'effective_state_digest':digest(_effective(s)),
                'observation_digest':native['observation']['observation_digest'], 'payload':_payload(s)}
    c.require(c.same_native(geo, expected), 'geometry leaf derivation/hash differs', 'RUNTIME_SNAPSHOT_MISMATCH')
    c.closed(binding, c.BINDING_KEYS)
    c.require(c.same_native(binding, _binding(native_raw,geometry_raw,native,geo,config,identities)),
              'frozen binding/source/config/environment differs', 'RUNTIME_SNAPSHOT_MISMATCH')
    c.require((current_state is None) == (observation is None), 'external state/observation pair required')
    if current_state is not None:
        fresh = _public(current_state, observation, project=True)
        c.require(c.same_native(s, fresh) and c.same_native(native['observation'], observation),
                  'external current state/observation differs', 'RUNTIME_SNAPSHOT_MISMATCH')
    exact, physical = _exact(geo['payload']), _native_payload(s)
    geometric = {'version':'geometry_space_input_v1',
                 'container':{k:exact['container'][k] for k in ('length_mm','width_mm','max_height_mm')},
                 'placed_items':[{k:p[k] for k in ('item_id','pose','oriented_size_mm')} for p in exact['placed_items']]}
    geometry_bytes = encode_exact(geometric).encode()
    try:
        geometry_state = parse_input(geometry_bytes)
    except GeometryError as exc:
        raise GeometryError('RUNTIME_EXACT_STATE_CONFLICT', exc.detail) from exc
    return {'native':native, 'geometry':geo, 'exact':exact, 'physical':physical,
            'geometry_state':geometry_state, 'geometry_bytes':geometry_bytes,
            'binding':copy.deepcopy(binding)}
