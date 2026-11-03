"""JN1-A constructed tasks / injected transport only; never authenticates."""
import copy
import json
import pytest
from semantic_pallet_planner.jev_select.tests.unit.test_packaging_runtime import mechanism_task,item
from semantic_pallet_planner.jev_select.packaging_remote import (
    load_remote_config,RequestLedger,remote_selector_factory,decision_record,preflight_remote)
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError,DecisionContext,validate_schema
from semantic_pallet_planner.jev_select.transport import outcome
from semantic_pallet_planner.jev_select.episode import decision_inputs,run_episode
from semantic_pallet_planner.jev_select.ledger import read
from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive

class Fake:
    origin='test_double'
    def __init__(self,change=None):self.calls=0;self.change=change
    def complete(self,body):
        self.calls+=1
        labels=list(body['questions']['next_action']['criteria'])
        response={'model':body['model'],'answers':{'next_action':{'type':'choice','choice':labels[-1],
                  'probabilities':{l:float(l==labels[-1]) for l in labels},'confidence':1.}},
                  'usage':{'input_tokens':17,'output_tokens':7}}
        if self.change:return self.change(response)
        return outcome('OK',json.dumps(response).encode(),http_status=200,network_attempted=True)

def fixture():
    t=mechanism_task([item(str(i),size=(20,20,20)) for i in range(3)])
    c=load_remote_config(data_identity=digest('CONSTRUCTED'),task_digest=digest(t),enabled=True)
    s=initial(t['container'],3)
    for o in t['items']:s=receive(s,o,t['attributes'][o['item_id']])
    _,_,b,ctx=decision_inputs(s,t,c,'J','J_D0000')
    return t,c,b,ctx

def selector(tmp,c,f):
    ledger=RequestLedger(tmp)
    return remote_selector_factory('jev_no_memory',config=c,transport=f,ledger=ledger,job_id='J'),ledger

def test_success_mapping_public_and_saved_response(tmp_path):
    t,c,b,ctx=fixture();f=Fake();s,l=selector(tmp_path,c,f)
    selected=s.select(ctx,decision_id='J_D0000').data
    assert selected['selected_candidate_id']==ctx.data['display_mapping'][selected['selected_display_id']]['candidate_id']
    assert selected['source']=='test_double' and selected['usage']['input_tokens']==17
    assert f.calls==1
    assert s.select(ctx,decision_id='J_D0000').data==selected and f.calls==1
    assert [v['state'] for v in l.data['requests'][0]['history']]==['INTENT','SENDING','RESPONSE_SAVED','SELECTION_SAVED']
    body=ctx.data['request_body'];assert body['state']['memories']==[]
    for banned in ('source_order','witness','reference_policy','monitor','certificate','reaction','future_items','task_id'):
        assert banned not in json.dumps(body)
    for o in body['state']['available_objects']:
        assert set(('dimensions_mm','mass_kg','stackable','remaining_top_load_kg','max_top_load_kg'))<=o.keys()
    bad=ctx.data;bad['display_mapping']['C01']['candidate_id']='stale'
    with pytest.raises(JevSelectError):s.select(DecisionContext.from_dict(bad),decision_id='J_D0000')
    with pytest.raises(JevSelectError):s.select(ctx,decision_id='wrong')

@pytest.mark.parametrize('failure',['unknown','illegal','json','oversize','duplicate','wrong_model','probability'])
def test_invalid_no_fallback(tmp_path,failure):
    _,c,_,ctx=fixture()
    def change(r):
        if failure in ('unknown','illegal'):r['answers']['next_action']['choice']='C99' if failure=='unknown' else 'move(1)'
        if failure=='wrong_model':r['model']='other'
        if failure=='probability':r['answers']['next_action']['probabilities']['C01']=2
        raw=json.dumps(r).encode()
        if failure=='json':raw=b'{bad'
        if failure=='duplicate':raw=b'{"model":"a","model":"b"}'
        if failure=='oversize':raw=b'x'*(c['response_max_bytes']+1)
        return outcome('OK',raw,http_status=200,network_attempted=True)
    f=Fake(change);s,l=selector(tmp_path,c,f)
    a=s.select(ctx,decision_id='J_D0000');assert a.data['status']=='invalid_response' and a.data['selected_candidate_id'] is None
    assert s.select(ctx,decision_id='J_D0000').data==a.data and f.calls==1

