import base64
import copy
import json
from pathlib import Path
import shutil

import pytest

from semantic_pallet_planner.jev_select.cli import main
from semantic_pallet_planner.jev_select.config import load_config
from semantic_pallet_planner.jev_select.contracts import JevSelectError, canonical, digest
from semantic_pallet_planner.jev_select.episode import run_episode
from semantic_pallet_planner.jev_select.experiment import prepare_plan, run_experiment, file_manifest, validate_plan, InputAdapter
from semantic_pallet_planner.jev_select.ledger import read, write
from semantic_pallet_planner.jev_select.replay import replay_experiment
from semantic_pallet_planner.jev_select.selector import LocalSelector
from semantic_pallet_planner.o4.extensions.e2.data import object_at, policy
from semantic_pallet_planner.o4.fixtures import CONTAINER
from semantic_pallet_planner.o4.extensions.e2.compiler import render_policy


@pytest.fixture(scope='module')
def completed_run(tmp_path_factory):
    base=tmp_path_factory.mktemp('j1-completed')
    prepare_plan(base/'plan')
    report=run_experiment(base/'plan',base/'run',offline=True)
    return base,report


def test_three_methods_same_pool_and_full_denominator(completed_run):
    base,report=completed_run
    assert report['verified_jobs']==18 and report['source_orders']==6 and report['model_api_calls']==0
    assert len(report['groups'])==6
    assert all(g['clean_completed']==4 for g in report['groups'] if g['stratum']=='positive_or_development')
    assert all(g['clean_completed']==0 for g in report['groups'] if g['stratum']=='contradictory_constructed')
    rows=read(base/'run/metrics/rows.json')
    assert len(rows)==18
    assert {r['selector_backend'] for r in rows}=={'jev_choice','shared_geometry','shared_constrained_first'}
    assert all(r['selectable_pool']=='hard_business_feasible' for r in rows)
    assert read(base/'run/metrics/summary.json')['model_usage'] is None


def test_replay_is_read_only_and_resume_of_completed_run_is_noop(completed_run):
    base,report=completed_run
    before=file_manifest(base/'run')
    assert replay_experiment(base/'run')==report
    assert run_experiment(base/'plan',base/'run',offline=True,resume=True)==report
    assert file_manifest(base/'run')==before
    with pytest.raises(JevSelectError,match='network_forbidden'):
        replay_experiment(base/'run',network_allowed=True)


def test_selected_last_option_commits_that_exact_box_and_pose(tmp_path):
    prepare_plan(tmp_path/'plan',methods=('jev_choice',),offline_scenario='pick_last')
    run_experiment(tmp_path/'plan',tmp_path/'run',offline=True)
    result=read(tmp_path/'run/episodes/J0000.json')
    placed=[e for e in result['events'] if e['event']=='PLACE']
    assert placed
    for event in placed:
        label=event['selection']['selected_display_id']
        assert label==sorted(event['context']['criteria'])[-1]
        mapped=event['context']['display_mapping'][label]
        candidate=next(c for c in event['bundle']['selectable_candidates'] if c['candidate_id']==mapped['candidate_id'])
        assert event['action']['candidate_id']==candidate['candidate_id']
        actual=next(o for o in event['after']['placed_items'] if o['item_id']==candidate['pick_item_id'])
        assert actual['pose']==candidate['pose']
        assert actual['oriented_size_mm']==candidate['oriented_size_mm']
    first=placed[0]
    assert first['selection']['selected_candidate_id']!=LocalSelector('shared_geometry').select(
        __import__('semantic_pallet_planner.jev_select.contracts',fromlist=['DecisionContext']).DecisionContext.from_dict(first['context']),
        decision_id=first['decision_id']).data['selected_candidate_id']


@pytest.mark.parametrize('scenario,reason',[('invalid_choice','INVALID_RESPONSE'),('wrong_model','INVALID_RESPONSE'),
    ('wrong_probabilities','INVALID_RESPONSE'),('non_json','INVALID_RESPONSE'),('timeout','UNKNOWN_IN_FLIGHT'),
    ('http_429','PROVIDER_FAILURE'),('http_529','PROVIDER_FAILURE')])
def test_failures_keep_every_order_without_fallback(tmp_path,scenario,reason):
    prepare_plan(tmp_path/'plan',methods=('jev_choice',),offline_scenario=scenario)
    report=run_experiment(tmp_path/'plan',tmp_path/'run',offline=True)
    rows=read(tmp_path/'run/metrics/rows.json')
    assert len(rows)==6 and report['model_api_calls']==0
    assert all(r['termination_reason']==reason and r['placed_items']==0 for r in rows)
    assert len(read(tmp_path/'run/audit/attempts.json')['attempts'])==6
    assert replay_experiment(tmp_path/'run')==report


