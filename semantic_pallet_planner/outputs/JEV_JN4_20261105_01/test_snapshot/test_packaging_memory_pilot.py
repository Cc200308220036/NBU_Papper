"""JN3-C constructed tasks/Fake transport only; no auth or real sends."""
import copy
import json
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select import packaging_memory_pilot as p
from semantic_pallet_planner.jev_select import packaging_pilot_memory as mem
from semantic_pallet_planner.jev_select.packaging_pilot_protocol import *
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError,DecisionContext
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.episode import decision_inputs,run_episode
from semantic_pallet_planner.jev_select.tests.unit.test_packaging_runtime import mechanism_task,item
from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive
from test_packaging_remote import Fake
REPO=Path(__file__).resolve().parents[3]


def setup(tmp_path,monkeypatch,n=4,tasks=2,watchdog=None,source_same=False,size=(20,20,20)):
    ts=[]
    for i in range(tasks):
        task=mechanism_task([item(str(j),size=size) for j in range(n)])
        task.update(task_id=f'CONSTRUCTED_{i}',source_group_id='SG_452dbbc128a50584' if source_same else f'CONSTRUCTED_S{i}',partition='train');ts.append(task)
    data={'data_identity':digest('CONSTRUCTED_ONLY'),'tasks':ts}
    def fresh(path):
        path=Path(path)
        if path.exists():raise JevSelectError('constructed_exists')
        path.mkdir(parents=True);return path
    monkeypatch.setattr(p,'REPO',tmp_path);monkeypatch.setattr(p.common,'REPO',tmp_path)
    monkeypatch.setattr(p,'PARENTS',{m:str(REPO/path) for m,path in p.PARENTS.items()})
    monkeypatch.setattr(p.common,'new_output',fresh);monkeypatch.setattr(p,'task_order',lambda:[t['task_id'] for t in ts])
    monkeypatch.setattr(p,'load_runtime_dataset',lambda _:copy.deepcopy(data))
    spec={'fixture_only':True}
    if watchdog is not None:spec['watchdog']=watchdog
    plan=p.prepare(tmp_path/'dataset',spec,tmp_path/'plan');fake=Fake()
    return plan,fake,lambda *a:fake


def test_six_full_orders_per_decision_retrieval_and_gate(tmp_path,monkeypatch):
    plan,fake,factory=setup(tmp_path,monkeypatch)
    result=p.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    assert result['status']=='PASS_IN_EXECUTED_SCOPE' and result['categories']['COMPLETE']==3 and result['categories']['NOT_RUN']==3
    assert fake.calls==12 and result['request_statistics']['send_reservations']==12 and result['model_calls']==0
    assert read(tmp_path/'run/pilot_gate.json')['status']=='PASS'
    p.validate_run(tmp_path/'run');before=read(tmp_path/'run/pilot_gate.json')['job_files_sha256']
    assert p.run(tmp_path/'plan',tmp_path/'run',resume=True,transport_factory=factory)==result and fake.calls==12
    result=p.run(tmp_path/'plan',tmp_path/'run',resume=True,continue_pending=True,transport_factory=factory)
    assert result['categories']['COMPLETE']==6 and fake.calls==24
    assert read(tmp_path/'run/pilot_gate.json')['job_files_sha256']==before
    assert all(len(read(tmp_path/'run/jobs'/j['job_id']/'checkpoint.json')['events'])>8 for j in plan['jobs'])
    for j in plan['jobs']:
        cp=read(tmp_path/'run/jobs'/j['job_id']/'checkpoint.json');choices=[e for e in cp['events'] if e.get('decision_id')]
        assert len({e['context']['retrieval_receipt']['query_digest'] for e in choices})>1
        assert all(e['context']['memory_view']['mode']==REGISTRY[j['method_id']]['mode'] for e in choices)
        assert all(not e['context']['model_state']['memories'] for e in choices) if j['method_id']=='jev_no_memory' else True
    assert len(read(tmp_path/'run/paired_differences.json'))==6
    assert read(tmp_path/'run/behavior_analysis.json')['matched_state_comparisons']
    p.validate_run(tmp_path/'run')
    p.run(tmp_path/'plan',tmp_path/'run',resume=True,continue_pending=True,transport_factory=factory);assert fake.calls==24
    from semantic_pallet_planner.jev_select.packaging_pilot_analysis import recommendation
    assert recommendation(tmp_path/'run',plan)['recommendation']=='REVISE'

