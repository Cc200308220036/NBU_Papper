import copy
import json

import pytest

from semantic_pallet_planner.o4.fixtures import CONTAINER, rule
from semantic_pallet_planner.o4.extensions.data import region
from semantic_pallet_planner.o4.extensions.e2.data import object_at, policy, request
from semantic_pallet_planner.o4.extensions.e2.compiler import render_policy
from semantic_pallet_planner.o4.extensions.e2.protocol import observation
from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive
from semantic_pallet_planner.jev_select.candidates import CandidateProvider,PublicBusinessGuard,decision_route
from semantic_pallet_planner.jev_select.config import load_v2_config,load_config,generator_config
from semantic_pallet_planner.jev_select.context import ContextBuilder,validate_context,resolve_display_id
from semantic_pallet_planner.jev_select.contracts import CandidateBundle,DecisionContext,JevSelectError,digest,canonical,validate_schema
from semantic_pallet_planner.jev_select.episode import run_episode,decision_inputs,semantic_record
from semantic_pallet_planner.jev_select.execution import commit_physical
from semantic_pallet_planner.jev_select.selector import LocalSelector,JevSelector,bind_decision,result
from semantic_pallet_planner.jev_select.ledger import Ledger
from semantic_pallet_planner.jev_select.testing import OfflineTransport
from semantic_pallet_planner.jev_select.evaluation import evaluate_committed_state,summarize_business_trajectory
from semantic_pallet_planner.jev_select.dataset import DatasetOrderAdapter,business_spec,attribute_value


def task_with_region(count=3,*,tiny_container=False):
    data=[object_at(f'box{i}',size=(100,80,100)) for i in range(count)]
    ast=policy([{'rule_id':'tiny','type':'inside_region','target':{'all':True},'region_id':'R','priority':20,'overrides':[]}])
    return {'task_id':'violating','source_order_key':'diagnostic','source_kind':'constructed','negative':False,
            'container':dict(CONTAINER,length_mm=100,width_mm=80,max_height_mm=100) if tiny_container else copy.deepcopy(CONTAINER),
            'items':[o for o,a in data],'attributes':{a['object_id']:a for o,a in data},
            'instruction_text':render_policy(ast),'reference_policy':ast,'regions':[region('R',-5,5,-5,5)]}


def task_state(task,capacity=3):
    state=initial(task['container'],capacity)
    for item in task['items'][:capacity]:state=receive(state,item,task['attributes'][item['item_id']])
    return state


@pytest.mark.parametrize('method',['shared_geometry','shared_business_lexicographic'])
def test_A02_A04_A20_business_violations_do_not_stop_episode(method):
    task=task_with_region(); cfg=dict(load_v2_config(),selector=method)
    episode=run_episode(task,LocalSelector(method),cfg,job_id='J0',method=method)
    row=episode['summary']
    assert row['completed'] and not row['clean_completed'] and not row['final_clean_completed']
    assert row['termination_reason']=='ALL_ITEMS_PLACED' and row['placed_items']==3
    assert row['new_violation_events']==3 and row['unique_violation_instances']==3
    assert row['violating_steps']==3 and row['final_violation_instances']==3
    assert all(e.get('reason')!='STOP_NO_BUSINESS_CANDIDATE' for e in episode['events'])


def test_A03_singleton_violating_action_is_submitted_without_selector():
    class Forbidden:
        def select(self,*a,**k):raise AssertionError('singleton should not query')
    task=task_with_region(1,tiny_container=True)
    episode=run_episode(task,Forbidden(),dict(load_v2_config(),buffer_capacity=1),job_id='J0',method='jev_choice')
    assert episode['summary']['completed'] and episode['summary']['final_violation_instances']==1
    event=next(e for e in episode['events'] if e['event']=='PLACE')
    assert event['selection']['source']=='singleton' and event['selection']['attempt_ids']==[]


