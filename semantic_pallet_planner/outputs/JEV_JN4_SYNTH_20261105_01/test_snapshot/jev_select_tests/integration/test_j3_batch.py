import base64
import copy
import json
from pathlib import Path
import shutil
import urllib.request

import pytest

from semantic_pallet_planner.jev_select.batch import prepare_plan_v2,run_experiment_v2,replay_experiment_v2,validate_plan_v2,preflight_v2,METHODS_V2
from semantic_pallet_planner.jev_select.contracts import JevSelectError,canonical,digest
from semantic_pallet_planner.jev_select.experiment import file_manifest
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.cli import main
from semantic_pallet_planner.jev_select.config import load_v2_config

DATASET=Path(__file__).resolve().parents[6]/'semantic_pallet_dataset_v1'


@pytest.fixture(scope='module')
def normal(tmp_path_factory):
    root=tmp_path_factory.mktemp('j3-normal')
    prepare_plan_v2(root/'plan',profile='constructed-eval',methods=METHODS_V2)
    report=run_experiment_v2(root/'plan',root/'run',offline=True)
    return root,report


def test_A20_A21_A22_three_methods_preserve_same_initial_facts(normal):
    root,report=normal
    assert report['verified_jobs']==18 and report['business_stop_events']==0 and report['model_api_calls']==0
    rows=read(root/'run/metrics/rows.json')
    assert all(r['completed'] for r in rows)
    assert all(not r['clean_completed'] and r['new_violation_events']>0 for r in rows if r['negative'])
    plan=read(root/'plan/plan.json');facts={}
    for job in plan['jobs']:
        episode=read(root/'run/episodes'/f"{job['job_id']}.json")
        event=next(e for e in episode['events'] if e.get('context'))
        body=event['context']['request_body']
        assert facts.setdefault(job['task_id'],body)==body
        assert event['bundle']['selectable_candidates']==event['bundle']['physical_candidates']


def test_A27_readonly_replay_does_not_use_key_or_live_model(normal,monkeypatch):
    root,report=normal;before=file_manifest(root/'run')
    def forbidden(*a,**k):raise AssertionError('live path used in replay')
    monkeypatch.setattr('semantic_pallet_planner.jev_select.transport.credential',forbidden)
    monkeypatch.setattr('semantic_pallet_planner.jev_select.transport.JevTransport.complete',forbidden)
    assert replay_experiment_v2(root/'run')==report
    assert file_manifest(root/'run')==before


@pytest.mark.parametrize('scenario,reason',[('invalid_choice','INVALID_RESPONSE'),('timeout','UNKNOWN_IN_FLIGHT'),('http_429','PROVIDER_FAILURE'),('http_529','PROVIDER_FAILURE')])
def test_A14_A26_A30_errors_preserve_all_jobs_no_fallback(tmp_path,scenario,reason):
    prepare_plan_v2(tmp_path/'plan',profile='constructed-eval',methods=('jev_choice',),offline_scenario=scenario)
    report=run_experiment_v2(tmp_path/'plan',tmp_path/'run',offline=True)
    rows=read(tmp_path/'run/metrics/rows.json')
    assert len(rows)==6 and all(r['termination_reason']==reason and r['placed_items']==0 for r in rows)
    assert report['execution_failures']==6 and report['offline_attempts']==6


