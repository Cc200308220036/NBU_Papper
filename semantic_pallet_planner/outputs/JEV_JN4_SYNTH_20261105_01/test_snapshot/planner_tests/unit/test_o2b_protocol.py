import json

import pytest

from semantic_pallet_planner.selectors.instruction_parser_o1b import policy, conditional_envelope
from semantic_pallet_planner.vlm.policy_protocol_o2b import (
    VERSION, model_request, parse_policy_response, validate_restricted_ast)
from semantic_pallet_planner.vlm.protocol_o2a import ChoiceProtocolError


def request():
    return {'request_id':'O1B_GROUP_001_C0','state_hash':'a'*64,'policy_digest':'b'*64,
            'schema_version':'pallet_request_v2_pilot','instruction_text':'public text',
            'container':{},'placed_items':[],
            'available_items':[{'weight_class':'heavy'}],
            'candidates':[],'buffer_size':1}


def response(req, ast):
    return json.dumps({'schema_version':VERSION,'request_id':req['request_id'],
                       'state_hash':req['state_hash'],'policy_digest':req['policy_digest'],
                       'policy_ast':ast})


def test_conditional_ast_and_three_bindings():
    req=request()
    ast=conditional_envelope(policy(1,('heavy_low','heavy_center')),
                             policy(3,('heavy_center','heavy_low')))
    assert parse_policy_response(response(req,ast),req)['policy_ast']==ast
    wrong=json.loads(response(req,ast));wrong['policy_digest']='c'*64
    with pytest.raises(ChoiceProtocolError,match='binding_policy_digest'):
        parse_policy_response(json.dumps(wrong),req)


def test_reject_unpublished_policy_domain_and_extra_output():
    req=request();ast=policy(1,('heavy_low','heavy_center'))
    ast['hard_constraints'][1]['right']={'weight_class':'light'}
    with pytest.raises(ChoiceProtocolError,match='policy_ast_domain'):
        parse_policy_response(response(req,ast),req)
    extra=json.loads(response(req,policy(1,('heavy_low','heavy_center'))))
    extra['candidate_id']='secret'
    with pytest.raises(ChoiceProtocolError,match='unexpected_fields'):
        parse_policy_response(json.dumps(extra),req)


def test_repair_prompt_never_echoes_prior_model_text():
    req=request()
    model=model_request(req,repair_error='malformed_json',private_strings=('SECRET_REAL_ID',))
    assert 'SECRET_REAL_ID' not in model.user_text
    assert 'malformed_json' in model.user_text


def test_reject_nested_arbitrary_ast():
    ast=policy(1,('heavy_low','heavy_center'))
    ast['code']='print(1)'
    with pytest.raises(ChoiceProtocolError):
        validate_restricted_ast(ast)


def test_nonfinite_threshold_is_not_a_valid_policy():
    req=request()
    ast=policy(1,('heavy_low','heavy_center'))
    ast['hard_constraints'][0]['threshold_kg']=float('nan')
    with pytest.raises(ChoiceProtocolError):
        parse_policy_response(response(req,ast),req)