@pytest.mark.parametrize('method',METHODS)
@pytest.mark.parametrize('phase',['DECISION_READY','SELECTED','MONITORED','COMMITTED'])
def test_restore_never_retrieves_reselects_remonitors_recommits(tmp_path,monkeypatch,method,phase):
    plan,fake,_=setup(tmp_path,monkeypatch,tasks=1);j=next(j for j in plan['jobs'] if j['method_id']==method)
    task=read(tmp_path/'plan/tasks'/f"{j['task_id']}.json");cfg=j['config'];mode=cfg['memory_mode'];snap=None if mode=='none' else read(tmp_path/'plan/memories'/p.FILES[mode])
    driver=mem.MemoryDriver(cfg,snapshot=snap);ledger=PilotLedger(tmp_path/'request_ledger',plan['request_budget'],{x['job_id']:x['config'] for x in plan['jobs']})
    selector=pilot_selector_factory(method,config=cfg,ledger=ledger,transport=fake,job_id=j['job_id']);saved=[]
    class Cut(BaseException):pass
    def cp(x):
        if x['phase']==phase:saved.append(x);raise Cut()
    with pytest.raises(Cut):run_episode(task,selector,cfg,job_id=j['job_id'],method=method,memory_driver=driver,on_checkpoint=cp)
    savedcp=saved[0];assert driver.calls==1
    def forbidden(*a,**k):raise AssertionError('saved stage dispatched')
    monkeypatch.setattr(driver,'resolve',forbidden)
    if phase!='DECISION_READY':monkeypatch.setattr(selector,'select',forbidden)
    import semantic_pallet_planner.jev_select.stability.monitor as mon
    import semantic_pallet_planner.jev_select.execution as ex
    if phase in ('MONITORED','COMMITTED'):monkeypatch.setattr(mon,'monitor_selected_action',forbidden)
    if phase=='COMMITTED':monkeypatch.setattr(ex,'commit_physical',forbidden)
    ep=run_episode(task,selector,cfg,job_id=j['job_id'],method=method,memory_driver=driver,resume=savedcp,event_limit=len(savedcp['events'])+1)
    assert ep['events'][-1]['event']=='PLACE' and fake.calls==1
    assert ep['events'][-1]['context']==savedcp['pending_event']['context']

@pytest.mark.parametrize('kind',['unknown','invalid','failure'])
def test_errors_stop_batch_complete_denominator(tmp_path,monkeypatch,kind):
    plan,fake,_=setup(tmp_path,monkeypatch)
    from semantic_pallet_planner.jev_select.transport import outcome
    fake.change=lambda r:outcome('UNKNOWN_IN_FLIGHT' if kind=='unknown' else 'OK' if kind=='invalid' else 'PROVIDER_FAILURE',b'{bad' if kind=='invalid' else b'',http_status=200 if kind=='invalid' else 401,error='CONSTRUCTED',network_attempted=True)
    result=p.run(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:fake)
    assert result['status']=='ERROR' and result['categories']['NOT_RUN']==5 and fake.calls==1
    p.validate_run(tmp_path/'run');p.run(tmp_path/'plan',tmp_path/'run',resume=True,continue_pending=True,transport_factory=lambda *a:fake);assert fake.calls==1


