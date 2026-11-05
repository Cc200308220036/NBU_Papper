"""Independent expected values and O4 boundary/semantic regression tests."""
import copy
import inspect
import pytest
from semantic_pallet_planner.o4.common import O4Error
from semantic_pallet_planner.o4.fixtures import gold_cases,task_policy,render_policy,rule,policy,eq,item,fixture_request,candidate
from semantic_pallet_planner.o4.observation import derive_attributes,build_observation,rebind,validate_observation
from semantic_pallet_planner.o4.compiler import compile_policy,parse_instruction,response_for,validate_response
from semantic_pallet_planner.o4.normalize import validate_policy,normalize_policy
from semantic_pallet_planner.o4.executor import evaluate_candidates
from semantic_pallet_planner.o4 import evaluator
from semantic_pallet_planner.o4.invalid import invalid_cases,execute_invalid_case
from semantic_pallet_planner.o4.client import OfflineClient,compile_with_client
from semantic_pallet_planner.runners.o4 import equal,transport_checks

GOLD=gold_cases()

@pytest.mark.parametrize('case',GOLD,ids=lambda c:c['case_id'])
def test_hand_declared_gold(case):
    req=case['request'];ast=compile_policy(req)['policy_ast']
    for result in (evaluate_candidates(req,ast,case['candidates']),evaluator.audit_reference(req,case['reference_policy'],case['candidates'])):
        assert result['allowed_ids']==case['expected_allowed_ids']
        for key,expected in case['expected_after'].items():
            assert equal(result['evaluations'][0]['after'][key],expected),(case['case_id'],key)

@pytest.mark.parametrize('case',invalid_cases(),ids=lambda c:c['recipe'])
def test_declared_invalid_inputs(case):
    with pytest.raises(O4Error) as err:execute_invalid_case(case,GOLD[0]['request'])
    assert err.value.code==case['expected_code']

@pytest.mark.parametrize('configuration',range(6))
def test_controlled_grammar_composes_and_normalizes(configuration):
    reference=task_policy(configuration)
    actual=parse_instruction(render_policy(reference,paraphrase=True))
    assert normalize_policy(actual)==normalize_policy(reference)
    assert evaluator.semantic_signature(actual)==evaluator.semantic_signature(reference)


def test_normative_work_order_and_portraits():
    text='本订单普通箱按各自标签的累计顶部限载执行；带禁压标记的箱体禁止顶部加载。已加固且无禁压标记的玻璃制品外箱，改按订单指定的2 kg业务限载执行，替代其标签业务限载。食品外箱与清洁用品外箱允许同托盘，但不得直接面接触。所有箱体仍须满足独立物理承载限制。'
    assert normalize_policy(parse_instruction(text))==normalize_policy(task_policy(5))
    for c in GOLD[-6:]:
        assert c['group']=='overrides'
        ast=parse_instruction(text)
        assert evaluate_candidates(c['request'],ast,c['candidates'])['evaluations'][0]['after']['limits_kg']==c['expected_after']['limits_kg']


def test_reference_interpreter_is_not_runtime_alias():
    source=inspect.getsource(evaluator)
    for forbidden in ('from .executor','from .normalize','from .compiler','import executor'):
        assert forbidden not in source


def test_future_attributes_never_serialized_and_physical_limit_preserved():
    base=item('base');top=item('top')
    attrs={i['item_id']:i['_attributes'] for i in (base,top)}
    state={'request_id':'public','container':GOLD[0]['request']['container'],'placed_items':[base],'available_items':[top]}
    a=build_observation(state,attrs,'无额外业务硬约束。')
    attrs['not_arrived']={'answer':'hidden'}
    assert build_observation(state,attrs,'无额外业务硬约束。')==a
    attrs['base']['physical_top_load_limit_kg']=1000
    with pytest.raises(O4Error,match='invalid_observation'):build_observation(state,attrs,'无额外业务硬约束。')


def test_independent_attribute_generation_not_inferred_from_category():
    base=item('base');top=item('top',category='electronics')
    a=derive_attributes(base,'SCN_X',1)
    assert a==derive_attributes(base,'SCN_X',1)
    assert derive_attributes(top,'SCN_X',1)['cargo_category']=='electronics'
    assert a['physical_top_load_limit_kg']==base['top_load_limit_kg_synthetic']


def test_all_binding_fields_checked():
    req=GOLD[0]['request'];ast=GOLD[0]['reference_policy']
    for key in ('request_id','state_hash','observation_digest','instruction_digest'):
        response=response_for(req,ast);response[key]='other' if key=='request_id' else 'f'*64
        with pytest.raises(O4Error,match='invalid_binding'):validate_response(response,req)


def test_valid_but_wrong_policy_not_repaired_and_reference_detects_it():
    c=GOLD[0];req=c['request'];wrong=policy([])
    client=OfflineClient([response_for(req,wrong)])
    result=compile_with_client(req,client)
    assert result['status'] is None and len(client.calls)==1
    assert result['response']['policy_ast']==wrong
    assert evaluate_candidates(req,wrong,c['candidates'])['allowed_ids']==['TOP']
    assert evaluator.audit_reference(req,c['reference_policy'],c['candidates'])['allowed_ids']==[]
    assert not evaluator.compare_policies(wrong,c['reference_policy'],req['placed_objects'])['semantic_equal']


