import pytest
from semantic_pallet_planner.jev_select.batch_j4 import prepare_j4, run_j4
from semantic_pallet_planner.jev_select.contracts import JevSelectError
from semantic_pallet_planner.jev_select.ledger import read


def plan(tmp_path):
    prepare_j4(tmp_path/'plan',methods=['jev_no_memory'])
    return tmp_path/'plan'


def test_offline_records_not_replay(tmp_path,monkeypatch):
    p=plan(tmp_path)
    def forbidden(*a,**k):raise AssertionError('records must not replay')
    monkeypatch.setattr('semantic_pallet_planner.jev_select.batch.replay_experiment_v2',forbidden)
    result=run_j4(p,tmp_path/'run',offline=True)
    assert result['verified_jobs']==6 and result['environment_steps']==0
    assert read(tmp_path/'run/verification_report.json')['full_replay_performed'] is False
    assert read(tmp_path/'run/metrics/summary.json')['model_api_calls']==0
    assert run_j4(p,tmp_path/'run',offline=True,resume=True)==result


@pytest.mark.parametrize('phase',['after_reserve','after_response','after_commit_checkpoint'])
def test_interrupt_resume_no_duplicate(tmp_path,phase):
    p=plan(tmp_path);fired=False
    def hook(current,value):
        nonlocal fired
        if current==phase and not fired:fired=True;raise KeyboardInterrupt('fixture')
    with pytest.raises(KeyboardInterrupt):run_j4(p,tmp_path/'run',offline=True,hook=hook)
    first=read(tmp_path/'run/audit/attempts.json')['attempts'][0]['attempt_id']
    run_j4(p,tmp_path/'run',offline=True,resume=True)
    a=read(tmp_path/'run/audit/attempts.json')['attempts']
    assert a[0]['attempt_id']==first and len({(x['job_id'],x['decision_id']) for x in a})==len(a)
    if phase=='after_reserve':assert a[0]['state']=='UNKNOWN_IN_FLIGHT'


def test_evaluation_failure_recovery(tmp_path,monkeypatch):
    p=plan(tmp_path)
    import semantic_pallet_planner.jev_select.evaluation as ev
    original=ev.evaluate_committed_state;once=True
    def fail(*a,**k):
        nonlocal once
        if once:once=False;raise ValueError('fixture')
        return original(*a,**k)
    monkeypatch.setattr(ev,'evaluate_committed_state',fail)
    assert run_j4(p,tmp_path/'run',offline=True)['status']=='NEEDS_RECOVERY'
    assert read(tmp_path/'run/checkpoints/J0000.json')['phase']=='COMMITTED'
    monkeypatch.setattr(ev,'evaluate_committed_state',original)
    assert run_j4(p,tmp_path/'run',offline=True,resume=True)['status']=='PASS'


def test_scope_and_budget_early_rejection(tmp_path):
    with pytest.raises(JevSelectError,match='finite_api_budget'):prepare_j4(tmp_path/'bad',mode='remote')
    with pytest.raises(JevSelectError,match='invalid_j4_methods'):prepare_j4(tmp_path/'b1',methods=['unsupported_method'])
    assert not (tmp_path/'bad').exists() and not (tmp_path/'b1').exists()


def test_selected_non_geometry_option_is_executed(tmp_path):
    prepare_j4(tmp_path/'plan',methods=['jev_no_memory'],offline_scenario='pick_last')
    run_j4(tmp_path/'plan',tmp_path/'run',offline=True)
    ep=read(tmp_path/'run/episodes/J0000.json')
    for e in ep['events']:
        if e['event']!='PLACE':continue
        ctx=e['context'];label=e['selection']['selected_display_id']
        assert label==sorted(ctx['criteria'])[-1]
        mapping=ctx['display_mapping'][label]
        placed=next(o for o in e['after']['placed_items'] if o['item_id']==mapping['pick_item_id'])
        assert placed['pose']==ctx['criteria'][label]['pose']