def test_watchdog_and_scope_old_schema(tmp_path,monkeypatch):
    plan,fake,factory=setup(tmp_path,monkeypatch,watchdog={'max_events':4,'max_active_wall_s':1800})
    with pytest.raises(JevSelectError):p.run(tmp_path/'plan',tmp_path/'run',task_ids=['outside'],transport_factory=factory)
    with pytest.raises(JevSelectError):p.run(tmp_path/'plan',tmp_path/'run',method_ids=['jev_no_memory'],transport_factory=factory)
    from semantic_pallet_planner.jev_select.contracts import validate_schema
    with pytest.raises(JevSelectError):validate_schema('packaging_full_order_plan_v2',plan)
    result=p.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    assert result['categories']['TECHNICAL_LIMIT']==1 and result['categories']['NOT_RUN']==5
    p.validate_run(tmp_path/'run')


def test_saved_response_restore_no_network_or_retrieval(tmp_path,monkeypatch):
    plan,fake,_=setup(tmp_path,monkeypatch,tasks=1);j=plan['jobs'][1];task=read(tmp_path/'plan/tasks'/f"{j['task_id']}.json");cfg=j['config']
    driver=mem.MemoryDriver(cfg,snapshot=read(tmp_path/'plan/memories'/p.FILES['T']));ledger=PilotLedger(tmp_path/'request_ledger',plan['request_budget'],{x['job_id']:x['config'] for x in plan['jobs']})
    selector=pilot_selector_factory(j['method_id'],config=cfg,ledger=ledger,transport=fake,job_id=j['job_id']);saved=[]
    class Cut(BaseException):pass
    def cp(x):
        if x['phase']=='DECISION_READY':saved.append(x);raise Cut()
    with pytest.raises(Cut):run_episode(task,selector,cfg,job_id=j['job_id'],method=j['method_id'],memory_driver=driver,on_checkpoint=cp)
    c=DecisionContext.from_dict(saved[0]['pending_event']['context']);ledger.request(c,j['job_id'],c.data['local_binding']['decision_id'],fake)
    selector.transport=None
    monkeypatch.setattr(driver,'resolve',lambda *a:(_ for _ in ()).throw(AssertionError('re-retrieval')))
    ep=run_episode(task,selector,cfg,job_id=j['job_id'],method=j['method_id'],memory_driver=driver,resume=saved[0],event_limit=4)
    assert fake.calls==1 and ep['events'][-1]['event']=='PLACE'
    assert p.orders.saved_reuses(tmp_path)[0]['has_response']


def test_job_and_shared_budget_persist(tmp_path,monkeypatch):
    plan,fake,_=setup(tmp_path,monkeypatch,tasks=1,n=3);j=plan['jobs'][0];task=read(tmp_path/'plan/tasks'/f"{j['task_id']}.json");cfg=j['config']
    state=initial(task['container'],3)
    for o in task['items']:state=receive(state,o,task['attributes'][o['item_id']])
    ctx=decision_inputs(state,task,cfg,j['job_id'],j['job_id']+'_D0000',memory_driver=mem.MemoryDriver(cfg))[3]
    budget={'per_job':{j['job_id']:1},'global':1};configs={j['job_id']:cfg};l=PilotLedger(tmp_path/'request_ledger',budget,configs)
    l.request(ctx,j['job_id'],j['job_id']+'_D0000',fake)
    l=PilotLedger(tmp_path/'request_ledger',budget,configs);l.request(ctx,j['job_id'],j['job_id']+'_D0000',fake);assert fake.calls==1
    from semantic_pallet_planner.jev_select.selector import bind_decision
    other=bind_decision(ctx,j['job_id'],j['job_id']+'_D0001',config=cfg)
    with pytest.raises(JevSelectError):l.request(other,j['job_id'],j['job_id']+'_D0001',fake)

