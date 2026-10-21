"""Ranking precision must not change hard tiers or original budget admissibility."""
import math
import copy
from pathlib import Path
import json

import pytest

from semantic_pallet_planner.selectors import layout_preserving_v2 as stable
from semantic_pallet_planner.selectors.layout_preserving import select_layout as legacy
from semantic_pallet_planner.selectors.instruction_parser_o1b import resolved_public_policy


def test_fsum_recovers_stored_roundoff_case():
    f = dict(support=.4833333333333333, capacity=.06120739456961294, height=.7176470588235294)
    assert stable.layout_score(f) == math.fsum(f.values())/3


def test_max_anchored_ties_are_not_pairwise_transitive():
    # A near B, B near C does not make C near the actual best A.
    scores = [1., 1.-.75e-12, 1.-1.5e-12]
    assert stable.stable_best(range(3), scores.__getitem__) == [0, 1]
    assert stable.stable_best([2, 1, 0], scores.__getitem__) == [1, 0]


def test_clear_score_difference_not_erased():
    assert stable.stable_best([0, 1], lambda i: [0., 1e-8][i]) == [1]


@pytest.mark.parametrize('values', [[], [math.nan], [math.inf], [-math.inf]])
def test_nonfinite_or_empty_rank_fails(values):
    with pytest.raises(ValueError):
        stable.stable_best(range(len(values)), values.__getitem__)


@pytest.fixture
def public_case():
    path = Path(__file__).resolve().parents[2]/'outputs/EXP_OPT_O3_LAYOUT_VALIDATION_20261019_01/episodes/safe/relaxed_wo_floor/O3_SCN_0053_P0/steps.jsonl'
    return json.loads(path.read_text().splitlines()[4])['request']


def test_original_control_unchanged(public_case):
    policy = resolved_public_policy(public_case['instruction_text'], public_case)
    assert stable.select_layout(public_case, policy, 'original')[0] == legacy(public_case, policy, 'original')[0]


def test_both_tie_tiers_use_frozen_epsilon_and_label_order(public_case, monkeypatch):
    policy = resolved_public_policy(public_case['instruction_text'], public_case)
    monkeypatch.setattr(stable, 'layout_features', lambda *args: dict(support=.5, capacity=.5, height=.5))
    for c in public_case['candidates']:
        c['geometry_score'] = 1.+int(c['display_label'][1:])*1e-15
    label, trace = stable.select_layout(public_case, policy, 'relaxed_wo_floor')
    assert label == min(trace['eligible_labels'])
    assert set(trace['geometry_tie_labels']) == set(trace['layout_tie_labels'])
    public_case['candidates'].reverse()
    assert stable.select_layout(public_case, policy, 'relaxed_wo_floor')[0] == label


@pytest.mark.parametrize('variant', ['relaxed_geometry', 'relaxed_wo_floor'])
def test_original_hard_pool_and_soft_budget_preserved(public_case, variant):
    policy = resolved_public_policy(public_case['instruction_text'], public_case)
    from semantic_pallet_planner.evaluation.policy_v2 import evaluate, EPS
    _, old = legacy(public_case, policy, variant)
    label, new = stable.select_layout(public_case, policy, variant)
    assert new['baseline_label'] == old['baseline_label']
    assert new['eligible_labels'] == old['eligible_labels']
    picked = next(c for c in public_case['candidates'] if c['display_label'] == label)
    assert not evaluate(public_case, picked, policy, public_case['container'])['after_violation_instances']
    assert all(loss is None or loss <= stable.SOFT_BUDGETS[p['metric']]+EPS for loss, p in
               zip(new['soft_loss_from_anchor'], policy['soft_priorities']))


def test_invalid_variant_rejected(public_case):
    with pytest.raises(ValueError):
        stable.select_layout(public_case, {}, 'relaxed_full')


@pytest.mark.parametrize('variant', stable.VARIANTS)
@pytest.mark.parametrize('existing_overload', [False, True])
def test_hard_and_minimum_harm_tiers_cannot_be_bought_by_score(variant, existing_overload):
    container = dict(length_mm=100, width_mm=100, max_height_mm=100, max_payload_kg=1000)
    def item(name, fragile=False):
        return dict(item_id=name, dimensions_mm=dict(length=10, width=10, height=10),
                    mass_kg=1., fragile=fragile, stackable=True, weight_class='heavy',
                    product_category='general', top_load_limit_kg_synthetic=10.)
    base = item('base', True)
    base.update(pose=dict(x_mm=0, y_mm=0, z_base_mm=0, yaw_deg=0), oriented_size_mm=[10,10,10])
    placed = [base]
    if existing_overload:
        old = item('old')
        old.update(pose=dict(x_mm=0, y_mm=0, z_base_mm=10, yaw_deg=0), oriented_size_mm=[10,10,10])
        placed.append(old)
    candidates = [dict(display_label=label, pick_item_id='current',
        pose=dict(x_mm=x, y_mm=0, z_base_mm=z, yaw_deg=0), oriented_size_mm=[10,10,10], geometry_score=score)
        for label, x, z, score in [('C01',0,20 if existing_overload else 10,1.),('C02',30,0,0.)]]
    req = dict(container=container, placed_items=placed, available_items=[item('current')], candidates=candidates)
    policy = dict(schema_version='pallet_policy_v2_pilot',
        hard_constraints=[dict(type='fragile_load_limit', selector=dict(fragile=True), threshold_kg=0.)],
        soft_priorities=[dict(priority=1,metric='heavy_center'),dict(priority=2,metric='heavy_low')])
    assert stable.select_layout(req, policy, variant, allow_business_violation=True)[0] == 'C02'
    if existing_overload:
        assert stable.select_layout(req, policy, variant, allow_business_violation=False)[0] is None
