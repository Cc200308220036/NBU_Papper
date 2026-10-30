import json
import socket
import subprocess
import sys
import urllib.error
from unittest.mock import Mock

import pytest

from semantic_pallet_planner.jev_select.config import load_config
from semantic_pallet_planner.jev_select.contracts import JevSelectError, canonical
from semantic_pallet_planner.jev_select.experiment import prepare_plan, preflight, run_experiment, file_manifest
from semantic_pallet_planner.jev_select.ledger import read
from semantic_pallet_planner.jev_select.replay import replay_experiment
from semantic_pallet_planner.jev_select.transport import credential


class HttpResponse:
    status=200
    def __init__(self,raw):self.raw=raw
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return self.raw[:limit]


def fake_http(monkeypatch,*,with_usage=True,error=None):
    calls=[]
    class Opener:
        def open(self,request,timeout):
            calls.append(request)
            assert request.full_url=='https://api.typesafe.ai/v1/systemone'
            if error is not None:raise error
            body=json.loads(request.data)
            options=body['questions']['next_action']['criteria']
            choice=min(options,key=lambda l:(-options[l]['features']['geometry_score'],
                options[l]['pose']['x_mm'],options[l]['pose']['y_mm'],options[l]['pose']['z_base_mm'],
                options[l]['pose']['yaw_deg'],options[l]['pick_object']))
            payload={'model':body['model'],'answers':{'next_action':{'type':'choice','choice':choice,
                'probabilities':{k:float(k==choice) for k in options},'confidence':1.}}}
            if with_usage:payload['usage']={'input_tokens':100,'output_tokens':12}
            return HttpResponse(canonical(payload).encode())
    monkeypatch.setattr('urllib.request.build_opener',lambda *args:Opener())
    monkeypatch.setenv('TYPESAFE_API_KEY','test-secret-not-real')
    return calls


def remote_plan(path,budget='unlimited'):
    return prepare_plan(path,profile='jev-smoke',methods=('jev_choice',),mode='remote',api_budget=budget)


def test_remote_native_path_usage_cost_and_network_free_replay(tmp_path,monkeypatch):
    calls=fake_http(monkeypatch)
    assert remote_plan(tmp_path/'plan')['planned_jobs']==1
    assert read(tmp_path/'plan/plan.json')['budget']=={'global_attempts':None,'per_job_attempts':None}
    check=preflight(tmp_path/'plan')
    assert check['status']=='PASS' and check['first_selectable_candidates']>=2 and check['model_api_calls']==0
    report=run_experiment(tmp_path/'plan',tmp_path/'run',remote=True,api_budget='unlimited')
    assert report['J2']=='PASS' and report['valid_remote_choices']==4 and len(calls)==4
    metrics=read(tmp_path/'run/metrics/summary.json')
    assert metrics['model_api_calls']==4 and metrics['offline_attempts']==0
    assert metrics['model_usage']=={'input_tokens':400,'output_tokens':48}
    assert metrics['estimated_model_cost_usd']==pytest.approx(400*.042/1_000_000)
    assert metrics['served_models']==['jev-1.14.0'] and metrics['model_latency_p95_s'] is not None
    before=file_manifest(tmp_path/'run')
    def forbidden(*a,**k):raise AssertionError('replay must not read credentials or send')
    monkeypatch.setattr('semantic_pallet_planner.jev_select.transport.credential',forbidden)
    monkeypatch.setattr('semantic_pallet_planner.jev_select.transport.JevTransport.complete',forbidden)
    assert replay_experiment(tmp_path/'run')==report
    assert run_experiment(tmp_path/'plan',tmp_path/'run',remote=True,resume=True)==report
    assert file_manifest(tmp_path/'run')==before and len(calls)==4
    assert not any(b'test-secret-not-real' in p.read_bytes() for p in (tmp_path/'run').rglob('*') if p.is_file())


@pytest.mark.parametrize('error,reason',[(TimeoutError(),'UNKNOWN_IN_FLIGHT'),
    (urllib.error.HTTPError('https://api.typesafe.ai',401,'Unauthorized',{},None),'PROVIDER_FAILURE'),
    (urllib.error.HTTPError('https://api.typesafe.ai',429,'Rate limit',{},None),'PROVIDER_FAILURE'),
    (urllib.error.HTTPError('https://api.typesafe.ai',529,'Overload',{},None),'PROVIDER_FAILURE')])
def test_real_transport_error_path_is_single_attempt(tmp_path,monkeypatch,error,reason):
    calls=fake_http(monkeypatch,error=error); remote_plan(tmp_path/'plan')
    report=run_experiment(tmp_path/'plan',tmp_path/'run',remote=True)
    assert len(calls)==1 and report['J2']=='FAIL_VALID_CHOICE'
    row=read(tmp_path/'run/metrics/rows.json')[0]
    assert row['termination_reason']==reason and row['placed_items']==0
    assert report['estimated_model_cost_usd'] is None
    assert replay_experiment(tmp_path/'run')==report and len(calls)==1