@pytest.mark.parametrize('method',METHODS)
def test_singleton_view_is_not_actual_injection(tmp_path,monkeypatch,method):
    from semantic_pallet_planner.jev_select.contracts import CandidateBundle
    from semantic_pallet_planner.jev_select.packaging_runtime import build_context
    from semantic_pallet_planner.jev_select.selector import bind_decision
    from semantic_pallet_planner.jev_select.candidates import PublicBusinessGuard
    plan,fake,_=setup(tmp_path,monkeypatch,tasks=1);j=next(j for j in plan['jobs'] if j['method_id']==method);cfg=j['config'];task=read(tmp_path/'plan/tasks'/f"{j['task_id']}.json")
    mode=cfg['memory_mode'];snapshot=None if mode=='none' else read(tmp_path/'plan/memories'/p.FILES[mode]);driver=mem.MemoryDriver(cfg,snapshot=snapshot)
    state=initial(task['container'],3)
    for o in task['items'][:3]:state=receive(state,o,task['attributes'][o['item_id']])
    req,pol,b,_=decision_inputs(state,task,cfg,j['job_id'],j['job_id']+'_D0000',memory_driver=driver)
    value=b.data;value['physical_candidates']=value['physical_candidates'][:1];value['selectable_candidates']=value['physical_candidates'];value['physical_digest']=value['selectable_digest']=digest(value['physical_candidates'])
    b=PublicBusinessGuard().filter(req,pol,CandidateBundle.from_dict(value),cfg)
    from semantic_pallet_planner.jev_select.packaging_runtime import public_facts
    _,public_state,public_criteria,_,_=public_facts(cfg,req,b,pol)
    explicit_view,receipt=driver.resolve(public_state,public_criteria)
    ctx=bind_decision(build_context(cfg,req,b,pol,memory_view=explicit_view,retrieval_receipt=receipt),j['job_id'],j['job_id']+'_D0000',config=cfg)
    ledger=PilotLedger(tmp_path/'request_ledger',plan['request_budget'],{x['job_id']:x['config'] for x in plan['jobs']})
    selector=pilot_selector_factory(method,config=cfg,ledger=ledger,transport=fake,job_id=j['job_id']);selected=selector.select(ctx,decision_id=j['job_id']+'_D0000')
    assert selected.data['source']=='singleton' and fake.calls==0 and not ledger.data['requests']
    event={'decision_id':j['job_id']+'_D0000','context':ctx.data,'bundle':b.data,'selection':selected.data,'monitor':None}
    x=p.exposure([event],[],mode,library_nonempty=bool(cfg['memory_index']))
    assert x['actually_sent_nonempty_count']==0 and x['body_nonempty_count']==0
    assert x['singleton_nonempty_view_count']==(mode!='none')


def test_empty_hit_keeps_assigned_mode_and_public_only_query(tmp_path,monkeypatch):
    plan,fake,_=setup(tmp_path,monkeypatch,tasks=1);j=plan['jobs'][1];task=read(tmp_path/'plan/tasks'/f"{j['task_id']}.json");old=j['config']
    cfg=load_pilot_config(data_identity=old['runtime_identity']['data_identity'],task_digest=digest(task),method=j['method_id'],snapshot_digest=old['memory_snapshot_digest'],memory_index=old['memory_index'],excluded_source_groups=['SG_452dbbc128a50584','SG_6dced793dc60def1'],enabled=True)
    driver=mem.MemoryDriver(cfg,snapshot=read(tmp_path/'plan/memories'/p.FILES['T']))
    state=initial(task['container'],3)
    for o in task['items'][:3]:state=receive(state,o,task['attributes'][o['item_id']])
    ctx=decision_inputs(state,task,cfg,j['job_id'],j['job_id']+'_D0000',memory_driver=driver)[3]
    assert ctx.data['memory_view']['mode']=='T' and ctx.data['request_body']['state']['memories']==[]
    mutated=copy.deepcopy(task);mutated['items'].append(item('PRIVATE_FUTURE',mass=999));mutated['witness']='PRIVATE'
    other=decision_inputs(state,mutated,cfg,j['job_id'],j['job_id']+'_D0000',memory_driver=driver)[3]
    assert ctx.data['request_body']==other.data['request_body']
    public=copy.deepcopy(ctx.data['model_state']);public['task_id']='PRIVATE'
    with pytest.raises(JevSelectError):driver.resolve(public,ctx.data['criteria'])
    ledger=PilotLedger(tmp_path/'request_ledger',{'per_job':{j['job_id']:4},'global':4},{j['job_id']:cfg})
    selector=pilot_selector_factory(j['method_id'],config=cfg,ledger=ledger,transport=fake,job_id=j['job_id'])
    assert selector.select(ctx,decision_id=j['job_id']+'_D0000').data['status']=='selected' and fake.calls==1