def test_A01_A11_A12_full_physical_pool_and_no_business_answer_features(monkeypatch):
    task=task_with_region();state=task_state(task);cfg=load_v2_config()
    def forbidden(*args,**kwargs):raise AssertionError('facts path must not evaluate business candidates')
    monkeypatch.setattr(PublicBusinessGuard,'evaluate',forbidden)
    req,p,b,c=decision_inputs(state,task,cfg,'J0','J0_D0000')
    assert b.data['physical_candidates']==b.data['selectable_candidates'] and len(c.data['criteria'])==48
    assert b.data['physical_digest']==b.data['selectable_digest']
    encoded=canonical(c.data['request_body'])
    for key in ('current_business_allowed','effective_business_limit_kg','remaining_business_limit_kg','reference_policy','policy_ast','new_violations','allowed_ids'):
        assert f'"{key}"' not in encoded
    assert 'some may violate business requirements' in encoded
    assert c.data['local_binding']['business_mode']=='evaluate_only'


@pytest.mark.parametrize('field,value',[('selectable_pool','hard_business_feasible'),('feature_version','features_basic_v1'),
    ('feature_version','features_public_predicates_v1'),('execution_version','legacy_business_commit'),('business_mode','hard'),('prompt_version','jev_direct_en_v1')])
def test_A31_incompatible_v2_combinations_rejected(field,value):
    cfg=load_v2_config();cfg[field]=value
    with pytest.raises(JevSelectError):validate_schema('config',cfg)


def test_A31_v1_context_not_accepted_by_physical_commit(pipeline):
    case,cfg,policy_context,bundle,context=pipeline
    selected=result(context,status='selected',source='local_baseline',label='C01')
    with pytest.raises(JevSelectError):
        commit_physical(case['state'],case['observation']['regions'],case['observation'],bundle,context,selected,load_v2_config())


def test_A08_stale_or_changed_selection_rejected():
    task=task_with_region();state=task_state(task);cfg=load_v2_config()
    req,p,b,c=decision_inputs(state,task,cfg,'J0','J0_D0000')
    selected=result(c,status='selected',source='local_baseline',label='C01')
    changed=copy.deepcopy(state);changed['event_index']+=1
    with pytest.raises(JevSelectError,match='stale'):
        commit_physical(changed,task['regions'],req,b,c,selected,cfg)
    forged=selected.data;forged['selected_candidate_id']='other'
    from semantic_pallet_planner.jev_select.selector import SelectionResult
    with pytest.raises(JevSelectError,match='mismatch'):
        commit_physical(state,task['regions'],req,b,c,SelectionResult.from_dict(forged),cfg)


@pytest.mark.parametrize('business_limit,kind',[(0.,'max_top_load'),(2.,'max_top_load'),(0.,'no_top_load')])
def test_A05_A06_business_load_limit_is_not_a_physical_rejection(business_limit,kind):
    ast=policy([rule('business',kind,target={'object_ids':['base']},limit=business_limit)])
    req,state=request(ast,placed=[object_at('base',no_top=True)],available=[object_at('top',mass=3.)],
                      container=dict(CONTAINER,length_mm=100,width_mm=100,max_height_mm=300))
    cfg=dict(load_v2_config(),buffer_capacity=1)
    guard=PublicBusinessGuard();p=guard.resolve(req)
    b=guard.filter(req,p,CandidateProvider().build(state,req,generator_config(),config=cfg),cfg)
    c=bind_decision(ContextBuilder(cfg).build(req,b,p),'J0','J0_D0000')
    labels=[l for l,f in c.data['criteria'].items() if f['pose']['z_base_mm']==100 and f['pose']['x_mm']==0 and f['pose']['y_mm']==0]
    assert labels
    selected=result(c,status='singleton' if c.data['route']=='SINGLETON_BYPASS' else 'selected',
                    source='singleton' if c.data['route']=='SINGLETON_BYPASS' else 'local_baseline',label=labels[0])
    after=commit_physical(state,req['regions'],req,b,c,selected,cfg)
    evaluation=evaluate_committed_state(after,ast,req['regions'])
    assert evaluation['instances'] and evaluation['instances'][0]['kind']==kind
    assert after['placed_count']==2


def test_A15_reference_policy_changes_only_downstream_evaluation():
    task=task_with_region();changed=copy.deepcopy(task);changed['reference_policy']=policy([])
    state=task_state(task);cfg=load_v2_config()
    a=decision_inputs(state,task,cfg,'J0','J0_D0000');b=decision_inputs(state,changed,cfg,'J0','J0_D0000')
    assert a[2].data==b[2].data and a[3].data==b[3].data
    assert run_episode(changed,LocalSelector('shared_geometry'),cfg,job_id='J0',method='shared_geometry')['summary']['final_violation_instances']==0


