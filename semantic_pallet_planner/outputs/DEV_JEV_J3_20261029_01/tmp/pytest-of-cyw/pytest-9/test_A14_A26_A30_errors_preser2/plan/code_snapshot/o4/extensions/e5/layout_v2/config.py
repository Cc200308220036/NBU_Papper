"""Closed, versioned opt-in configuration and predeclared geometry scales."""
from ....common import O4Error, digest
from . import VERSION

DEFAULT = {'version': VERSION, 'candidate_retention': True, 'ranking': True,
           'per_object_top_k': 16, 'alignment_reserve': 4,
           'search_depth': 3, 'beam_width': 8, 'max_successor_evaluations': 256,
           'narrow_gap_mm': 100.0, 'probe_quality': False, 'business_support_quality': False,
           'position_rank': ['side_contact_ratio', 'aligned_contact_ratio', 'narrow_free_area_fraction',
                             'extra_free_runs', 'geometry_score', 'stable_pose'],
           'path_rank': ['count', 'volume', 'layout_quality', 'height', 'geometry_score', 'stable_path']}


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT): raise O4Error('invalid_layout_config', 'closed fields required')
    for k, expected in DEFAULT.items():
        if k in ('candidate_retention', 'ranking'):
            if type(value[k]) is not bool: raise O4Error('invalid_layout_config', k)
        elif digest(value[k]) != digest(expected): raise O4Error('invalid_layout_config', k)
    return value
