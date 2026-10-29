"""Direct-Text risks. All transmissions use explicit test doubles under a socket guard."""
import copy
import json
from pathlib import Path
import pytest
from semantic_pallet_planner.o5.common import ROOT, O5Error, atomic, read, digest, offline_guard
from semantic_pallet_planner.o5.config import load
from semantic_pallet_planner.o5.candidates import generate, case_for, state_for
from semantic_pallet_planner.o5.public_request import build, parse_response, validate_request, TEXT_VERSION
from semantic_pallet_planner.o5.remote_config import validate, require_cost, request_version
from semantic_pallet_planner.o5.remote_transport import prepare_body, ChatHTTPTransport, HTTPWire
from semantic_pallet_planner.o5.remote_budget import Budget
from semantic_pallet_planner.o5.remote_runtime import Runtime
from semantic_pallet_planner.o5 import public_request as public, remote_experiment as ex, remote_authorized as auth
from semantic_pallet_planner.o5.episode import run_episode
from semantic_pallet_planner.o5.testing import fixture_task
from semantic_pallet_planner.runners import o5_direct_text as helper


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*a,**k):raise AssertionError('REAL_HTTP_FORBIDDEN')
    monkeypatch.setattr(HTTPWire,'post',reject)
    with offline_guard():yield


@pytest.fixture
def profile():return require_cost(read(helper.PROFILE))


@pytest.fixture
def decision(tmp_path):
    task=read(helper.DATASET/'private/development.json')[0];cfg=load()
    pool,_=generate(task['container'],[],task['items'][0],0,cfg)
    req,mapping=build(task['container'],[],task['items'][0],pool,cfg,'TEXT_TEST',tmp_path,request_version=TEXT_VERSION)
    return req,mapping,cfg,task


def answer(req,**kw):
    return {'request_id':req['request_id'],'state_hash':req['state_hash'],'action':'PLACE',
            'candidate_id':req['candidates'][0]['candidate_id'],**kw}


class TextWire(ex.FixtureWire):
    def post(self,endpoint,body,credential,timeout):
        status,headers,raw=super().post(endpoint,body,credential,timeout)
        if status==200:
            value=json.loads(raw);value['model']='deepseek-flash';raw=json.dumps(value)
        return status,headers,raw


def runtime(tmp_path,profile,script=None,limit=40):
    budget=Budget(tmp_path/'campaign',profile,'TEXT_ID',{'j':{'phase':'pilot','attempt_limit':limit}},True,create=True)
    wire=TextWire(script);rt=Runtime(budget,'j',profile,load(),tmp_path/'job',ChatHTTPTransport(profile,wire))
    return rt,wire,budget


def deny_assets(monkeypatch):
    def reject(*a,**kw):raise AssertionError('TEXT_TOUCHED_IMAGE_PATH')
    monkeypatch.setattr(public,'render',reject);monkeypatch.setattr(public,'image_bytes',reject)


def test_real_state_complete_text_body_no_asset_dependency(decision,profile,tmp_path,monkeypatch):
    req,mapping,cfg,task=decision;deny_assets(monkeypatch)
    body,bound=prepare_body(req,tmp_path/'DOES_NOT_EXIST',cfg,profile)
    assert len(body['messages'][1]['content'])==1
    assert set(req)=={'schema_version','request_id','state_hash','container','placed_items','current_item',
                      'candidates','task_goal','output_contract','units_and_coordinates'}
    assert req['current_item']['dimensions_mm']==task['items'][0]['dimensions_mm']
    assert req['container']==task['container'] and len(req['candidates'])<=16
    assert req['units_and_coordinates']['pose']=='x_mm,y_mm=box_planar_center;z_base_mm=box_bottom'
    for c in req['candidates']:
        assert set(c)=={'candidate_id','pose','oriented_size_mm','support'}
        assert c['pose']==mapping[c['candidate_id']]['pose']
    encoded=json.dumps(body)
    for forbidden in ('image_url','data:image','images','split','source_cluster_id','geometry_score','future','expected_fact','AST'):
        assert forbidden not in encoded
    text=sum(len(m['content'].encode()) if isinstance(m['content'],str) else
             sum(len(part['text'].encode()) for part in m['content']) for m in body['messages'])
    assert bound['input_upper']==text+512 and bound['image_sha256']==[]
    assert bound['maximum_amount'] is None and body['max_tokens']==256
    assert body['thinking']=={'type':'disabled'} and body['response_format']=={'type':'json_object'}
    pool,_=generate(task['container'],[],task['items'][0],0,cfg)
    req2,mapping2=build(task['container'],[],task['items'][0],pool,cfg,'TEXT_TEST',tmp_path/'absent',request_version=TEXT_VERSION)
    assert req2==req and mapping2==mapping and not (tmp_path/'absent').exists()


