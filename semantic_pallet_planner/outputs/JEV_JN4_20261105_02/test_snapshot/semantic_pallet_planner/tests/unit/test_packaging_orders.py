"""JN1-B constructed orders and fake transport; never sends to a model."""
import copy
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select import packaging_orders as orders
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError
from semantic_pallet_planner.jev_select.tests.unit.test_packaging_runtime import mechanism_task,item
from test_packaging_remote import Fake


def setup(tmp_path,monkeypatch,n=4,tasks=2,size=(20,20,20),watchdog=None):
    ts=[]
    for i in range(tasks):
        t=mechanism_task([item(str(j),size=size) for j in range(n)])
        t.update(task_id=f'CONSTRUCTED_{i}',source_group_id=f'CONSTRUCTED_S{i}',partition='train');ts.append(t)
    data={'data_identity':digest('CONSTRUCTED_ONLY'),'tasks':ts}
    def fresh(path):
        path=Path(path)
        if path.exists():raise JevSelectError('constructed_output_exists')
        path.mkdir(parents=True);return path
    monkeypatch.setattr(orders.common,'new_output',fresh)
    monkeypatch.setattr(orders,'parent_receipts',lambda:{'parent':'CONSTRUCTED_TEST_ONLY'})
    monkeypatch.setattr(orders,'REPO',tmp_path)
    monkeypatch.setattr(orders.common,'REPO',tmp_path)
    monkeypatch.setattr(orders,'task_order',lambda:[t['task_id'] for t in ts])
    monkeypatch.setattr(orders,'load_runtime_dataset',lambda _:copy.deepcopy(data))
    monkeypatch.setattr(orders.common,'inventory',lambda *a:dict(tasks=[{'task_id':t['task_id']} for t in ts]))
    plan=orders.prepare(tmp_path/'dataset',{} if watchdog is None else {'watchdog':watchdog},tmp_path/'plan')
    f=Fake();f.origin='jev' # Explicit injected fake; accounting test only.
    return plan,f,lambda c,j:f


def test_full_order_pilot_continuation_and_ledger(tmp_path,monkeypatch):
    p,f,factory=setup(tmp_path,monkeypatch)
    s=orders.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    assert s['status']=='PASS_IN_EXECUTED_SCOPE' and s['categories']['COMPLETE']==3 and s['categories']['NOT_RUN']==3
    assert f.calls==4 and s['model_calls']==4 and s['model_cost_usd']=='UNKNOWN'
    orders.validate_run(tmp_path/'run')
    before=read(tmp_path/'run/pilot_gate.json')['job_files_sha256']
    assert orders.run(tmp_path/'plan',tmp_path/'run',resume=True,transport_factory=factory)==s
    s=orders.run(tmp_path/'plan',tmp_path/'run',resume=True,continue_pending=True,transport_factory=factory)
    assert s['categories']['COMPLETE']==6 and f.calls==8 and s['request_statistics']['send_reservations']==8
    assert orders.pilot_gate(tmp_path/'run',p)['job_files_sha256']==before
    assert all(len(read(tmp_path/'run/jobs'/j['job_id']/'checkpoint.json')['events'])>8 for j in p['jobs'])
    for j in p['jobs']:
        r=read(tmp_path/'run/jobs'/j['job_id']/'metrics.json')
        assert r['cost']['model_calls']==(4 if j['method_id']=='jev_no_memory' else 0)
    assert len(read(tmp_path/'run/paired_differences.json'))==6
    assert all(x['comparison_valid'] for x in read(tmp_path/'run/paired_differences.json'))
    orders.validate_run(tmp_path/'run')
    assert orders.run(tmp_path/'plan',tmp_path/'run',resume=True,continue_pending=True,transport_factory=factory)==s and f.calls==8

