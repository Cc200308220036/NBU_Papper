"""JN0 behavior tests use explicitly constructed orders, not the real run matrix."""
import copy
from pathlib import Path
import pytest

from semantic_pallet_planner.jev_select.tests.unit.test_packaging_runtime import mechanism_task,item
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.packaging_protocol import selector_factory
from semantic_pallet_planner.jev_select.packaging_experiment import _run_job,validate_saved_checkpoint
from semantic_pallet_planner.jev_select.packaging_metrics import job_metrics,aggregate
from semantic_pallet_planner.jev_select.stability.monitor import load_monitor_config,seal_checkpoint
from semantic_pallet_planner.jev_select.episode import run_episode


def fixture(n=6):
    t=mechanism_task([item(str(i),size=(20,20,20)) for i in range(n)])
    t['source_group_id']='CONSTRUCTED_SOURCE'
    c=load_monitor_config(data_identity=digest('CONSTRUCTED_ONLY'),task_digest=digest(t),enabled=True)
    return t,c,{'job_id':'J','method_id':c['selector'],'config':c}


def start(job):
    write(job/'status.json',{'state':'NOT_RUN','category':'NOT_RUN','active_wall_s':0.,'error':None})


def test_full_order_exceeds_smoke_and_metrics(tmp_path):
    t,c,j=fixture();start(tmp_path)
    s=_run_job(t,j,tmp_path,{'max_events':1000,'max_active_wall_s':60})
    cp=read(tmp_path/'checkpoint.json');m=read(tmp_path/'metrics.json')
    assert s['category']=='COMPLETE' and len(cp['events'])>8
    assert m['loading']['placed_items']==6 and m['stable_complete']
    assert m['cost']['model_calls']==0 and m['assessable_coverage']==1
    assert m['fixed_container_utilization']>0 and m['latency_s']['candidate']['n']==6
    validate_saved_checkpoint(cp,t,c,'J')


@pytest.mark.parametrize('phase',['SELECTED','MONITORED','COMMITTED','READY','TERMINATED'])
def test_full_order_stage_resume_no_double_load(phase,tmp_path,monkeypatch):
    t,c,j=fixture();saved=[]
    class Cut(RuntimeError):pass
    def checkpoint(cp):
        if cp['phase']==phase and (cp['decision']>=2 or phase=='TERMINATED'):
            saved.append(copy.deepcopy(cp));raise Cut()
    if phase=='TERMINATED':
        saved.append(run_episode(t,selector_factory(c['selector']),c,job_id='J',method=c['selector'])['checkpoint'])
    else:
        with pytest.raises(Cut):
            run_episode(t,selector_factory(c['selector']),c,job_id='J',method=c['selector'],on_checkpoint=checkpoint)
    cp=saved[0];validate_saved_checkpoint(cp,t,c,'J')
    # Stored decisions may not re-enter selector; future decisions still may.
    from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
    original=LocalPackagingDouble.select;seen=[]
    def select(self,context,*,decision_id):
        assert decision_id not in {e['decision_id'] for e in cp['events'] if e.get('decision_id')}
        if phase in ('SELECTED','MONITORED','COMMITTED'):
            assert decision_id!=cp['pending_event']['decision_id']
        seen.append(decision_id);return original(self,context,decision_id=decision_id)
    monkeypatch.setattr(LocalPackagingDouble,'select',select)
    ep=run_episode(t,selector_factory(c['selector']),c,job_id='J',method=c['selector'],resume=cp)
    again=run_episode(t,selector_factory(c['selector']),c,job_id='J',method=c['selector'],resume=ep['checkpoint'])
    assert again['checkpoint']==ep['checkpoint']
    assert len(ep['final_state']['placed_items'])==6
    assert sum(e['event']=='PLACE' for e in ep['events'])==6
    assert not read_load_violations(ep['final_state'])


def read_load_violations(state):
    from semantic_pallet_planner.jev_select.packaging_runtime import evaluate_state
    return evaluate_state(state)['violations']


@pytest.mark.parametrize('watchdog',[{'max_events':2,'max_active_wall_s':60},{'max_events':1000,'max_active_wall_s':1e-9}])
def test_technical_limit_full_denominator(watchdog,tmp_path):
    t,c,j=fixture();start(tmp_path)
    s=_run_job(t,j,tmp_path,watchdog);m=read(tmp_path/'metrics.json')
    assert s['category']=='TECHNICAL_LIMIT' and not m['completed']
    assert m['loading']['planned_items']==6 and m['loading']['placed_items']==0
    a=aggregate([m],8)
    assert a['planned_jobs']==8 and a['categories']['NOT_RUN']==7 and a['complete_rate']==0