@pytest.mark.parametrize('target',['query','view','body','snapshot','metrics','phase'])
def test_resealed_saved_tamper_rejected(tmp_path,monkeypatch,target):
    plan,fake,factory=setup(tmp_path,monkeypatch,n=3,tasks=1);p.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    job=tmp_path/'run/jobs/J0001';cp=read(job/'checkpoint.json')
    if target=='metrics':
        x=read(job/'metrics.json');x['loading']['placed_items']=999;write(job/'metrics.json',x)
    elif target=='phase':
        f=next((job/'stages').glob('*/SELECTED.json'));x=read(f);x['state']['placed_count']+=1;x['record_digest']=digest({k:v for k,v in x.items() if k!='record_digest'});write(f,x)
    else:
        ev=next(e for e in cp['events'] if e.get('decision_id'));ctx=ev['context']
        if target=='query':ctx['retrieval_receipt']['query']['features']['placed_fill']=7
        if target=='view':ctx['memory_view']['entries']=[]
        if target=='body':ctx['request_body']=None
        if target=='snapshot':ctx['memory_view']['snapshot_digest']=digest('other')
        cp['record_digest']=digest({k:v for k,v in cp.items() if k!='record_digest'});write(job/'checkpoint.json',cp)
    write(tmp_path/'run/delivery_manifest.json',p.file_manifest(tmp_path/'run'))
    with pytest.raises(JevSelectError):p.validate_run(tmp_path/'run')

@pytest.mark.parametrize('phase',['metrics','summary'])
def test_derivation_fault_stops_without_extra_requests(tmp_path,monkeypatch,phase):
    plan,fake,factory=setup(tmp_path,monkeypatch,n=3)
    def broken(*a,**k):raise RuntimeError('CONSTRUCTED_DERIVATION_FAULT')
    original=p.metrics if phase=='metrics' else p.summarize
    monkeypatch.setattr(p,'metrics' if phase=='metrics' else 'summarize',broken)
    result=p.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    assert result['status']=='ERROR' and result['categories']['NOT_RUN']==(5 if phase=='metrics' else 3)
    assert fake.calls==(3 if phase=='metrics' else 9)
    monkeypatch.setattr(p,'metrics' if phase=='metrics' else 'summarize',original) # independently use the original pure derivation
    p.validate_run(tmp_path/'run')


def test_empty_pool_and_no_exposure_gate(tmp_path,monkeypatch):
    plan,fake,factory=setup(tmp_path,monkeypatch,n=3,size=(2000,2000,2000))
    result=p.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    assert result['categories']['EMPTY_POOL']==3 and fake.calls==0
    assert read(tmp_path/'run/pilot_gate.json')['status']=='DEFER_NO_EXPOSURE'
    with pytest.raises(JevSelectError):p.run(tmp_path/'plan',tmp_path/'run',resume=True,continue_pending=True,transport_factory=factory)
    p.validate_run(tmp_path/'run')


