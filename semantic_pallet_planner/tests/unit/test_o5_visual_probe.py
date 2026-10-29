"""Probe prompt/schema regression, including the actual failed response's shape."""
import json
import pytest
from semantic_pallet_planner.o5.visual_probe import contract,evaluate,PROMPT
from semantic_pallet_planner.o5.common import O5Error


def task():
    return {'response_contract':contract(),'images':[
        {'asset_id':'workspace','expected_fact':'red_circle'},
        {'asset_id':'candidates','expected_fact':'blue_square'}]}


def test_correct_flat_response_is_valid():
    assert evaluate(task(),'{"workspace":"red_circle","candidates":"blue_square"}')==(True,None)
    assert 'MUST be a string' in PROMPT and 'underscore' in PROMPT and 'nested objects' in PROMPT
    assert 'red_circle' not in PROMPT and 'blue_square' not in PROMPT


@pytest.mark.parametrize('value',[
    '{"workspace":{"color_shape":"red circle"},"candidates":{"color_shape":"blue square"}}',
    '{"workspace":"red circle","candidates":"blue square"}',
    '{"workspace":"red_circle","candidates":"blue_square","extra":true}',
    '{"workspace":"red_circle","workspace":"red_circle","candidates":"blue_square"}',
    'not json','[]'])
def test_format_failures_are_not_relabeled_as_visual_failure(value):
    assert evaluate(task(),value)==(False,'PREFLIGHT_RESPONSE_FORMAT_INVALID')


def test_schema_valid_wrong_fact_is_separate():
    assert evaluate(task(),'{"workspace":"blue_circle","candidates":"red_square"}')==(False,'PREFLIGHT_VISUAL_FACT_MISMATCH')


def test_legacy_outcome_and_contract_version_are_not_rewritten():
    t=task();t.pop('response_contract')
    old='{ "workspace": {"color_shape":"red circle"}, "candidates": {"color_shape":"blue square"}}'
    assert evaluate(t,old)==(False,None)
    t=task();t['response_contract']['version']='unknown'
    with pytest.raises(O5Error,match='UNSUPPORTED_VISUAL_PROBE_CONTRACT'):evaluate(t,old)