def test_same_candidate_mapping_as_legacy(decision,tmp_path):
    req,mapping,cfg,task=decision;pool,_=generate(task['container'],[],task['items'][0],0,cfg)
    legacy,old=build(task['container'],[],task['items'][0],pool,cfg,'TEXT_TEST',tmp_path/'image')
    assert mapping==old and req['candidates']==legacy['candidates']
    assert legacy['schema_version']=='o5_decision_request_v1' and len(legacy['images'])==2
    assert legacy['state_hash']!=req['state_hash']


@pytest.mark.parametrize('patch,code',[
    ({'candidate_id':'C99'},'UNKNOWN_CANDIDATE'),({'state_hash':'0'*64},'STALE_BINDING'),
    ({'request_id':'old'},'STALE_BINDING'),({'x_mm':0},'SCHEMA_ERROR'),
    ({'action':'STOP','candidate_id':'C01'},'INVALID_STOP'),({'action':'OTHER'},'SCHEMA_ERROR')])
def test_response_contract(decision,patch,code):
    req,*_=decision
    with pytest.raises(O5Error,match=code):parse_response(json.dumps(answer(req,**patch)),req)


@pytest.mark.parametrize('raw',['not json','{"action":"PLACE","action":"STOP"}','NaN'])
def test_bad_json_duplicate_keys(decision,raw):
    req,*_=decision
    with pytest.raises(O5Error):parse_response(raw,req)


def test_place_and_stop(decision):
    req,*_=decision
    assert parse_response(json.dumps(answer(req)),req)['action']=='PLACE'
    assert parse_response(json.dumps(answer(req,action='STOP',candidate_id=None)),req)['action']=='STOP'


@pytest.mark.parametrize('where,key',[('root','images'),('current_item','split'),('candidate','geometry_score'),('container','future')])
def test_closed_public_projection(decision,where,key):
    req=copy.deepcopy(decision[0]);target=req if where=='root' else req['candidates'][0] if where=='candidate' else req[where]
    target[key]=[]
    req['state_hash']=public.request_hash(req)
    with pytest.raises(O5Error,match='SCHEMA_ERROR'):validate_request(req)


def test_future_and_private_item_fields_never_projected(decision,tmp_path):
    req,mapping,cfg,task=decision;item=copy.deepcopy(task['items'][0]);item.update(split='secret',future=['secret'],score=999)
    pool,_=generate(task['container'],[],item,0,cfg)
    same,_=build(task['container'],[],item,pool,cfg,'TEXT_TEST',tmp_path,request_version=TEXT_VERSION)
    assert same==req


def test_cross_protocol_profile_rejected(decision,profile,tmp_path):
    req,_,cfg,_=decision
    legacy=read(ROOT/'semantic_pallet_planner/configs/o5_s2_deepseek_flash.json')
    with pytest.raises(O5Error,match='REQUEST_PROFILE_PROTOCOL_MISMATCH'):prepare_body(req,tmp_path,cfg,legacy)
    p=copy.deepcopy(profile);p['image_detail']='high'
    with pytest.raises(O5Error,match='REMOTE_SCHEMA_ERROR'):validate(p)
    p=copy.deepcopy(profile);p['token_bound']['per_image_tokens']=1024
    with pytest.raises(O5Error,match='REMOTE_SCHEMA_ERROR'):validate(p)


def test_input_boundary_and_repair_count_all_messages(decision,profile,tmp_path):
    req,_,cfg,_=decision;_,b=prepare_body(req,tmp_path,cfg,profile)
    profile['token_bound']['framing_tokens']+=12000-b['input_upper']
    assert prepare_body(req,tmp_path,cfg,profile)[1]['input_upper']==12000
    with pytest.raises(O5Error,match='INPUT_BOUND_EXCEEDED'):prepare_body(req,tmp_path,cfg,profile,'INVALID_JSON')


