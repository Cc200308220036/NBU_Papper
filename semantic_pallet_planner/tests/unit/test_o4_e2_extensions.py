import copy
import inspect
import ast
from pathlib import Path
import pytest

from semantic_pallet_planner.config import generator_config,load_config
from semantic_pallet_planner.o4.common import O4Error,digest
from semantic_pallet_planner.o4.extensions.e2 import protocol,runtime,reference,validation
from semantic_pallet_planner.o4.extensions.e2.data import dataset,gold_cases,construct_cases,request,policy,relative,object_at,candidate
from semantic_pallet_planner.o4.extensions.e2.compiler import compile_policy,parse_instruction,render_policy
from semantic_pallet_planner.o4.extensions.e2.candidates import generate
from semantic_pallet_planner.o4.extensions.e2.episode import episode,verify_episode,stable
from semantic_pallet_planner.o4.extensions.e2.witnesses import all_witnesses


@pytest.mark.parametrize('row',gold_cases(),ids=lambda x:x['case_id'])
def test_independent_arithmetic_gold(row):
    assert validation.gold([row])[0]['passed']


@pytest.mark.parametrize('row',dataset()['invalid'],ids=lambda x:x['purpose'])
def test_invalid_protocol(row):
    assert validation.invalid([row],gold_cases()[0]['request'])[0]['passed']


def test_pairs_and_previous_stage_regression():
    rows,checks=validation.pairs(dataset()['pairs'])
    assert len(rows)==48 and all(r['passed'] for r in checks)
    assert sum(r['allowed_set_changed'] for r in checks if r['backend']=='public_parser')>=4
    assert sum(r['action_changed'] for r in checks if r['backend']=='public_parser')>=2
    old=validation.regression();assert len(old)==108 and all(r['passed'] for r in old)


@pytest.mark.parametrize('direction,inverse',[('left_of','right_of'),('right_of','left_of'),('front_of','behind'),('behind','front_of')])
def test_inverse_with_swapped_roles_is_equivalent(direction,inverse):
    a=policy([relative(direction=direction,gap=50.)]);b=copy.deepcopy(a)
    b['rules'][0].update(relation=inverse,subject=a['rules'][0]['reference'],reference=a['rules'][0]['subject'],rule_id='new_id')
    assert reference.signature(a)==reference.signature(b)
    q,_=request(a,placed=[object_at('B','household_cleaner')])
    m=reference.compare(a,b,q['placed_objects']+q['available_objects'])
    assert m['semantic_equal'] and m['relation_direction_equal'] and m['relation_gap_equal']
    assert m['raw_subject_selectors_equal'] is False


def test_wrong_direction_gap_and_object_diagnostics_are_separate():
    a=policy([relative(gap=50.)]);q,_=request(a,placed=[object_at('B','household_cleaner')]);objects=q['placed_objects']+q['available_objects']
    b=copy.deepcopy(a);b['rules'][0]['relation']='right_of'
    m=reference.compare(b,a,objects)
    assert not m['semantic_equal'] and m['relation_endpoint_sets_equal'] and not m['relation_direction_equal'] and m['relation_gap_equal']
    b=copy.deepcopy(a);b['rules'][0]['min_gap_mm']=51.
    m=reference.compare(b,a,objects)
    assert not m['semantic_equal'] and m['relation_endpoint_sets_equal'] and m['relation_direction_equal'] and not m['relation_gap_equal']
    b=copy.deepcopy(a);b['rules'][0]['reference']={'eq':{'field':'cargo_category','value':'electronics'}}
    m=reference.compare(b,a,objects)
    assert not m['semantic_equal'] and m['relation_gap_equal'] is None and not m['conditions_exceptions_equal']


def test_duplicate_endpoint_scope_is_ambiguous_not_guessed():
    a=policy([relative(),relative('r2',gap=50)])
    q,_=request(a,placed=[object_at('B','household_cleaner')])
    m=reference.compare(a,a,q['placed_objects']+q['available_objects'])
    assert m['semantic_equal'] and m['relation_component_alignment']=='AMBIGUOUS'
    assert m['relation_gap_equal'] is None and m['relation_direction_equal'] is None


@pytest.mark.parametrize('direction,axis,sign',[('left_of','x',-1),('right_of','x',1),('front_of','y',-1),('behind','y',1)])
def test_exact_epsilon_boundary_decimal(direction,axis,sign):
    a=policy([relative(direction=direction)])
    q,_=request(a,placed=[object_at('B','household_cleaner')])
    c=candidate(x=sign*99.999999 if axis=='x' else 0,y=sign*99.999999 if axis=='y' else 0)
    assert runtime.evaluate_candidates(q,a,[c])['allowed_ids']==reference.audit(q,a,[c])['allowed_ids']==['C']
    if axis=='x':c['pose']['x_mm']=sign*99.999998
    else:c['pose']['y_mm']=sign*99.999998
    assert runtime.evaluate_candidates(q,a,[c])['allowed_ids']==reference.audit(q,a,[c])['allowed_ids']==[]


