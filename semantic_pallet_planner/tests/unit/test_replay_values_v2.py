import math
import pytest
from semantic_pallet_planner.evaluation.replay_values_v2 import replay_values_equal


def test_real_python_311_313_roundoff_sample():
    assert replay_values_equal({'d': [401.04599968690053, .473095201838829]},
                               {'d': [401.0459996869006, .4730952018388289]})


@pytest.mark.parametrize('actual,expected', [
    ({'distance': 400.001}, {'distance': 400.}),
    ({'request_id': 'a'}, {'request_id': 'b'}),
    ({'policy_digest': 'a'}, {'policy_digest': 'b'}),
    ({'state_hash': 'a'}, {'state_hash': 'b'}),
    ({'display_label': 'C01'}, {'display_label': 'C02'}),
    ({'applicable': True}, {'applicable': 1}),
    ({'count': 1}, {'count': 1.}),
    ({'quality': None}, {'quality': 0.}),
    ({'indices': [0, 1]}, {'indices': [1, 0]}),
    ({'quality': math.nan}, {'quality': math.nan}),
    ({'quality': math.inf}, {'quality': math.inf}),
    ({'extra': 0}, {}),
])
def test_semantic_binding_type_and_corruption_stay_strict(actual, expected):
    assert not replay_values_equal(actual, expected)