@pytest.mark.parametrize('script,reason,calls',[
    (['invalid','valid'],None,2),(['invalid','invalid'],'INVALID_JSON',2),
    ([(500,{},'failed')],'HTTP_500',1),
    ([lambda req,a:json.dumps({**a,'action':'STOP','candidate_id':None})],None,1)])
def test_repair_failure_stop_and_unknown_cost(decision,profile,tmp_path,script,reason,calls):
    req,_,_,_=decision;rt,wire,budget=runtime(tmp_path,profile,script)
    response,ids,error=rt.choose(req,tmp_path)
    assert error==reason and len(wire.calls)==calls and len(ids)==calls
    assert rt.choose(req,tmp_path)==(response,ids,error) and len(wire.calls)==calls
    assert budget.totals()['total'] is None and budget.totals()['unknown_attempts']['total']==calls
    if calls==2:
        second=json.loads(wire.calls[1]['messages'][1]['content'][0]['text'])
        assert second=={'public_input':req,'repair_error':'INVALID_JSON'}


def test_unknown_stops_and_never_resends(decision,profile,tmp_path):
    rt,wire,budget=runtime(tmp_path,profile,[TimeoutError()]);req=decision[0]
    for _ in range(2):
        with pytest.raises(O5Error,match='UNKNOWN_IN_FLIGHT'):rt.choose(req,tmp_path)
    assert len(wire.calls)==1 and budget.totals()['total'] is None


def test_receipt_crash_replays_without_second_wire(decision,profile,tmp_path,monkeypatch):
    req=decision[0];rt,wire,budget=runtime(tmp_path,profile)
    settle=budget._settle
    def crash(*a):raise KeyboardInterrupt()
    monkeypatch.setattr(budget,'_settle',crash)
    with pytest.raises(KeyboardInterrupt):rt.choose(req,tmp_path)
    monkeypatch.setattr(budget,'_settle',settle)
    assert rt.choose(req,tmp_path)[0]['action']=='PLACE' and len(wire.calls)==1


def test_commit_independent_physical_check(decision,profile,tmp_path,monkeypatch):
    from semantic_pallet_planner.o5 import episode
    rt,wire,budget=runtime(tmp_path,profile)
    monkeypatch.setattr(episode,'check_candidate',lambda *a:['INJECTED_PHYSICAL_REJECTION'])
    result=run_episode(decision[3],'D0',load(),tmp_path/'job','j','TEXT_ID',_runtime=rt)
    assert result['final_state']==[] and result['summary']['termination_reason']=='PHYSICAL_REJECTION'
    assert result['summary']['planned_items']==len(decision[3]['items']) and len(wire.calls)==1


def test_text_fixture_resume_verify_report_without_images(profile,tmp_path,monkeypatch):
    deny_assets(monkeypatch)
    plan=tmp_path/'plan';run=tmp_path/'run'
    ex.prepare(None,plan,profile,fixture=True)
    wire=TextWire()
    ex.execute_fixture(plan,run,stop_after=2,wire=wire)
    partial=ex.verify(run);assert partial['status']=='PARTIAL' and partial['verified_prefixes']
    ex.execute_fixture(plan,run,resume=True,wire=wire)
    checked=ex.verify(run)
    assert checked['status']=='PASS' and checked['verified_jobs']==4
    assert checked['mode']=='OFFLINE_HTTP_FIXTURE' and checked['model_performance']=='NOT_MEASURED'
    assert checked['protocol_version']=='o5_direct_text_v1' and checked['budget']['total'] is None
    before=len(wire.calls);ex.execute_fixture(plan,run,resume=True,wire=wire)
    assert len(wire.calls)==before and not list(tmp_path.rglob('*.png'))
    assert ex.report(run,tmp_path/'report')['status']=='PASS'
    assert all(r['test_double'] is True for r in checked['results'])
    body=next((run/'campaign/attempts').glob('*/body.json'));bad=read(body);bad['image_url']='bad';atomic(body,bad)
    with pytest.raises(O5Error,match='SAVED_REMOTE_BODY_CHANGED'):ex.verify(run)


