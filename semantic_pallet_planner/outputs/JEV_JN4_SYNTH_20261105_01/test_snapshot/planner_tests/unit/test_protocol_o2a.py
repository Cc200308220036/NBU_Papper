"""O2a protocol rejects unbound/extra actions and repairs only from public facts."""
import json
import pytest

from semantic_pallet_planner.vlm.protocol_o2a import (VERSION, ChoiceProtocolError,
    parse_choice, repair_user_text, public_input)


def request():
    return {'schema_version':'pallet_request_v2_pilot','request_id':'V2_PILOT_101_0',
            'state_hash':'a'*64,'policy_digest':'b'*64,'instruction_text':'易碎箱累计承载不得超过1 kg',
            'container':{},'placed_items':[],'available_items':[{'item_id':'item_1'}],
            'candidates':[{'display_label':'C01'}],'buffer_size':1}


def response(**changes):
    obj={'schema_version':VERSION,'request_id':'V2_PILOT_101_0','state_hash':'a'*64,
         'policy_digest':'b'*64,'action':'select','display_label':'C01','reason':'公开事实'}
    obj.update(changes)
    return json.dumps(obj,ensure_ascii=False)


def test_exact_choice_and_abstain():
    assert parse_choice(response(),request())['display_label']=='C01'
    assert parse_choice(response(action='abstain',display_label=None),request())['action']=='abstain'


@pytest.mark.parametrize(('raw','code'),[
    (response(type='json_object'),'unexpected_fields'),
    (response(request_id='another'),'binding_request_id'),
    (response(state_hash='0'*64),'binding_state_hash'),
    (response(policy_digest='0'*64),'binding_policy_digest'),
    (response(display_label='C17'),'action_or_label'),
    (response(x_mm=15),'unexpected_fields'),
    ('{"action":','malformed_json'),
])
def test_rejects_untrusted_outputs(raw,code):
    with pytest.raises(ChoiceProtocolError) as exc:
        parse_choice(raw,request())
    assert exc.value.code==code


def test_public_and_repair_scan_never_echo_raw():
    req=request()
    assert 'V2_PILOT_101_0' in public_input(req,('secret_real_candidate',))
    repaired=repair_user_text(req,'unexpected_fields',('secret_real_candidate',))
    assert 'secret_real_candidate' not in repaired
    assert '上次输出' in repaired
    req['candidate_id']='secret_real_candidate'
    with pytest.raises(ChoiceProtocolError) as exc:
        repair_user_text(req,'unexpected_fields',('secret_real_candidate',))
    assert exc.value.code=='public_input_leakage'
