"""GP6 formal equality contract and durable recovery gates; synthetic/offline only."""
import copy
from pathlib import Path
from unittest.mock import patch

import pytest
from semantic_pallet_planner.jev_select.contracts import digest, JevSelectError, DecisionContext
from semantic_pallet_planner.jev_select.geometry_jev_protocol import (
    prepare_jev_plan, validate_jev_plan, development_binding, GP6_ORDER)
from semantic_pallet_planner.jev_select.geometry_jev_execution import (
    GeometryJevRequestLedger, run_jev_job, validate_jev_request_ledger_binding)
from semantic_pallet_planner.jev_select.packaging_geometry_protocol import TASK_IDS
from semantic_pallet_planner.jev_select.stability import exact_adapter, balance_network
from test_gp6_jev_integration import (
    _adapted_synth, _fake_monitor_snapshot, _make_monitor_double, FakeChoiceTransport)


class Cut(RuntimeError):
    pass


def setup(root, limit=8):
    task=_adapted_synth('K01');snapshot=_fake_monitor_snapshot()
    plan=prepare_jev_plan([task],data_identity=digest('SYNTHETIC_ONLY'),per_job_max_sends=min(4,limit),shared_max_sends=limit)
    binding=development_binding(plan)
    ledger=GeometryJevRequestLedger(root/'requests',plan_digest=digest(plan),per_job_max_sends=plan['per_job_max_sends'],shared_max_sends=limit)
    return task,snapshot,plan,binding,ledger


@pytest.fixture(scope='module')
def selected(tmp_path_factory):
    root=tmp_path_factory.mktemp('gp6_rec_synthetic')
    task,snap,plan,binding,ledger=setup(root)
    saved={}
    def stop(stage,cp):
        if stage=='after_selected_checkpoint':
            saved['cp']=copy.deepcopy(cp);raise Cut()
    with pytest.raises(Cut):
        run_jev_job(plan,'G01',task,monitor_snapshot=snap,admission=binding,root=root/'run',
                    transport=FakeChoiceTransport(),ledger=ledger,hook=stop)
    return root,task,snap,plan,binding,ledger,saved['cp']


@pytest.mark.parametrize('model,shared',[(1,2),(2,1),(1,1)])
def test_formal_budget_equality_before_ledger_dispatch(tmp_path,model,shared):
    # Pure draft-only synthetic plan identity; no formal freeze or credential.
    tasks=[_adapted_synth('K01'),_adapted_synth('K02')]
    for t,tid in zip(tasks,TASK_IDS):
        t['identity'].update(origin='EXPOSED_TRAIN',task_id=tid)
    plan=prepare_jev_plan(tasks,data_identity=digest('SYNTHETIC_ONLY'),scope=GP6_ORDER,
                          shared_max_sends=shared,request_ledger_path=str(tmp_path/'requests/requests.json'))
    plan['model_calls_max']=model
    transport=FakeChoiceTransport(origin='jev')
    ledger=GeometryJevRequestLedger(tmp_path/'requests',plan_digest=digest(plan),per_job_max_sends=19,
                                   shared_max_sends=shared,allow_real_transport=True)
    cfg={'plan_digest':digest(plan),'per_job_max_sends':19,'shared_max_sends':shared,'transport_evidence':'REAL_JEV'}
    if model!=shared:
        with pytest.raises(JevSelectError,match='geometry_jev_formal_budget'):validate_jev_plan(plan)
        with pytest.raises(JevSelectError,match='geometry_jev_formal_budget'):
            validate_jev_request_ledger_binding(plan,cfg,ledger,transport,real_authorized=True)
    else:
        validate_jev_plan(plan)
        validate_jev_request_ledger_binding(plan,cfg,ledger,transport,real_authorized=True)
    assert not transport.bodies and ledger.statistics()['send_reservations']==0


def test_uniform_formal_limit_unknown_reservation_never_released(selected,tmp_path):
    _,_,_,_,_,_,cp=selected
    context=DecisionContext.from_dict(cp['pending_event']['context'])
    ledger=GeometryJevRequestLedger(tmp_path/'requests',plan_digest=digest('synthetic formal budget'),
                per_job_max_sends=1,shared_max_sends=1,allow_real_transport=True)
    def timeout(*args):raise TimeoutError('SYNTHETIC_ONLY')
    transport=FakeChoiceTransport(origin='jev',responder=timeout)
    row=ledger.request(context,'G01','G01_D0000',transport)
    assert row['state']=='UNKNOWN_SEND' and row['send_started']
    ledger.request(context,'G01','G01_D0000',transport)  # no implicit retry
    # Different decision cannot consume another send; identity uses a fresh
    # valid context bound by a normal development run in the next test.
    with pytest.raises(JevSelectError,match='request_budget_exhausted'):
        ledger.admit_send({'job_id':'G01','origin':'jev'})
    assert len(transport.bodies)==1 and ledger.statistics()['send_reservations']==1


