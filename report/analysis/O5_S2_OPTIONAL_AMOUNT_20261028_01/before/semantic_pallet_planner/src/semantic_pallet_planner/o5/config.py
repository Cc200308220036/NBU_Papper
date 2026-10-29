"""Closed S1 protocol. No remote transport is constructed by this version."""
import copy
from .common import ROOT, VERSION, O5Error, read, digest

DEFAULT = {
    'version': VERSION, 'seed': 20261028, 'buffer_capacity': 1,
    'top_k': 16, 'yaw_degrees': [0, 90], 'regions': [],
    'candidate_backend': 'o4_e2_public_boundary_grid_candidates_v1',
    'stackable': True, 'physical_top_load_limit_kg': 100.,
    'max_format_repairs': 1, 'selection_max_output_tokens': 256,
    'input_token_limit': 12000, 'max_request_bytes': 30000000,
    'mode': 'offline_only', 'methods': ['G0', 'D0'],
    'container': {'container_id': 'P1210-H085', 'length_mm': 1200, 'width_mm': 1000,
                  'max_height_mm': 850, 'max_payload_kg': 1000.,
                  'coordinate_frame': 'container_bottom_center'},
    'split_targets': {'train': 60, 'development': 20, 'test_id': 40, 'test_geometry_ood': 20},
    'data_design_version': 'o5_complete_orders_quantile_v1',
    'ood_definition': {'feature': 'maximum_box_planar_aspect_ratio', 'quantile': .8,
                       'algorithm': 'nearest_rank', 'ood': 'strictly_greater', 'ties': 'id'},
}


def validate(config):
    if digest(config) != digest(DEFAULT):
        raise O5Error('INVALID_CONFIG', 'S1 protocol is closed; publish a new version for changes')
    return copy.deepcopy(config)


def load(path=None):
    return validate(read(path) if path else DEFAULT)


def geometry_config(config):
    validate(config)
    base = read(ROOT / 'semantic_pallet_dataset_v1/configs/mvd_v0.1.json')
    if (base['container'] != DEFAULT['container'] or base['support_ratio_min'] != .70
            or base['candidate_generator']['top_k'] != 16
            or base['candidate_generator']['yaw_degrees'] != [0, 90]
            or base['candidate_generator']['geometry_score_weights'] !=
            {'compactness': .35, 'height': .25, 'stability': .25, 'balance': .15}):
        raise O5Error('PHYSICAL_CONFIG_DRIFT')
    base['topk_mode'] = 'diverse_v1'
    return base
