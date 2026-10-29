"""S2-A negative/invariant tests; every HTTP exchange is injected, never networked."""
import copy
import json
from pathlib import Path
import pytest
from semantic_pallet_planner.o5.common import O5Error, atomic, read, digest, offline_guard
from semantic_pallet_planner.o5.config import load
from semantic_pallet_planner.o5.testing import fixture_task
from semantic_pallet_planner.o5.candidates import generate
from semantic_pallet_planner.o5.public_request import build
from semantic_pallet_planner.o5.remote_config import TEMPLATE,validate,gaps,charge
from semantic_pallet_planner.o5.remote_transport import prepare_body,ChatHTTPTransport,HTTPWire,NoRedirect
from semantic_pallet_planner.o5.remote_budget import Budget
from semantic_pallet_planner.o5.remote_runtime import Runtime
from semantic_pallet_planner.o5.remote_experiment import fixture_profile,FixtureWire,prepare,execute_fixture,verify,report


@pytest.fixture
def decision(tmp_path):
    task=fixture_task();cfg=load();pool,_=generate(task['container'],[],task['items'][0],0,cfg)
    req,mapping=build(task['container'],[],task['items'][0],pool,cfg,'S2TEST',tmp_path/'step')
    return req,tmp_path/'step',cfg


def setup_budget(tmp_path,p=None,jobs=None):
    p=p or fixture_profile()
    return Budget(tmp_path/'campaign',p,'IDENTITY',jobs or {'j':{'phase':'pilot','attempt_limit':4}},True,create=True)


def test_draft_closed_and_no_guessed_price():
    assert gaps(TEMPLATE)
    p=copy.deepcopy(TEMPLATE);p['api_key']='SECRET'
    with pytest.raises(O5Error,match='REMOTE_SCHEMA_ERROR'):validate(p)
    p=fixture_profile();p['endpoint']='https://secret@host/test'
    with pytest.raises(O5Error,match='INVALID_ENDPOINT'):validate(p)
    p=fixture_profile();p['pricing']['input_per_million']='NaN'
    with pytest.raises(O5Error,match='INVALID_DECIMAL'):validate(p)


def test_complete_input_includes_system_images_and_repair(decision):
    req,step,cfg=decision;p=fixture_profile()
    body,bound=prepare_body(req,step,cfg,p)
    text=sum(len(part['text'].encode()) for part in body['messages'][1]['content'] if part['type']=='text')
    assert bound['input_upper']==text+len(body['messages'][0]['content'].encode())+128+512
    assert bound['image_sha256']==[x['sha256'] for x in req['images']]
    body2,b2=prepare_body(req,step,cfg,p,'STALE_BINDING')
    assert b2['input_upper']>bound['input_upper'] and body2['messages'][1]['content'][1:]==body['messages'][1]['content'][1:]
    p['token_bound']['per_image_tokens']=12000
    with pytest.raises(O5Error,match='INPUT_BOUND_EXCEEDED'):prepare_body(req,step,cfg,p)
    (step/'workspace.png').write_bytes(b'changed')
    with pytest.raises(O5Error,match='IMAGE_CHANGED'):prepare_body(req,step,cfg,fixture_profile())


def test_wire_one_call_no_auth_header_saved(decision):
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    wire=FixtureWire();t=ChatHTTPTransport(p,wire)
    r=t.complete(body)
    assert len(wire.calls)==1 and t.calls==1 and r['provider_request_id']
    assert 'OFFLINE_HTTP_FIXTURE' not in json.dumps(r)
    assert NoRedirect().redirect_request(None,None,None,None,None,None) is None


@pytest.mark.parametrize('status,error',[(401,'SYSTEM_HTTP_401'),(429,'SYSTEM_HTTP_429'),(500,'HTTP_500'),(302,'SYSTEM_HTTP_302')])
def test_service_status_single_attempt_no_retry(decision,tmp_path,status,error):
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    wire=FixtureWire([(status,{},b'error')]);t=ChatHTTPTransport(p,wire);budget=setup_budget(tmp_path)
    receipt,i,e=budget.attempt('j',req,body,b,False,t)
    assert e==error and len(wire.calls)==1 and len(budget.rows('j'))==1
    budget.attempt('j',req,body,b,False,t)
    assert len(wire.calls)==1
    assert budget.rows('j')[0]['cost_basis']=='RESERVED_ESTIMATE'


