import copy
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select import packaging_evaluation_orders as p
from semantic_pallet_planner.jev_select.packaging_evaluation_protocol import *
from semantic_pallet_planner.jev_select import packaging_evaluation_memory as memory
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError,validate_schema
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.episode import run_episode,decision_inputs
from semantic_pallet_planner.jev_select.tests.unit.test_packaging_runtime import mechanism_task,item
from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive
from test_packaging_remote import Fake


def setup(tmp_path,n=3,tasks=1,watchdog=None):
    ts=[]
    for i in range(tasks):
        t=mechanism_task([item(str(j),size=(20,20,20)) for j in range(n)])
        t.update(task_id=f'CONSTRUCTED_{i}',source_group_id=f'CONSTRUCTED_S{i}',partition='train');ts.append(t)
    plan=p.prepare({'data_identity':digest('CONSTRUCTED_V10'),'fixture_only':True,'tasks':ts},tmp_path/'plan',watchdog=watchdog)
    f=Fake();return plan,f


def driver(cfg,plan):
    mode=cfg['memory_mode'];return memory.MemoryDriver(cfg,snapshot=None if mode=='none' else plan['snapshots']['E' if mode=='E_unrelated_control' else mode],control=plan['snapshots']['control'] if mode=='E_unrelated_control' else None)


def test_six_methods_same_protocol_control_length_and_paused_continuation(tmp_path,monkeypatch):
    plan,f=setup(tmp_path,tasks=2)
    s=p.run_validation(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:f)
    assert s['categories']['COMPLETE']==6 and s['categories']['NOT_RUN']==6 and f.calls==12
    assert read(tmp_path/'run/first_gate.json')['status']=='PASS'
    gate=read(tmp_path/'run/first_gate.json')
    assert p.run_validation(tmp_path/'plan',tmp_path/'run',resume=True,transport_factory=lambda *a:f)==s and f.calls==12
    s=p.run_validation(tmp_path/'plan',tmp_path/'run',resume=True,continue_pending=True,transport_factory=lambda *a:f)
    assert s['categories']['COMPLETE']==12 and f.calls==24
    assert read(tmp_path/'run/first_gate.json')==gate
    configs={j['config']['version'] for j in plan['jobs']};assert configs=={VERSION}
    for j in plan['jobs']:
        cfg=j['config'];job=tmp_path/'run/jobs'/j['job_id'];cp=read(job/'checkpoint.json');m=read(job/'metrics.json')
        assert m['memory_mode']==REGISTRY[j['method_id']]['mode']
        assert m['monitor_statuses']['STABLE']==3
        if not REGISTRY[j['method_id']]['remote']:assert m['cost']['send_reservations']==0
        for e in cp['events']:
            if e.get('context'):
                assert e['context']['version']=='jev_decision_context_v10'
                if cfg['memory_mode']=='none':assert e['context']['model_state']['memories']==[]
    e=read(tmp_path/'run/jobs/J0004/checkpoint.json')['events'][3]['context']['memory_view']
    u=read(tmp_path/'run/jobs/J0005/checkpoint.json')['events'][3]['context']['memory_view']
    assert u['injected_chars']==e['injected_chars'] and u['injected_utf8_bytes']==e['injected_utf8_bytes']
    assert u['entries'][0]['kind']=='UNRELATED_NON_EVIDENCE'
    def forbidden(*a,**k):raise AssertionError('saved validation dispatched')
    monkeypatch.setattr(memory.MemoryDriver,'resolve',forbidden)
    monkeypatch.setattr(p.common,'_run_job',forbidden)
    p.validate_run(tmp_path/'run')


