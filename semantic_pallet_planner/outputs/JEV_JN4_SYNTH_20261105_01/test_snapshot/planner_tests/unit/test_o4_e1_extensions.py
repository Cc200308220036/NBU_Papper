import copy
import json
import ast
from pathlib import Path
import pytest

from semantic_pallet_planner.config import generator_config, load_config
from semantic_pallet_planner.o4.common import O4Error, digest
from semantic_pallet_planner.o4.extensions import protocol, reference, runtime, validation
from semantic_pallet_planner.o4.extensions.compiler import compile_policy, parse_instruction, render_policy
from semantic_pallet_planner.o4.extensions.data import dataset, gold_cases, construct_cases, request, policy, spatial, region, make_item
from semantic_pallet_planner.o4.extensions.candidates import generate
from semantic_pallet_planner.o4.extensions.planning import choose, action_for, commit
from semantic_pallet_planner.o4.extensions.episode import episode, verify_episode, stable
from semantic_pallet_planner.o4.buffer.buffer_state import initial, receive


@pytest.mark.parametrize('row',gold_cases(),ids=lambda r:r['case_id'])
def test_arithmetic_gold(row):
    assert validation.gold([row])[0]['passed']


@pytest.mark.parametrize('row',dataset()['invalid'],ids=lambda r:r['purpose'])
def test_invalid_protocol(row):
    assert validation.invalid([row],gold_cases()[0]['request'])[0]['passed']


def test_old_gold_regression_and_pairs():
    assert all(r['passed'] for r in validation.regression())
    records,checks=validation.pairs(dataset()['pairs'])
    assert len(records)==48 and len(checks)==24
    assert all(r['passed'] for r in checks)


@pytest.mark.parametrize('change',['region','capacity','slot','eos','instruction','request'])
def test_stale_response_bindings(change):
    q,_=request();response=compile_policy(q);other=copy.deepcopy(q)
    if change=='region':other['regions'][0]['x_min_mm']-=1
    elif change=='capacity':other['buffer_context']['capacity']=2
    elif change=='slot':other['buffer_context']['capacity']=2;other['buffer_context']['pending'][0]['slot']=1
    elif change=='eos':other['buffer_context']['end_of_stream']=True
    elif change=='instruction':other['instruction_text']+=' '
    else:other['request_id']+='next'
    other=protocol.rebind(other)
    with pytest.raises(O4Error,match='invalid_binding'):protocol.validate_response(response,other)


def test_depth_and_schema_agree_and_diagnostics_have_path():
    q,_=request();p=policy([spatial()])
    p['rules'][0]['target']={'not':{'not':{'not':{'all':True}}}}
    protocol.validate_policy(p,q)
    p['rules'][0]['target']={'not':p['rules'][0]['target']}
    with pytest.raises(O4Error,match='path'):protocol.validate_policy(p,q)


@pytest.mark.parametrize('number',[True,float('nan'),float('inf'),'100'])
def test_non_numeric_region(number):
    q,_=request();q['regions'][0]['x_min_mm']=number
    with pytest.raises(O4Error):protocol.rebind(q)


def test_no_label_direction_ast_and_upright_only():
    q,_=request();p=policy([spatial()]);p['rules'][0]['type']='label_facing_up'
    with pytest.raises(O4Error):protocol.validate_policy(p,q)
    q['available_objects'][0]['pose']={'roll_deg':180}
    with pytest.raises(O4Error):protocol.rebind(q)


def test_semantic_equivalence_and_component_metrics():
    q,_=request();a=policy([spatial(),{'rule_id':'l','type':'no_top_load','target':{'all':True},'priority':20,'overrides':[]}])
    b=copy.deepcopy(a);b['rules'][1].update(type='max_top_load',limit={'constant_kg':0.})
    assert reference.compare(a,b,q['available_objects'])['semantic_equal']
    b=copy.deepcopy(a);b['rules'][0]['region_id']='wrong'
    m=reference.compare(a,b,q['available_objects'])
    assert not m['semantic_equal'] and m['applicable_objects_equal'] and m['region_references_equal'] is False
    b=copy.deepcopy(a);b['rules'][0]['target']={'object_ids':['box']}
    m=reference.compare(a,b,q['available_objects'])
    assert not m['semantic_equal'] and m['applicable_objects_equal']
    assert m['region_references_equal'] is None and not m['conditions_exceptions_equal']


