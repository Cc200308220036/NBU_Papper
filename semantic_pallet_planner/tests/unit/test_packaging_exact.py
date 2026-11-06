"""v3 exact geometry and v12 supplement; all transmissions are constructed."""
import copy
import socket
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select.stability.contracts import BoxInput,PlacedState
from semantic_pallet_planner.jev_select.stability import exact_adapter as exact
from semantic_pallet_planner.jev_select.stability import balance_adapter as v2
from semantic_pallet_planner.jev_select import packaging_exact_orders as supplement
from semantic_pallet_planner.jev_select import packaging_synthetic_orders as synthetic
from semantic_pallet_planner.jev_select import packaging_evaluation_orders as common
from semantic_pallet_planner.jev_select import transport
from semantic_pallet_planner.jev_select.contracts import JevSelectError,validate_schema
from semantic_pallet_planner.jev_select.ledger import read,write
from test_stability_balance import fixture_cases
from test_packaging_synthetic_execution import prepare,factory
from test_packaging_remote import Fake

@pytest.fixture(autouse=True)
def forbid_real_access(monkeypatch):
    def no(*a,**kw):pytest.fail('exact tests attempted real network or credentials')
    monkeypatch.setattr(socket.socket,'connect',no)
    monkeypatch.setattr(transport,'credential',no)

@pytest.mark.parametrize('name',[n for n in fixture_cases() if n!='height_mismatch'])
def test_exact_retains_analytic_balance_cases(name):
    state,candidate,status,_=fixture_cases()[name]
    before=copy.deepcopy(state)
    r=exact.assess_candidate(state,candidate).to_dict()
    assert r['status']==status
    assert state==before
    if status=='STABLE':
        d=r['diagnostics'];assert abs(d['global_mass_residual_kg'])<1e-8
        assert max(map(abs,d['global_moment_residual_kg_mm']))<1e-5

def cavity():
    pillars=(BoxInput('left',(100,100,180),1,(-100,0,0)),BoxInput('right',(100,100,180),1,(100,0,0)))
    shelf=BoxInput('shelf',(300,100,110),2,(0,0,180))
    return PlacedState((1000,800,1000),(*pillars,shelf)),BoxInput('insert',(40,80,140),1,(0,0,0))

def test_cavity_uses_exact_pose_and_old_algorithm_still_rejects_drop_mismatch():
    state,candidate=cavity();r=exact.assess_candidate(state,candidate).to_dict()
    assert r['status']=='STABLE' and r['height_delta_mm']==0
    assert r['evaluated_pose']['kernel_corner_mm'][2]==0
    assert not any(c['lower']=='insert' for c in r['diagnostics']['contact_rectangles'])
    old=v2.assess_candidate(state,candidate).to_dict()
    assert old['status']=='UNASSESSABLE' and old['reason_code']=='POSE_HEIGHT_MISMATCH'
    assert old['version']=='pct_stability_result_v2' and r['version']=='pct_stability_result_v3'

@pytest.mark.parametrize('kind',['overlap','floating','outside','duplicate','rotated'])
def test_exact_geometry_boundaries(kind):
    base=BoxInput('base',(100,100,100),1,(0,0,0));state=PlacedState((1000,800,1000),(base,))
    candidate=BoxInput('new',(100,100,100),1,(0,0,100))
    from dataclasses import replace
    if kind=='overlap':candidate=replace(candidate,bottom_center_mm=(0,0,50))
    elif kind=='floating':candidate=replace(candidate,bottom_center_mm=(0,0,101))
    elif kind=='outside':candidate=replace(candidate,bottom_center_mm=(500,0,0))
    elif kind=='duplicate':candidate=replace(candidate,item_id='base')
    else:candidate=replace(candidate,yaw_deg=90)
    r=exact.assess_candidate(state,candidate).to_dict()
    assert r['status']==('STABLE' if kind=='rotated' else 'UNASSESSABLE')
    if kind=='floating':assert r['reason_code']=='UNSUPPORTED_FLOATING_BOX'

def parent_run(tmp_path):
    p=prepare(tmp_path/'parent',tasks=2,n=2);f=Fake()
    synthetic.run_constructed(tmp_path/'parent/plan',tmp_path/'parent/run',transport_factory=factory(f))
    return p,f

def test_supplement_exact_six_methods_budget_and_completed_resume(tmp_path):
    old,f=parent_run(tmp_path)
    p=supplement.prepare(tmp_path/'parent/plan',tmp_path/'parent/run',tmp_path/'supplement/plan')
    assert [j['job_id'] for j in p['jobs']]==[j['job_id'] for j in old['jobs'][6:]]
    assert p['request_budget']['global']==8 and p['parent']['consumed_reservations']==8
    assert all(j['config']['stability_monitor']['algorithm']=='pct_exact_pose_network_v3' for j in p['jobs'])
    with pytest.raises(JevSelectError):validate_schema('config',dict(p['jobs'][0]['config'],version='jev_packaging_synthetic_v11'))
    result=supplement.run(tmp_path/'supplement/plan',constructed_factory=factory(f))
    assert result['status']=='PASS_IN_EXECUTED_SCOPE' and result['categories']['COMPLETE']==6
    assert result['request_statistics']['send_reservations']==8
    assert not (tmp_path/'supplement/run/first_gate.json').exists()
    before=f.calls;supplement.run(tmp_path/'supplement/plan',resume=True,constructed_factory=factory(f))
    assert f.calls==before
    common.validate_run(tmp_path/'supplement/run')
    # Re-signing edited local bytes must not alter inherited budget/scope.
    from semantic_pallet_planner.jev_select.contracts import digest
    from semantic_pallet_planner.jev_select.experiment import file_manifest
    altered=read(tmp_path/'supplement/plan/plan.json');altered['request_budget']['global']+=1
    write(tmp_path/'supplement/plan/plan.json',altered)
    write(tmp_path/'supplement/plan/plan_receipt.json',{'plan_digest':digest(altered)})
    write(tmp_path/'supplement/plan/delivery_manifest.json',file_manifest(tmp_path/'supplement/plan'))
    with pytest.raises(JevSelectError):supplement.validate_plan(tmp_path/'supplement/plan')

