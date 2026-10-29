import copy
import json
from pathlib import Path
from collections import defaultdict

import pytest

from semantic_pallet_planner.jev_select.contracts import JevSelectError,canonical
from semantic_pallet_planner.jev_select.dataset import DatasetOrderAdapter,business_spec,attribute_value

ROOT=Path(__file__).resolve().parents[6]/'semantic_pallet_dataset_v1'


@pytest.fixture(scope='module')
def dataset():
    return DatasetOrderAdapter().load(ROOT)


def test_A23_grouped_sources_and_variants_have_honest_denominators(dataset):
    audit=dataset['input_audit']
    assert audit['included_base_scenarios']==100 and audit['source_groups']==99 and audit['derived_tasks']==200
    assert len(audit['excluded_variants'])==40 and audit['cross_partition_source_groups']==0
    parts=defaultdict(set)
    for task in dataset['tasks']:parts[task['source_group_id']].add(task['partition'])
    assert all(len(p)==1 for p in parts.values())
    assert len(parts)==99


def test_full_arrivals_and_physical_attributes_are_preserved(dataset):
    for task in dataset['tasks']:
        original=json.loads((ROOT/'tasks/scenarios'/f"{task['scenario_id']}.json").read_text())
        lookup={o['item_id']:o for o in original['items']}
        assert task['items']==[lookup[i] for i in original['arrival_order']]
        for obj in task['items']:
            assert task['attributes'][obj['item_id']]['physical_top_load_limit_kg']==obj['top_load_limit_kg_synthetic']
        assert task['provenance']['original_instruction']==original['instruction']
        assert task['feasibility_status']=='unknown'


def test_controlled_business_categories_are_explicit_and_consistent(dataset):
    attrs=defaultdict(set)
    for task in dataset['tasks']:
        assert task['business_spec_source']=='public_generated_v1'
        for oid,facts in task['attributes'].items():
            attrs[task['provenance']['article_ids'][oid]].add(canonical({k:v for k,v in facts.items() if k not in ('object_id','physical_top_load_limit_kg')}))
    assert len(attrs)==405 and all(len(v)==1 for v in attrs.values())
    assert set(dataset['input_audit']['synthetic_business_category_counts'])=={'general','electronics','food','glassware','household_cleaner'}
    assert dataset['input_audit']['synthetic_label_counts']['business_no_top_physically_stackable']>0


def tiny_dataset(tmp_path):
    groups=json.loads((ROOT/'splits/group_manifest.json').read_text())
    groups['groups']=[r for r in groups['groups'] if r['scenario_id'] in ('SCN_0001','SCN_0002')]
    (tmp_path/'splits').mkdir();(tmp_path/'splits/group_manifest.json').write_text(json.dumps(groups))
    for folder in ('tasks/scenarios','annotations/ground_truth_rules'):
        (tmp_path/folder).mkdir(parents=True)
        for sid in ('SCN_0001','SCN_0002'):
            (tmp_path/folder/f'{sid}.json').write_bytes((ROOT/folder/f'{sid}.json').read_bytes())
    return tmp_path


def test_A24_private_ground_truth_rules_do_not_define_public_tasks(tmp_path):
    root=tiny_dataset(tmp_path)
    first=DatasetOrderAdapter().load(root)
    path=root/'annotations/ground_truth_rules/SCN_0001.json';data=json.loads(path.read_text())
    data['ground_truth_rules']=[{'secret':'must not reach current public requirements'}];data['reference_feasible_plan_id']='private-answer'
    path.write_text(json.dumps(data))
    changed=DatasetOrderAdapter().load(root)
    assert changed['tasks']==first['tasks']
    assert changed['input_audit']['source_file_manifest']!=first['input_audit']['source_file_manifest']


def test_cross_partition_physical_group_is_rejected_before_models(tmp_path):
    root=tiny_dataset(tmp_path)
    path=root/'splits/group_manifest.json';data=json.loads(path.read_text())
    data['groups'][1]['base_physical_id']=data['groups'][0]['base_physical_id'];path.write_text(json.dumps(data))
    path=root/'annotations/ground_truth_rules/SCN_0002.json';data=json.loads(path.read_text());data['split']='test_id';path.write_text(json.dumps(data))
    with pytest.raises(JevSelectError,match='cross_partition'):DatasetOrderAdapter().load(root)


def test_unfrozen_or_missing_data_inputs_fail(tmp_path):
    with pytest.raises(JevSelectError,match='missing'):DatasetOrderAdapter().load(tmp_path)
    spec=business_spec();spec['no_top_probability']=.9
    with pytest.raises(JevSelectError,match='not_frozen'):DatasetOrderAdapter().load(ROOT,spec_config=spec)
