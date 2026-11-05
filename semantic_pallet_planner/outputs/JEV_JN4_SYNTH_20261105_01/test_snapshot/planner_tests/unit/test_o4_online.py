"""C: real ranking/commit boundaries and independently specified opportunities."""
import copy
import inspect

import pytest

from semantic_pallet_planner.config import generator_config,load_config
from semantic_pallet_planner.o4.common import O4Error,digest
from semantic_pallet_planner.o4.compiler import compile_policy
from semantic_pallet_planner.o4.fixtures import policy
from semantic_pallet_planner.o4.observation import rebind
from semantic_pallet_planner.o4.online import planner_adapter as adapter
from semantic_pallet_planner.o4.online.cases import opportunity_cases,run_opportunities,diagnostic_scenario
from semantic_pallet_planner.o4.online.episode import episode,compile_backend
from semantic_pallet_planner.o4.online.validation import invariance_checks,diagnostics
from semantic_pallet_planner.runners.o4_online import offline_network_guard,load_online_config


@pytest.mark.parametrize('index',range(6))
def test_predeclared_cross_business_opportunity_has_real_action_change(index):
    result=run_opportunities([opportunity_cases()[index]])[0]
    assert result['passed'] and result['allowed_set_changed'] and result['action_changed']
    assert all(v['committed_label'] is not None and not v['physical_errors'] for v in result['variants'])
    assert result['variants'][0]['selected_pose']['z_base_mm']==100
    assert result['variants'][1]['selected_pose']['z_base_mm']==0


def test_submit_checks_all_bindings_and_candidate_mapping():
    v=opportunity_cases()[0]['variants'][0]
    req=v['request'];response=compile_policy(req);public,_=adapter.labeled_candidates(v['raw_candidates'])
    label,_,_=adapter.select_layout(req,response['policy_ast'],public)
    action=adapter.action_for(req,public,label)
    for field in ('request_id','state_hash','observation_digest','instruction_digest','candidate_set_digest'):
        bad={**action,field:'stale'}
        with pytest.raises(O4Error,match='invalid_binding'):
            adapter.submit_action(v['state'],v['attributes'],req,v['raw_candidates'],response,bad)
    with pytest.raises(O4Error,match='invalid_candidate'):
        adapter.submit_action(v['state'],v['attributes'],req,v['raw_candidates'],response,{**action,'label':'C99'})
    altered=copy.deepcopy(v['raw_candidates']);altered[0]['pose']['x_mm']+=1
    with pytest.raises(O4Error,match='candidate set changed'):
        adapter.submit_action(v['state'],v['attributes'],req,altered,response,action)
    state=copy.deepcopy(v['state']);state['placed_items'][0]['pose']['x_mm']+=1
    with pytest.raises(O4Error,match='invalid_binding'):
        adapter.submit_action(state,v['attributes'],req,v['raw_candidates'],response,action)


def test_business_rejection_does_not_commit_wrong_label():
    v=opportunity_cases()[0]['variants'][1]
    req=v['request'];public,_=adapter.labeled_candidates(v['raw_candidates'])
    response=compile_policy(req)
    forbidden=next(c['candidate_id'] for c in public if c['pose']['z_base_mm']==100)
    action=adapter.action_for(req,public,forbidden)
    placed,status,errors=adapter.submit_action(v['state'],v['attributes'],req,v['raw_candidates'],response,action)
    assert placed is None and status=='business_rejection' and not errors


def test_unknown_top_k_duplicate_pose_and_invalid_scores_rejected():
    v=opportunity_cases()[0]['variants'][0]
    with pytest.raises(O4Error):adapter.labeled_candidates(v['raw_candidates']*9)
    with pytest.raises(O4Error):adapter.labeled_candidates(v['raw_candidates']*2)
    req=v['request'];public,_=adapter.labeled_candidates(v['raw_candidates'])
    public[0]['geometry_score']=float('nan')
    with pytest.raises(ValueError):adapter.select_layout(req,policy([]),public)