@pytest.mark.parametrize('target',['mapping','response','business_metric','rule_evaluation','job_registry','checkpoint','timings','budget','plan_role'])
def test_A28_resigned_derived_artifact_tampering_is_rejected(tmp_path,normal,target):
    src,_=normal;root=tmp_path/'run';shutil.copytree(src/'run',root)
    if target=='mapping':
        p=next((root/'mappings').rglob('*.json'));v=read(p);v['display_mapping']['C01']['candidate_id']='forged'
    elif target=='response':
        p=root/'audit/attempts.json';v=read(p);r=v['attempts'][0]
        from semantic_pallet_planner.jev_select.transport import outcome
        body=json.loads(base64.b64decode(r['transport']['raw_body_b64']));body['answers']['next_action']['choice']='C99'
        r['transport']=outcome('OK',canonical(body).encode(),http_status=200);r['transport_digest']=digest(r['transport'])
    elif target=='business_metric':
        p=root/'metrics/rows.json';v=read(p);v[0]['new_violation_events']+=1
    elif target=='rule_evaluation':
        p=next((root/'episodes').glob('*.json'));v=read(p);e=next(e for e in v['events'] if e.get('business_after'))
        e['business_after']['coverage'][0]['checked']+=1
    elif target=='job_registry':
        p=root/'audit/jobs.json';v=read(p);v.pop()
    elif target=='checkpoint':
        p=next((root/'checkpoints').glob('*.json'));v=read(p);v['state']['placed_count']+=1
    elif target=='timings':
        p=root/'metrics/timings.json';v=read(p);v['rows'][0]['phase_totals_s']['selection_s']+=1
    elif target=='budget':
        p=root/'audit/attempts.json';v=read(p);v['budget']['global_attempts']=1
    else:
        p=root/'plan/plan.json';v=read(p);v['role']='formal_test'
    write(p,v)
    if target=='plan_role':write(root/'plan/delivery_manifest.json',file_manifest(root/'plan'))
    write(root/'delivery_manifest.json',file_manifest(root))
    with pytest.raises((ValueError,KeyError)):
        replay_experiment_v2(root)


class PowerLoss(BaseException):pass


def test_A25_A30_commit_checkpoint_resume_and_initial_registry(tmp_path):
    prepare_plan_v2(tmp_path/'plan',profile='constructed-eval',methods=('jev_choice',))
    fired=[]
    def crash(phase,value):
        if phase=='after_commit_checkpoint' and not fired:fired.append(True);raise PowerLoss()
    with pytest.raises(PowerLoss):run_experiment_v2(tmp_path/'plan',tmp_path/'run',offline=True,hook=crash)
    before=read(tmp_path/'run/audit/attempts.json')['attempts'];statuses=read(tmp_path/'run/audit/jobs.json')
    assert len(statuses)==6 and sum(r['status']=='NOT_RUN' for r in statuses)==5
    assert len(before)==1
    report=run_experiment_v2(tmp_path/'plan',tmp_path/'run',offline=True,resume=True)
    after=read(tmp_path/'run/audit/attempts.json')['attempts']
    assert after[0]==before[0] and len({(a['job_id'],a['decision_id']) for a in after})==len(after)
    assert report['verified_jobs']==6


def test_data_freeze_is_independent_of_original_dataset_after_prepare(tmp_path):
    report=prepare_plan_v2(tmp_path/'plan',profile='dataset-dev',dataset_root=DATASET,methods=('shared_geometry',))
    assert report['source_orders']==1 and report['planned_tasks']==2
    assert validate_plan_v2(tmp_path/'plan')==report
    v=read(tmp_path/'plan/plan.json');assert v['role']=='development'
    assert preflight_v2(tmp_path/'plan')['first_physical_candidates']>=1
    assert read(tmp_path/'plan/split_audit.json')['source_groups']==99


def test_formal_scope_contains_all_holdout_groups_and_no_development_rows(tmp_path):
    report=prepare_plan_v2(tmp_path/'plan',profile='dataset-orders',dataset_root=DATASET)
    tasks=read(tmp_path/'plan/private/input_snapshot.json')['tasks']
    assert report['planned_tasks']==80 and report['planned_jobs']==240 and report['source_orders']==39
    assert {t['partition'] for t in tasks}=={'test_id','test_geometry_ood','test_semantic_ood'}
    assert all(len(t['items'])==len(t['provenance']['original_arrival_order']) for t in tasks)


def test_cli_j3_prepare_preflight_and_mode_binding(tmp_path,capsys):
    assert main(['prepare','--profile','dataset-dev','--dataset-root',str(DATASET),'--methods','shared_geometry','--output',str(tmp_path/'plan')])==0
    assert main(['validate-plan','--plan',str(tmp_path/'plan')])==0
    assert main(['preflight','--plan',str(tmp_path/'plan')])==0
    assert 'J3_PREFLIGHT' in capsys.readouterr().out
    with pytest.raises(JevSelectError,match='mode_mismatch'):
        run_experiment_v2(tmp_path/'plan',tmp_path/'run',remote=True)


