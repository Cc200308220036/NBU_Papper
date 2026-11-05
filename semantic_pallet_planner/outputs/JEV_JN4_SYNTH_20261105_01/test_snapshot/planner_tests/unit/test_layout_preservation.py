import copy

import numpy as np
import pytest

from semantic_pallet_planner.evaluation.layout_preservation import layout_features, rectangle_quality
from semantic_pallet_planner.evaluation.policy_v2 import evaluate, optimal_set
from semantic_pallet_planner.selectors.layout_preserving import SOFT_BUDGETS, VARIANTS, select_layout
from semantic_pallet_planner.selectors.policy_executor_v2 import execute_policy


CONTAINER={'length_mm':100,'width_mm':100,'max_height_mm':100,'max_payload_kg':1000}
POLICY={'schema_version':'pallet_policy_v2_pilot','hard_constraints':[],
        'soft_priorities':[{'priority':1,'metric':'heavy_center'},{'priority':2,'metric':'heavy_low'}]}


def item(identifier='current',fragile=False):
    return {'item_id':identifier,'dimensions_mm':{'length':10,'width':10,'height':10},
            'mass_kg':1.,'fragile':fragile,'stackable':True,'weight_class':'heavy',
            'product_category':'general','top_load_limit_kg_synthetic':10.}


def candidate(label,x,z=0,score=.5):
    return {'display_label':label,'pick_item_id':'current',
            'pose':{'x_mm':x,'y_mm':0,'z_base_mm':z,'yaw_deg':0},
            'oriented_size_mm':[10,10,10],'geometry_score':score}


def request(candidates,placed=None):
    return {'container':CONTAINER,'placed_items':placed or [],'available_items':[item()],
            'candidates':candidates}


def test_aspect_sensitive_probe_does_not_confuse_area_with_fit():
    # A long thin strip has ample area but cannot fit the 4x4 probe.
    area,fit=rectangle_quality(np.ones((1,1),dtype=bool),[0,10],[0,2],[(4,4)])
    assert area==20 and fit==0


def test_exposed_capacity_uses_business_limit_and_reconstructed_load():
    p=item('base',True)
    p.update(pose={'x_mm':0,'y_mm':0,'z_base_mm':0,'yaw_deg':0},
             oriented_size_mm=[100,100,10],supported_load_kg=999.)
    policy=copy.deepcopy(POLICY)
    policy['hard_constraints']=[{'type':'fragile_load_limit','selector':{'fragile':True},'threshold_kg':0.}]
    f=layout_features(CONTAINER,[p],policy,1.)
    assert f['capacity']==0
    no_business=layout_features(CONTAINER,[p],POLICY,1.)
    assert no_business['capacity']==1
    assert f['support']>0
    assert f['height']==.9
    f['height']=-1
    assert layout_features(CONTAINER,[p],policy,1.)['height']==.9


@pytest.mark.parametrize('variant',VARIANTS)
def test_hard_feasible_candidate_cannot_be_displaced_by_violating_one(variant):
    base=item('base',True)
    base.update(pose={'x_mm':0,'y_mm':0,'z_base_mm':0,'yaw_deg':0},oriented_size_mm=[10,10,10])
    policy=copy.deepcopy(POLICY)
    policy['hard_constraints']=[{'type':'fragile_load_limit','selector':{'fragile':True},'threshold_kg':0.}]
    req=request([candidate('C01',0,10,1.),candidate('C02',30,0,0.)],[base])
    label,_=select_layout(req,policy,variant,allow_business_violation=True)
    assert label=='C02'


def test_soft_budget_is_per_metric_and_original_anchor_remains_available():
    req=request([candidate('C01',0,0,.1),candidate('C02',10,0,.8),candidate('C03',30,0,1.)])
    label,trace=select_layout(req,POLICY,'relaxed_geometry')
    assert label=='C02'
    assert trace['eligible_labels']==['C01','C02']
    assert trace['baseline_label']=='C01'
    assert trace['soft_loss_from_anchor'][0]<=SOFT_BUDGETS['heavy_center']
    assert trace['soft_loss_from_anchor'][1]<=SOFT_BUDGETS['heavy_low']


def test_strict_layout_never_widens_original_equivalence_set():
    req=request([candidate('C01',10,0,.1),candidate('C02',-10,0,.8),candidate('C03',20,0,1.)])
    label,_=select_layout(req,POLICY,'strict_layout')
    values=[evaluate(req,c,POLICY,CONTAINER) for c in req['candidates']]
    allowed={req['candidates'][i]['display_label'] for i in optimal_set(values)['equivalent_indices']}
    assert label in allowed and 'C03' not in allowed


def test_observation_harm_tiers_precede_all_layout_preferences():
    # Existing fragile business overload: all choices have post violations.
    base=item('base',True)
    base.update(pose={'x_mm':0,'y_mm':0,'z_base_mm':0,'yaw_deg':0},oriented_size_mm=[10,10,10])
    existing=item('existing')
    existing.update(pose={'x_mm':0,'y_mm':0,'z_base_mm':10,'yaw_deg':0},oriented_size_mm=[10,10,10])
    policy=copy.deepcopy(POLICY)
    policy['hard_constraints']=[{'type':'fragile_load_limit','selector':{'fragile':True},'threshold_kg':0.}]
    req=request([candidate('C01',0,20,1.),candidate('C02',30,0,0.)],[base,existing])
    for variant in VARIANTS:
        label,_=select_layout(req,policy,variant,allow_business_violation=True)
        assert label=='C02'
        assert select_layout(req,policy,variant,allow_business_violation=False)[0] is None


def test_original_variant_matches_unmodified_executor():
    req=request([candidate('C01',0),candidate('C02',10,score=1.)])
    assert select_layout(req,POLICY,'original')[0]==execute_policy(req,POLICY)