def test_missing_usage_is_unknown_cost(tmp_path,monkeypatch):
    fake_http(monkeypatch,with_usage=False); remote_plan(tmp_path/'plan')
    report=run_experiment(tmp_path/'plan',tmp_path/'run',remote=True)
    assert report['J2']=='PASS' and not report['usage_complete'] and report['estimated_model_cost_usd'] is None


def test_optional_finite_budget_cannot_be_increased_at_run(tmp_path,monkeypatch):
    calls=fake_http(monkeypatch); remote_plan(tmp_path/'plan',1)
    with pytest.raises(JevSelectError,match='runtime_budget_changed'):
        run_experiment(tmp_path/'plan',tmp_path/'bad',remote=True,api_budget='unlimited')
    assert not (tmp_path/'bad').exists() and calls==[]
    report=run_experiment(tmp_path/'plan',tmp_path/'run',remote=True,api_budget=1)
    assert len(calls)==1 and report['valid_remote_choices']==1
    assert read(tmp_path/'run/metrics/rows.json')[0]['termination_reason']=='BUDGET_EXHAUSTED'


def test_no_key_and_mode_mismatch_fail_before_output_creation(tmp_path):
    remote_plan(tmp_path/'plan')
    assert preflight(tmp_path/'plan')['status']=='NEEDS_API_KEY'
    with pytest.raises(JevSelectError,match='missing_or_invalid_api_key'):
        run_experiment(tmp_path/'plan',tmp_path/'run',remote=True)
    with pytest.raises(JevSelectError,match='plan_mode_mismatch'):
        run_experiment(tmp_path/'plan',tmp_path/'run',offline=True)
    assert not (tmp_path/'run').exists()


def test_local_markdown_credential_file_is_supported_without_echo(tmp_path):
    path=tmp_path/'credential.md'; path.write_text('# Local credential\n\n```text\ntest-secret-abcdefghijklmnop\n```\n')
    assert credential('TYPESAFE_API_KEY',path)=='test-secret-abcdefghijklmnop'
    remote_plan(tmp_path/'plan')
    assert preflight(tmp_path/'plan',api_key_file=path)['status']=='PASS'
    assert 'test-secret' not in canonical(preflight(tmp_path/'plan',api_key_file=path))
    path.write_text('TYPESAFE_API_KEY="test-secret-abcdefghijklmnop"\n')
    assert credential('TYPESAFE_API_KEY',path)=='test-secret-abcdefghijklmnop'
    path.write_text('test-secret-abcdefghijklmnop\nanother-key-abcdefghijklmnop\n')
    with pytest.raises(JevSelectError,match='ambiguous'):
        credential('TYPESAFE_API_KEY',path)


def test_remote_plan_requires_explicit_policy_and_smoke_profile(tmp_path):
    with pytest.raises(JevSelectError,match='explicit_api_budget_required'):
        prepare_plan(tmp_path/'plan',profile='jev-smoke',methods=('jev_choice',),mode='remote')
    with pytest.raises(JevSelectError,match='remote_requires_jev_smoke'):
        prepare_plan(tmp_path/'plan',methods=('jev_choice',),mode='remote',api_budget='unlimited')


def test_fresh_remote_process_does_not_import_offline_double(tmp_path):
    script=r'''
import builtins,json,os,socket,sys
from pathlib import Path
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.endswith('.testing') or (name=='testing' and kwargs.get('level')):
        raise AssertionError('offline double imported by remote branch')
    return original(name,*args,**kwargs)
builtins.__import__=guarded
def denied(*a,**k):raise AssertionError('network forbidden in automated test')
socket.socket.connect=denied
from semantic_pallet_planner.jev_select.experiment import prepare_plan,run_experiment
from semantic_pallet_planner.jev_select.contracts import canonical
import urllib.request
class Response:
    status=200
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self,limit):return self.raw[:limit]
class Opener:
    def open(self,request,timeout):
        body=json.loads(request.data); options=body['questions']['next_action']['criteria']; choice=next(iter(options))
        payload={'model':body['model'],'answers':{'next_action':{'type':'choice','choice':choice,'probabilities':{l:float(l==choice) for l in options},'confidence':1.}}}
        response=Response();response.raw=canonical(payload).encode();return response
urllib.request.build_opener=lambda *a:Opener()
os.environ['TYPESAFE_API_KEY']='test-key-not-real'
root=Path(sys.argv[1])
prepare_plan(root/'plan',profile='jev-smoke',methods=('jev_choice',),mode='remote',api_budget='unlimited')
report=run_experiment(root/'plan',root/'run',remote=True)
assert 'semantic_pallet_planner.jev_select.testing' not in sys.modules
print(json.dumps({'status':report['status'],'offline_double_imported':False}))
'''
    completed=subprocess.run([sys.executable,'-c',script,str(tmp_path)],capture_output=True,text=True)
    assert completed.returncode==0,completed.stderr
    assert json.loads(completed.stdout)=={'status':'PASS','offline_double_imported':False}
