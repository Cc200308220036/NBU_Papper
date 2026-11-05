import copy
import json
import pytest
from semantic_pallet_planner.jev_select.config import load_v2_config, load_v3_config, generator_config
from semantic_pallet_planner.jev_select.contracts import MemorySnapshot, DecisionContext, JevSelectError, digest, validate_schema
from semantic_pallet_planner.jev_select.memory_store import empty_snapshot, freeze_snapshot, load_snapshot, MemoryStore
from semantic_pallet_planner.jev_select.candidates import CandidateProvider, PublicBusinessGuard
from semantic_pallet_planner.jev_select.context import ContextBuilder, validate_context
from semantic_pallet_planner.jev_select.episode import run_episode
from semantic_pallet_planner.jev_select.experiment import constructed_cases, InputAdapter
from semantic_pallet_planner.jev_select.selector import LocalSelector
from semantic_pallet_planner.jev_select.memory_export import export_completed_episode


def pipeline(cfg):
    case=constructed_cases()[0];g=PublicBusinessGuard();req=case['observation'];policy=g.resolve(req)
    b=CandidateProvider().build(case['state'],req,generator_config(),config=cfg)
    b=g.filter(req,policy,b,cfg)
    return case,policy,b,ContextBuilder(cfg).build(req,b,policy)


def test_dispatch_and_legacy_rejection():
    assert load_v3_config()['memory_snapshot_digest']==digest(empty_snapshot().data)
    cfg=load_v2_config();case,p,b,c=pipeline(cfg)
    with pytest.raises(JevSelectError,match='memory_not_implemented'):ContextBuilder(cfg).build(case['observation'],b,p,memories=empty_snapshot())
    with pytest.raises(JevSelectError):validate_schema('config',dict(load_v3_config(),version='jev_direct_choice_v4'))
    with pytest.raises(JevSelectError):validate_schema('config',dict(cfg,memory_mode='cards'))


def test_five_methods_preserve_pool_and_body():
    values=[]
    for method,mode in [('shared_geometry','none'),('shared_business_lexicographic','none'),('jev_no_memory','none'),('jev_raw_history','raw_history'),('jev_memory_cards','cards')]:
        case,p,b,c=pipeline(dict(load_v3_config(),selector=method,memory_mode=mode))
        assert b.data['physical_candidates']==b.data['selectable_candidates']
        values.append((b.data['physical_candidates'],c.data['request_body']))
    assert all(x==values[0] for x in values)


@pytest.mark.parametrize('field',['memory_snapshot_digest','corpus_digest','query_digest','retrieval_digest','injected_text_digest'])
def test_binding_tampering(field):
    cfg=load_v3_config();case,p,b,c=pipeline(cfg);v=c.data;v['local_binding'][field]='0'*64
    with pytest.raises(JevSelectError):validate_context(DecisionContext.from_dict(v),case['observation'],b,cfg)


def test_snapshot_integrity_fixture_and_existing(tmp_path):
    freeze_snapshot(empty_snapshot(),tmp_path/'frozen');assert load_snapshot(tmp_path/'frozen').data==empty_snapshot().data
    with pytest.raises(JevSelectError):freeze_snapshot(empty_snapshot(),tmp_path/'frozen')
    v=empty_snapshot().data;v['fixture_only']=True;freeze_snapshot(MemorySnapshot.from_dict(v),tmp_path/'fixture')
    with pytest.raises(JevSelectError,match='fixture_memory'):load_snapshot(tmp_path/'fixture',remote=True)
    p=tmp_path/'frozen/snapshot.json';v=json.loads(p.read_text());v['corpus_digest']='1'*64;p.write_text(json.dumps(v))
    with pytest.raises(JevSelectError,match='memory_files_changed'):load_snapshot(tmp_path/'frozen')


@pytest.fixture(scope='module')
def training_episode():
    cfg=dict(load_v3_config(),selector='shared_geometry');t=InputAdapter().load('constructed-smoke')[0][0];t['partition']='train'
    ep=run_episode(t,LocalSelector('shared_geometry'),cfg,job_id='TRAIN_FIXTURE',method='shared_geometry')
    ep['summary']['selector_backend']='jev_no_memory'
    # In-memory protocol fixture only; never enters a sealed production corpus.
    for e in ep['events']:
        if e['event']=='PLACE':e['selection']['source']='jev'
    return ep


def manifest(ep):return {'source_groups':[ep['summary']['source_order_key']],'source_code_digest':'1'*64,'episodes':{ep['job_id']:{'episode_digest':digest(ep),'source_code_digest':'1'*64,'fixture_only':False}}}


def test_export_whitelist_and_idempotence(training_episode,tmp_path):
    ep=training_episode;export=export_completed_episode(ep,manifest(ep));changed=copy.deepcopy(ep)
    changed['private_reference']={'policy_ast':'secret'};changed['future_items']=['never visible']
    assert export_completed_episode(changed,manifest(changed))==export
    assert 'policy_ast' not in json.dumps(export) and 'never visible' not in json.dumps(export)
    store=MemoryStore(tmp_path/'store');assert store.ingest(export)['status']=='INGESTED';assert store.ingest(export)['status']=='ALREADY_INGESTED'
    store.freeze_snapshot(tmp_path/'snapshot');assert load_snapshot(tmp_path/'snapshot').data['corpus_digest']==digest([digest(export)])
    with pytest.raises(JevSelectError,match='readonly'):MemoryStore(tmp_path/'snapshot').ingest(export)


@pytest.mark.parametrize('mutation',['nontrain','unevaluated','unbound','code','fixture','teacher'])
def test_export_rejects_invalid_evidence(training_episode,mutation):
    ep=copy.deepcopy(training_episode);m=manifest(ep)
    if mutation=='nontrain':ep['summary']['partition']='validation'
    if mutation=='unevaluated':ep['checkpoint']['phase']='COMMITTED'
    if mutation=='unbound':m['episodes'][ep['job_id']]['episode_digest']='0'*64
    if mutation=='code':m['episodes'][ep['job_id']]['source_code_digest']='0'*64
    if mutation=='fixture':m['episodes'][ep['job_id']]['fixture_only']=True
    if mutation=='teacher':ep['summary']['selector_backend']='shared_business_lexicographic';m=manifest(ep)
    with pytest.raises(JevSelectError):export_completed_episode(ep,m)