@pytest.mark.parametrize('kind',['unknown','invalid','explicit_failure'])
def test_failure_stops_batch_and_keeps_denominator(tmp_path,monkeypatch,kind):
    p,f,_=setup(tmp_path,monkeypatch)
    from semantic_pallet_planner.jev_select.transport import outcome
    f.change=lambda r:outcome('UNKNOWN_IN_FLIGHT' if kind=='unknown' else 'OK' if kind=='invalid' else 'PROVIDER_FAILURE',
                             b'{bad' if kind=='invalid' else b'',http_status=200 if kind=='invalid' else 401,
                             error='TEST_FAILURE' if kind!='invalid' else None,network_attempted=True)
    s=orders.run(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:f)
    assert s['status']=='ERROR' and s['categories']['NOT_RUN']==5 and f.calls==1
    assert s['model_calls']==1 and s['model_cost_usd']=='UNKNOWN'
    assert s['request_statistics']['unknown_sends']==(kind=='unknown')
    assert s['request_statistics']['failed_requests']==(kind!='unknown')
    orders.validate_run(tmp_path/'run')
    orders.run(tmp_path/'plan',tmp_path/'run',resume=True,continue_pending=True,transport_factory=lambda *a:f)
    assert f.calls==1


def test_per_job_and_shared_budget(tmp_path):
    from test_packaging_remote import fixture
    from semantic_pallet_planner.jev_select.selector import bind_decision
    _,_,_,ctx=fixture();f=Fake();l=orders.OrderLedger(tmp_path,{'global':2,'per_job':{'J':1,'K':1,'LOCAL':0}})
    l.request(ctx,'J','J_D0000',f)
    assert l.request(ctx,'J','J_D0000',f) and f.calls==1
    with pytest.raises(JevSelectError,match='job_budget_exhausted'):
        l.request(bind_decision(ctx,'J','J_D0001'),'J','J_D0001',f)
    l.request(bind_decision(ctx,'K','K_D0000'),'K','K_D0000',f)
    with pytest.raises(JevSelectError):l.request(bind_decision(ctx,'LOCAL','L'),'LOCAL','L',f)
    again=orders.OrderLedger(tmp_path,{'global':2,'per_job':{'J':1,'K':1,'LOCAL':0}})
    with pytest.raises(JevSelectError):again.request(bind_decision(ctx,'K','K_D0001'),'K','K_D0001',f)
    assert f.calls==2


def test_scope_identity_and_old_protection(tmp_path,monkeypatch):
    p,f,factory=setup(tmp_path,monkeypatch)
    with pytest.raises(JevSelectError):orders.run(tmp_path/'plan',tmp_path/'run',task_ids=['outside'],transport_factory=factory)
    with pytest.raises(JevSelectError):orders.run(tmp_path/'plan',tmp_path/'run',method_ids=['jev_no_memory'],transport_factory=factory)
    from semantic_pallet_planner.jev_select.contracts import validate_schema
    with pytest.raises(JevSelectError):validate_schema('packaging_full_order_plan_v1',p)
    from semantic_pallet_planner.jev_select.packaging_protocol import selector_factory
    with pytest.raises(JevSelectError):selector_factory('jev_no_memory')
    from semantic_pallet_planner.jev_select.experiment import file_manifest
    changed=copy.deepcopy(p);changed['request_budget']['global']+=1;write(tmp_path/'plan/plan.json',changed)
    write(tmp_path/'plan/plan_receipt.json',{'version':orders.PLAN,'plan_digest':digest(changed)})
    write(tmp_path/'plan/delivery_manifest.json',file_manifest(tmp_path/'plan'))
    with pytest.raises(JevSelectError):orders.validate_plan(tmp_path/'plan')


def test_summary_failure_never_passes(tmp_path,monkeypatch):
    p,f,factory=setup(tmp_path,monkeypatch,tasks=1)
    def fail(*a):raise ValueError('CONSTRUCTED_SUMMARY_FAILURE')
    monkeypatch.setattr(orders,'summarize',fail)
    s=orders.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    assert s['status']=='ERROR' and read(tmp_path/'run/technical_failure.json')['phase']=='BATCH_SUMMARY_OR_VALIDATION'
    assert orders.run(tmp_path/'plan',tmp_path/'run',resume=True,transport_factory=factory)['status']=='ERROR'


