import pytest
from semantic_pallet_planner.jev_select.tests.unit.test_j3_core import task_with_region
from semantic_pallet_planner.jev_select.config import load_v3_config
from semantic_pallet_planner.jev_select.contracts import validate_schema,JevSelectError
from semantic_pallet_planner.jev_select.episode import run_episode
from semantic_pallet_planner.jev_select.selector import LocalSelector


def test_j4_capacity_is_fixed_at_three():
    for invalid in (1,2):
        with pytest.raises(JevSelectError):validate_schema('config',dict(load_v3_config(),buffer_capacity=invalid))


@pytest.mark.parametrize('empty',[False,True])
def test_v3_singleton_empty_and_business_evaluation_never_query_selector(empty):
    class Forbidden:
        def select(self,*a,**k):raise AssertionError('Singleton/empty must bypass selector')
    task=task_with_region(1,tiny_container=True)
    if empty:task['items'][0]['dimensions_mm']['length']=500
    ep=run_episode(task,Forbidden(),load_v3_config(),job_id='ROUTE',method='jev_no_memory')
    places=[e for e in ep['events'] if e['event']=='PLACE']
    assert len(places)==(0 if empty else 1)
    if not empty:assert places[0]['selection']['source']=='singleton'
    assert ep['summary']['final_violation_instances']==(0 if empty else 1)
    assert ep['summary']['termination_reason']==('STOP_NO_PHYSICAL_CANDIDATE' if empty else 'ALL_ITEMS_PLACED')


def test_v3_business_violation_does_not_terminate_order():
    task=task_with_region();cfg=dict(load_v3_config(),selector='shared_geometry')
    ep=run_episode(task,LocalSelector('shared_geometry'),cfg,job_id='BUSINESS',method='shared_geometry')
    assert ep['summary']['completed'] and ep['summary']['new_violation_events']==3
    assert len([e for e in ep['events'] if e['event']=='PLACE'])==3