def test_pending_endpoints_and_absent_future_have_no_invented_pose():
    row=gold_cases()[21];r=runtime.evaluate_candidates(row['request'],row['reference_policy'],row['candidates'])
    after=r['evaluations'][0]['after']
    assert len(after['deferred_relations'])==1 and after['relation_status']['rel']['status']=='deferred'
    assert after['relation_instances']==[] and 'pose' not in row['request']['available_objects'][1]
    missing=gold_cases()[20];r=reference.audit(missing['request'],missing['reference_policy'],missing['candidates'])
    assert r['evaluations'][0]['after']['relation_status']['rel']['status']=='deferred'


def test_all_pairs_and_full_existing_state_are_checked():
    row=gold_cases()[18]
    out=runtime.evaluate_candidates(row['request'],row['reference_policy'],row['candidates'])
    assert not out['allowed_ids'] and out['evaluations'][0]['after']['violations']
    assert len(out['evaluations'][0]['after']['relation_instances'])==2


def test_zero_gap_does_not_override_forbidden_contact():
    from semantic_pallet_planner.o4.fixtures import rule
    p=policy([relative()]);q,_=request(p,placed=[object_at('B','household_cleaner')]);c=candidate(x=-100)
    assert runtime.evaluate_candidates(q,p,[c])['allowed_ids']==['C']
    p['rules'].append(rule('contact','forbidden_contact'))
    assert not runtime.evaluate_candidates(q,p,[c])['allowed_ids']


@pytest.mark.parametrize('change',['request','instruction','slot','eos','grid','coordinate'])
def test_binding_and_capability_changes_rejected(change):
    p=policy([relative()]);q,_=request(p,placed=[object_at('B','household_cleaner')]);r=compile_policy(q);other=copy.deepcopy(q)
    if change=='request':other['request_id']+='new'
    elif change=='instruction':other['instruction_text']+=' '
    elif change=='slot':other['buffer_context']['capacity']=2;other['buffer_context']['pending'][0]['slot']=1
    elif change=='eos':other['buffer_context']['end_of_stream']=True
    elif change=='grid':other['sampling_grid_mm']=[0,75]
    else:other['coordinate_convention']='screen_xy'
    with pytest.raises(O4Error):protocol.validate_response(r,protocol.rebind(other))


def test_default_gap_and_schema_depth_limits():
    text=render_policy(policy([relative()])).replace('；最小间距0.0mm','').replace('；最小间距0mm','')
    assert parse_instruction(text)['rules'][0]['min_gap_mm']==0
    p=policy([relative()]);p['rules'][0]['subject']={'not':{'not':{'not':{'all':True}}}};protocol.validate_policy(p)
    p['rules'][0]['subject']={'not':p['rules'][0]['subject']}
    with pytest.raises(O4Error,match='path'):protocol.validate_policy(p)


def test_public_sampler_and_cached_copies_have_no_private_input():
    from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive
    t=construct_cases()[0];s=initial(t['container'],3)
    for o in t['items'][:3]:s=receive(s,o,t['attributes'][o['item_id']])
    cfg=generator_config(load_config());a,audit=generate(s,'A',t['regions'],cfg)
    other=copy.deepcopy(s);other['future_items']=[{'impossible':'secret'}]
    b,_=generate(other,'A',t['regions'],cfg);assert a==b
    a[0]['pose']['x_mm']+=1
    c,_=generate(s,'A',t['regions'],cfg);assert c==b
    assert set(inspect.signature(generate).parameters)=={'state','pick','regions','config'}
    assert len(c)<=16 and audit['sampling_grid_mm']==[0,50,100]


def test_cached_runtime_and_reference_results_do_not_alias():
    row=gold_cases()[0];q=row['request'];p=row['reference_policy']
    a=runtime.evaluate_candidates(q,p,row['candidates']);a['evaluations'][0]['after']['relation_instances'].clear()
    b=runtime.evaluate_candidates(q,p,row['candidates']);assert b['evaluations'][0]['after']['relation_instances']
    a=reference.audit(q,p,row['candidates']);a['evaluations'][0]['after']['relation_status'].clear()
    assert reference.audit(q,p,row['candidates'])['evaluations'][0]['after']['relation_status']