@pytest.mark.parametrize('global_budget,job_budget,expected_attempts',[(0,32,0),(128,0,0),(1,32,1),(128,1,6)])
def test_global_and_per_job_attempt_budgets_preserve_denominator(tmp_path,global_budget,job_budget,expected_attempts):
    prepare_plan(tmp_path/'plan',methods=('jev_choice',),global_attempts=global_budget,per_job_attempts=job_budget)
    report=run_experiment(tmp_path/'plan',tmp_path/'run',offline=True)
    assert report['verified_jobs']==6 and report['offline_attempts']==expected_attempts
    assert all(r['termination_reason']=='BUDGET_EXHAUSTED' for r in read(tmp_path/'run/metrics/rows.json'))


class PowerLoss(BaseException):pass


@pytest.mark.parametrize('phase',['after_reserve','after_response','before_commit','after_checkpoint'])
def test_resume_no_duplicate_attempt_or_placement(tmp_path,phase):
    prepare_plan(tmp_path/'plan',methods=('jev_choice',))
    fired=[]
    def crash(name,value):
        if name==phase and not fired and (phase!='after_checkpoint' or value['state']['placed_count']==1):
            fired.append(True); raise PowerLoss()
    with pytest.raises(PowerLoss):
        run_experiment(tmp_path/'plan',tmp_path/'run',offline=True,hook=crash)
    before=read(tmp_path/'run/audit/attempts.json')['attempts']
    assert len(before)==1
    first_id=before[0]['attempt_id']; first_did=before[0]['decision_id']
    report=run_experiment(tmp_path/'plan',tmp_path/'run',offline=True,resume=True)
    after=read(tmp_path/'run/audit/attempts.json')['attempts']
    matching=[r for r in after if r['decision_id']==first_did]
    assert len(matching)==1 and matching[0]['attempt_id']==first_id
    first=read(tmp_path/'run/episodes/J0000.json')
    if phase=='after_reserve':
        assert first['summary']['termination_reason']=='UNKNOWN_IN_FLIGHT'
        assert first['summary']['placed_items']==0
        assert matching[0]['state']=='UNKNOWN_IN_FLIGHT'
    else:
        assert matching[0]==before[0]
        assert first['summary']['clean_completed']
        assert len({o['item_id'] for o in first['final_state']['placed_items']})==4
        assert sum(e['event']=='PLACE' for e in first['events'])==4
    assert replay_experiment(tmp_path/'run')==report


@pytest.mark.parametrize('target',['mapping','response','usage','budget','summary','checkpoint','orphan'])
def test_resigned_artifact_tampering_is_detected(tmp_path,completed_run,target):
    base,_=completed_run; root=tmp_path/'run'; shutil.copytree(base/'run',root)
    if target=='mapping':
        path=next((root/'mappings').rglob('*.json')); value=read(path)
        value['display_mapping']['C01']['candidate_id']='forged'
    elif target in ('response','usage','budget','orphan'):
        path=root/'audit/attempts.json'; value=read(path)
        if target=='budget':value['budget']['global_attempts']+=1
        elif target=='orphan':value['attempts'][0]['job_id']='UNKNOWN_JOB'
        else:
            row=value['attempts'][0]; saved=row['transport']
            payload=json.loads(base64.b64decode(saved['raw_body_b64']))
            if target=='response':payload['answers']['next_action']['choice']='C99'
            else:payload['usage']={'input_tokens':1,'output_tokens':0}
            from semantic_pallet_planner.jev_select.transport import outcome
            row['transport']=outcome('OK',canonical(payload).encode(),http_status=200)
            row['transport_digest']=digest(row['transport'])
    elif target=='summary':
        path=root/'metrics/summary.json'; value=read(path); value['planned_jobs']-=1
    else:
        path=root/'checkpoints/J0000.json'; value=read(path); value['state']['placed_count']+=1
    write(path,value)
    write(root/'delivery_manifest.json',file_manifest(root))
    with pytest.raises((JevSelectError,ValueError)):
        replay_experiment(root)


def tiny_task(size=(100,80,100),container_size=(100,80,100)):
    item,attrs=object_at('only',size=size)
    ast=policy([])
    return {'task_id':'tiny','source_order_key':'tiny','source_kind':'constructed','negative':False,
            'container':dict(CONTAINER,length_mm=container_size[0],width_mm=container_size[1],max_height_mm=container_size[2]),
            'items':[item],'attributes':{'only':attrs},'regions':[], 'reference_policy':ast,'instruction_text':render_policy(ast)}


