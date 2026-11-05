import json

import pytest

from semantic_pallet_planner.config import load_config
from semantic_pallet_planner.repository import DatasetRepository
from semantic_pallet_planner.runners.attribute_o3_online import task_plan
from semantic_pallet_planner.runners.layout_ablation import replay, run
from semantic_pallet_planner.vlm.pilot_protocol_v2 import digest


@pytest.fixture(scope='module')
def experiment(tmp_path_factory):
    root=tmp_path_factory.mktemp('layout')/'pilot'
    result=run(root,'train',1,('original','strict_layout'),('safe',))
    assert result['status']=='PASS'
    assert result['episodes']==4
    cfg=load_config(seed=20261015,top_k=16,topk_mode='diverse_v1',fallback_policy='abort')
    repo=DatasetRepository(cfg['dataset'])
    tasks,_=task_plan(repo,'train',1)
    return root,cfg,repo,tasks


def test_replay_detects_summary_tampering(experiment):
    root,cfg,repo,tasks=experiment
    path=root/'episodes/safe/original'/tasks[0]['episode_id']/'episode.json'
    original=path.read_text()
    record=json.loads(original)
    record['summary']['clean_completed']=not record['summary']['clean_completed']
    path.write_text(json.dumps(record))
    try:
        result=replay(root,tasks,('original','strict_layout'),('safe',),cfg,repo)
        assert any(x.endswith(':summary') for x in result['failures'])
    finally:
        path.write_text(original)


def test_replay_recomputes_trace_even_with_updated_event_digest(experiment):
    root,cfg,repo,tasks=experiment
    directory=root/'episodes/safe/strict_layout'/tasks[0]['episode_id']
    path=directory/'steps.jsonl';ep=directory/'episode.json'
    original,old_ep=path.read_text(),ep.read_text()
    events=[json.loads(x) for x in original.splitlines()]
    selected=next(e for e in events if e['committed_label'])
    selected['trace']['baseline_label']='C99'
    record=json.loads(old_ep);record['events_digest']=digest(events)
    path.write_text(''.join(json.dumps(e)+'\n' for e in events));ep.write_text(json.dumps(record))
    try:
        result=replay(root,tasks,('original','strict_layout'),('safe',),cfg,repo)
        assert any(x.endswith(':selection') for x in result['failures'])
    finally:
        path.write_text(original);ep.write_text(old_ep)