def test_supplement_unknown_send_stops_and_does_not_retry(tmp_path,monkeypatch):
    parent_run(tmp_path);supplement.prepare(tmp_path/'parent/plan',tmp_path/'parent/run',tmp_path/'supplement/plan')
    from semantic_pallet_planner.jev_select.packaging_exact_protocol import ExactLedger
    original=ExactLedger._transition
    class Cut(BaseException):pass
    def interrupt(self,row,state):
        original(self,row,state)
        if state=='SENDING':raise Cut()
    monkeypatch.setattr(ExactLedger,'_transition',interrupt);f=Fake()
    with pytest.raises(Cut):supplement.run(tmp_path/'supplement/plan',constructed_factory=factory(f))
    monkeypatch.setattr(ExactLedger,'_transition',original)
    r=supplement.run(tmp_path/'supplement/plan',resume=True,constructed_factory=factory(f))
    assert r['status']=='ERROR' and r['request_statistics']['unknown_sends']==1 and f.calls==0
    assert r['categories']['NOT_RUN']==3
    assert r['request_statistics']['send_reservations']==1
    before=f.calls;supplement.run(tmp_path/'supplement/plan',resume=True,constructed_factory=factory(f))
    assert f.calls==before

def test_numerical_failure_remains_serializable_error(monkeypatch):
    from semantic_pallet_planner.jev_select.stability.balance_network import BalanceNumericalError
    from semantic_pallet_planner.jev_select.contracts import canonical
    def fail(*args,**kwargs):raise BalanceNumericalError('NONFINITE_NETWORK',{'raw_solver_vector':[float('nan')]})
    monkeypatch.setattr(exact,'solve_network',fail)
    r=exact.assess_candidate(PlacedState((1000,800,1000)),BoxInput('floor',(100,100,100),1,(0,0,0))).to_dict()
    assert r['status']=='ERROR' and r['reason_code']=='NONFINITE_NETWORK'
    canonical(r)

@pytest.mark.parametrize('phase',['MONITORED','COMMITTED'])
def test_exact_saved_stage_does_not_reselect_remonitor_or_recommit(tmp_path,monkeypatch,phase):
    parent_run(tmp_path);p=supplement.prepare(tmp_path/'parent/plan',tmp_path/'parent/run',tmp_path/'supplement/plan')
    j=p['jobs'][0];cfg=j['config'];task=next(t for t in p['data']['tasks'] if t['task_id']==j['task_id'])
    from semantic_pallet_planner.jev_select.packaging_exact_protocol import selector_factory,ExactLedger
    from semantic_pallet_planner.jev_select.packaging_evaluation_memory import MemoryDriver
    from semantic_pallet_planner.jev_select.episode import run_episode
    from semantic_pallet_planner.jev_select.stability import monitor
    from semantic_pallet_planner.jev_select import execution
    ledger=ExactLedger(tmp_path/'ledger',p['request_budget'],{x['job_id']:x['config'] for x in p['jobs']})
    selector=selector_factory(j['method_id'],config=cfg,transport=None,ledger=ledger,job_id=j['job_id'])
    driver=MemoryDriver(cfg);saved=[]
    class Cut(BaseException):pass
    def checkpoint(cp):
        if cp['phase']==phase:saved.append(cp);raise Cut()
    with pytest.raises(Cut):run_episode(task,selector,cfg,job_id=j['job_id'],method=j['method_id'],memory_driver=driver,on_checkpoint=checkpoint)
    def forbidden(*a,**kw):pytest.fail('saved stage dispatched again')
    monkeypatch.setattr(selector,'select',forbidden);monkeypatch.setattr(driver,'resolve',forbidden)
    monkeypatch.setattr(monitor,'monitor_selected_action',forbidden)
    if phase=='COMMITTED':monkeypatch.setattr(execution,'commit_physical',forbidden)
    cp=saved[0]
    result=run_episode(task,selector,cfg,job_id=j['job_id'],method=j['method_id'],memory_driver=driver,resume=cp,event_limit=len(cp['events'])+1)
    assert result['final_state']['placed_count']==1

def test_formal_supplement_owner_cannot_be_replaced_by_new_plan(tmp_path,monkeypatch):
    # Only ownership registration is exercised; no formal job is dispatched.
    p={'data':{'fixture_only':False},'run_location':str(tmp_path/'run'),
       'parent':{'run_manifest_sha256':'a'*64}}
    monkeypatch.setattr(supplement,'validate_plan',lambda _:copy.deepcopy(p))
    monkeypatch.setattr(common,'REPO',tmp_path)
    (tmp_path/'semantic_pallet_planner/outputs').mkdir(parents=True)
    calls=[]
    def no_dispatch(*a,**kw):calls.append(kw);return {'status':'CONSTRUCTED_OWNER_CHECK_ONLY'}
    monkeypatch.setattr(common,'_run_plan',no_dispatch)
    supplement.run(tmp_path/'plan');assert len(calls)==1
    p['run_location']=str(tmp_path/'duplicate_run')
    with pytest.raises(JevSelectError,match='exact_supplement_already_registered'):
        supplement.run(tmp_path/'new_plan')
    assert len(calls)==1
