"""Versioned closed public contracts and durable record validators."""
import copy
import jsonschema
from .common import canonical, O5Error


def obj(properties, required=None):
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else required, 'additionalProperties': False}


NUMBER = {'type': 'number', 'minimum': 0}
POSITIVE = {'type': 'number', 'exclusiveMinimum': 0}
TEXT = {'type': 'string', 'minLength': 1}
HASH = {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}
POSE = obj({'x_mm': {'type': 'number'}, 'y_mm': {'type': 'number'}, 'z_base_mm': NUMBER,
            'yaw_deg': {'enum': [0, 90]}})
SIZE = {'type': 'array', 'items': POSITIVE, 'minItems': 3, 'maxItems': 3}
ITEM = obj({'item_id': TEXT, 'dimensions_mm': obj({k: POSITIVE for k in ('length', 'width', 'height')}),
            'mass_kg': POSITIVE, 'stackable': {'const': True}, 'physical_top_load_limit_kg': {'const': 100.}})
PLACED = copy.deepcopy(ITEM)
PLACED['properties'].update(pose=POSE, oriented_size_mm=SIZE, supported_load_kg=NUMBER)
PLACED['required'] += ['pose', 'oriented_size_mm', 'supported_load_kg']
CONTAINER = obj({'container_id': TEXT, 'length_mm': POSITIVE, 'width_mm': POSITIVE,
                 'max_height_mm': POSITIVE, 'max_payload_kg': POSITIVE,
                 'coordinate_frame': {'const': 'container_bottom_center'}})
SUPPORT = obj({'support_item_ids': {'type': 'array', 'items': TEXT, 'uniqueItems': True},
               'support_ratio': {'type': 'number', 'minimum': 0, 'maximum': 1}, 'com_margin_mm': NUMBER})
CANDIDATE = obj({'candidate_id': {'type': 'string', 'pattern': '^C[0-9]{2}$'},
                 'pose': POSE, 'oriented_size_mm': SIZE, 'support': SUPPORT})
IMAGE = obj({'asset_id': {'enum': ['workspace', 'candidates']}, 'sha256': HASH,
             'width': {'type': 'integer', 'minimum': 1}, 'height': {'type': 'integer', 'minimum': 1},
             'media_type': {'const': 'image/png'}})
REQUEST = obj({'schema_version': {'const': 'o5_decision_request_v1'}, 'request_id': TEXT,
               'state_hash': HASH, 'container': CONTAINER,
               'placed_items': {'type': 'array', 'items': PLACED}, 'current_item': ITEM,
               'candidates': {'type': 'array', 'items': CANDIDATE, 'maxItems': 16},
               'images': {'type': 'array', 'items': IMAGE, 'minItems': 2, 'maxItems': 2},
               'task_goal': TEXT, 'output_contract': TEXT})
RESPONSE = obj({'request_id': TEXT, 'state_hash': HASH, 'action': {'enum': ['PLACE', 'STOP']},
                'candidate_id': {'type': ['string', 'null']}})

# Internal/evaluator payloads are opaque records, never sent to selectors.
def record(version, fields):
    return obj({'schema_version': {'const': version}, **fields})


SCHEMAS = {
    'DecisionRequest': REQUEST, 'DecisionResponse': RESPONSE,
    'DatasetManifest': record('o5_dataset_manifest_v1', {
        'protocol_version': TEXT, 'status': {'enum': ['PASS', 'BLOCKED_DATA']}, 'raw_sha256': HASH,
        'raw_orders': {'type': 'integer'}, 'short_orders': {'type': 'integer'},
        'eligible_source_clusters': {'type': 'integer'}, 'iid_available': {'type': 'integer'}, 'ood_available': {'type': 'integer'},
        'config': {'type': 'object'}, 'split_counts': {'type': 'object'}, 'splits': {'type': 'object'},
        'selection': {'type': 'object'}, 'unselected_digest': HASH, 'status_counts': {'type': 'object'},
        'physical_attributes': TEXT, 'independent_collection': {'const': False},
        'model_pretraining_exposure': {'const': 'UNKNOWN'}, 'new_api_attempts': {'const': 0},
        'planning_calls': {'const': 0}, 'files': {'type': 'object'}}),
    'DecisionJournal': record('o5_decision_journal_v1', {
        'request': REQUEST, 'private_mapping': {'type': 'object'}, 'pool_fingerprint': HASH,
        'candidate_audit': {'type': 'object'}, 'attempt_ids': {'type': 'array', 'items': TEXT},
        'response': {'anyOf': [RESPONSE, {'type': 'null'}]}, 'reason': TEXT,
        'before': {'type': 'array'}, 'after': {'type': 'array'},
        'proposed_candidate': {'type': ['object', 'null']}, 'committed_candidate': {'type': ['object', 'null']},
        'physical_errors': {'type': 'array', 'items': TEXT}}),
    'EpisodeResult': record('o5_episode_result_v1', {
        'job_id': TEXT, 'task_id': TEXT, 'source_cluster_id': TEXT, 'method': {'enum': ['G0', 'D0']},
        'test_double': {'type': 'boolean'}, 'summary': {'type': 'object'},
        'decisions': {'type': 'array', 'items': {'type': 'string'}}, 'final_state': {'type': 'array'}}),
    'BudgetLedger': record('o5_budget_ledger_v1', {
        'job_id': TEXT, 'attempt_limit': {'type': 'integer', 'minimum': 0},
        'real_api_attempts': {'const': 0}, 'test_double': {'const': True},
        'attempts': {'type': 'array', 'items': obj({
            'attempt_id': TEXT, 'request_digest': HASH, 'repair': {'type': 'boolean'},
            'status': {'enum': ['planned', 'sent', 'completed', 'failed', 'unknown']},
            'envelope_digest': HASH, 'response': {}, 'error': {'type': ['string', 'null']},
            'latency_seconds': NUMBER, 'usage': {'type': ['object', 'null']},
            'cost': {'type': ['number', 'null']}})}}),
    'PlanManifest': record('o5_plan_manifest_v1', {
        'protocol_version': TEXT, 'mode': {'const': 'OFFLINE_ENGINEERING_ONLY'},
        'dataset_path': TEXT, 'dataset_digest': HASH, 'config': {'type': 'object'},
        'source_files': {'type': 'object'}, 'dependency_versions': {'type': 'object'},
        'jobs': {'type': 'array'}, 'stub_policy': TEXT, 'new_api_attempts': {'const': 0}}),
}

# Older blocked S0 records remain readable; successful quantile datasets require
# this field through validate_dataset's semantic checks.
SCHEMAS['DatasetManifest']['properties']['ood_rule'] = {'type': 'object'}
SCHEMAS['DatasetManifest']['properties']['raw_path'] = TEXT


def validate(name, value):
    try:
        canonical(value)
        jsonschema.Draft202012Validator(SCHEMAS[name]).validate(value)
    except (ValueError, TypeError, jsonschema.ValidationError) as error:
        raise O5Error('SCHEMA_ERROR', name) from error
    return value
