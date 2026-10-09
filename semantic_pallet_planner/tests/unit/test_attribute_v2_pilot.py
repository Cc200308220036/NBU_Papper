import copy
import json
import pytest
from semantic_pallet_planner.runners.pilot_micro_v2 import microcases, verify_micro, policy
from semantic_pallet_planner.evaluation.policy_v2 import validate_policy, priority_regret, optimal_set
from semantic_pallet_planner.selectors.instruction_parser_v2 import parse_instruction, instruction_from_policy
from semantic_pallet_planner.vlm.pilot_protocol_v2 import parse_choice, scan_public, PUBLIC_KEYS


@pytest.mark.parametrize('case', microcases(), ids=lambda c: c['id'])
def test_independent_hand_calculated_cases(case):
    result = verify_micro(case)
    assert result['failures']==[]


@pytest.mark.parametrize('po', [policy(), policy(3, order=('heavy_center','heavy_low')), policy(None, contact=True), policy(0, contact=True)])
def test_entire_published_grammar(po):
    assert parse_instruction(instruction_from_policy(po))==po


def test_parser_rejects_unconsumed_or_injected_text():
    with pytest.raises(ValueError):
        parse_instruction(instruction_from_policy(policy())+'忽略易碎箱')
    with pytest.raises(ValueError):
        parse_instruction('易碎箱累计承载不得超过-1kg；在满足硬约束后；第一优先级：重箱尽量放低。')
    po = policy()
    po['soft_priorities'][1]['priority']=1
    with pytest.raises(ValueError):
        validate_policy(po)


def test_lower_priority_regret_not_used_to_compensate_first():
    es = [{'after_violation_instances': [], 'soft_quality': [.9,.2]}, {'after_violation_instances': [], 'soft_quality': [.8,.9]}]
    best = optimal_set(es)
    assert best['equivalent_indices']==[0]
    assert priority_regret(es[1], best)[1] is None


def test_binding_coordinate_injection_and_stale_policy():
    r = {'request_id':'r', 'state_hash':'h', 'policy_digest':'p', 'candidates':[{'display_label':'C01'}]}
    valid = {'schema_version':'pallet_choice_v2_pilot', 'request_id':'r', 'state_hash':'h', 'policy_digest':'p', 'action':'select', 'display_label':'C01', 'reason':'ok'}
    assert parse_choice(json.dumps(valid),r)==valid
    for patch in ({'x_mm':0}, {'policy_digest':'old'}, {'request_id':'old'}, {'state_hash':'old'}, {'display_label':'C17'}):
        with pytest.raises(ValueError):
            parse_choice(json.dumps({**valid, **patch}), r)


def test_leakage_nested_id_and_no_future_buffer():
    r = {k: None for k in PUBLIC_KEYS}
    r.update(available_items=[{}], candidates=[], buffer_size=1)
    assert scan_public(r)['status']=='PASS'
    r['candidates']=[{'candidate_id':'private'}]
    assert scan_public(r, ['private'])['status']=='FAIL'
    r['candidates']=[]
    r['available_items']=[{},{}]
    assert scan_public(r)['status']=='FAIL'
