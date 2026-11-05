"""Minimal execution wiring on constructed tasks only. Never formal six tasks."""
import copy
import socket
from types import SimpleNamespace
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select import packaging_synthetic_orders as synth
from semantic_pallet_planner.jev_select import packaging_evaluation_orders as common
from semantic_pallet_planner.jev_select import packaging_synthetic_protocol as protocol
from semantic_pallet_planner.jev_select import packaging_evaluation_memory as memory
from semantic_pallet_planner.jev_select import transport
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.tests.unit.test_packaging_runtime import mechanism_task,item
from test_packaging_remote import Fake


@pytest.fixture(autouse=True)
def blocked(monkeypatch):
    def no(*a,**kw):raise AssertionError('real network or credential access')
    monkeypatch.setattr(socket.socket,'connect',no)
    monkeypatch.setattr(transport,'credential',no)


def prepare(tmp_path,*,tasks=2,n=3):
    ts=[];relations={}
    for i in range(tasks):
        t=mechanism_task([item(str(j),size=(20,20,20)) for j in range(n)])
        t.update(task_id=f'CONSTRUCTED_EXEC_{i}',source_group_id=f'CONSTRUCTED_GROUP_{i}',partition='train')
        ts.append(t);relations[t['task_id']]={'memory_scope_version':protocol.MEMORY_SCOPE,
          'material_source_components':[],'order_related_source_groups':[], 'excluded_fork_digests':[],'new_combination_status':'PASS'}
    return synth.prepare({'version':'jev_synthetic_combo_dataset_v1','fixture_only':True,'data_identity':digest('CONSTRUCTED_EXECUTION'),
       'tasks':ts,'dataset_root':None,'relations':relations},tmp_path/'plan',purpose='SYNTHETIC_ENGINEERING')


def factory(fake,origin='jev',calls=None):
    def make(cfg,job):
        if calls is not None:calls.append(job['method_id'])
        return synth.ConstructedTransport(fake,simulated_origin=origin)
    return make


def test_native_factory_lazy_and_spoof_rejected(tmp_path):
    p=prepare(tmp_path,tasks=1);cfg=p['jobs'][2]['config']
    native=synth.native_transport(cfg,p['jobs'][2])
    assert type(native) is transport.JevTransport
    synth.check_execution_transport(native,cfg,'JEV_TRANSPORT')
    with pytest.raises(JevSelectError):synth.check_execution_transport(SimpleNamespace(origin='jev'),cfg,'JEV_TRANSPORT')
    with pytest.raises(JevSelectError):synth.check_execution_transport(synth.ConstructedTransport(Fake(),simulated_origin='jev'),cfg,'JEV_TRANSPORT')
    with pytest.raises(JevSelectError):synth.run_formal(tmp_path/'plan')
    with pytest.raises(JevSelectError):synth.check_execution_transport(native,p['jobs'][0]['config'],'JEV_TRANSPORT')
    synth.check_execution_transport(None,p['jobs'][0]['config'],'JEV_TRANSPORT')


def test_first_block_gate_before_continue_and_resume_grant(tmp_path,monkeypatch):
    p=prepare(tmp_path);f=Fake();calls=[];visited=[];run=tmp_path/'run';original=common.common._run_job
    def observe(task,j,*a,**kw):
        visited.append(j['job_id'])
        if int(j['job_id'][1:])>=6:
            assert read(run/'first_gate.json')['status']=='PASS'
            assert read(run/'continuation.json')['first_gate_digest']==digest(read(run/'first_gate.json'))
        return original(task,j,*a,**kw)
    monkeypatch.setattr(common.common,'_run_job',observe)
    validation=common.validate_run;validations=[]
    def validated(root):
        validations.append((Path(root)/'first_gate.json').exists())
        return validation(root)
    monkeypatch.setattr(common,'validate_run',validated)
    s=synth.run_constructed(tmp_path/'plan',run,transport_factory=factory(f,calls=calls))
    assert validations[:2]==[False,True]  # Saved facts validate before publishing gate.
    assert s['categories']['COMPLETE']==6 and s['categories']['NOT_RUN']==6
    assert len(calls)==4 and len(visited)==6 and f.calls==12
    assert s['execution_evidence']['fixture_only'] and s['actual_model_api_calls']==12
    first=read(run/'first_gate.json')
    synth.run_constructed(tmp_path/'plan',run,transport_factory=factory(f),resume=True)
    assert len(visited)==6 and not (run/'continuation.json').exists()
    class Cut(BaseException):pass
    def interrupt(task,j,*a,**kw):
        if j['job_id']=='J0006':raise Cut()
        return observe(task,j,*a,**kw)
    monkeypatch.setattr(common.common,'_run_job',interrupt)
    with pytest.raises(Cut):synth.run_constructed(tmp_path/'plan',run,transport_factory=factory(f),resume=True,continue_pending=True)
    assert (run/'continuation.json').exists() and read(run/'first_gate.json')==first
    monkeypatch.setattr(common.common,'_run_job',observe)
    s=synth.run_constructed(tmp_path/'plan',run,transport_factory=factory(f),resume=True)
    assert s['categories']['COMPLETE']==12 and f.calls==24 and read(run/'first_gate.json')==first
    common.validate_run(run)