@pytest.mark.parametrize('failure',['ledger','mapping','checkpoint'])
def test_missing_recovery_evidence_not_recreated(profile,tmp_path,failure):
    plan=tmp_path/'plan';run=tmp_path/'run';ex.prepare(None,plan,profile,fixture=True)
    ex.execute_fixture(plan,run,max_jobs=1,stop_after=1,wire=TextWire())
    root=run/'jobs/J001_G0'
    path={'ledger':root/'ledger.json','mapping':root/'decisions/000/mapping.private.json','checkpoint':root/'checkpoint.json'}[failure]
    path.unlink()
    with pytest.raises(O5Error,match='MISSING_'):ex.execute_fixture(plan,run,resume=True,wire=TextWire())
    assert not path.exists()


def prepare_real_state_plan(tmp_path,profile):
    plan=tmp_path/'preplan';ex.prepare(helper.DATASET,plan,profile,stage='preflight')
    a=helper.operator_record(plan,tmp_path/'campaign','preflight','OFFLINE_TEST_ONLY')
    a['instruction_reference']='OFFLINE_TEST_DOUBLE_NOT_OPERATOR_RUN';atomic(tmp_path/'auth.json',a)
    return plan,tmp_path/'auth.json'


def test_real_dev_preflight_offline_double_cannot_unlock_pilot(profile,tmp_path,monkeypatch):
    deny_assets(monkeypatch);plan,a=prepare_real_state_plan(tmp_path,profile)
    value,tasks=ex.validate_plan(plan)
    assert len(tasks)==8 and value['maximum_selection_attempts']==290 and value['gaps']==[]
    probes=value['preflight_tasks'];assert [t['task_id'] for t in probes]==['text_state_0','text_state_1']
    assert len(read(plan/probes[1]['request_path'])['placed_items'])==1
    wire=TextWire(['invalid','valid','valid'])
    result=auth.preflight(plan,tmp_path/'run',a,_offline_wire=wire)
    assert result['status']=='PASS' and result['real_api_attempts']==0 and result['test_double'] is True
    assert len(wire.calls)==3 and not list(plan.rglob('*.png'))
    checked=auth.verify_preflight(tmp_path/'run')
    assert checked['status']=='PASS' and checked['test_double'] is True and checked['real_api_attempts']==0
    with pytest.raises(O5Error,match='PREFLIGHT_NOT_REAL'):auth.prepare_pilot_from_preflight(tmp_path/'run',tmp_path/'pilot')
    auth.preflight(plan,tmp_path/'run',a,resume=True,_offline_wire=wire)
    assert len(wire.calls)==3


@pytest.mark.parametrize('script,error',[
    (['invalid','invalid'],'INVALID_JSON'), ([(500,{},'error')],'HTTP_500'),
    ([TimeoutError()],'UNKNOWN_IN_FLIGHT')])
def test_failed_text_preflight_keeps_evidence(profile,tmp_path,script,error):
    plan,a=prepare_real_state_plan(tmp_path,profile);wire=TextWire(script)
    result=auth.preflight(plan,tmp_path/'run',a,_offline_wire=wire)
    assert result['status']=='HOLD_ENGINEERING' and result['error']==error and result['real_api_attempts']==0
    assert auth.verify_preflight(tmp_path/'run')['status']=='HOLD_ENGINEERING'
    assert read(tmp_path/'campaign/budget.json')['attempts']


def test_placed_state_matches_oracle_and_candidate_mapping(profile,tmp_path):
    from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate
    from semantic_pallet_planner.evaluation.state import apply_candidate
    from semantic_pallet_planner.o5.selectors import geometry_choice
    plan,a=prepare_real_state_plan(tmp_path,profile);p,tasks=ex.validate_plan(plan);task=tasks[0]
    first=read(plan/'text_states/0/request.json');mapping=read(plan/'text_states/0/mapping.private.json')
    placed=apply_candidate(case_for(state_for(task['container'],[],task['items'][0],0)),mapping[geometry_choice(first,mapping)['candidate_id']])
    second=read(plan/'text_states/1/request.json');second_map=read(plan/'text_states/1/mapping.private.json')
    assert second['placed_items']==[public.item_projection(placed[0],True)]
    for c in second['candidates']:
        assert not check_candidate(case_for(state_for(task['container'],placed,task['items'][1],1)),{'container':task['container']},second_map[c['candidate_id']])
    assert second['current_item']==public.item_projection(task['items'][1])


