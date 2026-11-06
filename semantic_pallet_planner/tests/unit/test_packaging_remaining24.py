"""Minimal remainder dispatch checks; no formal job, network or credential access."""
import copy
import socket
import pytest
from semantic_pallet_planner.jev_select import packaging_exact_orders as exact
from semantic_pallet_planner.jev_select import packaging_synthetic_orders as synth
from semantic_pallet_planner.jev_select import packaging_evaluation_orders as common
from semantic_pallet_planner.jev_select import transport
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError,validate_schema
from semantic_pallet_planner.jev_select.experiment import file_manifest
from semantic_pallet_planner.jev_select.ledger import read,write,exclusive
from test_packaging_synthetic_execution import prepare,factory
from test_packaging_remote import Fake

@pytest.fixture(autouse=True)
def block_external(monkeypatch):
    def no(*a,**kw):pytest.fail('network or credentials requested')
    monkeypatch.setattr(socket.socket,'connect',no)
    monkeypatch.setattr(transport,'credential',no)
    monkeypatch.setattr(exact,'native_transport',no)

@pytest.fixture(scope='module')
def archived_fixture(tmp_path_factory):
    tmp_path=tmp_path_factory.mktemp('remaining_parent')
    # Module fixture also guards setup before function-level guards are applied.
    with pytest.MonkeyPatch.context() as m:
        def no(*a,**kw):pytest.fail('fixture attempted network or credential access')
        m.setattr(socket.socket,'connect',no);m.setattr(transport,'credential',no)
        return build_parent(tmp_path)


def build_parent(tmp_path):
    prepare(tmp_path/'original',tasks=3,n=2)
    synth.run_constructed(tmp_path/'original/plan',tmp_path/'original/run',transport_factory=factory(Fake()))
    exact.prepare(tmp_path/'original/plan',tmp_path/'original/run',tmp_path/'parent/plan')
    f=Fake();f.change=lambda _:transport.outcome('UNKNOWN_IN_FLIGHT',error='CONSTRUCTED',network_attempted=True)
    s=exact.run(tmp_path/'parent/plan',constructed_factory=factory(f))
    assert s['categories']['COMPLETE']==2 and s['categories']['SELECTION_FAILURE']==1
    assert s['categories']['NOT_RUN']==9
    import shutil
    shutil.copytree(tmp_path/'parent',tmp_path/'parent_backup')
    return tmp_path


@pytest.fixture
def stopped(archived_fixture):
    import shutil
    root=archived_fixture
    # Restore small constructed archives to the same bound paths, retaining the
    # parent identities. No historical formal order is replayed or copied.
    shutil.rmtree(root/'parent');shutil.copytree(root/'parent_backup',root/'parent')
    for name in ('next','bad'):
        if (root/name).exists():shutil.rmtree(root/name)
    return root


def test_derive_budget_scope_and_static_tampering(stopped):
    p=exact.prepare_remaining(stopped/'parent/plan',stopped/'parent/run',stopped/'next/plan')
    assert [j['job_id'] for j in p['jobs']]==[f'J{i:04d}' for i in range(9,18)]
    a=p['remainder']['accounting']
    assert (a['original_global_cap'],a['consumed_reservations'],a['remaining_cap'])==(24,9,15)
    assert a['unknown_real_send_count']==1 and a['known_real_model_calls']==8
    assert a['real_model_call_interval']=={'minimum':8,'maximum':9}
    assert sum(p['request_budget']['per_job'].values())==14
    assert common.validate_plan(stopped/'next/plan')==p
    assert not (stopped/'next/run').exists()
    assert not exact.account_root().joinpath('remaining24_owner.json').exists()
    for change in ('budget','range','config','extra'):
        altered=copy.deepcopy(p)
        if change=='budget':altered['request_budget']['global']+=1
        elif change=='range':altered['jobs']=altered['jobs'][1:]
        elif change=='config':altered['jobs'][0]['config']['display_order_seed']+=1
        else:altered['remainder']['extra']=True
        write(stopped/'next/plan/plan.json',altered)
        write(stopped/'next/plan/plan_receipt.json',{'plan_digest':digest(altered)})
        write(stopped/'next/plan/delivery_manifest.json',file_manifest(stopped/'next/plan'))
        with pytest.raises(JevSelectError):exact.validate_plan(stopped/'next/plan')

@pytest.mark.parametrize('change',['checkpoint','request','status','active','nested'])
def test_parent_rejects_started_or_changed_scope(stopped,change):
    run=stopped/'parent/run';plan=stopped/'parent/plan'
    if change=='checkpoint':write(run/'jobs/J0009/checkpoint.json',{})
    elif change=='request':
        d=read(run/'request_ledger/requests.json');d['requests'][0]['job_id']='J0009';write(run/'request_ledger/requests.json',d)
    elif change=='status':write(run/'jobs/J0009/status.json',{'state':'FINISHED'})
    elif change=='active':
        with exclusive(run):
            with pytest.raises(JevSelectError,match='locked'):exact.capture_stopped(plan,run)
        return
    else:
        exact.prepare_remaining(plan,run,stopped/'next/plan');plan=stopped/'next/plan'
    with pytest.raises(JevSelectError):exact.prepare_remaining(plan,run,stopped/'bad/plan')


