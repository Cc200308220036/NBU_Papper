"""P2/P3 integration; all tasks constructed, critical classifications use real v2."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from semantic_pallet_planner.jev_select.tests.unit.test_packaging_runtime import (
    mechanism_task,item,manual_candidate,StackDouble)
from semantic_pallet_planner.jev_select.stability.monitor import (
    load_monitor_config,validate_checkpoint,seal_checkpoint,freeze)
from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
from semantic_pallet_planner.jev_select.episode import run_episode,decision_inputs
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError,CandidateBundle
from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive


def config(task,enabled=True):
    return load_monitor_config(data_identity=digest('CONSTRUCTED'),task_digest=digest(task),enabled=enabled)


def run(task,cfg,**kw):
    return run_episode(task,LocalPackagingDouble(),cfg,job_id='P',method=cfg['selector'],**kw)


def test_off_no_kernel_import_and_same_old_behavior():
    script='''
import builtins,sys
real=builtins.__import__
def blocked(name,*a,**kw):
 if name.startswith('scipy') or any(x in name for x in ('balance_adapter','balance_network','pct_adapter','vendor.pct')):
  raise AssertionError('disabled imported '+name)
 return real(name,*a,**kw)
builtins.__import__=blocked
from semantic_pallet_planner.jev_select.tests.unit.test_packaging_runtime import mechanism_task,item
from semantic_pallet_planner.jev_select.stability.monitor import load_monitor_config
from semantic_pallet_planner.jev_select.packaging_runtime import load_runtime_config,LocalPackagingDouble
from semantic_pallet_planner.jev_select.episode import run_episode
from semantic_pallet_planner.jev_select.contracts import digest
t=mechanism_task([item('a'),item('b')]);cfg=load_monitor_config(data_identity=digest('x'),task_digest=digest(t))
e=run_episode(t,LocalPackagingDouble(),cfg,job_id='P',method=cfg['selector'])
v4=load_runtime_config(data_identity=digest('x'),task_digest=digest(t))
old=run_episode(t,LocalPackagingDouble(),v4,job_id='P',method=v4['selector'])
assert e['final_state']==old['final_state']
assert [x.get('action') for x in e['events']]==[x.get('action') for x in old['events']]
s=e['summary']['monitor_statistics'];assert s['statuses']['DISABLED']==2 and s['actual_assessments']==0
assert s['stable_complete_rate']=='NOT_APPLICABLE'
assert not any(n.startswith('scipy') or '.vendor.pct' in n or n.endswith('balance_adapter') for n in sys.modules)
'''
    subprocess.run([sys.executable,'-c',script],check=True,env=os.environ.copy())


def test_on_off_pool_order_numbering_and_body_equal():
    task=mechanism_task([item('a'),item('b'),item('c')]);s=initial(task['container'],3)
    for o in task['items']:s=receive(s,o,task['attributes'][o['item_id']])
    inputs=[decision_inputs(s,task,config(task,e),'P','P_D0000') for e in (False,True)]
    a,b=inputs
    for key in ('physical_candidates','selectable_candidates','generation_counts','physical_digest','selectable_digest'):
        assert a[2].data[key]==b[2].data[key]
    for key in ('request_body','display_mapping','criteria','model_state'):
        assert a[3].data[key]==b[3].data[key]
    assert LocalPackagingDouble().select(a[3],decision_id='P_D0000').data['selected_candidate_id']==LocalPackagingDouble().select(b[3],decision_id='P_D0000').data['selected_candidate_id']


@pytest.mark.parametrize('phase',['SELECTED','MONITORED','COMMITTED','READY','TERMINATED'])
def test_recovery_no_reselection_no_reassessment_and_repeat(phase,monkeypatch,tmp_path):
    from semantic_pallet_planner.jev_select.ledger import write,read
    task=mechanism_task([item('a')]);cfg=config(task);saved=[];path=tmp_path/'checkpoint.json'
    class Cut(RuntimeError):pass
    def hook(name,cp):
        target={'SELECTED':'after_selected_checkpoint','MONITORED':'after_monitored_checkpoint',
                'COMMITTED':'after_commit_checkpoint','READY':'after_checkpoint','TERMINATED':'never'}[phase]
        if name==target and (phase!='READY' or cp['decision']>0):
            saved.append(copy.deepcopy(cp));raise Cut()
    if phase=='TERMINATED':cp=run(task,cfg,on_checkpoint=lambda cp:write(path,cp))['checkpoint']
    else:
        with pytest.raises(Cut):run(task,cfg,hook=hook,on_checkpoint=lambda cp:write(path,cp))
        cp=saved[0]
    assert read(path)==cp
    # Interrupted atomic leftovers have no part in selecting a valid checkpoint.
    (tmp_path/'.atomic-debris').write_text('{invalid')
    def forbidden(*a,**kw):raise AssertionError('reselected or reassessed')
    monkeypatch.setattr(LocalPackagingDouble,'select',forbidden)
    if phase!='SELECTED':
        import semantic_pallet_planner.jev_select.stability.balance_adapter as ba
        monkeypatch.setattr(ba,'assess_candidate',forbidden)
    resumed=run(task,cfg,resume=cp)
    assert resumed['final_state']['placed_count']==1 and len(resumed['events'])==3
    again=run(task,cfg,resume=resumed['checkpoint'])
    assert again['checkpoint']==resumed['checkpoint']
    assert sum(e['event']=='PLACE' for e in again['events'])==1


def fixture_provider(monkeypatch,choices=False):
    """Constructed oracle-admissible pool; no claim about Top16 reachability."""
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
    original=CandidateProvider.build
    def build(self,state,obs,generator_config,*,config):
        b=original(self,state,obs,generator_config,config=config).data
        pending={p['item']['item_id'] for p in state['pending_items']}
        name=next(n for n in ('base','shelf','top','later') if n in pending)
        poses={'base':(-70,-100,0),'shelf':(-70,-100,100),'top':(70,-50,200),'later':(-300,-300,0)}
        x,y,z=poses[name];raw,error=manual_candidate(state,name,x=x,y=y,z=z)
        assert error is None,(name,error)
        pool=[raw['visible']]
        if choices:
            alt,err=manual_candidate(state,name,x=-400,y=-400,z=0)
            assert err is None;pool.append(alt['visible'])
        b.update(physical_candidates=pool,physical_digest=digest(pool),selectable_candidates=[],
                 selectable_digest=digest([]),selectable_pool='unfiltered')
        return CandidateBundle.from_dict(b)
    monkeypatch.setattr(CandidateProvider,'build',build)


def unstable_task():
    return mechanism_task([item('base',size=(140,200,100),capacity=200),
        item('shelf',size=(200,200,100),capacity=200),
        item('top',mass=100,size=(60,100,100)),item('later')])


@pytest.mark.parametrize('choices',[False,True])
def test_real_ancestor_instability_stops_without_place_or_alternative(monkeypatch,choices):
    fixture_provider(monkeypatch,choices)
    task=unstable_task();cfg=config(task)
    # C01 display order is randomized. Choose known constructed placement from
    # visible facts only, without inspecting monitor output.
    class Exact(LocalPackagingDouble):
        calls=0
        def select(self,context,*,decision_id):
            from semantic_pallet_planner.jev_select.selector import result
            self.calls+=1
            wanted=next(l for l,c in context.data['criteria'].items() if c['pose']['x_mm']>-300)
            return result(context,status='selected',source='test_double',label=wanted)
    sel=Exact();ep=run_episode(task,sel,cfg,job_id='P',method=cfg['selector'])
    assert ep['checkpoint']['reason']=='PREDICTED_STATIC_INSTABILITY'
    assert ep['final_state']['placed_count']==2
    assert [o['item_id'] for o in ep['final_state']['placed_items']]==['base','shelf']
    last=ep['events'][-1]
    assert last['before']==last['after'] and last['action'] is None
    assert last['monitor']['result']['diagnostics']['infeasibility_certificate']['verified']
    assert last['monitor']['result']['version']=='pct_stability_result_v2'
    assert sel.calls==(3 if choices else 0)
    assert ep['summary']['placed_mass_kg']==2
    assert ep['summary']['monitor_statistics']['statuses']==dict(DISABLED=0,STABLE=2,UNSTABLE=1,UNASSESSABLE=0,ERROR=0)
    validate_checkpoint(ep['checkpoint'],task,cfg,'P',cfg['selector'])
    # Terminal resume never executes the remaining buffer or suffix.
    assert run_episode(task,sel,cfg,job_id='P',method=cfg['selector'],resume=ep['checkpoint'])['checkpoint']==ep['checkpoint']


@pytest.mark.parametrize('status,reason',[('UNASSESSABLE','STABILITY_UNASSESSABLE'),('ERROR','STABILITY_MONITOR_ERROR')])
def test_explicit_fault_injection_technical_branches(monkeypatch,status,reason):
    from dataclasses import replace
    from semantic_pallet_planner.jev_select.stability import balance_adapter as ba
    real=ba.assess_candidate
    def inject(*a,**kw):
        return replace(real(*a,**kw),status=status,reason_code='EXPLICIT_TEST_FAULT')
    monkeypatch.setattr(ba,'assess_candidate',inject)
    t=mechanism_task([item('a'),item('b')]);cfg=config(t);ep=run(t,cfg)
    assert ep['checkpoint']['reason']==reason and ep['final_state']['placed_count']==0
    assert ep['summary']['monitor_statistics']['statuses']['UNSTABLE']==0
    validate_checkpoint(ep['checkpoint'],t,cfg,'P',cfg['selector'])


def test_missing_dependency_and_config_conflict(monkeypatch):
    import builtins
    orig=builtins.__import__
    def blocked(name,*a,**k):
        if name.endswith('balance_adapter'):raise ImportError('explicit missing dependency injection')
        return orig(name,*a,**k)
    monkeypatch.setattr(builtins,'__import__',blocked)
    with pytest.raises(JevSelectError,match='stability_preflight_failed'):freeze(True)
    assert freeze(False)['enabled'] is False
    with pytest.raises(JevSelectError,match='cli_config_conflict'):
        load_monitor_config(data_identity=digest('x'),task_digest=digest('t'),enabled=True,monitor_config={'enabled':False})


@pytest.mark.parametrize('target',['state','candidate','task','config','enabled','algorithm','result','selection','phase','reason'])
def test_tampering_rejected_even_with_outer_checkpoint_resealed(target):
    task=mechanism_task([item('a')]);cfg=config(task);cp=run(task,cfg)['checkpoint']
    bad=copy.deepcopy(cp);tc=copy.deepcopy(task);cc=copy.deepcopy(cfg)
    e=next(e for e in bad['events'] if e.get('monitor'))
    if target=='state':bad['state']['placed_count']+=1
    elif target=='candidate':e['bundle']['physical_candidates'][0]['pose']['x_mm']+=1
    elif target=='task':tc['items'][0]['mass_kg']+=1
    elif target=='config':cc['display_order_seed']+=1
    elif target=='enabled':cc['stability_monitor']['enabled']=False
    elif target=='algorithm':cc['stability_monitor']['algorithm']='pct_static_v1'
    elif target=='result':e['monitor']['result']['status']='UNSTABLE'
    elif target=='selection':e['selection']['selected_candidate_id']='fake'
    elif target=='phase':bad['phase']='READY'
    else:bad['reason']='PREDICTED_STATIC_INSTABILITY'
    seal_checkpoint(bad)
    with pytest.raises((ValueError,KeyError)):
        run(tc,cc,resume=bad)


def test_stable_monitor_persisted_before_original_commit(monkeypatch):
    import semantic_pallet_planner.jev_select.execution as execution
    real=execution.commit_physical;saved=[];calls=[]
    t=mechanism_task([item('a')]);cfg=config(t)
    def commit(*a,**kw):
        assert saved[-1]['phase']=='MONITORED'
        assert saved[-1]['pending_event']['monitor']['status']=='STABLE'
        calls.append(a[0]['placed_count'])
        return real(*a,**kw)
    monkeypatch.setattr(execution,'commit_physical',commit)
    ep=run(t,cfg,on_checkpoint=lambda cp:saved.append(copy.deepcopy(cp)))
    assert calls==[0] and ep['final_state']['placed_count']==1


def test_interrupted_predicted_stop_restores_saved_result(monkeypatch):
    fixture_provider(monkeypatch)
    task=unstable_task();cfg=config(task);saved=[]
    class Cut(RuntimeError):pass
    def hook(name,cp):
        if name=='after_monitored_checkpoint' and cp['pending_event']['monitor']['status']=='UNSTABLE':
            saved.append(copy.deepcopy(cp));raise Cut()
    with pytest.raises(Cut):run(task,cfg,hook=hook)
    import semantic_pallet_planner.jev_select.stability.balance_adapter as ba
    def forbidden(*a,**kw):raise AssertionError('reassessed or reselected saved stop')
    monkeypatch.setattr(ba,'assess_candidate',forbidden)
    monkeypatch.setattr(LocalPackagingDouble,'select',forbidden)
    ep=run(task,cfg,resume=saved[0])
    assert ep['checkpoint']['reason']=='PREDICTED_STATIC_INSTABILITY'
    assert ep['final_state']['placed_count']==2
    assert ep['summary']['monitor_statistics']['saved_result_reuses']==1


def test_original_commit_error_independent(monkeypatch):
    import semantic_pallet_planner.jev_select.execution as execution
    def fail(*a,**kw):raise JevSelectError('EXPLICIT_ORIGINAL_COMMIT_FAILURE')
    monkeypatch.setattr(execution,'commit_physical',fail)
    task=mechanism_task([item('a')]);cfg=config(task);ep=run(task,cfg)
    assert ep['events'][-1]['event']=='COMMIT_FAILURE'
    assert ep['events'][-1]['monitor']['status']=='STABLE'
    assert ep['final_state']['placed_count']==0
    assert ep['summary']['monitor_statistics']['termination_category']=='COMMIT_ERROR'
    validate_checkpoint(ep['checkpoint'],task,cfg,'P',cfg['selector'])


def test_cli_help_and_conflicting_switch(tmp_path):
    command=[sys.executable,'-m','semantic_pallet_planner.jev_select']
    cp=subprocess.run(command+['smoke-packaging-monitor','--help'],capture_output=True,text=True)
    assert cp.returncode==0 and '--stability-monitor' in cp.stdout
    opt=tmp_path/'options.json';opt.write_text('{"enabled":false}')
    dataset=Path(__file__).resolve().parents[3]/'semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02'
    output=Path(__file__).resolve().parents[3]/'semantic_pallet_planner/outputs/SHOULD_NOT_CREATE_MONITOR_CONFLICT'
    cp=subprocess.run(command+['smoke-packaging-monitor','--dataset',str(dataset),'--output',str(output),
        '--stability-monitor','on','--monitor-config',str(opt)],capture_output=True,text=True)
    assert cp.returncode!=0 and 'stability_cli_config_conflict' in cp.stdout+cp.stderr
    assert not output.exists()


def test_runtime_exception_is_v2_error(monkeypatch):
    import semantic_pallet_planner.jev_select.stability.balance_adapter as ba
    def fail(*a,**kw):raise RuntimeError('EXPLICIT_RUNTIME_EXCEPTION')
    monkeypatch.setattr(ba,'assess_candidate',fail)
    t=mechanism_task([item('a')]);cfg=config(t);ep=run(t,cfg)
    assert ep['checkpoint']['reason']=='STABILITY_MONITOR_ERROR'
    r=ep['events'][-1]['monitor']['result']
    assert r['version']=='pct_stability_result_v2' and r['reason_code']=='MONITOR_EXCEPTION'
    validate_checkpoint(ep['checkpoint'],t,cfg,'P',cfg['selector'])


def test_source_and_dependency_changes_refused(monkeypatch):
    from semantic_pallet_planner.jev_select import experiment
    task=mechanism_task([item('a')]);cfg=config(task);cp=run(task,cfg)['checkpoint']
    actual=experiment.source_manifest
    monkeypatch.setattr(experiment,'source_manifest',lambda:{**actual(),'EXPLICIT_SOURCE_CHANGE.py':digest('changed')})
    with pytest.raises(JevSelectError,match='source_or_strategy_changed'):
        run(task,cfg,resume=cp)
    monkeypatch.setattr(experiment,'source_manifest',actual)
    import semantic_pallet_planner.jev_select.stability.balance_adapter as ba
    original=ba.algorithm_identity
    def changed():
        v=original();v['dependencies']['highs_core_sha256']=digest('changed');return v
    monkeypatch.setattr(ba,'algorithm_identity',changed)
    with pytest.raises(JevSelectError,match='frozen_identity_changed'):
        run(task,cfg,resume=cp)