def test_three_methods_same_public_base_and_old_versions_protected(tmp_path,monkeypatch):
    plan,fake,_=setup(tmp_path,monkeypatch,tasks=1);task=read(tmp_path/'plan/tasks'/f"{plan['jobs'][0]['task_id']}.json")
    state=initial(task['container'],3)
    for o in task['items'][:3]:state=receive(state,o,task['attributes'][o['item_id']])
    values=[]
    for j in plan['jobs']:
        cfg=j['config'];mode=cfg['memory_mode'];driver=mem.MemoryDriver(cfg,snapshot=None if mode=='none' else read(tmp_path/'plan/memories'/p.FILES[mode]))
        values.append(decision_inputs(state,task,cfg,j['job_id'],j['job_id']+'_D0000',memory_driver=driver)[3].data)
    for value in values[1:]:
        state0=copy.deepcopy(values[0]['model_state']);state1=copy.deepcopy(value['model_state']);state0['memories']=state1['memories']=[]
        assert state0==state1 and value['criteria']==values[0]['criteria'] and value['display_mapping']==values[0]['display_mapping']
        assert value['request_body']['questions']==values[0]['request_body']['questions']
        assert value['retrieval_receipt']['query']==values[0]['retrieval_receipt']['query']
    from semantic_pallet_planner.jev_select.contracts import validate_schema
    for version in ['v6','v7','v8']:
        with pytest.raises(JevSelectError):validate_schema('decision_context_'+version,values[0])
    bad=copy.deepcopy(plan['jobs'][0]['config']);bad['memory_mode']='T'
    with pytest.raises(JevSelectError):validate_schema('config',bad)


def test_v9_real_kernel_instability_no_second_choice(tmp_path,monkeypatch):
    from test_stability_monitor import fixture_provider,unstable_task
    from semantic_pallet_planner.jev_select.transport import outcome
    fixture_provider(monkeypatch,choices=True);task=unstable_task()
    cfg=load_pilot_config(data_identity=digest('CONSTRUCTED'),task_digest=digest(task),method='jev_no_memory',snapshot_digest=mem.NONE_DIGEST,memory_index=[],excluded_source_groups=[],enabled=True)
    class GeometricFake:
        origin='test_double';calls=0
        def complete(self,body):
            self.calls+=1;criteria=body['questions']['next_action']['criteria'];label=next(l for l,c in criteria.items() if c['pose']['x_mm']>-300)
            response={'model':body['model'],'answers':{'next_action':{'type':'choice','choice':label,'probabilities':{l:float(l==label) for l in criteria},'confidence':1.}},'usage':{'input_tokens':1,'output_tokens':1}}
            return outcome('OK',json.dumps(response).encode(),http_status=200,network_attempted=True)
    fake=GeometricFake();ledger=PilotLedger(tmp_path/'request_ledger',{'per_job':{'P':4},'global':4},{'P':cfg})
    selector=pilot_selector_factory('jev_no_memory',config=cfg,ledger=ledger,transport=fake,job_id='P');driver=mem.MemoryDriver(cfg)
    ep=run_episode(task,selector,cfg,job_id='P',method='jev_no_memory',memory_driver=driver)
    assert ep['checkpoint']['reason']=='PREDICTED_STATIC_INSTABILITY' and ep['final_state']['placed_count']==2 and fake.calls==3
    assert ep['events'][-1]['before']==ep['events'][-1]['after'] and ep['events'][-1]['action'] is None
    assert ep['events'][-1]['monitor']['result']['diagnostics']['infeasibility_certificate']['verified']
    p.common.validate_saved_checkpoint(ep['checkpoint'],task,cfg,'P')

@pytest.mark.parametrize('status,code,remaining',[('UNASSESSABLE','POSE_HEIGHT_MISMATCH',3),('ERROR','BALANCE_KERNEL_ERROR',5)])
def test_range_vs_technical_stop_and_invalid_pairs(tmp_path,monkeypatch,status,code,remaining):
    from dataclasses import replace
    from semantic_pallet_planner.jev_select.stability import balance_adapter as ba
    plan,fake,factory=setup(tmp_path,monkeypatch,n=3);real=ba.assess_candidate
    monkeypatch.setattr(ba,'assess_candidate',lambda *a,**k:replace(real(*a,**k),status=status,reason_code=code))
    result=p.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory)
    assert result['categories']['NOT_RUN']==remaining
    assert all(not x['evaluation']['comparison_valid'] for x in read(tmp_path/'run/paired_differences.json'))
    if status=='UNASSESSABLE':assert read(tmp_path/'run/pilot_gate.json')['status']=='PASS'
    p.validate_run(tmp_path/'run')