def test_remainder_unknown_stops_without_followup_or_resend(stopped,monkeypatch):
    exact.prepare_remaining(stopped/'parent/plan',stopped/'parent/run',stopped/'next/plan')
    f=Fake();f.change=lambda _:transport.outcome('UNKNOWN_IN_FLIGHT',error='CONSTRUCTED',network_attempted=True)
    original=common._run_plan;entries=[]
    def shared(*a,**kw):entries.append(kw['resume']);return original(*a,**kw)
    monkeypatch.setattr(common,'_run_plan',shared)
    s=exact.run(stopped/'next/plan',constructed_factory=factory(f))
    assert s['status']=='ERROR' and s['categories']['NOT_RUN']==8
    assert s['request_statistics']['send_reservations']==1
    before=f.calls
    again=exact.run(stopped/'next/plan',resume=True,constructed_factory=factory(f))
    assert again==s and before==f.calls==1 and entries==[False,True]
    common.validate_run(stopped/'next/run')
    assert not (stopped/'next/run/first_gate.json').exists()


def test_owner_same_run_resume_and_duplicate_rejected(tmp_path):
    account=tmp_path/'account';account.mkdir();owner={'run':'old','plan_digest':'a','parent_run_manifest':'b'}
    write(account/'owner.json',owner);before=(account/'owner.json').read_bytes()
    from semantic_pallet_planner.jev_select.packaging_source_audit import sha
    p={'remainder':{'owner':owner,'owner_sha256':sha(account/'owner.json'),
       'run_manifest_sha256':'c','not_run_job_ids':['J0012']},'run_location':'newrun'}
    exact.register_remaining(p,account);exact.register_remaining(p,account)
    assert (account/'owner.json').read_bytes()==before
    other=copy.deepcopy(p);other['run_location']='other'
    with pytest.raises(JevSelectError,match='remaining_already_registered'):exact.register_remaining(other,account)

@pytest.mark.parametrize('phase',['SENDING','RESPONSE_SAVED'])
def test_remainder_saved_request_restore(stopped,monkeypatch,phase):
    p=exact.prepare_remaining(stopped/'parent/plan',stopped/'parent/run',stopped/'next/plan')
    from semantic_pallet_planner.jev_select.packaging_exact_protocol import ExactLedger
    from semantic_pallet_planner.jev_select.packaging_evaluation_memory import MemoryDriver
    original=ExactLedger._transition
    class Cut(BaseException):pass
    def pause(self,row,state):
        original(self,row,state)
        if state==phase:raise Cut()
    monkeypatch.setattr(ExactLedger,'_transition',pause);f=Fake()
    with pytest.raises(Cut):exact.run(stopped/'next/plan',constructed_factory=factory(f))
    monkeypatch.setattr(ExactLedger,'_transition',original)
    if phase=='SENDING':
        monkeypatch.setattr(MemoryDriver,'resolve',lambda *a:pytest.fail('DECISION_READY re-retrieved'))
        s=exact.run(stopped/'next/plan',resume=True,constructed_factory=factory(f))
        assert s['request_statistics']['unknown_sends']==1 and f.calls==0
    else:
        # Restore exactly the saved decision; stop before another decision needs retrieval.
        from semantic_pallet_planner.jev_select.packaging_exact_protocol import selector_factory
        from semantic_pallet_planner.jev_select.episode import run_episode
        j=p['jobs'][0];cfg=j['config'];task=next(t for t in p['data']['tasks'] if t['task_id']==j['task_id'])
        cp=read(stopped/'next/run/jobs'/j['job_id']/'checkpoint.json')
        ledger=ExactLedger(stopped/'next/run/request_ledger',p['request_budget'],{x['job_id']:x['config'] for x in p['jobs']})
        sel=selector_factory(j['method_id'],config=cfg,transport=None,ledger=ledger,job_id=j['job_id'])
        driver=MemoryDriver(cfg,snapshot=p['snapshots'][cfg['memory_mode']]);monkeypatch.setattr(driver,'resolve',lambda *a:pytest.fail('DECISION_READY re-retrieved'))
        r=run_episode(task,sel,cfg,job_id=j['job_id'],method=j['method_id'],memory_driver=driver,
                      resume=cp,event_limit=len(cp['events'])+1)
        assert f.calls==1 and r['final_state']['placed_count']==1


def test_future_formal_entry_registers_then_uses_shared_loop(tmp_path,monkeypatch):
    p={'version':exact.REMAINDER_PLAN,'data':{'fixture_only':False},'run_location':str(tmp_path/'run')}
    monkeypatch.setattr(exact,'validate_plan',lambda _:p)
    monkeypatch.setattr(common,'REPO',tmp_path)
    (tmp_path/'semantic_pallet_planner/outputs').mkdir(parents=True)
    calls=[]
    monkeypatch.setattr(exact,'register_remaining',lambda plan,account:calls.append('owner'))
    def no_dispatch(*a,**kw):
        assert calls==['owner'];assert kw['execution_mode']=='JEV_SUPPLEMENTAL_TRANSPORT'
        return {'status':'OWNER_ROUTING_ONLY_NO_JOB_DISPATCH'}
    monkeypatch.setattr(common,'_run_plan',no_dispatch)
    assert exact.run(tmp_path/'plan')['status']=='OWNER_ROUTING_ONLY_NO_JOB_DISPATCH'
