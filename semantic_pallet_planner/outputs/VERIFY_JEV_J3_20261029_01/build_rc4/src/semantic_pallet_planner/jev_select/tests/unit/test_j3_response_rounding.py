"""Provider's observed quantization is a validation contract, never a new choice."""
import json

import pytest

from semantic_pallet_planner.jev_select.candidates import CandidateProvider, PublicBusinessGuard
from semantic_pallet_planner.jev_select.config import load_v2_config, generator_config
from semantic_pallet_planner.jev_select.context import ContextBuilder
from semantic_pallet_planner.jev_select.selector import parse_response
from semantic_pallet_planner.jev_select.transport import outcome


@pytest.fixture
def v2(pipeline):
    case, _, _, _, _ = pipeline
    cfg = load_v2_config()
    guard = PublicBusinessGuard()
    policy = guard.resolve(case['observation'])
    bundle = CandidateProvider().build(case['state'], case['observation'], generator_config(), config=cfg)
    bundle = guard.filter(case['observation'], policy, bundle, cfg)
    ctx = ContextBuilder(cfg).build(case['observation'], bundle, policy)
    assert len(ctx.data['criteria']) == 48
    return cfg, ctx


def parsed(ctx, cfg, prefix, *, choice='C01'):
    values = [*prefix, *([0.] * (len(ctx.data['criteria'])-len(prefix)))]
    probabilities = dict(zip(ctx.data['criteria'], values))
    payload = {'model': cfg['model'], 'answers': {'next_action': {'type': 'choice',
               'choice': choice, 'probabilities': probabilities, 'confidence': .15}},
               'usage': {'input_tokens': 123, 'output_tokens': 20}}
    raw = json.dumps(payload).encode()
    attempt = {'attempt_id': 'A000001', 'origin': 'jev', 'transport': outcome('OK', raw, http_status=200)}
    return parse_response(ctx, attempt, cfg).data, probabilities


@pytest.mark.parametrize('values', [[.33, .33, .33], [.34, .34, .33], [1.], [.3400000000000001, .33, .32], [.5900000000000001, .33, .06999999999999999]])
def test_A14_rounded_unit_distribution_preserves_raw_and_choice(v2, values):
    cfg, ctx = v2
    selection, raw = parsed(ctx, cfg, values)
    assert selection['status'] == 'selected'
    assert selection['selected_display_id'] == 'C01'
    assert selection['probabilities'] == raw
    assert selection['usage'] == {'input_tokens': 123, 'output_tokens': 20}


@pytest.mark.parametrize('values', [[0.]*48, [1.]*48, [.01]*48, [.333, .333, .333], [.33000000001, .33, .33]])
def test_A14_impossible_or_undeclared_precision_sum_is_rejected(v2, values):
    cfg, ctx = v2
    selection, _ = parsed(ctx, cfg, values)
    assert selection['status'] == 'invalid_response'
    assert selection['error'] == 'invalid_probability_sum'


def test_A14_rounding_does_not_relax_choice_maximum(v2):
    cfg, ctx = v2
    selection, _ = parsed(ctx, cfg, [.33, .33, .33], choice='C04')
    assert selection['status'] == 'invalid_response'
    assert selection['error'] == 'choice_not_maximum'


def test_A31_v1_keeps_its_original_strict_sum_policy(pipeline):
    _, cfg, _, _, ctx = pipeline
    selection, _ = parsed(ctx, cfg, [.33, .33, .33])
    assert selection['status'] == 'invalid_response'
    assert selection['error'] == 'invalid_probability_sum'
