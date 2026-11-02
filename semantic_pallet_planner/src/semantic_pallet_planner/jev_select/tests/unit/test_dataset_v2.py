"""Targeted v2 engineering checks; no rollout or candidate enumeration."""
import copy
from pathlib import Path
import shutil

import pytest

from semantic_pallet_planner.jev_select.contracts import JevSelectError, validate_schema
from semantic_pallet_planner.jev_select.dataset import (
    DatasetOrderAdapter, business_spec, calibrate_v2, ceil_half, v2_labels, build_business_policy,
)
from semantic_pallet_planner.jev_select.dataset_j4 import (
    V2_SOURCE_PACKAGES, offline_dataset_guard, load_dataset_v2_delivery,
)
from semantic_pallet_planner.jev_select.ledger import read, write
from semantic_pallet_planner.jev_select.experiment import file_manifest

REPO=Path(__file__).resolve().parents[6]


@pytest.fixture
def exposed_sources(tmp_path):
    groups=[]
    for package in V2_SOURCE_PACKAGES:
        src=REPO/'semantic_pallet_planner/outputs'/package/'dataset'
        if not src.is_dir(): pytest.skip('requires archived exposed-train packages')
        for group in read(src/'splits/group_manifest.json')['groups']:
            groups.append(group)
            for name in (f"tasks/scenarios/{group['scenario_id']}.json",f"annotations/ground_truth_rules/{group['scenario_id']}.json"):
                target=tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src/name,target)
    write(tmp_path/'splits/group_manifest.json',{'groups':groups})
    return tmp_path


def test_version_dispatch_and_closed_schema():
    for config in ({'version':'unknown'}, {'version':'public_generated_v3'}, {}):
        with pytest.raises(JevSelectError,match='unknown_business_spec_version'):
            DatasetOrderAdapter().load('/not-read',spec_config=config)
    spec=business_spec('public_generated_v2')
    for bad in ({**spec,'unrecognized':True},{**spec,'attribute_seed':7},
                {k:v for k,v in spec.items() if k!='calibration'}):
        with pytest.raises(JevSelectError): validate_schema('business_spec_v2',bad)


def test_calibration_conflicts_split_without_choosing_a_weight():
    a={'item_id':'a','mass_kg':2.,'dimensions_mm':{'length':10,'width':20,'height':30}}
    b={**a,'item_id':'b','mass_kg':10.}
    tasks=[{'business_configuration':'B1','scenario_id':'one','partition':'train',
            'items':[a,b,{**a,'item_id':'c'}], 'provenance':{'article_ids':{'a':'same','b':'same','c':'same'}}}]
    stats,ids=calibrate_v2(tasks)
    assert stats['physical_product_count']==2 and stats['article_count']==1 and stats['instance_count']==3
    assert stats['m_ref_kg']==8. and stats['instance_weight_q75_kg']==6.
    assert 'same' in stats['conflicts'] and ids['one']['a']==ids['one']['c']!=ids['one']['b']
    with pytest.raises(JevSelectError,match='exposed_train'):
        calibrate_v2([{**tasks[0],'partition':'test_id'}])


def test_rounding_and_nested_difficulty():
    assert ceil_half('1.000')==1. and ceil_half('1.000000000000001')==1.5
    spec=business_spec('public_generated_v2')
    for identity in spec['calibration']['statistics']['members']:
        a,b,c=[v2_labels(spec,identity,n) for n in ('loose','moderate','strict')]
        assert a['max_top_load_kg']>=b['max_top_load_kg']>=c['max_top_load_kg']
        assert a['no_top_load']<=b['no_top_load']<=c['no_top_load']


