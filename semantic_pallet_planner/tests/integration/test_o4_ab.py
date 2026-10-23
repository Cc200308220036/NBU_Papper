"""End-to-end A/B derivation, independent audit, replay and tamper detection."""
import json
import socket
from pathlib import Path
import pytest
from semantic_pallet_planner.config import WORKSPACE
from semantic_pallet_planner.o4.common import read,write,digest
from semantic_pallet_planner.o4.dataset import build_data
from semantic_pallet_planner.runners.o4 import run,replay,artifact_hashes

@pytest.fixture(scope='module')
def delivery(tmp_path_factory):
    root=tmp_path_factory.mktemp('o4')/'delivery'
    before=root.parent/'before.json'
    # This suite tests a tiny protection list; the real delivery checks all old files.
    write(before,{})
    with pytest.MonkeyPatch.context() as patch:
        def denied(*a,**kw):raise AssertionError('A/B must not access network')
        patch.setattr(socket,'create_connection',denied)
        acceptance=run(root,protection_before=before)
    assert acceptance['status']=='PASS'
    return root


def test_full_declared_data_counts_and_source_isolation(delivery):
    data=read(delivery/'private/data.json')
    assert len(data['sources'])==len({s['source_order_key'] for s in data['sources']})==12
    assert [s['scenario_id'] for s in data['sources']]==[f'SCN_{i:04d}' for i in range(1,13)]
    assert len(data['pairs'])==144 and len(data['gold'])==36 and len(data['invalid'])==24
    assert len(data['order_tasks'])==72 and all(t['execution_status']=='NOT_RUN' for t in data['order_tasks'])
    assert data['reference_opportunity_pairs']>=6
    assert all(s['role']=='development' for s in data['sources'])


def test_regeneration_determinism(delivery):
    data=read(delivery/'private/data.json')
    assert digest(build_data(WORKSPACE/'semantic_pallet_dataset_v1'))==digest(data)


def test_read_only_replay_and_deferred_statuses(delivery):
    before=artifact_hashes(delivery)
    result=replay(delivery)
    assert result['status']=='PASS' and result['read_only']
    assert artifact_hashes(delivery)==before
    a=read(delivery/'acceptance_report.json')
    assert a['full_o4_status']=='INCOMPLETE' and a['remote_calls']==0
    assert a['criteria']['A5']=='DEFERRED_FORMAL_IMAGES'
    assert 'PENDING' in a['criteria']['A6']
    assert all(a['criteria'][k]=='NOT_RUN' for k in ('C','D','F'))


def test_refuse_overwrite_and_source_dataset_output(delivery,tmp_path):
    with pytest.raises(FileExistsError):run(delivery)
    with pytest.raises(ValueError):run(WORKSPACE/'semantic_pallet_dataset_v1'/'must-not-create')
    assert not (WORKSPACE/'semantic_pallet_dataset_v1'/'must-not-create').exists()

@pytest.mark.parametrize('target',['metrics/fixed.json','metrics/pairs.json','acceptance_report.json','public/O4_ANCHOR_01_0.json','private/data.json'])
def test_saved_ast_state_metrics_and_summary_tampering(delivery,target):
    path=delivery/target;original=path.read_bytes()
    try:
        value=json.loads(original);value['tampered']=True if isinstance(value,dict) else None
    except TypeError:
        value=json.loads(original);value[0]['tampered']=True
    try:
        write(path,value)
        assert replay(delivery)['status']=='FAIL'
    finally:path.write_bytes(original)


def test_recompute_detects_forged_metrics_even_if_delivery_hash_updated(delivery):
    path=delivery/'metrics/fixed.json';manifest=delivery/'delivery_manifest.json'
    original=path.read_bytes();saved=manifest.read_bytes()
    try:
        value=read(path);value[0]['actual']['allowed_ids']=['fabricated']
        write(path,value);write(manifest,{'files':artifact_hashes(delivery)})
        assert 'fixed recomputation' in replay(delivery)['failures']
    finally:path.write_bytes(original);manifest.write_bytes(saved)