def test_untriggered_threshold_difference_is_semantic_error():
    req=GOLD[0]['request']
    a=policy([rule(limit=4)]);b=policy([rule(limit=5)])
    assert evaluate_candidates(req,a,GOLD[0]['candidates'])['allowed_ids']==evaluate_candidates(req,b,GOLD[0]['candidates'])['allowed_ids']
    comparison=evaluator.compare_policies(a,b,req['placed_objects'])
    assert not comparison['semantic_equal']
    assert not comparison['finite_domain_equal']


def test_rule_id_and_object_order_invariance():
    ast=task_policy(5);renamed=copy.deepcopy(ast)
    ids={r['rule_id']:'new_'+r['rule_id'] for r in ast['rules']}
    for r in renamed['rules']:
        r['rule_id']=ids[r['rule_id']];r['overrides']=[ids[k] for k in r['overrides']]
    renamed['rules'].reverse()
    assert normalize_policy(ast)==normalize_policy(renamed)
    assert evaluator.semantic_signature(ast)==evaluator.semantic_signature(renamed)


def test_selector_re_evaluated_on_later_arrival_and_id_renaming():
    ast=policy([rule(kind='no_top_load',target=eq('labels.no_top_load',True))])
    req=fixture_request([item('base',no_top=False)],item('top',no_top=True),ast)
    assert evaluate_candidates(req,ast,[candidate()])['allowed_ids']==['TOP']
    req['placed_objects'][0]['labels']['no_top_load']=True;req=rebind(req)
    assert evaluate_candidates(req,ast,[candidate()])['allowed_ids']==[]
    req['placed_objects'][0]['object_id']='renamed';req=rebind(req)
    assert evaluate_candidates(req,ast,[candidate()])['allowed_ids']==[]


def test_override_can_not_remove_unrelated_contact_rule():
    ast=task_policy(5);ast['rules'][2]['overrides'].append('r4')
    with pytest.raises(O4Error,match='invalid_ast'):validate_policy(ast)


def test_schema_limits_and_numeric_type_boundaries():
    ast=policy([rule()]);ast['rules'][0]['target']={'eq':{'field':'mass_kg','value':True}}
    with pytest.raises(O4Error):validate_policy(ast)
    for value in [float('nan'),float('inf'),-1]:
        ast=policy([rule()]);ast['rules'][0]['limit']['constant_kg']=value
        with pytest.raises(O4Error):validate_policy(ast)
    expr={'all':True}
    for _ in range(3):expr={'not':expr}
    validate_policy(policy([rule(target=expr)]))
    with pytest.raises(O4Error):validate_policy(policy([rule(target={'not':expr})]))
    with pytest.raises(O4Error):validate_policy(policy([rule(target={'object_ids':[f'obj_{i}' for i in range(65)]})]))


def test_offline_transport_image_repair_and_service_failures():
    assert all(row['passed'] for row in transport_checks(GOLD[0]['request']))


def test_nonfake_client_rejected_before_network():
    class Real:
        fake=False
        def complete(self,prompt):raise AssertionError('must not be called')
    with pytest.raises(O4Error,match='real API deferred'):compile_with_client(GOLD[0]['request'],Real())


def test_point_and_edge_contact_are_not_forbidden_faces():
    ast=policy([rule(kind='forbidden_contact')])
    req=fixture_request([item('base',category='food')],item('top',category='household_cleaner'),ast)
    # Relation unit probes; physical placement feasibility is checked by C, not inferred here.
    for c in [candidate(x=100,y=100,z=100),candidate(x=100,y=0,z=100)]:
        for result in (evaluate_candidates(req,ast,[c]),evaluator.audit_reference(req,ast,[c])):
            assert result['evaluations'][0]['after']['contact_pairs']==[]


def test_raw_json_and_malformed_reply_repair_keeps_original():
    import json
    req=GOLD[0]['request'];good=response_for(req,GOLD[0]['reference_policy'])
    client=OfflineClient(['{broken',json.dumps(good)])
    result=compile_with_client(req,client)
    assert result['status'] is None and len(client.calls)==2
    assert result['attempts'][0]['raw_response']=='{broken'
    assert result['attempts'][1]['raw_response']==json.dumps(good)
    assert client.calls[1]['repair_error']=='invalid_ast'
    assert 'reference' not in client.calls[1]


def test_all_rule_types_can_be_disabled_without_silent_label_enforcement():
    req=GOLD[0]['request']
    assert evaluate_candidates(req,policy([]),GOLD[0]['candidates'])['allowed_ids']==['TOP']
    assert normalize_policy(parse_instruction('无额外业务硬约束。'))['rules']==[]
    with pytest.raises(O4Error,match='unsupported_construct'):parse_instruction('请合理码放。')


def test_context_digest_changes_with_label_and_rejects_stale_reply():
    req=GOLD[0]['request'];response=response_for(req,GOLD[0]['reference_policy'])
    changed=copy.deepcopy(req);changed['placed_objects'][0]['labels']['max_top_load_kg']=99;changed=rebind(changed)
    assert changed['observation_digest']!=req['observation_digest']
    with pytest.raises(O4Error,match='invalid_binding'):validate_response(response,changed)
