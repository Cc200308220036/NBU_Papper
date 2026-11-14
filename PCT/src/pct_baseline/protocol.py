"""Exact registration and semantic invariants; imports no planner or transport."""
from .contracts import require, digest

VERSION = 'pct_b1_config_v1'
SUFFIX = 'b1_v1'
PAIRS = {
    'config': ('pct_b1_config_v1', 'config_b1_v1'),
    'candidate_bundle': ('jev_candidate_bundle_b1_v1', 'candidate_bundle_b1_v1'),
    'decision_context': ('jev_decision_context_b1_v1', 'decision_context_b1_v1'),
    'task': ('pct_b1_task_v1', 'task_b1_v1'),
    'execution_spec': ('pct_b1_execution_spec_v1', 'execution_spec_b1_v1'),
}
SCHEMAS = frozenset(pair[1] for pair in PAIRS.values())
VERSIONS = frozenset(pair[0] for pair in PAIRS.values())
EXECUTION_ADMITTED = False


def schema_name(name, version):
    for base, (expected, resource) in PAIRS.items():
        if version == expected and name in (base, resource):
            return resource
    raise ValueError('PCT_B1_SCHEMA_VERSION_MISMATCH')


def validate_value(name, value):
    require(name in SCHEMAS, 'unknown_schema')
    base = next(k for k, pair in PAIRS.items() if pair[1] == name)
    require(value.get('version') == PAIRS[base][0], 'PCT_B1_SCHEMA_VERSION_MISMATCH')
    if base == 'candidate_bundle':
        physical, selected = value['physical_candidates'], value['selectable_candidates']
        require(value['physical_digest'] == digest(physical) and value['selectable_digest'] == digest(selected), 'PCT_B1_POOL_DIGEST')
        if value['selectable_pool'] == 'unfiltered':
            require(selected == [] and value['policy_digest'] is None, 'PCT_B1_UNFILTERED')
        else:
            require(value['selectable_pool'] == 'physical_feasible' and selected == physical and value['policy_digest'] is not None, 'PCT_B1_PHYSICAL_POOL')
    elif base == 'task':
        ids = [item['item_id'] for item in value['items']]
        require(bool(ids), 'EMPTY_TASK')
        require(len(set(ids)) == len(ids), 'DUPLICATE_ITEM')
        require(ids == value['arrival_order'], 'ARRIVAL_ORDER_MISMATCH')
        require(value['partition'] == value['parent_partition'], 'PARTITION_DRIFT')
        require(set(value['attributes']) == set(ids), 'ATTRIBUTE_IDS')
        for item in value['items']:
            capacity=item['top_load_limit_kg_synthetic']
            require(value['attributes'][item['item_id']] == {
                'object_id':item['item_id'],'cargo_category':'general','packaging':{'reinforced':False},
                'labels':{'no_top_load':not item['stackable'],'max_top_load_kg':capacity},
                'physical_top_load_limit_kg':capacity}, 'PHYSICAL_ALIAS_DRIFT')
        require(value['derived_task_digest'] == digest({k:v for k,v in value.items() if k != 'derived_task_digest'}), 'DERIVED_IDENTITY_DRIFT')
    elif base == 'decision_context':
        state = value['model_state']; pending = state['buffer']['pending']
        require(state['buffer']['capacity'] == 1 and len(pending) <= 1 and len(state['available_objects']) <= 1, 'PCT_B1_CAPACITY')
        require([p['object_id'] for p in pending] == [o['object_id'] for o in state['available_objects']], 'PCT_B1_PENDING')
        require(all(p['slot'] == 0 for p in pending), 'PCT_B1_SLOT')
        require(not (pending and state['buffer']['end_of_stream']), 'PCT_B1_EARLY_EOS')
        binding = value['local_binding']
        for field,key in [('mapping_digest','display_mapping'),('criteria_digest','criteria'),('model_state_digest','model_state'),('request_body_digest','request_body')]:
            require(binding[field] == digest(value[key]), 'PCT_B1_CONTEXT_DIGEST')


def validate_observed(observation):
    buffer = observation['buffer_context']
    available = observation['available_objects']
    placed = observation['placed_objects']
    require(buffer['capacity'] == 1 and len(available) <= 1 and len(buffer['pending']) <= 1, 'PCT_B1_CAPACITY')
    ids = [o['object_id'] for o in placed + available]
    require(len(set(ids)) == len(ids), 'DUPLICATE_ITEM')
    require([o['object_id'] for o in available] == [p['object_id'] for p in buffer['pending']], 'PCT_B1_PENDING')
    require(all(p['slot'] == 0 for p in buffer['pending']), 'PCT_B1_SLOT')
    require(not (available and buffer['end_of_stream']), 'PCT_B1_EARLY_EOS')
