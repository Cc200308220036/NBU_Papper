import copy
import pytest
from semantic_pallet_planner.config import generator_config,load_config
from semantic_pallet_planner.o4.buffer.cases import run_constructs,construct_cases
from semantic_pallet_planner.o4.buffer.buffer_evaluation import episode,audit_events,stable
from semantic_pallet_planner.o4.buffer.buffer_search import ranked

@pytest.fixture(scope='module')
def results():return run_constructs(generator_config(load_config()))

@pytest.mark.parametrize('index',range(12))
def test_independent_small_tree_and_declared_business_outcome(results,index):
    assert results[index]['passed']
    for key in ('single_events','search_events'):assert audit_events(results[index][key])['status']=='PASS'


def test_opportunity_and_negative_quotas(results):
    assert len({r['family'] for r in results})==4
    assert sum(r['decision_opportunity'] and r['reordered'] for r in results)==4
    assert sum(r['decision_opportunity'] and r['progress_gain']>0 for r in results)>=2
    assert sum(r['expected_no_progress_gain'] for r in results)>=4


def test_maximum_anchored_ties_are_not_pairwise():
    nodes=[{'score':[1,x,0,0,0],'tie':[i]} for i,x in [(0,0.),(1,.75e-12),(2,1.5e-12)]]
    assert [n['tie'][0] for n in ranked(nodes,use_remaining=True)]==[1,2,0]


def test_fifo_head_blocked_distinct_from_all_pending_infeasible():
    c=construct_cases()[6];cfg=generator_config(load_config())
    row,events,_=episode(c['scenario'],c['attributes'],c['task'],'buffer_fifo','oracle_ast',cfg)
    assert row['termination_reason']=='fifo_head_blocked'
    assert any(g['eligible'] for g in events[-1]['root_pools'][1:])


def test_checkpoint_binding_and_no_reference_repair():
    from semantic_pallet_planner.o4.common import O4Error
    c=construct_cases()[0];cfg=generator_config(load_config())
    _,_,cp=episode(c['scenario'],c['attributes'],c['task'],'buffer_search','oracle_ast',cfg,pause_after=1)
    cp['state']['end_of_stream']=True
    with pytest.raises(O4Error):episode(c['scenario'],c['attributes'],c['task'],'buffer_search','oracle_ast',cfg,checkpoint=cp)
    wrong,events,_=episode(c['scenario'],c['attributes'],c['task'],'buffer_search','public_parser',cfg,fault='drop_rules')
    assert wrong['completed'] and wrong['final_business_violation_count']>0 and not wrong['physical_violations']
