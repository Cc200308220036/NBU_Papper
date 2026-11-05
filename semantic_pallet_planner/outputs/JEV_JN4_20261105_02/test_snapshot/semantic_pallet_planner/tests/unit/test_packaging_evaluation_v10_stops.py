"""v10 monitor stops and CLI failure status; constructed/Fake only."""
from pathlib import Path
from dataclasses import replace
import pytest
from test_packaging_evaluation_v10 import setup
from semantic_pallet_planner.jev_select import packaging_evaluation_orders as p
from semantic_pallet_planner.jev_select.ledger import read

@pytest.mark.parametrize('status,code,left',[('UNASSESSABLE','POSE_HEIGHT_MISMATCH',0),('ERROR','BALANCE_KERNEL_ERROR',5)])
def test_v10_common_monitor_stop_and_complete_denominator(tmp_path,monkeypatch,status,code,left):
    plan,f=setup(tmp_path)
    from semantic_pallet_planner.jev_select.stability import balance_adapter as ba
    original=ba.assess_candidate
    monkeypatch.setattr(ba,'assess_candidate',lambda *a,**k:replace(original(*a,**k),status=status,reason_code=code))
    result=p.run_validation(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:f)
    assert result['categories']['NOT_RUN']==left
    assert result['categories']['UNASSESSABLE' if status=='UNASSESSABLE' else 'ERROR']==(6 if status=='UNASSESSABLE' else 1)
    for j in plan['jobs'][:6-left]:
        cp=read(tmp_path/'run/jobs'/j['job_id']/'checkpoint.json')
        assert cp['state']['placed_count']==0 and len(cp['state']['pending_items'])==3
        assert cp['events'][-1]['before']==cp['events'][-1]['after'] and cp['events'][-1]['action'] is None
    p.validate_run(tmp_path/'run')


def test_v10_cli_technical_failure_nonzero_exit(tmp_path,monkeypatch,capsys):
    plan,f=setup(tmp_path,watchdog={'max_events':1,'max_active_wall_s':1800})
    result=p.run_validation(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:f)
    assert result['status']=='ERROR' and result['categories']['NOT_RUN']==5 and f.calls==0
    monkeypatch.setattr('sys.argv',['evaluation','validate-run','--output',str(tmp_path/'run')])
    with pytest.raises(SystemExit) as exc:p.main()
    assert exc.value.code==1


def test_saved_validation_error_invalidates_success_gate_and_resume(tmp_path,monkeypatch):
    from semantic_pallet_planner.jev_select.contracts import JevSelectError
    plan,f=setup(tmp_path);original=p.validate_run
    def fail(*a,**k):raise JevSelectError('CONSTRUCTED_VALIDATION_FAILURE')
    monkeypatch.setattr(p,'validate_run',fail)
    with pytest.raises(JevSelectError):p.run_validation(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:f)
    assert read(tmp_path/'run/summary.json')['status']=='ERROR'
    assert read(tmp_path/'run/first_gate.json')['status']=='STOP_TECHNICAL'
    assert read(tmp_path/'run/technical_failure.json')['phase']=='EVALUATION_SAVED_VALIDATION'
    calls=f.calls;monkeypatch.setattr(p,'validate_run',original)
    original(tmp_path/'run')
    assert p.run_validation(tmp_path/'plan',tmp_path/'run',resume=True,continue_pending=True,transport_factory=lambda *a:f)['status']=='ERROR'
    assert f.calls==calls