@pytest.mark.parametrize('method',METHODS)
@pytest.mark.parametrize('phase',['DECISION_READY','SELECTED','MONITORED','COMMITTED'])
def test_all_six_methods_restore_exact_stage(tmp_path,monkeypatch,method,phase):
    plan,f=setup(tmp_path);j=next(j for j in plan['jobs'] if j['method_id']==method);cfg=j['config'];task=plan['data']['tasks'][0]
    ledger=EvaluationLedger(tmp_path/'ledger',plan['request_budget'],{j['job_id']:j['config'] for j in plan['jobs']})
    sel=selector_factory(method,config=cfg,transport=f if REGISTRY[method]['remote'] else None,ledger=ledger,job_id=j['job_id'])
    d=driver(cfg,plan);saved=[]
    class Cut(BaseException):pass
    def checkpoint(c):
        if c['phase']==phase:saved.append(c);raise Cut()
    with pytest.raises(Cut):run_episode(task,sel,cfg,job_id=j['job_id'],method=method,memory_driver=d,on_checkpoint=checkpoint)
    def forbidden(*a,**k):raise AssertionError('restored stage dispatched')
    monkeypatch.setattr(d,'resolve',forbidden)
    if phase!='DECISION_READY':monkeypatch.setattr(sel,'select',forbidden)
    from semantic_pallet_planner.jev_select import execution
    from semantic_pallet_planner.jev_select.stability import monitor
    if phase in ('MONITORED','COMMITTED'):monkeypatch.setattr(monitor,'monitor_selected_action',forbidden)
    if phase=='COMMITTED':monkeypatch.setattr(execution,'commit_physical',forbidden)
    cp=saved[0]
    result=run_episode(task,sel,cfg,job_id=j['job_id'],method=method,memory_driver=d,resume=cp,event_limit=len(cp['events'])+1)
    assert result['events'][-1]['event']=='PLACE' and f.calls==int(REGISTRY[method]['remote'])


@pytest.mark.parametrize('kind',['UNKNOWN_IN_FLIGHT','PROVIDER_FAILURE','invalid'])
def test_technical_stop_denominator_and_no_retry(tmp_path,kind):
    plan,f=setup(tmp_path,tasks=2)
    from semantic_pallet_planner.jev_select.transport import outcome
    f.change=lambda r:outcome('OK' if kind=='invalid' else kind,b'{bad' if kind=='invalid' else b'',http_status=200 if kind=='invalid' else 500,error='CONSTRUCTED',network_attempted=True)
    s=p.run_validation(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:f)
    assert s['status']=='ERROR' and s['categories']['NOT_RUN']==9 and f.calls==1
    p.run_validation(tmp_path/'plan',tmp_path/'run',resume=True,continue_pending=True,transport_factory=lambda *a:f);assert f.calls==1


def test_empty_hit_singleton_source_exclusion_and_old_schema(tmp_path):
    plan,f=setup(tmp_path,n=1)
    s=p.run_validation(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:f)
    # Singleton is determined by actual candidate count, not item count. Construct
    # empty criteria explicitly for the driver and keep the original method ID.
    j=plan['jobs'][5];cfg=j['config'];d=driver(cfg,plan)
    cp=read(tmp_path/'run/jobs/J0005/checkpoint.json');ctx=next(e['context'] for e in cp['events'] if e.get('context'))
    public=copy.deepcopy(ctx['model_state']);public['memories']=[]
    view,receipt=d.resolve(public,{})
    assert view.data['mode']=='E_unrelated_control' and not view.data['entries']
    with pytest.raises(JevSelectError):validate_schema('config_v9',cfg)
    with pytest.raises(JevSelectError):validate_schema('checkpoint_v9',cp)
    with pytest.raises(JevSelectError):p.run_validation(tmp_path/'plan',tmp_path/'other',transport_factory=lambda *a:f,task_ids=['outside'])


def test_watchdog_and_resealed_control_rejected(tmp_path):
    plan,f=setup(tmp_path,watchdog={'max_events':4,'max_active_wall_s':1800})
    s=p.run_validation(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:f)
    assert s['categories']['TECHNICAL_LIMIT']==1 and s['categories']['NOT_RUN']==5
    bad=copy.deepcopy(plan);bad['snapshots']['control']['entries'][0]['public_fragment']['text']='changed'
    write(tmp_path/'plan/plan.json',bad);write(tmp_path/'plan/plan_receipt.json',{'plan_digest':digest(bad)})
    from semantic_pallet_planner.jev_select.experiment import file_manifest
    write(tmp_path/'plan/delivery_manifest.json',file_manifest(tmp_path/'plan'))
    with pytest.raises(JevSelectError):p.validate_plan(tmp_path/'plan')