@pytest.mark.parametrize('oversize',[False,True])
def test_singleton_or_empty_pool_never_calls_selector(oversize):
    task=tiny_task(size=(200,200,200) if oversize else (100,80,100))
    class ForbiddenSelector:
        def select(self,*args,**kwargs):raise AssertionError('selector must not be called')
    config=dict(load_config(),buffer_capacity=1)
    result=run_episode(task,ForbiddenSelector(),config,job_id='Jtiny',method='jev_choice')
    assert result['summary']['termination_reason']==('STOP_NO_PHYSICAL_CANDIDATE' if oversize else 'ALL_ITEMS_PLACED')
    if not oversize:
        assert result['summary']['singleton_steps']==1
        selection=next(e['selection'] for e in result['events'] if e['event']=='PLACE')
        assert selection['source']=='singleton' and selection['probabilities'] is None and selection['attempt_ids']==[]


def test_missing_snapshot_and_remote_fail_before_creating_output(tmp_path):
    with pytest.raises(JevSelectError,match='missing_input_snapshot'):
        prepare_plan(tmp_path/'plan',profile='orders',input_snapshot=tmp_path/'missing.json')
    assert not (tmp_path/'plan').exists()
    prepare_plan(tmp_path/'plan',methods=('shared_geometry',))
    with pytest.raises(JevSelectError,match='explicit_execution_mode_required'):
        run_experiment(tmp_path/'plan',tmp_path/'run')
    assert not (tmp_path/'run').exists()
    assert main(['run','--plan',str(tmp_path/'plan'),'--output',str(tmp_path/'run'),'--remote'])==1
    assert not (tmp_path/'run').exists()


def test_cli_prepare_validate_offline_replay(tmp_path,capsys):
    assert main(['prepare','--methods','shared_geometry','--output',str(tmp_path/'plan')])==0
    assert main(['validate-plan','--plan',str(tmp_path/'plan')])==0
    assert main(['run','--plan',str(tmp_path/'plan'),'--output',str(tmp_path/'run'),'--offline'])==0
    assert main(['replay','--experiment',str(tmp_path/'run')])==0
    assert '"model_api_calls": 0' in capsys.readouterr().out


def test_commit_failure_keeps_proposal_and_unchanged_state(monkeypatch):
    from semantic_pallet_planner.o4.common import O4Error
    calls=[]
    def rejected(*args):
        calls.append(True); raise O4Error('physical_rejection','simulated precommit rejection')
    monkeypatch.setattr('semantic_pallet_planner.jev_select.episode.commit',rejected)
    result=run_episode(tiny_task(),LocalSelector('shared_geometry'),dict(load_config(),buffer_capacity=1),job_id='Jtiny',method='shared_geometry')
    event=result['events'][-1]
    assert len(calls)==1 and event['event']=='COMMIT_FAILURE'
    assert event['proposed_action'] is not None and event['action'] is None
    assert event['before']==event['after'] and result['summary']['placed_items']==0
    assert result['summary']['physical_check_failures']==1


def test_explicit_frozen_snapshot_adapter_preserves_arrival_provenance(tmp_path):
    item,attrs=object_at('item0','food')
    items=[]; attributes={}
    for i in range(4):
        obj,att=object_at(f'item{i}','food'); items.append(obj); attributes[obj['item_id']]=att
    snapshot={'data':{'sources':[],'attributes':{}},'scenarios':{}}
    for i in range(12):
        sid=f'S{i:02d}'
        snapshot['data']['sources'].append({'source_order_key':str(i),'scenario_id':sid})
        snapshot['scenarios'][sid]={'container':CONTAINER,'items':items,'arrival_order':['item3','item1','item0','item2']}
        snapshot['data']['attributes'][sid]={'attribute_source':'synthetic','objects':attributes}
    path=tmp_path/'restored.json';write(path,snapshot)
    tasks,provenance,_=InputAdapter().load('orders',path)
    assert len(tasks)==24 and provenance['adapter']=='e5_frozen_snapshot_v1'
    assert [o['item_id'] for o in tasks[0]['items']]==['item3','item1','item0','item2']
    assert tasks[0]['provenance']['source_sha256']==provenance['input_sha256']
    report=prepare_plan(tmp_path/'plan',profile='orders-smoke',input_snapshot=path,methods=('shared_geometry',))
    assert report['planned_tasks']==4 and report['source_orders']==2
    assert validate_plan(tmp_path/'plan')==report
    # The frozen plan remains independent of the external file.
    path.unlink()
    assert validate_plan(tmp_path/'plan')==report