@pytest.mark.parametrize('difficulty',['loose','moderate','strict'])
def test_override_resolution_including_reinforced_no_top(difficulty):
    from semantic_pallet_planner.o4.normalize import resolve_limits
    spec=business_spec('public_generated_v2'); setting=spec['difficulties'][difficulty]
    policy_spec=business_spec();policy_spec['reinforced_limit_kg']=setting['reinforced_limit_kg']
    ast=build_business_policy(policy_spec,'fixture','B1')
    for nt,reinforced,winner in [(True,True,'no_top'),(False,True,'reinforced'),(False,False,'label')]:
        obj={'object_id':'box','cargo_category':'glassware','packaging':{'reinforced':reinforced},
             'labels':{'no_top_load':nt,'max_top_load_kg':setting['maximum_normal_label_kg']}}
        limits,_,active=resolve_limits([obj],ast)
        assert active['box']==[winner]
        assert limits['box']==(0 if nt else setting['reinforced_limit_kg'] if reinforced else setting['maximum_normal_label_kg'])


def test_v2_load_preserves_v1_and_rejects_source_tamper(exposed_sources):
    with offline_dataset_guard() as counters:
        base=DatasetOrderAdapter().load(exposed_sources)
        assert base==DatasetOrderAdapter().load(exposed_sources,spec_config=business_spec())
        for n in ('loose','moderate','strict'):
            v2=DatasetOrderAdapter().load(exposed_sources,spec_config=business_spec('public_generated_v2'),difficulty=n)
            assert len(v2['tasks'])==8 and len(v2['split_manifest']['groups'])==4
            assert v2['split_manifest']==base['split_manifest']
            for a,b in zip(base['tasks'],v2['tasks']):
                assert a['items']==b['items'] and a['container']==b['container'] and a['provenance']==b['provenance']
        p=exposed_sources/'tasks/scenarios/NEW_00100027.json'
        raw=read(p);raw['items'][0]['mass_kg']+=1;write(p,raw)
        with pytest.raises(JevSelectError,match='source_digest_mismatch'):
            DatasetOrderAdapter().load(exposed_sources,spec_config=business_spec('public_generated_v2'))
        assert counters=={'credential_reads':0,'network_attempts':0}


def test_only_current_public_facts_enter_observation(exposed_sources):
    from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive
    from semantic_pallet_planner.o4.extensions.e2.protocol import observation
    from semantic_pallet_planner.jev_select.context import _public_object
    task=DatasetOrderAdapter().load(exposed_sources,spec_config=business_spec('public_generated_v2'))['tasks'][0]
    first=task['items'][0];state=receive(initial(task['container'],3),first,task['attributes'][first['item_id']])
    obs=observation(state,task['instruction_text'],task['regions'])
    assert len(obs['available_objects'])==1 and not obs['placed_objects']
    assert not any(k in str(obs) for k in ('article_ids','calibration','members','m_ref_kg'))
    current=obs['available_objects'][0]
    public=_public_object({**current,'article_ids':'private','calibration':{'members':'private'}},{current['object_id']:'B01'})
    assert 'article_ids' not in public and 'calibration' not in public


def test_reinforced_business_permission_cannot_override_physical():
    from semantic_pallet_planner.o4.extensions.e2.data import object_at, candidate
    from semantic_pallet_planner.o4.fixtures import CONTAINER
    from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate
    base,_=object_at('base');top,_=object_at('top',mass=3.)
    action=candidate(pick='top',z=100)
    action['support']={'support_item_ids':['base'],'support_ratio':1.0}
    action['resulting_geometry']={'max_height_mm':200,'volume_utilization':2000000/(CONTAINER['length_mm']*CONTAINER['width_mm']*CONTAINER['max_height_mm'])}
    base['top_load_limit_kg_synthetic']=1.
    case={'placed_items':[base],'available_items':[top]}
    assert 'overload' in check_candidate(case,{'container':CONTAINER},action)
    base['top_load_limit_kg_synthetic']=100.;base['stackable']=False
    assert 'non_stackable_support' in check_candidate(case,{'container':CONTAINER},action)