@pytest.mark.parametrize('mode',['timeout','failure','exception'])
def test_send_errors(tmp_path,mode):
    _,c,_,ctx=fixture()
    def change(r):
        if mode=='exception':raise TimeoutError('must not be saved')
        return outcome('UNKNOWN_IN_FLIGHT' if mode=='timeout' else 'PROVIDER_FAILURE',
                       error='TIMEOUT' if mode=='timeout' else 'HTTP_401',network_attempted=True,
                       error_stage='response_read',error_code='TIMEOUT' if mode=='timeout' else 'HTTP_401')
    f=Fake(change);f.origin='jev';s,l=selector(tmp_path,c,f)
    a=s.select(ctx,decision_id='J_D0000');assert a.data['status']==('provider_failure' if mode=='failure' else 'unknown_in_flight')
    assert s.select(ctx,decision_id='J_D0000').data==a.data and f.calls==1
    assert l.statistics()['send_reservations']==1
    assert l.statistics()['unknown_sends']==(mode!='failure')
    assert 'must not be saved' not in l.path.read_text()

@pytest.mark.parametrize('cut',['INTENT','SENDING','RESPONSE_SAVED','SELECTION_SAVED'])
def test_ledger_interruption(tmp_path,cut):
    _,c,_,ctx=fixture();f=Fake()
    class Cut(BaseException):pass
    def hook(phase,row):
        if phase==cut:raise Cut()
    l=RequestLedger(tmp_path,hook=hook)
    s=remote_selector_factory('jev_no_memory',config=c,transport=f,ledger=l,job_id='J')
    with pytest.raises(Cut):s.select(ctx,decision_id='J_D0000')
    s,l=selector(tmp_path,c,f)
    a=s.select(ctx,decision_id='J_D0000')
    assert f.calls==(0 if cut=='SENDING' else 1)
    assert a.data['status']==('unknown_in_flight' if cut=='SENDING' else 'selected')
    assert s.select(ctx,decision_id='J_D0000').data==a.data

@pytest.mark.parametrize('phase',['SELECTED','MONITORED','COMMITTED'])
def test_episode_resume_without_reselect_monitor_recommit(tmp_path,phase,monkeypatch):
    t,c,_,_=fixture();f=Fake();s,l=selector(tmp_path,c,f);saved=[]
    class Cut(BaseException):pass
    def checkpoint(cp):
        if cp['phase']==phase:saved.append(cp);raise Cut()
    with pytest.raises(Cut):run_episode(t,s,c,job_id='J',method='jev_no_memory',on_checkpoint=checkpoint)
    cp=saved[0]
    def forbidden(*a,**k):raise AssertionError('stored stage was dispatched again')
    monkeypatch.setattr(s,'select',forbidden)
    import semantic_pallet_planner.jev_select.stability.monitor as mon
    import semantic_pallet_planner.jev_select.execution as ex
    if phase in ('MONITORED','COMMITTED'):monkeypatch.setattr(mon,'monitor_selected_action',forbidden)
    if phase=='COMMITTED':monkeypatch.setattr(ex,'commit_physical',forbidden)
    ep=run_episode(t,s,c,job_id='J',method='jev_no_memory',resume=cp,event_limit=len(cp['events'])+1)
    assert ep['events'][-1]['event']=='PLACE' and len(ep['final_state']['placed_items'])==1 and f.calls==1
    assert decision_record(ep['events'][-1])['selected_candidate_id']