def test_changed_budget_or_missing_ledger_cannot_reset(tmp_path,monkeypatch):
    plan,fake,factory=setup(tmp_path,monkeypatch,n=3,tasks=1)
    p.run(tmp_path/'plan',tmp_path/'run',transport_factory=factory);calls=fake.calls
    configs={j['job_id']:j['config'] for j in plan['jobs']};changed=copy.deepcopy(plan['request_budget']);changed['per_job']['J0000']+=1
    with pytest.raises(JevSelectError):PilotLedger(tmp_path/'run/request_ledger',changed,configs)
    (tmp_path/'run/request_ledger/requests.json').unlink()
    with pytest.raises(JevSelectError):p.run(tmp_path/'plan',tmp_path/'run',resume=True,continue_pending=True,transport_factory=factory)
    assert fake.calls==calls


def test_shared_limit_across_distinct_jobs(tmp_path,monkeypatch):
    plan,fake,_=setup(tmp_path,monkeypatch,n=3,tasks=1);configs={j['job_id']:j['config'] for j in plan['jobs'][:2]}
    ledger=PilotLedger(tmp_path/'request_ledger',{'per_job':{j:1 for j in configs},'global':1},configs)
    for i,j in enumerate(plan['jobs'][:2]):
        task=read(tmp_path/'plan/tasks'/f"{j['task_id']}.json");cfg=j['config'];mode=cfg['memory_mode'];state=initial(task['container'],3)
        for o in task['items']:state=receive(state,o,task['attributes'][o['item_id']])
        driver=mem.MemoryDriver(cfg,snapshot=None if mode=='none' else read(tmp_path/'plan/memories'/p.FILES[mode]))
        ctx=decision_inputs(state,task,cfg,j['job_id'],j['job_id']+'_D0000',memory_driver=driver)[3]
        if i==0:ledger.request(ctx,j['job_id'],j['job_id']+'_D0000',fake)
        else:
            with pytest.raises(JevSelectError,match='budget'):ledger.request(ctx,j['job_id'],j['job_id']+'_D0000',fake)
    assert fake.calls==1


def test_archived_config_preflight_includes_algorithm_auxiliaries(tmp_path,monkeypatch):
    import subprocess,sys,os
    plan,_,_=setup(tmp_path,monkeypatch,tasks=1,n=3);root=tmp_path/'plan'
    cfg=root/'archived_fixture_config.json';write(cfg,plan['jobs'][0]['config'])
    script='''
import importlib.util,sys,json
from pathlib import Path
root=Path(sys.argv[1]);spec=importlib.util.spec_from_file_location('semantic_pallet_planner',root/'code_snapshot/__init__.py',submodule_search_locations=[str(root/'code_snapshot')])
pkg=importlib.util.module_from_spec(spec);sys.modules['semantic_pallet_planner']=pkg;spec.loader.exec_module(pkg)
from semantic_pallet_planner.jev_select.packaging_pilot_protocol import preflight_pilot
preflight_pilot(json.loads((root/'archived_fixture_config.json').read_text()))
'''
    result=subprocess.run([sys.executable,'-c',script,str(root)],capture_output=True,text=True,env={k:v for k,v in os.environ.items() if k not in ('TYPESAFE_API_KEY','DEEPSEEK_API_KEY')})
    assert result.returncode==0,result.stderr
    assert (root/'code_snapshot/jev_select/stability/vendor/pct/LICENSE').is_file()
    assert (root/'code_snapshot/jev_select/stability/BALANCE_DESIGN.md').is_file()