@pytest.mark.parametrize('method',[m for m in METHODS if REGISTRY[m]['remote']])
def test_saved_response_and_budget_resume_no_resend(tmp_path,monkeypatch,method):
    plan,f=setup(tmp_path);j=next(j for j in plan['jobs'] if j['method_id']==method);cfg=j['config'];task=plan['data']['tasks'][0]
    ledger=EvaluationLedger(tmp_path/'ledger',plan['request_budget'],{x['job_id']:x['config'] for x in plan['jobs']})
    sel=selector_factory(method,config=cfg,transport=f,ledger=ledger,job_id=j['job_id']);d=driver(cfg,plan);saved=[]
    class Cut(BaseException):pass
    def cp(x):
        if x['phase']=='DECISION_READY':saved.append(x);raise Cut()
    with pytest.raises(Cut):run_episode(task,sel,cfg,job_id=j['job_id'],method=method,memory_driver=d,on_checkpoint=cp)
    from semantic_pallet_planner.jev_select.contracts import DecisionContext
    context=DecisionContext.from_dict(saved[0]['pending_event']['context']);did=saved[0]['pending_event']['decision_id']
    ledger.request(context,j['job_id'],did,f);assert f.calls==1
    sel.transport=None
    monkeypatch.setattr(d,'resolve',lambda *a:(_ for _ in ()).throw(AssertionError('re-retrieval')))
    run_episode(task,sel,cfg,job_id=j['job_id'],method=method,memory_driver=d,resume=saved[0],event_limit=4)
    assert f.calls==1
    b=copy.deepcopy(plan['request_budget']);b['global']+=1
    with pytest.raises(JevSelectError):EvaluationLedger(tmp_path/'ledger',b,{x['job_id']:x['config'] for x in plan['jobs']})


def test_all_memory_modes_public_query_exclusion_and_empty_hit(tmp_path):
    plan,f=setup(tmp_path)
    task=plan['data']['tasks'][0];state=initial(task['container'],3)
    for o in task['items']:state=receive(state,o,task['attributes'][o['item_id']])
    for j in plan['jobs'][3:]:
        mode=j['config']['memory_mode'];refmode='E' if mode=='E_unrelated_control' else mode
        cfg=load_evaluation_config(data_identity=plan['data']['data_identity'],task_digest=digest(task),method=j['method_id'],snapshot=plan['snapshots'][refmode],control=plan['snapshots']['control'] if mode=='E_unrelated_control' else None,excluded_source_groups=plan['snapshots'][refmode]['source_groups'],enabled=True)
        d=driver(cfg,plan);context=decision_inputs(state,task,cfg,j['job_id'],j['job_id']+'_D0000',memory_driver=d)[3]
        assert context.data['route']=='CHOICE_REQUIRED' and not context.data['model_state']['memories'] and context.data['memory_view']['mode']==mode
        public=copy.deepcopy(context.data['model_state']);public['future_arrivals']=[]
        with pytest.raises(JevSelectError):d.resolve(public,context.data['criteria'])


def test_singleton_all_six_has_no_transport_send(tmp_path,monkeypatch):
    plan,f=setup(tmp_path,n=1)
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
    from semantic_pallet_planner.jev_select.contracts import CandidateBundle
    original=CandidateProvider.build
    def one(self,*args,**kwargs):
        b=original(self,*args,**kwargs).data
        b['physical_candidates']=b['physical_candidates'][:1];b['selectable_candidates']=b['selectable_candidates'][:1]
        b['physical_digest']=digest(b['physical_candidates']);b['selectable_digest']=digest(b['selectable_candidates'])
        return CandidateBundle.from_dict(b)
    monkeypatch.setattr(CandidateProvider,'build',one)
    s=p.run_validation(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:f)
    assert s['categories']['COMPLETE']==6 and f.calls==0
    assert read(tmp_path/'run/first_gate.json')['status']=='DEFER_NO_EXPOSURE'
