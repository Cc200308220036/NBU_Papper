"""QA-JM1A3-01: production validator and entry point, new fake runs only."""
import hashlib
import shutil

import pytest

from test_packaging_jev_forks import archived, stub_monitor
from test_packaging_jev_continuation import FakeTransport, frozen_inputs, guards
from test_packaging_jev_recovery import Crash, schedule, run, run_root
from semantic_pallet_planner.jev_select import packaging_jev_forks as jm
from semantic_pallet_planner.jev_select import packaging_jev_recovery as a3
from semantic_pallet_planner.jev_select.contracts import DecisionContext, JevSelectError
from semantic_pallet_planner.jev_select.ledger import read, write
from semantic_pallet_planner.jev_select.selector import bind_decision


def snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def stopped_run(archived, monkeypatch, point):
    start,_,_=archived
    stub_monitor(monkeypatch,'STABLE');frozen_inputs(monkeypatch,start)
    s=schedule(start);fake=FakeTransport()
    def interrupt(state,row):
        if state==point:raise Crash()
    with pytest.raises(Crash):run(s,fake,ledger_hook=interrupt)
    root=run_root(s)
    assert not (root/'episode.json').exists()
    return s,fake,root


def assert_rejected_without_dispatch(s,fake,root,monkeypatch,evidence):
    from semantic_pallet_planner.jev_select import episode,execution
    from semantic_pallet_planner.jev_select.packaging_remote import PackagingRemoteSelector
    from semantic_pallet_planner.jev_select.stability import monitor
    counters={k:0 for k in ('selector','transport','monitor','commit','candidate_inputs','selector_factory')}
    def forbid(name):
        def invoke(*a,**kw):
            counters[name]+=1
            pytest.fail('unexpected business dispatch: '+name)
        return invoke
    monkeypatch.setattr(PackagingRemoteSelector,'select',forbid('selector'))
    monkeypatch.setattr(fake,'complete',forbid('transport'))
    monkeypatch.setattr(monitor,'monitor_selected_action',forbid('monitor'))
    monkeypatch.setattr(execution,'commit_physical',forbid('commit'))
    monkeypatch.setattr(episode,'decision_inputs',forbid('candidate_inputs'))
    monkeypatch.setattr(a3,'selector_factory',forbid('selector_factory'))
    before=snapshot(jm.REPO/'a3')
    rejections=[]
    for name,call in [('validate_saved_execution',lambda:a3.validate_saved_execution(root)),
                      ('run_repeat',lambda:run(s,fake))]:
        with pytest.raises(JevSelectError) as exc:call()
        assert snapshot(jm.REPO/'a3')==before
        assert not any(counters.values())
        rejections.append({'entry':name,'error_code':exc.value.code,'dispatch_counts':dict(counters),
                           'remaining_files_unchanged':True})
    write(evidence,{'version':'jm1_a3_progress_rejection_v1','production_validator':True,
          'identities_or_schemas_substituted':False,'remaining_files_before':before,
          'remaining_files_after':snapshot(jm.REPO/'a3'),'rejections':rejections})


@pytest.mark.parametrize('point',['CONTEXT_SAVED','RESERVATION_SAVED','INTENT','RESPONSE_SAVED','SELECTION_SAVED'])
def test_joint_journal_head_loss_rejected_before_dispatch(archived,monkeypatch,point):
    s,fake,root=stopped_run(archived,monkeypatch,point)
    saved=a3.validate_saved_execution(root)
    assert saved['checkpoint']['phase']=='DECISION_READY'
    original_before=snapshot(root)
    original=jm.REPO;copy_root=original/'independent_copy'
    shutil.copytree(original/'parent',copy_root/'parent')
    shutil.copytree(original/'a3',copy_root/'a3')
    copied=copy_root/root.relative_to(original)
    assert snapshot(root)==snapshot(copied)
    shutil.rmtree(copied/'stages');(copied/'checkpoint_head.json').unlink()
    monkeypatch.setattr(jm,'REPO',copy_root)
    assert not (copied/'episode.json').exists()
    assert_rejected_without_dispatch(s,fake,copied,monkeypatch,original/'joint_loss_receipt.json')
    assert snapshot(root)==original_before


@pytest.mark.parametrize('point',['CONTEXT_SAVED','RESERVATION_SAVED','INTENT'])
def test_orphan_future_decision_progress_rejected(archived,monkeypatch,point):
    s,fake,root=stopped_run(archived,monkeypatch,'RESPONSE_SAVED')
    cp=a3.validate_saved_execution(root)['checkpoint'];ex=s['executions'][0];job=ex['branch_id']
    config=archived[2];did=job+'_D0002'
    context=bind_decision(DecisionContext.from_dict(cp['pending_event']['context']),job,did,config=config)
    def interrupt(state,row):
        if state==point:raise Crash()
    ledger=a3.RecoveryLedger(root/'ledger',ex,hook=interrupt)
    with pytest.raises(Crash):ledger.request(context,job,did,fake)
    assert len(fake.calls)==1
    assert_rejected_without_dispatch(s,fake,root,monkeypatch,jm.REPO/'orphan_receipt.json')


@pytest.mark.parametrize('point',['RESPONSE_SAVED','SELECTION_SAVED'])
def test_current_decision_ready_response_remains_recoverable(archived,monkeypatch,point):
    s,fake,root=stopped_run(archived,monkeypatch,point)
    before=snapshot(root);saved=a3.validate_saved_execution(root)
    assert saved['checkpoint']['phase']=='DECISION_READY' and saved['states']==[point]
    assert snapshot(root)==before and len(fake.calls)==1
    ep=run(s,fake)
    assert ep['checkpoint']['reason']=='ALL_ITEMS_PLACED' and len(fake.calls)==3
    write(jm.REPO/'legal_response_receipt.json',{'point':point,'saved_phase':'DECISION_READY',
          'final_sends':len(fake.calls),'completed':True,'saved_validation_readonly':True})


def test_activation_with_empty_ledger_still_recovers(archived,monkeypatch):
    s,fake,root=stopped_run(archived,monkeypatch,'ACTIVATED')
    a3.RecoveryLedger(root/'ledger',s['executions'][0])
    saved=a3.validate_saved_execution(root)
    assert saved['checkpoint']['phase']=='SELECTED' and saved['requests']==0 and saved['sequence']==0
    ep=run(s,fake)
    assert ep['checkpoint']['reason']=='ALL_ITEMS_PLACED' and len(fake.calls)==3