def test_A16_future_order_suffix_does_not_change_request():
    task=task_with_region(4);changed=copy.deepcopy(task)
    changed['items'][3]['mass_kg']+=10
    cfg=load_v2_config()
    a=decision_inputs(task_state(task),task,cfg,'J0','J0_D0000')
    b=decision_inputs(task_state(changed),changed,cfg,'J0','J0_D0000')
    assert a[3].data==b[3].data


@pytest.mark.parametrize('sequence,expected',[[[1,1,1],(1,1,3)],[[1,0,1],(2,1,2)]])
def test_A17_A18_onsets_persistence_and_recurrence(sequence,expected):
    rows=[{'event':'PLACE','business_after':{'instances':[{'identity':'one','rule_id':'r'}] if flag else []}} for flag in sequence]
    out=summarize_business_trajectory(rows,planned_items=3,rule_registry=[{'rule_id':'r','type':'inside_region'}])
    assert (out['new_violation_events'],out['unique_violation_instances'],out['violating_steps'])==expected


class PowerLoss(BaseException):pass


@pytest.mark.parametrize('phase',['after_reserve','after_response','before_commit','after_commit_checkpoint','after_checkpoint'])
def test_A25_recovery_across_response_commit_and_evaluation(tmp_path,phase):
    task=task_with_region();cfg=load_v2_config();ledger=Ledger(tmp_path,{'global_attempts':None,'per_job_attempts':None})
    transport=OfflineTransport(cfg);selector=JevSelector(cfg,ledger,'J0',transport)
    cps=[];fired=[]
    def crash(name,value):
        if name==phase and not fired and (phase!='after_checkpoint' or value['state']['placed_count']>=1):
            fired.append(True);raise PowerLoss()
    def checkpoint(value):cps.append(copy.deepcopy(value))
    ledger.hook=crash
    with pytest.raises(PowerLoss):
        run_episode(task,selector,cfg,job_id='J0',method='jev_choice',on_checkpoint=checkpoint,hook=crash)
    assert cps
    ledger=Ledger(tmp_path,{'global_attempts':None,'per_job_attempts':None})
    transport=OfflineTransport(cfg);selector=JevSelector(cfg,ledger,'J0',transport)
    restored=run_episode(task,selector,cfg,job_id='J0',method='jev_choice',resume=cps[-1])
    rows=ledger.data['attempts']
    assert len({(r['job_id'],r['decision_id']) for r in rows})==len(rows)
    if phase=='after_reserve':
        assert restored['summary']['termination_reason']=='UNKNOWN_IN_FLIGHT' and restored['summary']['placed_items']==0
    else:
        assert restored['summary']['completed'] and len({o['item_id'] for o in restored['final_state']['placed_items']})==3
        assert len(rows)==3


def test_A25_evaluation_failure_preserves_committed_state_and_recovers(monkeypatch):
    import semantic_pallet_planner.jev_select.evaluation as module
    task=task_with_region(1,tiny_container=True);cfg=dict(load_v2_config(),buffer_capacity=1)
    original=module.evaluate_committed_state
    def fail(*a,**k):raise ValueError('injected evaluation failure')
    monkeypatch.setattr(module,'evaluate_committed_state',fail)
    stopped=run_episode(task,LocalSelector('shared_geometry'),cfg,job_id='J0',method='shared_geometry')
    cp=stopped['checkpoint']
    assert cp['phase']=='COMMITTED' and cp['state']['placed_count']==1 and cp['reason']=='EVALUATION_ERROR'
    monkeypatch.setattr(module,'evaluate_committed_state',original)
    recovered=run_episode(task,LocalSelector('shared_geometry'),cfg,job_id='J0',method='shared_geometry',resume=cp)
    assert recovered['summary']['completed'] and len(recovered['final_state']['placed_items'])==1