def test_region_enrichment_is_public_and_recovers_two_orders():
    cfg=generator_config(load_config())
    for task in construct_cases()[:2]:
        s=receive(initial(task['container']),task['items'][0],task['attributes']['b0'])
        q=protocol.observation(s,task['instruction_text'],task['regions'])
        result,audit=generate(s,'b0',task['regions'],cfg)
        assert len(result)<=16
        assert not runtime.evaluate_candidates(q,task['reference_policy'],audit['baseline_candidates'])['allowed_ids']
        assert runtime.evaluate_candidates(q,task['reference_policy'],result)['allowed_ids']
        text_changed=copy.deepcopy(task);text_changed['instruction_text']='not passed to generate'
        assert generate(s,'b0',text_changed['regions'],cfg)[0]==result


@pytest.mark.parametrize('side',[-1,1])
def test_exact_epsilon_boundary(side):
    from semantic_pallet_planner.o4.extensions.data import candidate
    q,_=request();p=policy([spatial()]);c=candidate(x=side*(100+1e-6))
    assert runtime.evaluate_candidates(q,p,[c])['allowed_ids']==reference.audit(q,p,[c])['allowed_ids']==['C']


@pytest.mark.parametrize('planner',['single','buffer_fifo','buffer_heuristic','buffer_search'])
@pytest.mark.parametrize('index',[0,4,8])
def test_order_close_loop_repeat_restore(planner,index):
    task=construct_cases()[index];cfg=generator_config(load_config())
    result=episode(task,'public_parser',planner,cfg)
    assert result['summary']['completed']==task['expected_completed']
    assert not result['summary']['final_business_violations']
    checkpoint=result['checkpoints'][1]
    restored=episode(task,'public_parser',planner,cfg,resume=checkpoint)
    assert stable(restored['events'])==stable(result['events'])
    assert verify_episode(result,task,cfg)['independent_physics']
    for event in result['events']:
        if event['event']=='PLACE':assert event['search_trace']['evaluations']<=256


def test_reference_no_runtime_or_planner_imports():
    tree=ast.parse(Path(reference.__file__).read_text())
    assert not any(n.module and set(n.module.split('.')) & {'runtime','normalize','planning','candidates','compiler'}
                   for n in ast.walk(tree) if isinstance(n,ast.ImportFrom))


def test_actual_legal_wrong_ast_is_not_fixed_by_reference():
    r=episode(construct_cases()[4],'public_parser','single',generator_config(load_config()),fault='drop_rules')
    assert r['summary']['completed'] and r['summary']['final_business_violations']


def test_stop_tamper_detected():
    task=construct_cases()[4];cfg=generator_config(load_config());r=episode(task,'oracle_ast','single',cfg)
    r['events'][-1]['event']='PLACE'
    with pytest.raises(O4Error):verify_episode(r,task,cfg)


def test_tilted_candidate_rejected_before_commit():
    from semantic_pallet_planner.o4.extensions.data import candidate
    q,_=request();c=candidate();c['pose']['roll_deg']=180
    with pytest.raises(O4Error,match='upright'):runtime.evaluate_candidates(q,policy([spatial()]),[c])


def test_recomputed_digest_does_not_hide_candidate_pool_tamper():
    task=construct_cases()[0];cfg=generator_config(load_config());r=episode(task,'public_parser','single',cfg)
    event=next(e for e in r['events'] if e.get('action'))
    event['candidates']=copy.deepcopy(event['candidates'])
    event['candidates'][0]['pose']['x_mm']+=.125
    event['action']['candidate_set_digest']=digest(event['candidates'])
    with pytest.raises(O4Error,match='candidate_pool'):verify_episode(r,task,cfg)


def test_object_id_renaming_preserves_arrival_choice_and_geometry():
    task=construct_cases()[0];renamed=copy.deepcopy(task)
    mapping={f'b{i}':f'z{3-i}' for i in range(4)}
    renamed['attributes']={mapping[k]:{**v,'object_id':mapping[k]} for k,v in renamed['attributes'].items()}
    for obj in renamed['items']:obj['item_id']=mapping[obj['item_id']]
    cfg=generator_config(load_config())
    left=episode(task,'public_parser','buffer_search',cfg)
    right=episode(renamed,'public_parser','buffer_search',cfg)
    def actions(result):
        return [(next(i for i,p in enumerate(result['final_state']['arrived_ids']) if p==c['pick_item_id']),c['pose'],c['oriented_size_mm'])
                for e in result['events'] if e.get('action')
                for c in e['candidates'] if c['candidate_id']==e['action']['candidate_id']]
    assert actions(left)==actions(right)
