"""Packaging contract acceptance: static only, no model/candidate search/episodes."""
import copy
from pathlib import Path
import shutil
import tempfile

import pytest

from semantic_pallet_planner.jev_select.contracts import JevSelectError, validate_schema
from semantic_pallet_planner.jev_select.dataset import DatasetOrderAdapter
from semantic_pallet_planner.jev_select.dataset_j4 import offline_dataset_guard
from semantic_pallet_planner.jev_select.dataset_packaging import (
    VERSION, build_packaging_dataset, packaging_spec, materialize,
    load_packaging_delivery, static_audits, constructed_checks,
)
from semantic_pallet_planner.jev_select.experiment import file_manifest
from semantic_pallet_planner.jev_select.ledger import read, write

REPO = Path(__file__).resolve().parents[6]


@pytest.fixture(scope='module')
def delivery():
    outputs = REPO/'semantic_pallet_planner/outputs'
    source = outputs/'DATA_JEV_J4_V2_20261101_03'
    assert source.is_dir(), 'requires frozen exposed sources; no silent skip'
    parent = Path(tempfile.mkdtemp(prefix='PACKAGING_CONTRACT_TEST_',dir=outputs))
    target = parent/'delivery'
    from semantic_pallet_planner.jev_select.cli import main
    assert main(['build-packaging-dataset','--repo',str(REPO),'--output',str(target)]) == 0
    yield target
    shutil.rmtree(parent)


def test_constructed_oracle_contract():
    assert all(v=='PASS' for v in constructed_checks().values())


def test_frozen_config_and_closed_schemas(delivery):
    config = packaging_spec()
    with pytest.raises(JevSelectError):validate_schema('packaging_load_config_v1',{**config,'seed':9})
    task = read(next((delivery/'tasks').glob('*.json')))
    for key,value in [('pose',{}),('support_fractions',[]),('current_top_load_kg',0),
                      ('combined_centroid',[]),('stability_result','PASS')]:
        bad = copy.deepcopy(task); bad['items'][0][key]=value
        with pytest.raises(JevSelectError):validate_schema('packaging_load_task_v1',bad)
    for change in ('negative_mass','zero_dimension','false_support_positive_permission','old_rule','unsupported_yaw','feasibility'):
        bad = copy.deepcopy(task);obj=bad['items'][0]
        if change=='negative_mass':obj['mass_kg']=-1
        elif change=='zero_dimension':obj['dimensions_mm']['height']=0
        elif change=='false_support_positive_permission':obj.update(stackable=False,effective_top_permission_kg=3)
        elif change=='old_rule':bad['rules']=[{'type':'region'}]
        elif change=='unsupported_yaw':obj['allowed_yaw_deg']=[0,90,180]
        else:bad['feasibility_status']='FEASIBLE_WITNESS_AVAILABLE'
        with pytest.raises(JevSelectError):validate_schema('packaging_load_task_v1',bad)


def test_formal_entry_and_source_preservation(delivery):
    with offline_dataset_guard() as counters:
        data=DatasetOrderAdapter().load(delivery,spec_config=VERSION)
        again=DatasetOrderAdapter().load(delivery,spec_config=packaging_spec())
        assert data==again and len(data['tasks'])==16
        assert DatasetOrderAdapter().load(delivery,spec_config=delivery/'config.snapshot.json')==data
        assert {t['partition'] for t in data['tasks']}=={'train'}
        assert len({t['source_group_id'] for t in data['tasks']})==4
        assert all(t['feasibility_status']=='UNKNOWN' and not t['rules'] and not t['regions'] for t in data['tasks'])
        assert all(v==0 for v in counters.values())
        for task in data['tasks']:
            assert task['arrival_order']==[o['item_id'] for o in task['items']]
            for obj in task['items']:
                old=obj['original_physical']
                assert obj['mass_kg']==old['mass_kg'] and obj['dimensions_mm']==old['dimensions_mm']
                if task['mode']=='source_preserving':assert all(obj[k]==v for k,v in old.items())
    with pytest.raises(JevSelectError,match='no_runtime_overrides'):
        DatasetOrderAdapter().load(delivery,spec_config=VERSION,difficulty='loose')
    with pytest.raises(JevSelectError):
        DatasetOrderAdapter().load(delivery,spec_config={**packaging_spec(),'seed':3})


def test_sku_consistency_single_factor_and_static_audits(delivery):
    data=load_packaging_delivery(delivery)
    report=static_audits(data,delivery)
    assert len(report['static_conditions'])==16
    assert report['difficulty']['pair_count']==4
    assert report['source_isolation']['source_groups']==4
    identities={}
    for t in data['tasks']:
        for o in t['items']:
            key=(o['sku_id'],o['packaging_profile_id']);value=(o['max_top_load_kg'],o['stackable'])
            assert identities.setdefault(key,value)==value
    bad=copy.deepcopy(data);bad['tasks'][0]['items'][0]['mass_kg']+=1
    with pytest.raises(JevSelectError,match='source_preservation'):static_audits(bad,delivery)
    bad=copy.deepcopy(data);bad['tasks'][0]['container']['max_payload_kg']=1
    with pytest.raises(JevSelectError,match='single_item_payload'):static_audits(bad,delivery)
    bad=copy.deepcopy(data)
    for t in bad['tasks']:
        if t['layer']=='controlled_capacity_tight':t['items'][0]['stackable']=not t['items'][0]['stackable'];break
    with pytest.raises(JevSelectError):static_audits(bad,delivery)


def test_tamper_even_if_manifest_resigned(delivery):
    # Mutations only in a disposable copy of this test's new delivery.
    parent=delivery.parent/'tamper';shutil.copytree(delivery,parent)
    taskpath=next((parent/'tasks').glob('*.json'));original=taskpath.read_bytes()
    task=read(taskpath);task['items'][0]['max_top_load_kg']+=1;write(taskpath,task)
    with pytest.raises(JevSelectError,match='delivery_digest'):load_packaging_delivery(parent)
    write(parent/'delivery_manifest.json',file_manifest(parent))
    with pytest.raises(JevSelectError,match='task_snapshot'):load_packaging_delivery(parent)
    taskpath.write_bytes(original)
    sourcepath=parent/'sources/tasks/scenarios/NEW_00100027.json'
    source=read(sourcepath);source['items'][0]['mass_kg']+=1;write(sourcepath,source)
    write(parent/'delivery_manifest.json',file_manifest(parent))
    with pytest.raises(JevSelectError,match='source_digest'):load_packaging_delivery(parent)


def test_unsafe_output_prevents_mutation(tmp_path):
    with pytest.raises(JevSelectError):build_packaging_dataset(REPO,tmp_path/'not-ignored')
    assert not (tmp_path/'not-ignored').exists()


def test_validation_cli_success_exit(delivery,capsys):
    from semantic_pallet_planner.jev_select.cli import main
    assert main(['validate-packaging-dataset','--dataset',str(delivery)])==0
    assert 'STATIC_CHECKS_COMPLETE' in capsys.readouterr().out