def test_handoff_offline_without_key_and_pilot_gate(tmp_path,monkeypatch):
    paths={k:tmp_path/k for k in helper.paths('OFFLINE_TEST')}
    monkeypatch.setattr(helper,'paths',lambda i:paths)
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    result=helper.prepare_handoff('OFFLINE_TEST')
    assert result['protocol_version']=='o5_direct_text_v1' and result['real_api_attempts']==0
    assert helper.operate('validate-plan','OFFLINE_TEST')['status']=='READY_FOR_USER_TEXT_PREFLIGHT'
    assert not paths['campaign'].exists() and not paths['preflight_run'].exists() and not paths['pilot_plan'].exists()
    with pytest.raises(FileNotFoundError):helper.operate('prepare-pilot','OFFLINE_TEST')
    with pytest.raises(O5Error,match='HANDOFF_ID_ALREADY_USED'):helper.prepare_handoff('OFFLINE_TEST')


def test_text_plan_rejects_cross_modal_profile(profile,tmp_path):
    plan,a=prepare_real_state_plan(tmp_path,profile);p=read(plan/'plan.json')
    p['profile']=read(ROOT/'semantic_pallet_planner/configs/o5_s2_deepseek_flash.json');atomic(plan/'plan.json',p)
    with pytest.raises(O5Error,match='PLAN_PROFILE_PROTOCOL_MISMATCH'):ex.validate_plan(plan)


def test_text_usage_above_bound_halts(decision,profile,tmp_path):
    rt,wire,budget=runtime(tmp_path,profile)
    req=decision[0]
    def too_large(req,a):
        return (200,{},json.dumps({'model':'deepseek-flash','choices':[{'finish_reason':'stop','message':{'content':json.dumps(a)}}],
               'usage':{'prompt_tokens':12001,'completion_tokens':40}}))
    wire.script=[too_large]
    response,ids,error=rt.choose(req,tmp_path)
    assert response is None and error=='SYSTEM_USAGE_BOUND_EXCEEDED' and len(ids)==1
    assert rt.choose(req,tmp_path)==(response,ids,error)  # Replays the saved failure, never a new call.
    next_req={**req,'request_id':req['request_id']+'_next'}
    with pytest.raises(O5Error,match='SYSTEM_USAGE_BOUND_EXCEEDED'):rt.choose(next_req,tmp_path)
    assert len(wire.calls)==1 and budget.load()['halt']=='SYSTEM_USAGE_BOUND_EXCEEDED'


def test_text_empty_pool_does_not_call_model(profile,tmp_path,monkeypatch):
    from semantic_pallet_planner.o5 import episode
    task=fixture_task();rt,wire,budget=runtime(tmp_path,profile)
    monkeypatch.setattr(episode,'generate',lambda *a:([],{'test_double':'EMPTY_POOL_INJECTION'}))
    result=run_episode(task,'D0',load(),tmp_path/'job','j','TEXT_ID',_runtime=rt)
    assert result['summary']['termination_reason']=='NO_PHYSICAL_CANDIDATE' and not wire.calls
    assert result['summary']['planned_items']==14 and budget.totals()['total']=='0'


def test_interrupted_preflight_prefix_rechecked_before_more_calls(profile,tmp_path):
    plan,a=prepare_real_state_plan(tmp_path,profile)
    wire=TextWire(['valid',KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):auth.preflight(plan,tmp_path/'run',a,_offline_wire=wire)
    state=read(tmp_path/'run/preflight.json')
    assert state['status']=='IN_PROGRESS' and len(state['results'])==1
    state['results'][0]['pass']=False
    atomic(tmp_path/'run/preflight.json',state)
    before=len(wire.calls)
    with pytest.raises(O5Error,match='PREFLIGHT_RESULT_CHANGED'):
        auth.preflight(plan,tmp_path/'run',a,resume=True,_offline_wire=wire)
    assert len(wire.calls)==before