def test_timeout_unknown_stops_other_job_and_never_resends(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    jobs={j:{'phase':'pilot','attempt_limit':2} for j in ('j','other')}
    budget=setup_budget(tmp_path,jobs=jobs);wire=FixtureWire([TimeoutError('SECRET')]);t=ChatHTTPTransport(p,wire)
    for job in ('j','j','other'):
        with pytest.raises(O5Error,match='UNKNOWN_IN_FLIGHT'):budget.attempt(job,req,body,b,False,t)
    assert len(wire.calls)==1 and budget.state['halt']=='UNKNOWN_IN_FLIGHT'
    assert 'SECRET' not in budget.path.read_text()


def test_crash_after_sent_leaves_unknown(decision,tmp_path):
    class Crash(BaseException):pass
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    budget=setup_budget(tmp_path);wire=FixtureWire([Crash()]);t=ChatHTTPTransport(p,wire)
    with pytest.raises(Crash):budget.attempt('j',req,body,b,False,t)
    assert budget.rows('j')[0]['status']=='sent'
    with pytest.raises(O5Error,match='UNKNOWN_IN_FLIGHT'):budget.attempt('j',req,body,b,False,t)
    assert len(wire.calls)==1


def test_durable_receipt_reconciles_without_wire(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    budget=setup_budget(tmp_path);wire=FixtureWire();t=ChatHTTPTransport(p,wire)
    original=budget._settle
    def crash(*args):raise KeyboardInterrupt()
    budget._settle=crash
    with pytest.raises(KeyboardInterrupt):budget.attempt('j',req,body,b,False,t)
    budget._settle=original
    receipt,i,e=budget.attempt('j',req,body,b,False,t)
    assert e is None and len(wire.calls)==1


def test_two_attempt_repair_and_accounting(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();budget=setup_budget(tmp_path)
    wire=FixtureWire(['invalid','valid']);t=ChatHTTPTransport(p,wire)
    runtime=Runtime(budget,'j',p,cfg,tmp_path/'job',t)
    response,ids,error=runtime.choose(req,step)
    assert error is None and len(ids)==2 and response['action']=='PLACE'
    assert len(wire.calls)==2
    content=json.loads(wire.calls[1]['messages'][1]['content'][0]['text'])
    assert content['repair_error']=='INVALID_JSON' and content['public_input']==req
    a=runtime.choose(req,step)
    assert a==(response,ids,error) and len(wire.calls)==2


def test_two_invalid_no_third_and_stop_is_legal(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();budget=setup_budget(tmp_path)
    wire=FixtureWire(['bad','bad','valid']);rt=Runtime(budget,'j',p,cfg,tmp_path/'job',ChatHTTPTransport(p,wire))
    r,ids,e=rt.choose(req,step)
    assert r is None and len(ids)==2 and e=='INVALID_JSON' and len(wire.calls)==2


def test_global_phase_and_total_caps_before_send(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    p['limits']['total_amount']='0'
    budget=setup_budget(tmp_path,p);wire=FixtureWire();t=ChatHTTPTransport(p,wire)
    with pytest.raises(O5Error,match='AMOUNT_BUDGET_EXHAUSTED'):budget.attempt('j',req,body,b,False,t)
    assert not wire.calls and not budget.rows('j')
    assert charge(p,1,1)=='0.000003'


def test_exact_budget_boundary_and_missing_usage_retains_reservation(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    p['limits']['pilot_amount']=b['maximum_amount'];p['limits']['total_amount']=b['maximum_amount']
    budget=setup_budget(tmp_path,p);wire=FixtureWire([(500,{},b'failure')]);t=ChatHTTPTransport(p,wire)
    budget.attempt('j',req,body,b,False,t)
    assert budget.totals()['total']==b['maximum_amount']
    with pytest.raises(O5Error,match='AMOUNT_BUDGET_EXHAUSTED'):budget.attempt('j',req,body,b,True,t)
    assert len(wire.calls)==1


def test_job_and_stage_attempt_caps(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    budget=setup_budget(tmp_path,jobs={'j':{'phase':'pilot','attempt_limit':1}});wire=FixtureWire(['bad']);t=ChatHTTPTransport(p,wire)
    budget.attempt('j',req,body,b,False,t)
    with pytest.raises(O5Error,match='ATTEMPT_BUDGET_EXHAUSTED'):budget.attempt('j',req,body,b,True,t)
    assert len(wire.calls)==1


def test_usage_over_bound_halts_and_cost_not_zero(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    data={'model':p['returned_model'],'choices':[{'finish_reason':'stop','message':{'content':'bad'}}],
          'usage':{'prompt_tokens':50000,'completion_tokens':1}}
    budget=setup_budget(tmp_path);t=ChatHTTPTransport(p,FixtureWire([(200,{},json.dumps(data))]))
    receipt,i,e=budget.attempt('j',req,body,b,False,t)
    assert e=='SYSTEM_USAGE_BOUND_EXCEEDED' and budget.state['halt']==e
    assert float(budget.totals()['total'])>0


def test_missing_changed_ledger_receipt_body_rejected(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    budget=setup_budget(tmp_path);t=ChatHTTPTransport(p,FixtureWire());_,i,_=budget.attempt('j',req,body,b,False,t)
    receipt=budget.root/'attempts'/i/'receipt.json';d=read(receipt);d['text']='bad';atomic(receipt,d)
    with pytest.raises(O5Error,match='REMOTE_RECEIPT_CHANGED'):budget.load()
    budget.path.unlink()
    with pytest.raises(O5Error,match='MISSING_REMOTE_LEDGER'):Budget(budget.root,p,'IDENTITY',budget.jobs,True)


def test_budget_lock_refuses_concurrent_writer(decision,tmp_path):
    from semantic_pallet_planner.o5.common import exclusive
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    budget=setup_budget(tmp_path);t=ChatHTTPTransport(p,FixtureWire())
    with exclusive(budget.root/'budget.lock'):
        with pytest.raises(O5Error,match='RUN_BUSY'):budget.attempt('j',req,body,b,False,t)
    assert t.calls==0


def test_full_fixture_checkpoint_resume_verify_and_report_offline(tmp_path):
    plan=tmp_path/'plan';run=tmp_path/'run'
    with offline_guard():
        prepared=prepare(None,plan,fixture_profile(),fixture=True)
        assert prepared['planned_jobs']==4
        partial=execute_fixture(plan,run,stop_after=2,max_jobs=1)
        assert partial['status']=='PARTIAL'
        completed=execute_fixture(plan,run,resume=True)
        assert completed['status']=='PASS'
        before={str(p):p.read_bytes() for p in run.rglob('*') if p.is_file()}
        checked=verify(run);out=report(run,tmp_path/'report')
        assert checked['verified_jobs']==4 and out['status']=='PASS' and checked['new_api_attempts']==0
        assert before=={str(p):p.read_bytes() for p in run.rglob('*') if p.is_file()}
        # Full denominator preserved, even for STOP/error jobs in other tests.
        assert [r['summary']['planned_items'] for r in checked['results']]==[14,14,20,20]
        assert all(r['summary']['actual_physical_violations']==0 for r in checked['results'])
        with pytest.raises(O5Error,match='JOB_REGISTRY_CHANGED'):
            state=read(run/'run.json');state['jobs'].pop();atomic(run/'run.json',state);verify(run)

@pytest.mark.parametrize('field,value', [('endpoint','http://host/api'),('seed_support','UNKNOWN'),('token_bound',None)])
def test_incomplete_provider_never_ready(field,value):
    p=fixture_profile()
    if field=='token_bound':p['token_bound']['per_image_tokens']=None
    else:p[field]=value
    if field=='endpoint':
        with pytest.raises(O5Error):validate(p)
    else:
        from semantic_pallet_planner.o5.remote_config import require_cost
        with pytest.raises(O5Error,match='COST_NOT_FROZEN'):require_cost(p)


def test_auth_requires_exact_plan_stage_account_and_amount(tmp_path):
    from semantic_pallet_planner.o5.remote_authorized import authorization
    p=fixture_profile();plan={'profile':p}
    a={'schema_version':'o5_s2_operator_authorization_v1','plan_digest':digest(plan),
       'campaign_path':str(tmp_path/'campaign'),'profile_digest':digest(p),'account_id':p['account_id'],
       'currency':'TEST_UNITS','stage':'pilot','stage_amount':'10','total_amount':'20',
       'instruction_reference':'OFFLINE_TEST_ONLY_NOT_USER_AUTHORIZATION'}
    path=tmp_path/'auth.json';atomic(path,a)
    assert authorization(plan,path,'pilot')==a
    for k,v in [('plan_digest','bad'),('account_id','other'),('stage','preflight'),('total_amount','999')]:
        changed={**a,k:v};atomic(path,changed)
        with pytest.raises(O5Error):authorization(plan,path,'pilot')


def test_true_httpwire_uses_one_post_no_proxy_and_strips_secret(monkeypatch,decision):
    # Exercise actual wire construction with urllib opener replaced, not a loopback network server.
    import urllib.request
    monkeypatch.setenv('O5_FIXTURE_KEY','SECRET_TOKEN_MUST_NOT_PERSIST')
    class Response:
        status=200;headers={'x-request-id':'id-1','authorization':'SECRET_TOKEN_MUST_NOT_PERSIST'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps({'model':'FIXTURE_NOT_A_REAL_MODEL','choices':[
            {'finish_reason':'stop','message':{'content':'SECRET_TOKEN_MUST_NOT_PERSIST'}}]}).encode()
    class Opener:
        calls=[]
        def open(self,request,timeout):
            self.calls.append(request)
            assert request.method=='POST' and request.get_header('Authorization')=='Bearer SECRET_TOKEN_MUST_NOT_PERSIST'
            return Response()
    opener=Opener()
    def build_opener(*handlers):
        assert isinstance(handlers[0],urllib.request.ProxyHandler) and handlers[0].proxies=={}
        assert isinstance(handlers[1],NoRedirect)
        return opener
    monkeypatch.setattr(urllib.request,'build_opener',build_opener)
    req,step,cfg=decision;p=fixture_profile();body,_=prepare_body(req,step,cfg,p)
    with offline_guard():result=ChatHTTPTransport(p).complete(body)
    assert len(opener.calls)==1 and 'SECRET_TOKEN' not in json.dumps(result)


@pytest.mark.parametrize('change,error',[
    ({'finish_reason':'length'},'MODEL_TRUNCATED_OR_UNEXPECTED_FINISH'),
    ({'model':'drift'},'SYSTEM_MODEL_DRIFT'),
    ({'refusal':'refused'},'MODEL_REFUSAL_OR_TOOL_OUTPUT'),
    ({'tool_calls':[{}]},'MODEL_REFUSAL_OR_TOOL_OUTPUT'),
    ({'content':''},'EMPTY_MODEL_OUTPUT')])
def test_provider_refusal_finish_and_model_metadata(decision,change,error):
    req,step,cfg=decision;p=fixture_profile();body,_=prepare_body(req,step,cfg,p)
    data={'model':p['returned_model'],'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
    for k,v in change.items():
        if k=='model':data[k]=v
        elif k=='finish_reason':data['choices'][0][k]=v
        else:data['choices'][0]['message'][k]=v
    t=ChatHTTPTransport(p,FixtureWire([(200,{},json.dumps(data))]))
    assert t.complete(body)['error']==error


def test_missing_credential_is_not_sent(decision,tmp_path,monkeypatch):
    p=fixture_profile();monkeypatch.delenv(p['credential_env'],raising=False)
    t=ChatHTTPTransport(p)
    with pytest.raises(O5Error,match='MISSING_CREDENTIAL'):t.precheck()
    assert t.calls==0


def test_reserved_before_send_recovers_without_second_reservation(decision,tmp_path):
    from semantic_pallet_planner.o5 import remote_budget
    req,step,cfg=decision;p=fixture_profile();body,bound=prepare_body(req,step,cfg,p)
    budget=setup_budget(tmp_path);wire=FixtureWire();t=ChatHTTPTransport(p,wire)
    original=remote_budget.atomic
    def stop_sent(path,value):
        if Path(path)==budget.path and any(r['status']=='sent' for r in value['attempts']):raise KeyboardInterrupt()
        original(path,value)
    remote_budget.atomic=stop_sent
    try:
        with pytest.raises(KeyboardInterrupt):budget.attempt('j',req,body,bound,False,t)
    finally:remote_budget.atomic=original
    assert budget.rows('j')[0]['status']=='reserved' and not wire.calls
    budget.attempt('j',req,body,bound,False,t)
    assert len(budget.rows('j'))==1 and len(wire.calls)==1


def test_preflight_and_pilot_share_total_budget(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    p['limits']['total_amount']=b['maximum_amount']
    jobs={'pre':{'phase':'preflight','attempt_limit':1},'pilot':{'phase':'pilot','attempt_limit':2}}
    budget=setup_budget(tmp_path,p,jobs);wire=FixtureWire([(500,{},b'error')]);t=ChatHTTPTransport(p,wire)
    budget.attempt('pre',req,body,b,False,t)
    with pytest.raises(O5Error,match='AMOUNT_BUDGET_EXHAUSTED'):budget.attempt('pilot',req,body,b,False,t)
    assert len(wire.calls)==1


def test_first_429_or_unknown_halts_complete_fixture_batch(tmp_path):
    plan=tmp_path/'plan';run=tmp_path/'run'
    prepare(None,plan,fixture_profile(),fixture=True)
    wire=FixtureWire([(429,{},b'limit')])
    with offline_guard():
        with pytest.raises(O5Error,match='SYSTEM_HTTP_429'):execute_fixture(plan,run,wire=wire)
        with pytest.raises(O5Error,match='SYSTEM_HTTP_429'):execute_fixture(plan,run,resume=True,wire=wire)
    state=read(run/'run.json')
    assert len(wire.calls)==1 and state['jobs'][1]['status']=='STOPPED' and all(j['status']=='NOT_RUN' for j in state['jobs'][2:])


def test_source_drift_and_closed_plan_rejected(tmp_path,monkeypatch):
    from semantic_pallet_planner.o5 import remote_experiment
    plan=tmp_path/'plan';prepare(None,plan,fixture_profile(),fixture=True)
    monkeypatch.setattr(remote_experiment,'source_files',lambda:{'changed':'source'})
    with pytest.raises(O5Error,match='PLAN_OR_SOURCE_DRIFT'):remote_experiment.validate_plan(plan)


def test_visual_probes_both_png_paths_no_answer_in_body(tmp_path):
    from semantic_pallet_planner.o5.remote_authorized import visual_body
    plan=tmp_path/'plan';prepare(None,plan,fixture_profile(),fixture=True)
    p=read(plan/'plan.json')
    for task in p['preflight_tasks'][:2]:
        body,b=visual_body(task,plan,p['profile'])
        assert len(body['messages'][0]['content'])==3
        assert len(b['image_sha256'])==2
        assert 'expected_fact' not in json.dumps(body) and 'candidate_id' not in json.dumps(body)


def test_remote_command_rejects_unready_and_no_plan_overwrite(tmp_path):
    from semantic_pallet_planner.o5.remote_authorized import run_pilot
    plan=tmp_path/'plan';prepare(None,plan,fixture_profile(),fixture=True)
    with pytest.raises(O5Error,match='PILOT_PLAN_NOT_READY'):run_pilot(plan,tmp_path/'run',tmp_path/'missing-auth')
    assert not (tmp_path/'run').exists()
    with pytest.raises(FileExistsError):prepare(None,plan,fixture_profile(),fixture=True)


def test_interrupted_prefix_is_independently_verified_and_read_only(tmp_path,monkeypatch):
    from semantic_pallet_planner.o5 import remote_experiment
    plan=tmp_path/'plan';run=tmp_path/'run'
    prepare(None,plan,fixture_profile(),fixture=True)
    with offline_guard():execute_fixture(plan,run,stop_after=1,max_jobs=1)
    monkeypatch.setattr(remote_experiment,'ChatHTTPTransport',lambda *a,**k: (_ for _ in ()).throw(AssertionError('client constructed during verify')))
    with offline_guard():checked=verify(run)
    assert checked['status']=='PARTIAL' and checked['verified_prefixes'][0]['verified_decisions']==1
    cp=run/'jobs/J001_G0/checkpoint.json';d=read(cp);d['placed'][0]['pose']['x_mm']+=1;atomic(cp,d)
    with pytest.raises(O5Error,match='CHECKPOINT_STATE_CHANGED'):verify(run)


def test_remote_stop_failure_and_repair_keep_complete_denominator(tmp_path):
    from semantic_pallet_planner.o5.episode import run_episode
    p=fixture_profile();task=fixture_task();cfg=load()
    budget=setup_budget(tmp_path,jobs={'j':{'phase':'pilot','attempt_limit':28}})
    def stop(req,answer):return json.dumps({**answer,'action':'STOP','candidate_id':None})
    wire=FixtureWire([stop]);rt=Runtime(budget,'j',p,cfg,tmp_path/'job',ChatHTTPTransport(p,wire))
    with offline_guard():result=run_episode(task,'D0',cfg,tmp_path/'job','j','IDENTITY',attempt_limit=28,_runtime=rt)
    assert result['summary']['planned_items']==14 and result['summary']['placed_items']==0
    assert result['summary']['termination_reason']=='MODEL_STOP' and len(wire.calls)==1
    rt.verify(read(tmp_path/'job/decisions/000/journal.json'),'D0',tmp_path/'job/decisions/000')


def test_cross_process_lock_rejects_other_writer(tmp_path):
    import multiprocessing
    from semantic_pallet_planner.o5.common import exclusive
    ctx=multiprocessing.get_context('fork');queue=ctx.Queue();path=tmp_path/'lock'
    def contender():
        try:
            with exclusive(path):queue.put('ACQUIRED')
        except O5Error as e:queue.put(e.code)
    with exclusive(path):
        proc=ctx.Process(target=contender);proc.start();proc.join(5)
        assert not proc.is_alive() and queue.get(timeout=2)=='RUN_BUSY'
    queue.close()


def test_repeated_5xx_stops_campaign_but_retains_both_costs(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    jobs={j:{'phase':'pilot','attempt_limit':1} for j in ('a','b','c')}
    budget=setup_budget(tmp_path,p,jobs);wire=FixtureWire([(500,{},b'error'),(503,{},b'error')]);t=ChatHTTPTransport(p,wire)
    budget.attempt('a',req,body,b,False,t);budget.attempt('b',req,body,b,False,t)
    with pytest.raises(O5Error,match='SYSTEM_REPEATED_HTTP_5XX'):budget.attempt('c',req,body,b,False,t)
    assert len(wire.calls)==2 and float(budget.totals()['total'])>0


def test_unknown_ledger_halt_cannot_be_erased(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();body,b=prepare_body(req,step,cfg,p)
    budget=setup_budget(tmp_path)
    with pytest.raises(O5Error):budget.attempt('j',req,body,b,False,ChatHTTPTransport(p,FixtureWire([TimeoutError()])))
    data=read(budget.path);data['halt']=None;atomic(budget.path,data)
    with pytest.raises(O5Error,match='UNKNOWN_HALT_CHANGED'):budget.load()


@pytest.mark.parametrize('policy',['capped','unlimited'])
def test_authorized_lifecycle_only_with_replaced_http_no_network(tmp_path,monkeypatch,policy):
    """Native-wire workflow exercised with a synthetic dataset and HTTP opener, not real-model evidence."""
    import urllib.request
    from semantic_pallet_planner.o5 import remote_experiment as ex
    from semantic_pallet_planner.o5.remote_authorized import preflight,verify_preflight,prepare_pilot_from_preflight,run_pilot
    dataset=tmp_path/'synthetic-data';(dataset/'private').mkdir(parents=True)
    tasks=[]
    for i in range(8):
        t=fixture_task(14,800,800,800);t['task_id']=f'development_{i+1:03d}';t['source_cluster_id']='SYNTHETIC_'+str(i);tasks.append(t)
    atomic(dataset/'private/development.json',tasks)
    monkeypatch.setattr(ex,'validate_dataset',lambda root:{'scope':'SYNTHETIC_NATIVE_WIRE_TEST_NOT_RESEARCH_DATA'})
    p=fixture_profile()
    if policy=='unlimited':
        p['amount_policy']='unlimited'
        p['pricing']={k:None for k in p['pricing']}
        for k in ('preflight_amount','pilot_amount','total_amount'):p['limits'][k]=None
    monkeypatch.setenv(p['credential_env'],'SECRET-NATIVE-WIRE-TEST')
    class Opener:
        calls=[]
        def open(self,request,timeout):
            body=json.loads(request.data)
            self.calls.append(body)
            if len(self.calls)<=2:
                text=json.dumps({'workspace':'red_circle','candidates':'blue_square'} if len(self.calls)==1 else
                                {'workspace':'green_circle','candidates':'yellow_square'})
            else:
                req=json.loads(body['messages'][1]['content'][0]['text'])['public_input']
                text=json.dumps({'request_id':req['request_id'],'state_hash':req['state_hash'],
                                 'action':'PLACE','candidate_id':req['candidates'][0]['candidate_id']})
            raw=json.dumps({'model':p['returned_model'],'id':'NATIVE_WIRE_STUB_'+str(len(self.calls)),
                'choices':[{'finish_reason':'stop','message':{'content':text}}],
                'usage':{'prompt_tokens':100,'completion_tokens':40}}).encode()
            class Response:
                status=200;headers={}
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self):return raw
            return Response()
    opener=Opener();monkeypatch.setattr(urllib.request,'build_opener',lambda *args:opener)
    preplan=tmp_path/'preplan';prerun=tmp_path/'prerun';pilotplan=tmp_path/'pilotplan';pilotrun=tmp_path/'pilotrun'
    campaign=tmp_path/'campaign'
    def auth(planroot,stage):
        plan=read(planroot/'plan.json');path=tmp_path/(stage+'-auth.json')
        record={'schema_version':'o5_s2_operator_authorization_v1','plan_digest':digest(plan),
            'campaign_path':str(campaign),'profile_digest':digest(p),'account_id':p['account_id'],
            'currency':'TEST_UNITS','stage':stage,'stage_amount':p['limits'][stage+'_amount'],
            'total_amount':'20','instruction_reference':'UNIT_TEST_SYNTHETIC_NOT_ACTUAL_USER_AUTHORIZATION'}
        if policy=='unlimited':
            record.update(schema_version='o5_s2_operator_authorization_v2',amount_policy='unlimited')
            for k in ('currency','stage_amount','total_amount'):record.pop(k)
        atomic(path,record)
        return path
    with offline_guard():
        prepare(dataset,preplan,p,stage='preflight')
        assert preflight(preplan,prerun,auth(preplan,'preflight'))['status']=='PASS'
        assert verify_preflight(prerun)['status']=='PASS'
        prepare_pilot_from_preflight(prerun,pilotplan)
        result=run_pilot(pilotplan,pilotrun,auth(pilotplan,'pilot'))
        assert result['status']=='EXECUTION_COMPLETE_REQUIRES_VERIFICATION'
        checked=verify(pilotrun)
        assert checked['status']=='PASS' and checked['verified_jobs']==16
        if policy=='unlimited':
            assert checked['budget']['total'] is None
            assert checked['budget']['unknown_attempts']['total']==11
        # 2 visual probes +1 contract +8 single-choice pilot jobs. All underlying HTTP was replaced.
        assert len(opener.calls)==11
        assert preflight(preplan,prerun,auth(preplan,'preflight'),resume=True)['status']=='PASS'
        run_pilot(pilotplan,pilotrun,auth(pilotplan,'pilot'),resume=True)
        assert len(opener.calls)==11
        assert 'SECRET-NATIVE-WIRE-TEST' not in (campaign/'budget.json').read_text()
        assert (prerun/'authorization.json').is_file() and (pilotrun/'authorization.json').is_file()
        changed=read(pilotrun/'authorization.json');changed['stage_amount']='999';atomic(pilotrun/'authorization.json',changed)
        with pytest.raises(O5Error,match='AUTHORIZATION_AMOUNT'):verify(pilotrun)


@pytest.mark.parametrize('missing',['checkpoint','mapping'])
def test_missing_checkpoint_or_mapping_never_recreates_s2_job(decision,tmp_path,missing):
    req,step,cfg=decision;p=fixture_profile();budget=setup_budget(tmp_path)
    job=tmp_path/'job';Runtime(budget,'j',p,cfg,job)
    atomic(job/'decisions/000/request.json',req)
    if missing=='mapping':atomic(job/'checkpoint.json',{'identity':'saved'})
    else:atomic(job/'decisions/000/mapping.private.json',{})
    code='MISSING_CHECKPOINT' if missing=='checkpoint' else 'MISSING_MAPPING'
    with pytest.raises(O5Error,match=code):Runtime(budget,'j',p,cfg,job)