@pytest.mark.parametrize('index',[0,2,3,4,8])
@pytest.mark.parametrize('planner',['single','buffer_fifo','buffer_heuristic','buffer_search'])
def test_order_modes_repeat_restore_and_independent_recomputation(index,planner):
    t=construct_cases()[index];cfg=generator_config(load_config());r=episode(t,'public_parser',planner,cfg)
    assert r['summary']['completed']==t['expected_by_planner'][planner]
    assert not r['summary']['final_business_violations']
    assert verify_episode(r,t,cfg)['independent_physics']
    restored=episode(t,'public_parser',planner,cfg,resume=r['checkpoints'][1])
    assert stable(restored['events'])==stable(r['events'])
    for e in r['events']:
        if 'search_trace' in e:
            assert e['search_trace']['evaluations']<=256
            assert e['search_trace'].get('max_depth',0)<=3 and e['search_trace'].get('max_beam',0)<=8


def test_manual_paths_and_negative_certificates_are_independent():
    rows=all_witnesses(construct_cases());assert len(rows)==12 and all(r['passed'] for r in rows)
    assert sum(r['kind']=='physical_only' for r in rows)==4
    for r in rows:
        if r['kind']=='physical_only':assert r['analytic_certificate']['contradiction']


def test_reference_import_boundary():
    tree=ast.parse(Path(reference.__file__).read_text())
    for n in ast.walk(tree):
        if isinstance(n,ast.ImportFrom):assert not set((n.module or '').split('.')) & {'runtime','planning','compiler','normalize','candidates'}


def test_wrong_legal_direction_ast_is_exposed_not_repaired():
    t=construct_cases()[0];r=episode(t,'public_parser','single',generator_config(load_config()),fault='invert_relation')
    assert r['summary']['completed'] and r['summary']['final_business_violations']


def test_tampered_candidates_with_recomputed_digest_still_rejected():
    t=construct_cases()[0];cfg=generator_config(load_config());r=episode(t,'public_parser','single',cfg)
    e=next(e for e in r['events'] if e.get('action'));e['candidates']=copy.deepcopy(e['candidates']);e['candidates'][0]['pose']['x_mm']+=.125
    e['action']['candidate_set_digest']=digest(e['candidates'])
    with pytest.raises(O4Error,match='candidate_pool'):verify_episode(r,t,cfg)


def test_public_sampler_and_planner_are_invariant_to_object_id_rename():
    from semantic_pallet_planner.o4.extensions.e2.planning import select_layout
    p=policy([relative()]);q,s=request(p,placed=[object_at('B','household_cleaner')]);cfg=generator_config(load_config())
    c,_=generate(s,'A',[],cfg);selected,_,_=select_layout(q,p,c)
    renamed=__import__('json').loads(__import__('json').dumps(s).replace('"A"','"ZZ"').replace('"B"','"YY"'))
    q2=protocol.observation(renamed,q['instruction_text'],[])
    c2,_=generate(renamed,'ZZ',[],cfg);selected2,_,_=select_layout(q2,p,c2)
    assert [v['pose'] for v in c]==[v['pose'] for v in c2]
    assert selected['pose']==selected2['pose']


def test_zero_load_alias_is_retained_with_relative_rules():
    from semantic_pallet_planner.o4.fixtures import rule
    a=policy([relative(),rule('load',limit=0.)]);b=copy.deepcopy(a)
    b['rules'][1]['type']='no_top_load';b['rules'][1].pop('limit',None)
    assert reference.signature(a)==reference.signature(b)
    b['rules'][0]['priority']+=1
    assert reference.signature(a)!=reference.signature(b)


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-float('inf'),True])
def test_nonfinite_and_boolean_gaps_rejected(value):
    p=policy([relative(gap=value)])
    with pytest.raises(O4Error):protocol.validate_policy(p)


def test_exact_rule_limit_and_no_implicit_new_rule_override():
    p=policy([relative(identifier=f'r{i}') for i in range(32)]);protocol.validate_policy(p)
    p['rules'].append(relative(identifier='r32'))
    with pytest.raises(O4Error):protocol.validate_policy(p)
    p=policy([relative()]);p['rules'][0]['overrides']=['rel']
    with pytest.raises(O4Error):protocol.validate_policy(p)


@pytest.mark.parametrize('field,value',[('roll_deg',0),('pitch_deg',180),('yaw_deg',180),('yaw_deg',89.9),('yaw_deg',True)])
def test_candidate_upright_and_discrete_angles_are_closed(field,value):
    p=policy([relative()]);q,_=request(p);c=candidate();c['pose'][field]=value
    with pytest.raises(O4Error):protocol.validate_candidates(q,[c])


def test_side_label_rejected_even_with_rebound_observation():
    q,_=request(policy([relative()]));q['available_objects'][0]['label_face']='pos_x'
    with pytest.raises(O4Error):protocol.rebind(q)