@pytest.mark.parametrize('mutation', ['missing_attempt','missing_selection','value','digest','state','send_started','origin'])
def test_saved_request_selection_requires_ledger_match(selected,mutation):
    root,task,snap,plan,binding,ledger,cp=selected
    original=ledger.path.read_bytes()
    ledger._load();row=ledger.data['requests'][0]
    if mutation=='missing_attempt':ledger.data['requests']=[]
    elif mutation=='missing_selection':row.update(selection=None,selection_digest=None)
    elif mutation=='value':
        row['selection']['served_model']='SYNTHETIC_DIFFERENT';row['selection_digest']=digest(row['selection'])
    elif mutation=='digest':row['selection_digest']='0'*64
    elif mutation=='state':row['state']='RESPONSE_SAVED'
    elif mutation=='send_started':row['send_started']=False
    else:row['origin']='jev'
    ledger._save(ledger.data)
    transport=FakeChoiceTransport()
    try:
        with patch.object(exact_adapter,'assess_candidate',side_effect=AssertionError('ASSESS_FORBIDDEN')) as assess, \
             patch.object(balance_network,'linprog',side_effect=AssertionError('LP_FORBIDDEN')) as lp, \
             patch('semantic_pallet_planner.jev_select.execution.commit_physical',side_effect=AssertionError('COMMIT_FORBIDDEN')) as commit:
            with pytest.raises(JevSelectError):
                run_jev_job(plan,'G01',task,monitor_snapshot=snap,admission=binding,root=root/'run',
                            ledger=ledger,transport=transport,resume=copy.deepcopy(cp))
            assert not transport.bodies
            assert assess.call_count==lp.call_count==commit.call_count==0
    finally:ledger.path.write_bytes(original)


@pytest.mark.parametrize('stage',['RESPONSE_SAVED','SELECTION_SAVED'])
def test_response_or_selection_saved_before_checkpoint_is_legal(tmp_path,stage):
    task,snap,plan,binding,ledger=setup(tmp_path)
    saved={}
    def save(cp):saved['cp']=copy.deepcopy(cp)
    def cut(state,row):
        if state==stage:raise Cut()
    ledger.hook=cut;transport=FakeChoiceTransport()
    with pytest.raises(Cut):
        run_jev_job(plan,'G01',task,monitor_snapshot=snap,admission=binding,root=tmp_path/'run',
                    ledger=ledger,transport=transport,on_checkpoint=save)
    cp=saved['cp'];assert cp['phase']=='DECISION_READY' and cp['pending_event']['selection'] is None
    ledger.hook=None;assess,calls=_make_monitor_double(snap)
    with patch.object(exact_adapter,'assess_candidate',assess):
        out=run_jev_job(plan,'G01',task,monitor_snapshot=snap,admission=binding,root=tmp_path/'run',
                       ledger=ledger,transport=transport,resume=cp)
    assert out['summary']['completed'] and len(transport.bodies)==1 and len(calls)==1


@pytest.mark.parametrize('unknown',[False,True])
def test_shared_limit_blocks_new_job_and_budget_checkpoint_recovers_without_send(tmp_path,unknown):
    task,snap,plan,binding,ledger=setup(tmp_path,limit=1)
    def timeout(*args):raise TimeoutError('SYNTHETIC_ONLY')
    transport=FakeChoiceTransport(responder=timeout if unknown else None)
    assess,calls=_make_monitor_double(snap)
    with patch.object(exact_adapter,'assess_candidate',assess):
        first=run_jev_job(plan,'G00',task,monitor_snapshot=snap,admission=binding,root=tmp_path/'run',ledger=ledger,transport=transport)
    if unknown:assert first['summary']['termination_class']=='UNKNOWN_SEND'
    before=len(transport.bodies)
    # Reopen from durable bytes: failed/unknown send reservations still count.
    ledger=GeometryJevRequestLedger(ledger.root,plan_digest=digest(plan),per_job_max_sends=1,shared_max_sends=1)
    with patch.object(exact_adapter,'assess_candidate',side_effect=AssertionError('ASSESS_FORBIDDEN')) as mon, \
         patch.object(balance_network,'linprog',side_effect=AssertionError('LP_FORBIDDEN')) as lp, \
         patch('semantic_pallet_planner.jev_select.execution.commit_physical',side_effect=AssertionError('COMMIT_FORBIDDEN')) as commit:
        stopped=run_jev_job(plan,'G01',task,monitor_snapshot=snap,admission=binding,root=tmp_path/'run',ledger=ledger,transport=transport)
        assert stopped['checkpoint']['reason']=='BUDGET_EXHAUSTED'
        run_jev_job(plan,'G01',task,monitor_snapshot=snap,admission=binding,root=tmp_path/'run',ledger=ledger,transport=transport,resume=stopped['checkpoint'])
        assert len(transport.bodies)==before==1
        assert mon.call_count==lp.call_count==commit.call_count==0


def test_singleton_checkpoint_remains_zero_send_on_resume(tmp_path):
    task=_adapted_synth('K02_INT');snap=_fake_monitor_snapshot()
    plan=prepare_jev_plan([task],data_identity=digest('SYNTHETIC_ONLY'),per_job_max_sends=4,shared_max_sends=8)
    binding=development_binding(plan)
    ledger=GeometryJevRequestLedger(tmp_path/'req',plan_digest=digest(plan),per_job_max_sends=4,shared_max_sends=8)
    transport=FakeChoiceTransport();assess,calls=_make_monitor_double(snap);saved={}
    def stop(stage,cp):
        if stage=='after_selected_checkpoint' and cp['pending_event']['selection']['source']=='singleton':
            saved['cp']=copy.deepcopy(cp);raise Cut()
    with patch.object(exact_adapter,'assess_candidate',assess):
        with pytest.raises(Cut):
            run_jev_job(plan,'G01',task,monitor_snapshot=snap,admission=binding,root=tmp_path/'run',ledger=ledger,transport=transport,hook=stop)
        run_jev_job(plan,'G01',task,monitor_snapshot=snap,admission=binding,root=tmp_path/'run',ledger=ledger,transport=transport,resume=saved['cp'])
    assert len(transport.bodies)==1 and len(calls)==2
    did=saved['cp']['pending_event']['decision_id']
    assert ledger.find_attempt('G01',did) is None
