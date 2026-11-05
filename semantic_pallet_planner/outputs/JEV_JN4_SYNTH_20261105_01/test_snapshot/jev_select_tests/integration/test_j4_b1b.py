"""Offline engineering fixtures: no real model, training claim or credentials."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

from semantic_pallet_planner.jev_select.batch_j4 import prepare_j4,run_j4,preflight_j4,audit_records_j4,REGISTERED_METHODS,validate_plan_j4
from semantic_pallet_planner.jev_select.config import load_v3_config,config_for_memory
from semantic_pallet_planner.jev_select.contracts import JevSelectError,canonical,digest,DecisionContext
from semantic_pallet_planner.jev_select.memory_store import indexed_snapshot,freeze_snapshot,empty_snapshot,load_snapshot
from semantic_pallet_planner.jev_select.memory_retrieval import retrieve,validate_saved_retrieval
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.tests.unit.test_j4_b1a import card,history


def fixture_memory(output):
    c=card();c['applicability']+=' food container support_ratio mass_kg'
    c['content_digest']=digest({k:c[k] for k in ('applicability','advice','observed_evidence','limitations_counterexamples','evidence_refs','knowledge_role','gates','fixture_only')})
    inactive=[]
    for status in ('candidate','retired','rejected'):
        x=copy.deepcopy(c);x.update(card_id='fixture_'+status,status=status);inactive.append(x)
    rows=[history('Historical fixture: support load container food; negative feedback retained.','fixture_hit'),
          history('support_ratio '+ '负'*540,'fixture_long'),
          history('support_ratio','fixture_false',[{'field':'available_count','op':'gt','value':100}]),
          history('qzxxyy','fixture_zero')]
    s=indexed_snapshot([],cards=[c,*inactive],fixture_only=True,raw_history=rows)
    freeze_snapshot(s,output);return s


def plan(tmp_path,methods=('jev_raw_history','jev_memory_cards'),config=None):
    fixture_memory(tmp_path/'memory')
    prepare_j4(tmp_path/'plan',methods=methods,memory=tmp_path/'memory',task_limit=1,config=config)
    return tmp_path/'plan'


def test_three_arms_same_state_body_and_pool(tmp_path):
    from semantic_pallet_planner.jev_select.tests.unit.test_j4_memory import pipeline
    from semantic_pallet_planner.jev_select.context import ContextBuilder
    s=fixture_memory(tmp_path/'memory');case,policy,bundle,_=pipeline(load_v3_config());values=[]
    for method in ('jev_no_memory','jev_raw_history','jev_memory_cards'):
        memory=empty_snapshot() if method=='jev_no_memory' else s
        cfg=config_for_memory(load_v3_config(),method,memory)
        ctx=ContextBuilder(cfg).build(case['observation'],bundle,policy,memories=memory).data
        assert ctx['local_binding']['method']==method
        texts=ctx['request_body']['state'].pop('memories')
        assert bool(texts)==(method!='jev_no_memory')
        values.append((bundle.data['physical_candidates'],ctx['request_body']))
    assert values[0]==values[1]==values[2]


def test_five_methods_nonempty_records_metrics_viewer(tmp_path,monkeypatch):
    p=plan(tmp_path,REGISTERED_METHODS)
    assert preflight_j4(p)['planned_jobs']==5
    r=run_j4(p,tmp_path/'run',offline=True);assert r['verified_jobs']==5 and r['verified_placements']==20
    summary=read(tmp_path/'run/metrics/summary.json');assert summary['model_api_calls']==0
    assert summary['memory_statistics']['raw_history']['injected_items']>0
    assert summary['memory_statistics']['cards']['injected_items']>0
    assert summary['memory_statistics']['raw_history']['exclusion_reason_counts']['ITEM_TOO_LARGE']>0
    assert summary['memory_statistics']['raw_history']['exclusion_reason_counts']['NOT_APPLICABLE']>0
    assert summary['memory_statistics']['raw_history']['exclusion_reason_counts']['NO_MATCH']>0
    assert (tmp_path/'run/process/index.html').exists()
    html=(tmp_path/'run/process/index.html').read_text();assert 'negative feedback retained' in html and 'mode_index_digest' in html
    monkeypatch.setattr('semantic_pallet_planner.jev_select.episode.decision_inputs',lambda *a,**k:pytest.fail('records replayed'))
    assert audit_records_j4(tmp_path/'run')[0]==r
    assert run_j4(p,tmp_path/'run',offline=True,resume=True)==r
    snapshot=load_snapshot(tmp_path/'memory');assert len(snapshot.data['cards'])==4
    assert len(snapshot.data['index']['modes']['cards']['documents'])==1


CHILD=r'''
import os,sys,json
from pathlib import Path
from semantic_pallet_planner.jev_select.batch_j4 import run_j4
from semantic_pallet_planner.jev_select.testing import OfflineTransport
import semantic_pallet_planner.jev_select.memory_retrieval as retrieval
plan,output,log,phase=sys.argv[1:];path=Path(log)
state=json.loads(path.read_text()) if path.exists() else {'sends':[],'commits':[],'queries':[],'interrupted':False}
def save():path.write_text(json.dumps(state))
original=OfflineTransport.complete
def complete(self,body):
 state['sends'].append(__import__('semantic_pallet_planner.jev_select.contracts',fromlist=['digest']).digest(body));save()
 return original(self,body)
OfflineTransport.complete=complete
original_retrieve=retrieval.retrieve
old_queries=set(state['queries'])
def retrieve(query,*args,**kw):
 assert query['query_digest'] not in old_queries,'re-retrieved a saved decision after restart'
 state['queries'].append(query['query_digest']);save()
 return original_retrieve(query,*args,**kw)
retrieval.retrieve=retrieve
def hook(current,value):
 if current=='after_commit_checkpoint':
  event=value['pending_event'];state['commits'].append(event['decision_id']);save()
 if current==phase and not state['interrupted']:
  state['interrupted']=True;save();os._exit(75)
result=run_j4(plan,output,offline=True,resume=state['interrupted'],hook=hook)
save();print(json.dumps(result))
'''


@pytest.mark.parametrize('method',['jev_raw_history','jev_memory_cards'])
@pytest.mark.parametrize('phase',['after_reserve','after_response','after_commit_checkpoint'])
def test_real_process_restart_no_requery_send_or_duplicate_commit(tmp_path,method,phase):
    p=plan(tmp_path,[method]);args=[sys.executable,'-c',CHILD,str(p),str(tmp_path/'run'),str(tmp_path/'protocol.json'),phase]
    assert subprocess.run(args).returncode==75
    first=read(tmp_path/'protocol.json');assert first['queries']
    assert subprocess.run(args).returncode==0
    log=read(tmp_path/'protocol.json');assert len(log['commits'])==len(set(log['commits']))
    assert len(log['queries'])==len(set(log['queries']))
    attempts=read(tmp_path/'run/audit/attempts.json')['attempts']
    assert len({(a['job_id'],a['decision_id']) for a in attempts})==len(attempts)
    assert len(log['sends'])==(0 if phase=='after_reserve' else len(attempts))
    if phase=='after_reserve':
        assert len(attempts)==1 and attempts[0]['state']=='UNKNOWN_IN_FLIGHT'
        assert read(tmp_path/'run/audit/jobs.json')[0]['status']=='FAILED'
        assert not log['commits']
    else:assert len(log['commits'])==4


def test_nonempty_evaluation_failure_only_completes_evaluation(tmp_path,monkeypatch):
    import semantic_pallet_planner.jev_select.evaluation as ev
    p=plan(tmp_path,['jev_memory_cards']);original=ev.evaluate_committed_state;once=True;commits=[]
    def fail(*a,**k):
        nonlocal once
        if once:once=False;raise ValueError('fixture evaluation interruption')
        return original(*a,**k)
    def hook(phase,event):
        if phase=='after_commit_checkpoint':commits.append(event['pending_event']['decision_id'])
    monkeypatch.setattr(ev,'evaluate_committed_state',fail)
    assert run_j4(p,tmp_path/'run',offline=True,hook=hook)['status']=='NEEDS_RECOVERY'
    cp=read(tmp_path/'run/checkpoints/J0000.json');assert cp['phase']=='COMMITTED'
    assert cp['pending_event']['context']['model_state']['memories']
    monkeypatch.setattr(ev,'evaluate_committed_state',original)
    assert run_j4(p,tmp_path/'run',offline=True,resume=True,hook=hook)['status']=='PASS'
    assert len(commits)==len(set(commits))==4


@pytest.mark.parametrize('target',['query','text','index','mode','checkpoint'])
def test_saved_decision_tampering_refused(tmp_path,target):
    p=plan(tmp_path,['jev_memory_cards'])
    def interrupt(phase,event):
        if phase=='after_response':raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):run_j4(p,tmp_path/'run',offline=True,hook=interrupt)
    sends=len(read(tmp_path/'run/audit/attempts.json')['attempts'])
    cpfile=tmp_path/'run/checkpoints/J0000.json';cp=read(cpfile)
    ctx=cp['pending_event']['context']
    if target=='query':ctx['retrieval']['query']['text']='tampered'
    if target=='text':ctx['model_state']['memories']=['tampered']
    if target=='index':ctx['local_binding']['index_digest']='0'*64
    if target=='mode':ctx['local_binding']['memory_mode']='raw_history'
    if target=='checkpoint':cp['memory_snapshot_digest']='0'*64
    write(cpfile,cp)
    with pytest.raises(JevSelectError):run_j4(p,tmp_path/'run',offline=True,resume=True)
    assert len(read(tmp_path/'run/audit/attempts.json')['attempts'])==sends


def test_library_switch_and_fixture_remote_rejected(tmp_path):
    p=plan(tmp_path,['jev_memory_cards'])
    with pytest.raises(JevSelectError,match='fixture_memory'):prepare_j4(tmp_path/'remote',mode='remote',api_budget=10,memory=tmp_path/'memory',methods=['jev_memory_cards'])
    def interrupt(phase,event):
        if phase=='after_response':raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):run_j4(p,tmp_path/'run',offline=True,hook=interrupt)
    prepare_j4(tmp_path/'other',methods=['jev_memory_cards'],task_limit=1)
    with pytest.raises(JevSelectError,match='identity_changed'):run_j4(tmp_path/'other',tmp_path/'run',offline=True,resume=True)


def test_full_request_budget_failure_keeps_context_candidates(tmp_path):
    cfg=dict(load_v3_config(),max_request_bytes=4096)
    p=plan(tmp_path,['jev_raw_history'],config=cfg);r=run_j4(p,tmp_path/'run',offline=True)
    assert r['verified_jobs']==1
    e=read(tmp_path/'run/episodes/J0000.json');assert e['summary']['termination_reason']=='MEMORY_CONTEXT_TOO_LARGE'
    assert e['events'][-1]['context']['criteria'] and e['events'][-1]['bundle']['physical_candidates']
    assert not read(tmp_path/'run/audit/attempts.json')['attempts']
    assert read(tmp_path/'run/audit/jobs.json')[0]['status']=='FAILED'


def test_empty_memory_runs_both_arms(tmp_path):
    prepare_j4(tmp_path/'plan',methods=['jev_raw_history','jev_memory_cards'],task_limit=1)
    assert run_j4(tmp_path/'plan',tmp_path/'run',offline=True)['verified_placements']==8
    assert all(not e['context']['model_state']['memories'] for p in (tmp_path/'run/episodes').glob('*.json') for e in read(p)['events'] if e.get('context'))


@pytest.mark.parametrize('method',['jev_raw_history','jev_memory_cards'])
@pytest.mark.parametrize('empty',[False,True])
def test_nonempty_singleton_empty_and_unknown_bypass_selector(tmp_path,method,empty):
    from semantic_pallet_planner.jev_select.tests.unit.test_j3_core import task_with_region
    from semantic_pallet_planner.jev_select.episode import run_episode
    class Forbidden:
        def select(self,*a,**k):raise AssertionError('must bypass selector')
    c=card();c['gates']=[{'field':'min_support_ratio','op':'ge','value':0}]
    c['content_digest']=digest({k:c[k] for k in ('applicability','advice','observed_evidence','limitations_counterexamples','evidence_refs','knowledge_role','gates','fixture_only')})
    s=indexed_snapshot([],cards=[c],fixture_only=True,raw_history=[history('container support_ratio','fixture_unknown',[{'field':'min_support_ratio','op':'ge','value':0}])])
    task=task_with_region(1,tiny_container=True)
    if empty:task['items'][0]['dimensions_mm']['length']=500
    cfg=config_for_memory(load_v3_config(),method,s)
    ep=run_episode(task,Forbidden(),cfg,job_id='FIXTURE_ROUTE',method=method,memory_snapshot=s)
    ctx=next(e['context'] for e in ep['events'] if e.get('context'))
    assert ep['summary']['placed_items']==(0 if empty else 1)
    if empty:assert ctx['retrieval']['exclusions'][0]['reason']=='APPLICABILITY_UNKNOWN'
    else:assert next(e for e in ep['events'] if e['event']=='PLACE')['selection']['source']=='singleton'


def test_nonempty_global_no_match(tmp_path):
    c=card()
    for key in ('applicability','advice','observed_evidence','limitations_counterexamples'):c[key]='qzxxyy'
    c['content_digest']=digest({k:c[k] for k in ('applicability','advice','observed_evidence','limitations_counterexamples','evidence_refs','knowledge_role','gates','fixture_only')})
    freeze_snapshot(indexed_snapshot([],cards=[c],fixture_only=True,raw_history=[history('qzxxyy')]),tmp_path/'memory')
    prepare_j4(tmp_path/'plan',methods=['jev_raw_history','jev_memory_cards'],memory=tmp_path/'memory',task_limit=1)
    assert run_j4(tmp_path/'plan',tmp_path/'run',offline=True)['verified_placements']==8
    assert all(e['context']['retrieval']['status']=='NO_MATCH' for p in (tmp_path/'run/episodes').glob('*.json') for e in read(p)['events'] if e.get('context'))


def test_no_production_activation_relaxation():
    c=card();c['evidence_refs']=c['evidence_refs'][:1]
    c['content_digest']=digest({k:c[k] for k in ('applicability','advice','observed_evidence','limitations_counterexamples','evidence_refs','knowledge_role','gates','fixture_only')})
    with pytest.raises(JevSelectError,match='not_eligible'):indexed_snapshot([],cards=[c],fixture_only=True)


def test_offline_entrypoints_no_credentials_or_network(tmp_path):
    # Guard before fresh production-module import, then exercise all local flows.
    script=r'''
import builtins,pathlib,socket,os,sys
original=builtins.open;original_path=pathlib.Path.open;original_env=os._Environ.__getitem__
def check(path):
 if any(x in pathlib.Path(path).name.lower() for x in ('api_key','credential','typesafe','.env')):raise AssertionError('credential read')
def guarded(path,*a,**k):check(path);return original(path,*a,**k)
def guarded_path(path,*a,**k):check(path);return original_path(path,*a,**k)
def guarded_env(self,key):
 if any(x in str(key).lower() for x in ('api_key','credential','token','secret')):raise AssertionError('credential environment read')
 return original_env(self,key)
def blocked(*a,**k):raise AssertionError('network use')
class OfflineSocket(socket.socket):
 def connect(self,*a,**k):blocked()
 def connect_ex(self,*a,**k):blocked()
 def sendto(self,*a,**k):blocked()
builtins.open=guarded;pathlib.Path.open=guarded_path;os._Environ.__getitem__=guarded_env
socket.socket=OfflineSocket;socket.create_connection=blocked
from semantic_pallet_planner.jev_select.batch_j4 import prepare_j4,preflight_j4,run_j4,audit_records_j4,REGISTERED_METHODS
from semantic_pallet_planner.jev_select.diagnostics import inspect_experiment
from semantic_pallet_planner.jev_select.experiment import validate_plan
root=pathlib.Path(sys.argv[1])
prepare_j4(root/'plan',methods=REGISTERED_METHODS,memory=sys.argv[2],task_limit=1)
preflight_j4(root/'plan');validate_plan(root/'plan')
run_j4(root/'plan',root/'run',offline=True);audit_records_j4(root/'run')
inspect_experiment(root/'run',root/'inspect')
'''
    fixture_memory(tmp_path/'memory')
    subprocess.run([sys.executable,'-c',script,str(tmp_path/'guarded'),str(tmp_path/'memory')],check=True)


def test_runtime_total_budget_exclusion(tmp_path):
    rows=[history('support_ratio '+c*1585,'fixture_budget_'+c) for c in ('a','b','c')]
    freeze_snapshot(indexed_snapshot([],fixture_only=True,raw_history=rows),tmp_path/'memory')
    prepare_j4(tmp_path/'plan',methods=['jev_raw_history'],memory=tmp_path/'memory',task_limit=1)
    assert run_j4(tmp_path/'plan',tmp_path/'run',offline=True)['verified_placements']==4
    m=read(tmp_path/'run/metrics/summary.json')['memory_statistics']['raw_history']
    assert m['exclusion_reason_counts']['TOTAL_BUDGET']>0
    for e in read(tmp_path/'run/episodes/J0000.json')['events']:
        if e.get('context'):assert e['context']['retrieval']['utf8_bytes']<=4800


def test_remote_selector_rejects_fixture_before_transport(tmp_path):
    from semantic_pallet_planner.jev_select.tests.unit.test_j4_memory import pipeline
    from semantic_pallet_planner.jev_select.context import ContextBuilder
    from semantic_pallet_planner.jev_select.selector import JevSelector,bind_decision
    from semantic_pallet_planner.jev_select.ledger import Ledger
    s=fixture_memory(tmp_path/'memory');case,policy,bundle,_=pipeline(load_v3_config())
    cfg=config_for_memory(load_v3_config(),'jev_memory_cards',s)
    ctx=bind_decision(ContextBuilder(cfg).build(case['observation'],bundle,policy,memories=s),'FIXTURE','D0000')
    class ForbiddenRemote:
        origin='jev'
        def complete(self,*a,**k):raise AssertionError('credential/network path reached')
    (tmp_path/'ledger').mkdir();ledger=Ledger(tmp_path/'ledger',{'global_attempts':10,'per_job_attempts':10})
    with pytest.raises(JevSelectError,match='fixture_memory'):JevSelector(cfg,ledger,'FIXTURE',ForbiddenRemote()).select(ctx,decision_id='D0000')
    assert ledger.data['attempts']==[]


def test_single_source_candidate_and_retired_parent_remain_immutable(tmp_path):
    candidate=card();candidate.update(card_id='fixture_single_source',status='candidate')
    candidate['evidence_refs']=candidate['evidence_refs'][:1]
    candidate['content_digest']=digest({k:candidate[k] for k in ('applicability','advice','observed_evidence','limitations_counterexamples','evidence_refs','knowledge_role','gates','fixture_only')})
    retired=card();retired.update(card_id='fixture_retired_parent',status='retired')
    active=card();active.update(card_id='fixture_child',card_version=2,parent_card_ids=[retired['card_id']])
    snapshot=indexed_snapshot([],cards=[candidate,retired,active],fixture_only=True)
    freeze_snapshot(snapshot,tmp_path/'frozen')
    loaded=load_snapshot(tmp_path/'frozen');assert loaded.data['cards']==snapshot.data['cards']
    assert {d['document_id'] for d in loaded.data['index']['modes']['cards']['documents']}=={'fixture_child'}
    assert next(c for c in loaded.data['cards'] if c['card_id']=='fixture_single_source')['status']=='candidate'
    assert next(c for c in loaded.data['cards'] if c['status']=='retired')['advice']==retired['advice']