def test_readonly_validation_and_resigned_tamper(tmp_path,monkeypatch):
    p,f,factory=setup(tmp_path,monkeypatch,tasks=1,n=1)
    orders.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    from semantic_pallet_planner.jev_select.experiment import file_manifest
    before=file_manifest(tmp_path/'run')
    def forbidden(*a,**kw):raise AssertionError('read-only validation dispatched execution')
    import semantic_pallet_planner.jev_select.episode as ep
    import semantic_pallet_planner.jev_select.execution as ex
    import semantic_pallet_planner.jev_select.stability.balance_adapter as ba
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
    monkeypatch.setattr(ep,'run_episode',forbidden);monkeypatch.setattr(ex,'commit_physical',forbidden)
    monkeypatch.setattr(ba,'assess_candidate',forbidden);monkeypatch.setattr(CandidateProvider,'build',forbidden)
    orders.validate_run(tmp_path/'run');assert file_manifest(tmp_path/'run')==before
    path=next((tmp_path/'run/jobs/J0000/decisions').glob('*.json'));d=read(path);d['selected_candidate_id']='TAMPER'
    d['record_digest']=digest({k:v for k,v in d.items() if k!='record_digest'});write(path,d)
    write(tmp_path/'run/delivery_manifest.json',file_manifest(tmp_path/'run'))
    with pytest.raises(JevSelectError):orders.validate_run(tmp_path/'run')


def test_natural_empty_and_no_real_request(tmp_path,monkeypatch):
    p,f,factory=setup(tmp_path,monkeypatch,n=1,tasks=1,size=(2000,2000,2000))
    s=orders.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    assert s['categories']['EMPTY_POOL']==3 and s['model_calls']==0 and f.calls==0 and s['status']=='PASS_IN_EXECUTED_SCOPE'
    orders.validate_run(tmp_path/'run')

@pytest.mark.parametrize('status',['UNASSESSABLE','ERROR'])
def test_range_and_monitor_technical_stop(tmp_path,monkeypatch,status):
    p,f,factory=setup(tmp_path,monkeypatch,n=1,tasks=1)
    from dataclasses import replace
    from semantic_pallet_planner.jev_select.stability import balance_adapter as ba
    real=ba.assess_candidate
    monkeypatch.setattr(ba,'assess_candidate',lambda *a,**kw:replace(real(*a,**kw),status=status,reason_code='EXPLICIT_CONSTRUCTED_FAULT'))
    s=orders.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    if status=='UNASSESSABLE':
        assert s['categories']['UNASSESSABLE']==3 and s['status']=='PASS_IN_EXECUTED_SCOPE'
        assert not any(r['comparison_valid'] for r in read(tmp_path/'run/paired_differences.json'))
    else:assert s['status']=='ERROR' and s['categories']['NOT_RUN']==2
    assert read(tmp_path/'run/jobs/J0000/metrics.json')['loading']['placed_items']==0
    orders.validate_run(tmp_path/'run')


def test_watchdog_stops_batch_and_budget(tmp_path,monkeypatch):
    p,f,factory=setup(tmp_path,monkeypatch,n=1,tasks=1,watchdog={'max_events':1,'max_active_wall_s':60})
    s=orders.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    assert s['status']=='ERROR' and s['categories']['TECHNICAL_LIMIT']==1 and s['categories']['NOT_RUN']==2 and f.calls==0
    orders.validate_run(tmp_path/'run')


def test_job_metric_error_keeps_ledger_cost(tmp_path,monkeypatch):
    p,f,factory=setup(tmp_path,monkeypatch,n=1,tasks=1)
    def fail(*a):raise ValueError('CONSTRUCTED_METRICS_FAILURE')
    monkeypatch.setattr(orders,'metrics',fail)
    s=orders.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    assert s['status']=='ERROR' and s['model_calls']==1 and s['model_cost_usd']=='UNKNOWN' and s['categories']['NOT_RUN']==2
    assert s['selected_actions']=='UNKNOWN'