@pytest.mark.parametrize('kind',['forbidden_contact','inside_region','relative_position'])
def test_A07_business_rule_families_allow_physical_submission(kind):
    from semantic_pallet_planner.o4.extensions.e2.data import relative
    if kind=='forbidden_contact':
        ast=policy([rule('contact','forbidden_contact')]);base=object_at('base','food');top=object_at('top','household_cleaner');regions=[]
    elif kind=='relative_position':
        ast=policy([relative('rel',subject={'object_ids':['top']},reference={'object_ids':['base']},direction='left_of',gap=50.)])
        base=object_at('base');top=object_at('top');regions=[]
    else:
        ast=policy([{'rule_id':'region','type':'inside_region','target':{'object_ids':['top']},'region_id':'R','priority':20,'overrides':[]}])
        base=object_at('base');top=object_at('top');regions=[region('R',-5,5,-5,5)]
    req,state=request(ast,placed=[base],available=[top],regions=regions,container=dict(CONTAINER,length_mm=100,width_mm=100,max_height_mm=300))
    cfg=dict(load_v2_config(),buffer_capacity=1);g=PublicBusinessGuard();p=g.resolve(req)
    b=g.filter(req,p,CandidateProvider().build(state,req,generator_config(),config=cfg),cfg)
    c=bind_decision(ContextBuilder(cfg).build(req,b,p),'J0','J0_D0000');label=next(iter(c.data['criteria']))
    selected=result(c,status='singleton' if c.data['route']=='SINGLETON_BYPASS' else 'selected',source='singleton' if c.data['route']=='SINGLETON_BYPASS' else 'local_baseline',label=label)
    after=commit_physical(state,regions,req,b,c,selected,cfg)
    assert any(i['kind']==kind for i in evaluate_committed_state(after,ast,regions)['instances'])


@pytest.mark.parametrize('physical_constraint',['non_stackable','overload'])
def test_A08_physical_stackability_and_capacity_remain_hard(physical_constraint):
    base,attrs=object_at('base')
    base['stackable']=physical_constraint!='non_stackable'
    if physical_constraint=='overload':
        base['top_load_limit_kg_synthetic']=.5;attrs['physical_top_load_limit_kg']=.5
    req,state=request(policy([]),placed=[(base,attrs)],available=[object_at('top',mass=2.)],container=dict(CONTAINER,length_mm=100,width_mm=100,max_height_mm=300))
    cfg=dict(load_v2_config(),buffer_capacity=1);g=PublicBusinessGuard();p=g.resolve(req)
    bundle=g.filter(req,p,CandidateProvider().build(state,req,generator_config(),config=cfg),cfg)
    assert not bundle.data['physical_candidates'] and decision_route(bundle)=='STOP_NO_PHYSICAL_CANDIDATE'


def test_A09_A10_another_box_can_be_selected_when_one_has_no_physical_pose():
    task=task_with_region(2);task['items'][0]['dimensions_mm']={'length':2000,'width':2000,'height':2000}
    cfg=load_v2_config();state=task_state(task)
    req,p,b,c=decision_inputs(state,task,cfg,'J0','J0_D0000')
    assert {x['pick_item_id'] for x in b.data['selectable_candidates']}=={'box1'}
    episode=run_episode(task,LocalSelector('shared_geometry'),cfg,job_id='J0',method='shared_geometry')
    assert episode['summary']['placed_items']==1 and episode['summary']['termination_reason']=='STOP_NO_PHYSICAL_CANDIDATE'


def test_A19_pending_relative_relation_is_deferred_not_satisfied():
    from semantic_pallet_planner.o4.extensions.e2.data import relative
    ast=policy([relative()]);req,state=request(ast,available=[object_at('a','food'),object_at('b','household_cleaner')],capacity=3)
    feedback=evaluate_committed_state(state,ast,[])
    assert not feedback['instances'] and feedback['coverage'][0]['deferred']==1
    assert feedback['coverage'][0]['status']=='deferred'


def test_A28_renamed_or_reordered_physical_pool_cannot_be_resigned_as_business_subset():
    task=task_with_region();state=task_state(task);cfg=load_v2_config()
    req,p,b,c=decision_inputs(state,task,cfg,'J0','J0_D0000')
    forged=b.data;forged['selectable_candidates']=forged['selectable_candidates'][:-1]
    forged['selectable_digest']=digest(forged['selectable_candidates'])
    with pytest.raises(JevSelectError,match='business_filtered'):
        from semantic_pallet_planner.jev_select.candidates import validate_bundle
        validate_bundle(req,CandidateBundle.from_dict(forged))


