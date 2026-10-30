"""Closed B0 policy. Independent identities for all planning decisions."""
import copy
from ....common import O4Error, digest
from ..layout_v2.config import DEFAULT as V2

DEFAULT = {'version': 'o4_e5_capacity_b0_v1', 'candidate_policy': 'frozen_v2_B_retention_v1',
           'position_policy': 'e2_geometry_v1', 'beam_policy': 'e2_count_volume_height_stable_v1',
           'leaf_policy': 'e2_count_volume_stable_v1', 'scheduler': 'e2_ordered_budget_v1',
           'per_object_top_k': 16, 'joint_candidates_max': 48, 'search_depth': 3,
           'beam_width': 8, 'max_successor_evaluations': 256,
           'terminal_quality': 'NOT_IMPLEMENTED', 'business_support_quality': 'NOT_IMPLEMENTED',
           'probe_quality': 'NOT_IMPLEMENTED'}


def validate(config):
    value = config.get('o4_e5_capacity')
    if type(value) is not dict or digest(value) != digest(DEFAULT) or 'o4_e5_layout' in config:
        raise O4Error('invalid_capacity_config', 'B0 closed version and unambiguous dispatch required')
    return value


def v2_config(config):
    validate(config)
    result = copy.deepcopy(config); result.pop('o4_e5_capacity')
    result['o4_e5_layout'] = {**copy.deepcopy(V2), 'candidate_retention': True, 'ranking': False}
    return result