def test_singleton_in_full_order_zero_requests(tmp_path,monkeypatch):
    p,f,factory=setup(tmp_path,monkeypatch,n=1,tasks=1)
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
    from semantic_pallet_planner.jev_select.contracts import CandidateBundle
    real=CandidateProvider.build
    def one(self,*args,**kw):
        b=real(self,*args,**kw).data
        b['physical_candidates']=b['physical_candidates'][:1];b['physical_digest']=digest(b['physical_candidates'])
        return CandidateBundle.from_dict(b)
    monkeypatch.setattr(CandidateProvider,'build',one)
    s=orders.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    assert s['categories']['COMPLETE']==3 and f.calls==0 and s['request_statistics']['send_reservations']==0
    assert all(read(tmp_path/'run/jobs'/j['job_id']/'metrics.json')['singleton_decisions']==1 for j in p['jobs'])
    orders.validate_run(tmp_path/'run')


def test_usage_available_when_choice_rejected(tmp_path):
    from test_packaging_remote import fixture
    from semantic_pallet_planner.jev_select.packaging_remote import remote_selector_factory
    from semantic_pallet_planner.jev_select.transport import outcome
    import json
    _,c,_,ctx=fixture();f=Fake();f.origin='jev'
    def bad(r):
        r['answers']['next_action']['choice']='C99'
        return outcome('OK',json.dumps(r).encode(),http_status=200,network_attempted=True)
    f.change=bad;ledger=orders.OrderLedger(tmp_path,{'global':1,'per_job':{'J':1}})
    selector=remote_selector_factory('jev_no_memory',config=c,ledger=ledger,transport=f,job_id='J')
    assert selector.select(ctx,decision_id='J_D0000').data['status']=='invalid_response'
    stats=orders.request_statistics(ledger._load()['requests'])
    assert stats['failed_requests']==1 and stats['usage']['input_tokens']==17 and stats['model_cost_usd']=='UNKNOWN'


def test_unsent_intent_cannot_bypass_job_cap_on_recovery(tmp_path):
    from test_packaging_remote import fixture
    from semantic_pallet_planner.jev_select.selector import bind_decision
    _,_,_,ctx=fixture();f=Fake()
    class Cut(BaseException):pass
    def cut(phase,row):
        if phase=='INTENT':raise Cut()
    limits={'global':2,'per_job':{'J':1,'K':1}}
    ledger=orders.OrderLedger(tmp_path,limits,hook=cut)
    with pytest.raises(Cut):ledger.request(ctx,'J','J_D0000',f)
    ledger=orders.OrderLedger(tmp_path,limits)
    ledger.request(bind_decision(ctx,'J','J_D0001'),'J','J_D0001',f)
    with pytest.raises(JevSelectError,match='job_budget_exhausted'):ledger.request(ctx,'J','J_D0000',f)
    assert f.calls==1


def test_reuse_receipt_not_another_send(tmp_path):
    from test_packaging_remote import fixture
    from semantic_pallet_planner.jev_select.packaging_remote import remote_selector_factory
    _,cfg,_,ctx=fixture();f=Fake();f.origin='jev'
    ledger=orders.OrderLedger(tmp_path/'request_ledger',{'global':1,'per_job':{'J':1}})
    selector=remote_selector_factory('jev_no_memory',config=cfg,ledger=ledger,transport=f,job_id='J')
    first=selector.select(ctx,decision_id='J_D0000')
    assert selector.select(ctx,decision_id='J_D0000').data==first.data
    events=orders.saved_reuses(tmp_path);assert len(events)==1
    stats=orders.request_statistics(ledger._load()['requests'],events)
    assert stats['stored_selection_reuses']==1 and stats['stored_response_reuses']==1 and stats['model_calls']==1 and f.calls==1