@pytest.mark.parametrize('rounded_response', [False, True])
def test_A13_A27_A29_native_v2_mixed_methods_no_double_and_usage(tmp_path,monkeypatch,rounded_response):
    import sys
    import math
    calls=[]
    class Response:
        status=200
        def __init__(self,raw):self.raw=raw
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):return self.raw[:limit]
    class Opener:
        def open(self,request,timeout):
            body=json.loads(request.data);calls.append(body)
            assert request.full_url=='https://api.typesafe.ai/v1/systemone'
            labels=body['questions']['next_action']['criteria']
            choice=min(labels,key=lambda l:-labels[l]['features']['geometry_score'])
            answer={'model':body['model'],'answers':{'next_action':{'type':'choice','choice':choice,
                    'probabilities':{l:float(l==choice) for l in labels},'confidence':1.}},'usage':{'input_tokens':100,'output_tokens':12}}
            if rounded_response:
                probabilities={l:round(1/len(labels),2) for l in labels}
                probabilities[choice]=math.nextafter(probabilities[choice],1.)
                answer['answers']['next_action']['probabilities']=probabilities
            return Response(canonical(answer).encode())
    monkeypatch.setattr(urllib.request,'build_opener',lambda *args:Opener())
    monkeypatch.setenv('TYPESAFE_API_KEY','test-native-v2-only-not-real')
    monkeypatch.delitem(sys.modules,'semantic_pallet_planner.jev_select.testing',raising=False)
    prepare_plan_v2(tmp_path/'plan',profile='constructed-eval',mode='remote',api_budget='unlimited')
    report=run_experiment_v2(tmp_path/'plan',tmp_path/'run',remote=True,api_budget='unlimited')
    assert len(calls)==24 and report['model_api_calls']==24 and report['offline_attempts']==0
    assert 'semantic_pallet_planner.jev_select.testing' not in sys.modules
    summary=read(tmp_path/'run/metrics/summary.json')
    assert summary['model_usage']=={'input_tokens':2400,'output_tokens':288}
    assert summary['estimated_model_cost_usd']==pytest.approx(2400*.042/1_000_000)
    before=file_manifest(tmp_path/'run')
    def forbidden(*a,**k):raise AssertionError('replay should not send or read credentials')
    monkeypatch.setattr('semantic_pallet_planner.jev_select.transport.credential',forbidden)
    monkeypatch.setattr('semantic_pallet_planner.jev_select.transport.JevTransport.complete',forbidden)
    assert replay_experiment_v2(tmp_path/'run')==report and file_manifest(tmp_path/'run')==before
    assert len(calls)==24


def test_A25_evaluation_error_is_durable_and_recoverable_without_new_first_call(tmp_path,monkeypatch):
    import semantic_pallet_planner.jev_select.evaluation as evaluation
    prepare_plan_v2(tmp_path/'plan',profile='constructed-eval',methods=('jev_choice',))
    original=evaluation.evaluate_committed_state;fired=[]
    def fail_once(*args,**kwargs):
        if not fired:fired.append(True);raise ValueError('injected transient evaluation error')
        return original(*args,**kwargs)
    monkeypatch.setattr(evaluation,'evaluate_committed_state',fail_once)
    partial=run_experiment_v2(tmp_path/'plan',tmp_path/'run',offline=True)
    assert partial['status']=='NEEDS_RECOVERY'
    first=read(tmp_path/'run/audit/attempts.json')['attempts'][0]
    assert len(read(tmp_path/'run/audit/evaluation_failures.json'))==1
    monkeypatch.setattr(evaluation,'evaluate_committed_state',original)
    report=run_experiment_v2(tmp_path/'plan',tmp_path/'run',offline=True,resume=True)
    assert report['verified_jobs']==6 and read(tmp_path/'run/audit/attempts.json')['attempts'][0]==first
    assert len(read(tmp_path/'run/audit/evaluation_failures.json'))==1