def test_cancel_and_technical_error(tmp_path,monkeypatch):
    import semantic_pallet_planner.jev_select.episode as ep
    def cancel(*a,**kw):raise KeyboardInterrupt()
    t,c,j=fixture();start(tmp_path);monkeypatch.setattr(ep,'run_episode',cancel)
    assert _run_job(t,j,tmp_path,{'max_events':100,'max_active_wall_s':60})['category']=='CANCELED'
    def fail(*a,**kw):raise RuntimeError('constructed technical fault')
    monkeypatch.setattr(ep,'run_episode',fail);start(tmp_path)
    assert _run_job(t,j,tmp_path,{'max_events':100,'max_active_wall_s':60})['category']=='ERROR'


def test_saved_validation_does_not_dispatch_and_rejects_resigned_tamper(monkeypatch):
    t,c,j=fixture()
    ep=run_episode(t,selector_factory(c['selector']),c,job_id='J',method=c['selector']);cp=ep['checkpoint']
    def forbidden(*a,**k):raise AssertionError('forbidden execution during saved audit')
    import semantic_pallet_planner.jev_select.execution as ex
    import semantic_pallet_planner.jev_select.stability.balance_adapter as ba
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
    monkeypatch.setattr(ex,'commit_physical',forbidden);monkeypatch.setattr(ba,'assess_candidate',forbidden)
    monkeypatch.setattr(CandidateProvider,'build',forbidden)
    validate_saved_checkpoint(cp,t,c,'J')
    bad=copy.deepcopy(cp);next(e for e in bad['events'] if e['event']=='PLACE')['selection']['selected_candidate_id']='tampered'
    seal_checkpoint(bad)
    with pytest.raises(JevSelectError):validate_saved_checkpoint(bad,t,c,'J')


def test_registry_and_unchanged_smoke_limit(tmp_path):
    for m in ('jev_choice','jev_no_memory','shared_geometry'):
        with pytest.raises(JevSelectError):selector_factory(m)
    from semantic_pallet_planner.jev_select.stability.runtime import smoke
    with pytest.raises(JevSelectError,match='monitor_smoke_event_limit'):
        smoke('NOT_READ',Path(__file__).resolve().parents[2]/'outputs/NEVER_CREATED_JN0_SMOKE_LIMIT',event_limit=9)


def constructed_plan(tmp_path,monkeypatch,watchdog=None):
    import semantic_pallet_planner.jev_select.packaging_experiment as pe
    t,c,j=fixture(1);t.update(source_group_id='CONSTRUCTED_SOURCE',source_order_key='CONSTRUCTED',partition='train')
    data={'data_identity':digest('CONSTRUCTED_ONLY'),'tasks':[t]}
    inv={'tasks':[{'task_id':t['task_id'],'source_group_id':t['source_group_id'],'distinct_capacity_count':1,'distinct_mass_count':1,'items':1}]}
    monkeypatch.setattr(pe,'REPO',tmp_path)
    monkeypatch.setattr(pe,'load_runtime_dataset',lambda _:copy.deepcopy(data))
    monkeypatch.setattr(pe,'inventory',lambda *a:copy.deepcopy(inv))
    def fresh(path):
        path=Path(path)
        if path.exists():raise JevSelectError('full_order_output_exists')
        path.mkdir(parents=True);return path
    monkeypatch.setattr(pe,'new_output',fresh)
    spec={} if watchdog is None else {'watchdog':watchdog}
    pe.prepare_packaging_plan(tmp_path/'dataset',spec,tmp_path/'plan')
    return pe,t


def test_frozen_plan_scope_config_and_source_changes(tmp_path,monkeypatch):
    pe,t=constructed_plan(tmp_path,monkeypatch)
    pe.validate_packaging_plan(tmp_path/'plan')
    for kw in ({'task_ids':['outside']},{'method_ids':['jev_choice']}):
        with pytest.raises(JevSelectError):pe.run_packaging_plan(tmp_path/'plan',tmp_path/'run',**kw)
    plan=read(tmp_path/'plan/plan.json');plan['jobs'][0]['config']['buffer_capacity']=1
    write(tmp_path/'plan/plan.json',plan)
    with pytest.raises(JevSelectError):pe.validate_packaging_plan(tmp_path/'plan')