def test_singleton_and_legacy_protection(tmp_path):
    from semantic_pallet_planner.jev_select.packaging_protocol import selector_factory
    from semantic_pallet_planner.jev_select.selector import JevSelector
    from semantic_pallet_planner.jev_select.stability.monitor import load_monitor_config
    from semantic_pallet_planner.jev_select.packaging_runtime import load_runtime_config
    t,c,b,ctx=fixture();f=Fake();s,l=selector(tmp_path,c,f)
    # Construct a valid singleton context through the shared builder, not hand-edited labels.
    from semantic_pallet_planner.jev_select.packaging_runtime import build_context,no_policy
    from semantic_pallet_planner.jev_select.contracts import CandidateBundle
    from semantic_pallet_planner.jev_select.selector import bind_decision
    from semantic_pallet_planner.jev_select.context import ContextBuilder
    from semantic_pallet_planner.o4.extensions.e2.protocol import observation
    state=initial(t['container'],3)
    o=t['items'][0];state=receive(state,o,t['attributes'][o['item_id']])
    req=observation(state,t['instruction_text'],[])
    # A deliberately constructed one-candidate original pool, labelled as fixture.
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider,PublicBusinessGuard
    from semantic_pallet_planner.jev_select.config import generator_config
    b=CandidateProvider().build(state,req,generator_config(),config=c).data
    b['physical_candidates']=b['physical_candidates'][:1];b['selectable_candidates']=b['physical_candidates']
    b['physical_digest']=b['selectable_digest']=digest(b['physical_candidates'])
    b=CandidateBundle.from_dict(b);b=PublicBusinessGuard().filter(req,no_policy(req),b,c)
    ctx=bind_decision(build_context(c,req,b,no_policy(req)),'J','J_D0000')
    assert s.select(ctx,decision_id='J_D0000').data['status']=='singleton'
    assert f.calls==0 and l.statistics()['model_calls']==0 and not l.data['requests']
    for method in ('jev_no_memory','unknown'):
        with pytest.raises(JevSelectError):selector_factory(method)
    old=load_monitor_config(data_identity=digest('fixture'),task_digest=digest(t))
    with pytest.raises(JevSelectError):JevSelector(old,None,'J').select(ctx,decision_id='J_D0000')
    bad=copy.deepcopy(old);bad['selector']='jev_no_memory'
    with pytest.raises(JevSelectError):validate_schema('config',bad)
    for method in ('local_first_test_double','local_geometry_test_double'):
        cfg=load_remote_config(data_identity=digest('fixture'),task_digest=digest(t),method=method)
        assert selector_factory(method,execution_version=cfg['version'],config=cfg)
    preflight_remote(c)
    bad=copy.deepcopy(c);bad['runtime_identity']['strategy_identity']=digest('changed')
    with pytest.raises(JevSelectError):preflight_remote(bad)


def test_real_origin_usage_count_budget_and_body_binding(tmp_path):
    _,c,_,ctx=fixture();f=Fake();f.origin='jev';s,l=selector(tmp_path,c,f)
    a=s.select(ctx,decision_id='J_D0000')
    assert a.data['source']=='jev' and a.data['network_attempted'] is True
    assert l.statistics()['model_calls']==1 and l.statistics()['usage']==[{'input_tokens':17,'output_tokens':7}]
    from semantic_pallet_planner.jev_select.selector import bind_decision
    other=bind_decision(ctx,'J','J_D0001')
    with pytest.raises(JevSelectError,match='budget_exhausted'):s.select(other,decision_id='J_D0001')
    assert f.calls==1
    bad=ctx.data;bad['request_body']['model']='LOCAL_TEST_DOUBLE_NOT_JEV';bad['local_binding']['request_body_digest']=digest(bad['request_body'])
    with pytest.raises(JevSelectError):s.select(DecisionContext.from_dict(bad),decision_id='J_D0000')


def test_saved_response_parses_without_transport(tmp_path):
    _,c,_,ctx=fixture();f=Fake();l=RequestLedger(tmp_path)
    l.request(ctx,'J','J_D0000',f)
    recovered=remote_selector_factory('jev_no_memory',config=c,transport=None,ledger=RequestLedger(tmp_path),job_id='J')
    assert recovered.select(ctx,decision_id='J_D0000').data['status']=='selected' and f.calls==1


def test_transport_no_retry_auth_not_persisted(monkeypatch):
    from semantic_pallet_planner.jev_select.transport import JevTransport
    import urllib.request
    import urllib.error
    _,c,_,ctx=fixture();calls=[]
    monkeypatch.setenv('TYPESAFE_API_KEY','CONSTRUCTED_SECRET_DO_NOT_SAVE')
    class Opener:
        def open(self,req,timeout):
            calls.append(req)
            assert req.get_header('Authorization')=='Bearer CONSTRUCTED_SECRET_DO_NOT_SAVE'
            raise urllib.error.HTTPError(req.full_url,429,'secret error',{'Authorization':'secret'},None)
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a:Opener())
    response=JevTransport(c).complete(ctx.data['request_body'])
    assert len(calls)==1 and response['status']=='PROVIDER_FAILURE' and response['error']=='HTTP_429'
    assert 'SECRET' not in json.dumps(response) and 'Authorization' not in json.dumps(response)


def test_no_private_future_or_monitor_mutation_changes_public_body():
    t,c,b,ctx=fixture()
    from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive
    state=initial(t['container'],3)
    for o in t['items']:state=receive(state,o,t['attributes'][o['item_id']])
    # Task-private fields are never copied to state/criteria. Existing observed items are identical.
    mutated=copy.deepcopy(t)
    mutated['items'].append(item('PRIVATE_FUTURE_SENTINEL',mass=999))
    mutated.update(witness='PRIVATE_WITNESS_SENTINEL',monitor={'status':'UNSTABLE'})
    _,_,_,other=decision_inputs(state,mutated,c,'J','J_D0000')
    assert ctx.data['request_body']==other.data['request_body']