def test_regenerated_invariance_and_physical_negative_probes():
    assert all(r['passed'] for r in invariance_checks())
    records=diagnostics(generator_config(load_config()))
    assert all(r['passed'] for r in records)
    invalid=next(r for r in records if r['case_id']=='physical_rejection')
    assert invalid['result']['committed_label'] is None
    assert 'out_of_bounds' in invalid['result']['physical_errors']


def test_reference_does_not_intercept_valid_but_wrong_ast(monkeypatch):
    from semantic_pallet_planner.o4.online import episode as module
    scenario,attrs,task=diagnostic_scenario();cfg=generator_config(load_config())
    before=digest(scenario)
    row,events=episode(scenario,attrs,task,'public_parser',cfg,fault='drop_rules')
    assert row['completed'] and row['final_business_violation_count']>0 and row['physical_violations']==0
    original=module.audit_reference
    def deny_all(*args,**kwargs):
        value=original(*args,**kwargs);value['allowed_ids']=[];return value
    monkeypatch.setattr(module,'audit_reference',deny_all)
    other,events2=episode(scenario,attrs,task,'public_parser',cfg,fault='drop_rules')
    assert [e['committed_label'] for e in events2]==[e['committed_label'] for e in events]
    assert other['placed_items']==row['placed_items'] and digest(scenario)==before
    assert 'from ..evaluator' not in inspect.getsource(adapter)
    assert 'oracle_policy' not in inspect.signature(adapter.select_and_commit).parameters


def test_soft_targets_na_anchor_budget_and_stable_ties():
    v=opportunity_cases()[0]['variants'][0];req=v['request']
    public,_=adapter.labeled_candidates(v['raw_candidates'])
    _,trace,_=adapter.select_layout(req,policy([]),public)
    assert trace['anchor_soft_quality']==[None,None]
    tied=copy.deepcopy(public)
    for c in tied:c['geometry_score']=1.
    assert adapter.select_layout(req,policy([]),tied)[0]=='C01'
    heavy=copy.deepcopy(req)
    for k in ('placed_objects','available_objects'):
        for o in heavy[k]:o['weight_class']='heavy'
    heavy=rebind(heavy)
    label,trace,_=adapter.select_layout(heavy,policy([]),public)
    assert all(loss is None or loss<=budget+1e-6 for loss,budget in zip(trace['soft_loss_from_anchor'],(.05,.25)))
    assert trace['anchor_label'] in trace['eligible_labels'] and label in trace['eligible_labels']


def test_current_decision_never_receives_future_object_facts():
    scenario,attrs,task=diagnostic_scenario();cfg=generator_config(load_config())
    row,events=episode(scenario,attrs,task,'public_parser',cfg)
    for e in events:
        seen=set(scenario['arrival_order'][:e['step_index']+1])
        visible={o['object_id'] for k in ('placed_objects','available_objects') for o in e['request'][k]}
        assert visible==seen
        assert 'planned_items' not in e['request'] and 'scenario_id' not in e['request']
    other=copy.deepcopy(scenario);other['items'][-1]['mass_kg']=99.
    row2,events2=episode(other,attrs,task,'public_parser',cfg)
    assert events2[0]==events[0]
    with pytest.raises(O4Error):compile_backend(events[0]['request'],'flash')


def test_offline_guard_blocks_network_and_restores_socket():
    import socket
    old=socket.create_connection
    with offline_network_guard() as ledger:
        with pytest.raises(RuntimeError,match='forbids network'):socket.create_connection(('example.invalid',80))
        assert ledger['network_attempts']==1
    assert socket.create_connection is old


def test_frozen_online_config_rejects_budget_or_method_changes(tmp_path):
    import yaml
    cfg=load_online_config();cfg['soft_budgets']=[1.,1.]
    path=tmp_path/'wrong.yaml';path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError,match='frozen'):load_online_config(path)