def test_complete_pair_saved_audit_and_completed_resume(tmp_path,monkeypatch):
    pe,t=constructed_plan(tmp_path,monkeypatch)
    result=pe.run_packaging_plan(tmp_path/'plan',tmp_path/'run')
    assert result['complete_rate']==1 and result['planned_jobs']==2
    def forbidden(*a,**k):raise AssertionError('completed resume must not execute')
    monkeypatch.setattr(pe,'_run_job',forbidden)
    assert pe.run_packaging_plan(tmp_path/'plan',tmp_path/'run',resume=True)==result
    assert pe.validate_packaging_run(tmp_path/'run')['status']=='PASS'
    p=tmp_path/'run/jobs/J0000/metrics.json';m=read(p);m['loading']['placed_items']=42;write(p,m)
    write(tmp_path/'run/delivery_manifest.json',pe.file_manifest(tmp_path/'run'))
    with pytest.raises(JevSelectError):pe.validate_packaging_run(tmp_path/'run')


def test_watchdog_stops_batch_preserves_not_run(tmp_path,monkeypatch):
    pe,t=constructed_plan(tmp_path,monkeypatch,{'max_events':1,'max_active_wall_s':60})
    result=pe.run_packaging_plan(tmp_path/'plan',tmp_path/'run')
    assert result['categories']['TECHNICAL_LIMIT']==1 and result['categories']['NOT_RUN']==1
    assert result['planned_jobs']==2


def test_run_resume_after_process_loss(tmp_path,monkeypatch):
    pe,t=constructed_plan(tmp_path,monkeypatch)
    import semantic_pallet_planner.jev_select.episode as episode
    original=episode.run_episode
    class ProcessLoss(BaseException):pass
    def crash(*args,**kwargs):
        persist=kwargs['on_checkpoint']
        def interrupted(cp):
            persist(cp)
            if cp['phase']=='COMMITTED':raise ProcessLoss()
        kwargs['on_checkpoint']=interrupted
        return original(*args,**kwargs)
    monkeypatch.setattr(episode,'run_episode',crash)
    with pytest.raises(ProcessLoss):pe.run_packaging_plan(tmp_path/'plan',tmp_path/'run')
    assert read(tmp_path/'run/jobs/J0000/checkpoint.json')['phase']=='COMMITTED'
    monkeypatch.setattr(episode,'run_episode',original)
    result=pe.run_packaging_plan(tmp_path/'plan',tmp_path/'run',resume=True)
    assert result['complete_rate']==1
    for p in (tmp_path/'run/jobs').glob('*/metrics.json'):
        assert read(p)['loading']['placed_items']==1


@pytest.mark.parametrize('command',['plan-packaging-orders','run-packaging-orders'])
def test_cli_receipt_status(command,monkeypatch,capsys):
    import semantic_pallet_planner.jev_select.packaging_experiment as pe
    from semantic_pallet_planner.jev_select.cli import main
    monkeypatch.setattr(pe,'prepare_packaging_plan',lambda *a,**k:{'planned_jobs':8})
    monkeypatch.setattr(pe,'run_packaging_plan',lambda *a,**k:{'planned_jobs':8})
    args=([command,'--dataset','NOT_READ','--output','NOT_WRITTEN'] if command.startswith('plan') else
        [command,'--plan','NOT_READ','--output','NOT_WRITTEN'])
    assert main(args)==0
    assert 'PASS' in capsys.readouterr().out


def test_empty_pool_null_monitor_is_natural_stop_with_full_denominator(tmp_path):
    t=mechanism_task([item(str(i),size=(2000,2000,2000)) for i in range(4)])
    t['source_group_id']='CONSTRUCTED_EMPTY_POOL'
    c=load_monitor_config(data_identity=digest('CONSTRUCTED_EMPTY_POOL'),task_digest=digest(t),enabled=True)
    j={'job_id':'J','method_id':c['selector'],'config':c};start(tmp_path)
    result=_run_job(t,j,tmp_path,{'max_events':100,'max_active_wall_s':60})
    assert result['category']=='EMPTY_POOL' and result['error'] is None
    cp=read(tmp_path/'checkpoint.json');validate_saved_checkpoint(cp,t,c,'J')
    m=read(tmp_path/'metrics.json')
    assert cp['events'][-1]['monitor'] is None
    assert m['loading']['planned_items']==4 and m['loading']['arrived_items']==3
    assert m['loading']['placed_items']==0 and m['actual_height_mm']=='NA'
    assert m['selected_actions']==0 and m['assessable_coverage']=='NA'
    assert aggregate([m],8)['categories']['EMPTY_POOL']==1
