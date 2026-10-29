"""Synthetic repository tests for the full dataset path, never real OOD redesign."""
import copy
import socket
from pathlib import Path
import pytest

from semantic_pallet_planner.o5 import data
from semantic_pallet_planner.o5.common import O5Error, atomic, read, sha


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('offline data audit contacted network'))


def make_repository(root, monkeypatch, ood_count, tie_id=False):
    raw = {}
    for index in range(130+ood_count):
        count = 14+index % 7
        length = (200 if tie_id else 140+index) if index < 130 else 400+index
        raw[f'SRC_{index:03d}'] = {
            'properties': {'order_nr': f'ORDER_{index:03d}', 'id': f'ID_{index:03d}'},
            # Storage order intentionally differs from arrival sequence.
            'item_sequence': {str(i): {'sequence': i+1, 'length/mm': length, 'width/mm': 100,
                                       'height/mm': 20, 'weight/kg': 1.+index/1000}
                              for i in reversed(range(count))}}
    raw['CLONE'] = copy.deepcopy(raw['SRC_004'])
    raw['CLONE']['properties'] = {'order_nr': 'CLONE_ORDER', 'id': 'CLONE_ID'}
    path = root/'raw/bed_bpp/bed-bpp_v1.json'
    atomic(path, raw)
    monkeypatch.setattr(data, 'RAW_SHA', sha(path))
    atomic(root/'semantic_pallet_planner/outputs/DATA_O4_D_RESEARCH_20261024_01/private/source_registry.json',
           [{'source_order_key': 'SRC_001', 'split': 'test'}])
    atomic(root/'semantic_pallet_dataset_v1/annotations/ground_truth_rules/known.json',
           {'source_order_key': 'SRC_000', 'source_sequence_positions': [1, 2, 3, 4]})
    atomic(root/'report/provenance.json', {'source_order_key': 'UNRESOLVED_SOURCE'})
    return raw


def test_full_derivation_preserves_orders_and_excludes_reserved_unknown(tmp_path, monkeypatch):
    root = tmp_path/'repo'
    raw = make_repository(root, monkeypatch, 22)
    dest = tmp_path/'dataset'
    manifest = data.prepare(dest, root=root)
    assert manifest['status'] == 'PASS'
    assert manifest['split_counts'] == {'train': 60, 'development': 20, 'test_id': 40, 'test_geometry_ood': 20}
    selected = []
    for split in manifest['split_counts']:
        tasks = read(dest/f'private/{split}.json')
        assert len(tasks) == manifest['split_counts'][split]
        assert not (dest/f'private/{split}.json').stat().st_mode & 0o222
        for task in tasks:
            key = task['source_order_key']
            assert key not in ('SRC_000', 'SRC_001', 'UNRESOLVED_SOURCE')
            expected = data.sequence(raw[key])
            assert len(task['items']) == len(expected)
            assert task['items'] == [data.item_from_raw(row, i) for i, row in enumerate(expected)]
            ratio = max(max(row['length/mm'], row['width/mm'])/min(row['length/mm'], row['width/mm']) for row in expected)
            assert (ratio > manifest['ood_rule']['threshold']) == (split == 'test_geometry_ood')
            selected.append(task['source_cluster_id'])
    assert len(selected) == len(set(selected)) == 140
    ledger = read(dest/'source_exposure_ledger.json')
    by_key = {r['source_order_key']: r for r in ledger['orders']}
    assert by_key['SRC_000']['status'] == 'EXPOSED'
    assert by_key['SRC_001']['status'] == 'RESERVED'
    assert by_key['CLONE']['source_cluster_id'] == by_key['SRC_004']['source_cluster_id']
    assert ledger['audit']['unresolved_references'][0]['eligible_for_selection'] is False
    assert data.validate_dataset(dest) == manifest
    original = read(dest/'private/development.json')
    original[0]['items'].pop()
    atomic(dest/'private/development.json', original)
    with pytest.raises(O5Error, match='DATASET_CHANGED'):
        data.validate_dataset(dest)


def test_ood_shortfall_keeps_evidence_without_partial_splits(tmp_path, monkeypatch):
    root = tmp_path/'repo'
    make_repository(root, monkeypatch, 4, tie_id=True)
    dest = tmp_path/'blocked'
    manifest = data.prepare(dest, root=root)
    assert manifest['status'] == 'BLOCKED_DATA' and manifest['ood_available'] == 4
    assert manifest['split_counts'] == {} and not (dest/'private').exists()
    assert (dest/'source_exposure_ledger.json').is_file()
    with pytest.raises(O5Error, match='BLOCKED_DATA'):
        data.validate_dataset(dest)


def test_quantile_ties_and_fixed_rank_without_outcomes():
    from semantic_pallet_planner.o5.config import DEFAULT
    rows = [{'source_cluster_id': str(i), 'source_order_key': str(i), 'maximum_planar_aspect_ratio': x}
            for i, x in enumerate([1., 1.5, 2., 2., 3.])]
    rule = data.quantile_rule(rows, DEFAULT)
    assert rule['rank_1_based'] == 4 and rule['threshold'] == 2.
    assert rule['ties_at_boundary'] == 2 and rule['id_pool'] == 4 and rule['ood_pool'] == 1


def test_real_prepare_requires_explicit_rule_freeze(tmp_path):
    with pytest.raises(O5Error, match='OOD_RULE_PLAN_REQUIRED'):
        data.prepare(tmp_path/'unfrozen')
    assert not (tmp_path/'unfrozen').exists()


def test_frozen_rule_tamper_is_rejected(tmp_path, monkeypatch):
    root = tmp_path/'repo'
    make_repository(root, monkeypatch, 22)
    dataset = tmp_path/'data'
    data.prepare(dataset, root=root)
    plan = tmp_path/'rule'
    rule = data.freeze_rule(dataset, plan)
    assert rule['frozen_before_sampling'] and read(plan/'manifest.json')['selected_orders'] == 0
    assert data.validate_rule_plan(plan, read(dataset/'manifest.json')['config']) == rule
    rule['threshold'] += .1
    atomic(plan/'rule.json', rule)
    with pytest.raises(O5Error, match='OOD_RULE_PLAN_CHANGED'):
        data.validate_rule_plan(plan, read(dataset/'manifest.json')['config'])