@pytest.mark.parametrize('kind',['fake','empty','unknown'])
def test_nonpass_never_starts_seventh(tmp_path,monkeypatch,kind):
    p=prepare(tmp_path);run=tmp_path/'run';f=Fake();origin='test_double' if kind=='fake' else 'jev'
    if kind=='empty':
        # Freeze a constructed no-hit scope before execution, without changing real snapshots.
        import test_packaging_synthetic as helpers
        groups=synth.base.snapshots()['E']['source_groups'];r=p['data']['relations']
        for row in r.values():row['order_related_source_groups']=groups
        # Use a new constructed plan; prior bytes retained as a draft fixture.
        import shutil
        shutil.move(tmp_path/'plan',tmp_path/'draft')
        p=synth.prepare(p['data'],tmp_path/'plan',purpose='SYNTHETIC_ENGINEERING')
    if kind=='unknown':
        f.change=lambda r:transport.outcome('UNKNOWN_IN_FLIGHT',error='CONSTRUCTED',network_attempted=None)
    s=synth.run_constructed(tmp_path/'plan',run,transport_factory=factory(f,origin))
    assert all(read(run/'jobs'/j['job_id']/'status.json')['state']=='NOT_RUN' for j in p['jobs'][6:])
    if kind=='unknown':
        assert s['status']=='ERROR' and s['actual_model_api_calls']=='UNKNOWN'
        before=f.calls;synth.run_constructed(tmp_path/'plan',run,transport_factory=factory(f,origin),resume=True,continue_pending=True)
        assert f.calls==before
    else:
        assert read(run/'first_gate.json')['status']=='DEFER_NO_EXPOSURE'
        with pytest.raises(JevSelectError):synth.run_constructed(tmp_path/'plan',run,transport_factory=factory(f,origin),resume=True,continue_pending=True)
    assert not (run/'continuation.json').exists()


def test_unknown_sending_and_saved_response_resume_same_loop(tmp_path,monkeypatch):
    p=prepare(tmp_path,tasks=1);run=tmp_path/'run';f=Fake();original=protocol.SyntheticLedger._transition
    class Cut(BaseException):pass
    def cut(self,row,state):
        original(self,row,state)
        if state=='SENDING':raise Cut()
    monkeypatch.setattr(protocol.SyntheticLedger,'_transition',cut)
    with pytest.raises(Cut):synth.run_constructed(tmp_path/'plan',run,transport_factory=factory(f))
    assert f.calls==0
    monkeypatch.setattr(protocol.SyntheticLedger,'_transition',original)
    monkeypatch.setattr(memory.MemoryDriver,'resolve',lambda *a:pytest.fail('DECISION_READY re-retrieved'))
    s=synth.run_constructed(tmp_path/'plan',run,transport_factory=factory(f),resume=True)
    assert s['status']=='ERROR' and s['request_statistics']['send_reservations']==1 and f.calls==0
    assert common.saved_requests(run,p)[0]['state']=='UNKNOWN_SEND'


def test_old_fake_entry_still_rejects_formal_and_real_origin(tmp_path,monkeypatch):
    p=prepare(tmp_path,tasks=1);formal=copy.deepcopy(p);formal['purpose']=protocol.PURPOSE
    monkeypatch.setattr(common,'validate_plan',lambda *a:formal)
    with pytest.raises(JevSelectError):common.run_validation(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:pytest.fail('dispatch'))
    monkeypatch.setattr(common,'validate_plan',lambda *a:p)
    s=common.run_validation(tmp_path/'plan',tmp_path/'run',transport_factory=factory(Fake()))
    assert s['status']=='ERROR' and s['request_statistics']['send_reservations']==0


def test_continuation_marker_crash_has_no_stale_closure(tmp_path,monkeypatch):
    p=prepare(tmp_path);run=tmp_path/'run'
    write(run/'run_receipt.json',{'version':protocol.VERSIONS['run'],'plan':common.location(tmp_path/'plan'),'plan_digest':digest(p)})
    write(run/'execution_evidence.json',{'version':'jev_synthetic_execution_evidence_v1','plan_digest':digest(p),'kind':'CONSTRUCTED_TRANSPORT_ONLY','fixture_only':True})
    protocol.SyntheticLedger(run/'request_ledger',p['request_budget'],{j['job_id']:j['config'] for j in p['jobs']})
    first={'status':'PASS','plan_digest':digest(p)}
    write(run/'first_gate.json',first);write(run/'summary.json',{'status':'PASS_IN_EXECUTED_SCOPE'})
    write(run/'delivery_manifest.json',{})
    # Isolate the marker transaction; full job/gate semantics are tested above.
    monkeypatch.setattr(common,'validate_run',lambda *a:None)
    monkeypatch.setattr(common,'gate',lambda *a:first)
    original=common.write
    class Cut(BaseException):pass
    def cut(path,value):
        original(path,value)
        if Path(path).name=='continuation.json':raise Cut()
    monkeypatch.setattr(common,'write',cut)
    with pytest.raises(Cut):synth.run_constructed(tmp_path/'plan',run,transport_factory=lambda *a:pytest.fail('dispatch'),resume=True,continue_pending=True)
    assert not (run/'delivery_manifest.json').exists()
    assert read(run/'continuation.json')['first_gate_digest']==digest(first)


def test_saved_response_reuse_existing_shared_ledger(tmp_path,monkeypatch):
    from test_packaging_evaluation_v10 import test_saved_response_and_budget_resume_no_resend
    test_saved_response_and_budget_resume_no_resend(tmp_path,monkeypatch,'jev_with_contrast_experience')


def test_committed_restore_existing_v11(tmp_path,monkeypatch):
    from test_packaging_synthetic import test_v11_resume_binding_no_retrieval_or_recommit
    test_v11_resume_binding_no_retrieval_or_recommit(tmp_path,monkeypatch,'COMMITTED')