def test_delivery_rejects_tamper_even_with_resigned_manifest(tmp_path):
    # Copy only the small dataset delivery, never touch historical evidence.
    deliveries=sorted((REPO/'semantic_pallet_planner/outputs').glob('DATA_JEV_J4_V2_20261101_*'),reverse=True)
    source=next((p for p in deliveries if (p/'delivery_manifest.json').is_file() and
                 read(p/'business_spec.snapshot.json')==business_spec('public_generated_v2')),None)
    if source is None:pytest.skip('requires current frozen v2 delivery')
    dst=tmp_path/'delivery';shutil.copytree(source,dst)
    assert len(load_dataset_v2_delivery(dst)['tasks'])==24
    tasks=read(dst/'dataset/tasks.json');tasks[0]['attributes'][tasks[0]['items'][0]['item_id']]['labels']['max_top_load_kg']+=.5
    write(dst/'dataset/tasks.json',tasks)
    with pytest.raises(JevSelectError,match='delivery_digest_mismatch'):load_dataset_v2_delivery(dst)
    write(dst/'delivery_manifest.json',file_manifest(dst))
    with pytest.raises(JevSelectError,match='task_snapshot_mismatch'):load_dataset_v2_delivery(dst)
    shutil.copyfile(source/'dataset/tasks.json',dst/'dataset/tasks.json')
    snapshot=read(dst/'business_spec.snapshot.json');snapshot['calibration']['statistics']['m_ref_kg']+=1
    write(dst/'business_spec.snapshot.json',snapshot);write(dst/'delivery_manifest.json',file_manifest(dst))
    with pytest.raises(JevSelectError,match='business_spec_not_frozen'):load_dataset_v2_delivery(dst)


def test_guard_blocks_before_credential_read_and_network():
    import os
    import socket
    with offline_dataset_guard() as counters:
        with pytest.raises(JevSelectError,match='credential_read_forbidden'):Path('/nonexistent/deepseek_api.md').read_text()
        with pytest.raises(JevSelectError,match='credential_environment_forbidden'):os.getenv('DEEPSEEK_API_KEY')
        with pytest.raises(JevSelectError,match='network_forbidden'):socket.getaddrinfo('localhost',1)
        assert counters=={'credential_reads':2,'network_attempts':1}


def test_existing_j4_adapter_entry_receives_v2_difficulty(exposed_sources,tmp_path,monkeypatch):
    from semantic_pallet_planner.jev_select import batch
    from semantic_pallet_planner.jev_select.batch_j4 import prepare_j4
    class Inspected(Exception): pass
    def inspect_scope(tasks,*args):
        assert len(tasks)==8
        assert all(t['business_spec_source']=='public_generated_v2' and t['business_difficulty']=='strict' for t in tasks)
        raise Inspected
    monkeypatch.setattr(batch,'_scope',inspect_scope)
    with offline_dataset_guard() as counts,pytest.raises(Inspected):
        prepare_j4(tmp_path/'not-created',profile='dev',dataset_root=exposed_sources,
            spec_config=business_spec('public_generated_v2'),difficulty='strict',methods=['jev_no_memory'])
    assert counts=={'credential_reads':0,'network_attempts':0}
    assert not (tmp_path/'not-created').exists()


def test_existing_cli_forwards_explicit_v2_parameters(monkeypatch,capsys):
    from semantic_pallet_planner.jev_select import batch_j4,cli
    def prepared(*args,**kwargs):
        assert kwargs['spec_config']=='frozen-v2.json' and kwargs['difficulty']=='moderate'
        return {'status':'PASS','episodes_run':0}
    monkeypatch.setattr(batch_j4,'prepare_j4',prepared)
    with offline_dataset_guard() as counts:
        assert cli.main(['prepare-j4','--profile','dev','--dataset-root','sources','--business-spec','frozen-v2.json',
                         '--difficulty','moderate','--output','not-created'])==0
    assert counts=={'credential_reads':0,'network_attempts':0}
    assert 'PASS' in capsys.readouterr().out
