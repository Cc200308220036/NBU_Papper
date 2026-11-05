"""C persisted smoke/replay coverage; full 144 episodes run by acceptance CLI."""
import copy
from pathlib import Path

import pytest

from semantic_pallet_planner.o4.common import read,write
from semantic_pallet_planner.runners.o4_online import run,replay,seal,delivery_hashes,episode_path,read_jsonl,write_jsonl


@pytest.fixture(scope='module')
def smoke(tmp_path_factory):
    folder=tmp_path_factory.mktemp('o4-c');root=folder/'delivery';protected=folder/'protected.json'
    write(protected,{})
    result=run(root,protection_before=protected,task_limit=2)
    assert result['status']=='PARTIAL' and result['criteria']['C1'] is False
    assert all(v for k,v in result['criteria'].items() if k!='C1')
    return root


def test_smoke_never_claims_full_acceptance_and_replay_is_read_only(smoke):
    before=delivery_hashes(smoke)
    result=replay(smoke)
    assert result['status']=='PASS' and result['read_only']
    assert before==delivery_hashes(smoke)
    report=read(smoke/'offline_acceptance.json')
    assert report['counts']['recorded_episodes']==4
    assert report['deferred']['D']=='NOT_RUN' and report['deferred']['F']=='NOT_RUN'
    assert read(smoke/'audit/network.json')['network_attempts']==0
    assert all(r['detected'] for r in read(smoke/'audit/tamper.json'))


@pytest.mark.parametrize('kind',['AST','action','mapping','summary'])
def test_forged_hash_list_does_not_hide_semantic_or_trajectory_tampering(smoke,kind):
    task=read(smoke/'plan.json')['tasks'][0]
    path=episode_path(smoke,'public_parser',task['task_id']);summary_path=smoke/'metrics/summary.json'
    old=path.read_bytes();summary=summary_path.read_bytes();seal_path=smoke/'delivery_manifest.json';saved_seal=seal_path.read_bytes()
    try:
        if kind=='summary':
            rows=read(summary_path);rows[0]['completed']+=1;write(summary_path,rows)
        else:
            events=read_jsonl(path);event=next(e for e in events if e['response'])
            if kind=='AST':event['response']['policy_ast']['rules']=[]
            elif kind=='action':event['committed_label']='C99'
            else:event['candidate_mapping']['C99']={'fake':True}
            write_jsonl(path,events)
        seal(smoke)
        result=replay(smoke)
        assert result['status']=='FAIL'
        assert any('recomputation' in r or 'episode:' in r or 'repeat evidence' in r for r in result['failures'])
    finally:
        path.write_bytes(old);summary_path.write_bytes(summary);seal_path.write_bytes(saved_seal)


def test_no_overwrite_or_mutation_of_source_paths(smoke,tmp_path):
    from semantic_pallet_planner.config import WORKSPACE
    with pytest.raises(FileExistsError):run(smoke)
    path=WORKSPACE/'semantic_pallet_dataset_v1'/'invalid-o4-c'
    with pytest.raises(ValueError,match='protected'):run(path)
    assert not path.exists()


def test_public_request_tampering_detected(smoke):
    path=next((smoke/'selector_inputs').rglob('*.json'));old=path.read_bytes()
    try:
        req=read(path);req['available_objects'][0]['labels']['max_top_load_kg']=999.;write(path,req)
        assert replay(smoke)['status']=='FAIL'
    finally:path.write_bytes(old)
