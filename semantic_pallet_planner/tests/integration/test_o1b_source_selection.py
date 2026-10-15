from semantic_pallet_planner.config import load_config
from semantic_pallet_planner.repository import DatasetRepository
from semantic_pallet_planner.runners.attribute_o1b import source_selection


def test_o1b_source_selection_is_disjoint_from_prior_development_and_test():
    repo=DatasetRepository(load_config()['dataset'])
    selected,audit=source_selection(repo)
    assert len(selected)==30
    assert len({source for source,_ in selected})==30
    assert all(len(cases)==3 for _,cases in selected)
    assert audit['overlap_v2_pilot']==[]
    assert audit['overlap_o2a']==[]
    assert audit['overlap_all_test_splits']==[]
    assert audit['test_labels_used_for_selection'] is False