def test_A13_last_model_option_is_exactly_executed(tmp_path):
    task=task_with_region();cfg=load_v2_config();ledger=Ledger(tmp_path,{'global_attempts':None,'per_job_attempts':None})
    selector=JevSelector(cfg,ledger,'J0',OfflineTransport(cfg,'pick_last'))
    episode=run_episode(task,selector,cfg,job_id='J0',method='jev_choice')
    different_from_geometry=False
    for event in episode['events']:
        if event['event']!='PLACE':continue
        label=event['selection']['selected_display_id'];criteria=event['context']['criteria']
        assert label==sorted(criteria)[-1]
        mapped=event['context']['display_mapping'][label]
        candidate=next(c for c in event['bundle']['physical_candidates'] if c['candidate_id']==mapped['candidate_id'])
        actual=next(o for o in event['after']['placed_items'] if o['item_id']==candidate['pick_item_id'])
        assert actual['pose']==candidate['pose'] and actual['oriented_size_mm']==candidate['oriented_size_mm']
        from semantic_pallet_planner.jev_select.selector import baseline_label
        different_from_geometry |= label!=baseline_label(DecisionContext.from_dict(event['context']),'shared_geometry')
    assert different_from_geometry and episode['summary']['completed']


def test_A17_preexisting_violation_is_not_a_new_onset():
    initial={'instances':[{'identity':'existing','rule_id':'r'}]}
    events=[{'event':'PLACE','business_after':{'instances':[{'identity':'existing','rule_id':'r'}]}}]
    out=summarize_business_trajectory(events,planned_items=2,rule_registry=[{'rule_id':'r','type':'inside_region'}],initial_evaluation=initial)
    assert out['new_violation_events']==0 and out['unique_violation_instances']==1 and out['violating_steps']==1


def test_A19_unarrived_targets_are_not_certified_not_applicable():
    from semantic_pallet_planner.o4.extensions.e2.data import relative
    ast=policy([relative()]);req,state=request(ast,available=[object_at('a','general')],capacity=3)
    audit=evaluate_committed_state(state,ast,[])
    assert audit['coverage'][0]['status']=='deferred' and not audit['instances']
    task=task_with_region(4);episode=run_episode(task,LocalSelector('shared_geometry'),load_v2_config(),job_id='J0',method='shared_geometry')
    assert all(r['unarrived_instances']==0 and r['pending_or_unarrived_instances']==0 for r in episode['summary']['planned_rule_coverage'])


@pytest.mark.parametrize('case,expected_error',[('collision','overlap'),('bounds','out_of_bounds'),('unsupported','insufficient_support')])
def test_A08_commit_rejects_resigned_physically_invalid_candidate(case,expected_error):
    from semantic_pallet_planner.jev_select.candidates import validate_bundle
    req,state=request(policy([]),placed=[object_at('base')],available=[object_at('top')])
    cfg=dict(load_v2_config(),buffer_capacity=1);g=PublicBusinessGuard();pub=g.resolve(req)
    bundle=g.filter(req,pub,CandidateProvider().build(state,req,generator_config(),config=cfg),cfg)
    raw=bundle.data;c=raw['physical_candidates'][0]
    c['pose'].update(x_mm=0.,y_mm=0.,z_base_mm=0.)
    if case=='bounds':c['pose']['x_mm']=1000.
    if case=='unsupported':c['pose']['z_base_mm']=50.
    raw['physical_digest']=digest(raw['physical_candidates']);raw['selectable_candidates']=copy.deepcopy(raw['physical_candidates']);raw['selectable_digest']=raw['physical_digest']
    forged=CandidateBundle.from_dict(raw);validate_bundle(req,forged)
    ctx=bind_decision(ContextBuilder(cfg).build(req,forged,pub),'J0','J0_D0000')
    label=next(l for l,m in ctx.data['display_mapping'].items() if m['candidate_id']==c['candidate_id'])
    choice=result(ctx,status='selected',source='local_baseline',label=label)
    before=copy.deepcopy(state)
    with pytest.raises(JevSelectError,match=expected_error):commit_physical(state,[],req,forged,ctx,choice,cfg)
    assert state==before
