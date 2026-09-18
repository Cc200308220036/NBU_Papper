import copy
import pytest
from semantic_pallet_planner.planner.constraints import evaluate_pose,commit_candidate,visible_placed
from semantic_pallet_planner.config import generator_config
from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate


def item(identifier='A',dims=(100,100,100),mass=10,stackable=True,cap=100):
    return dict(item_id=identifier,geometry_id="G_TEST",dimensions=list(dims),dimensions_mm=dict(zip(('length','width','height'),dims)),mass_kg=mass,
        stackable=stackable,top_load_limit_kg_synthetic=cap,fragile=False,weight_class='normal',product_category='general',material='Cardboard')


def place(it,placed,cfg,x=0,y=0,z=0,yaw=0):
    l,w=it['dimensions'][:2]
    if yaw:l,w=w,l
    return evaluate_pose(it,placed,x,y,z,l,w,yaw,cfg)


def test_empty_edge_rotation(cfg):
    cfg=generator_config(cfg);a=item(dims=(80,120,100))
    c,err=place(a,[],cfg,x=-600,y=-500,yaw=90)
    assert err is None and c['visible']['oriented_size_mm']==[120,80,100]
    assert c['visible']['pose']==dict(x_mm=-540.0,y_mm=-460.0,z_base_mm=0,yaw_deg=90)
    assert place(a,[],cfg,x=599)[1]=='out_of_bounds'


def test_upper_partial_com_and_collision(cfg):
    cfg=generator_config(cfg);placed=[]
    base,_=place(item(),placed,cfg);commit_candidate(base,placed)
    assert place(item('B'),placed,cfg)[1]=='overlap'
    upper,err=place(item('B'),placed,cfg,x=30,z=100)
    assert err is None and upper['visible']['support']['support_ratio']==.7
    assert place(item('B'),placed,cfg,x=31,z=100)[1]=='insufficient_support'
    # 使用围绕中心空隙的大支撑环验证质心拒绝：支撑面积超过 70%，但质心位于支撑并集之外。
    ring=[]
    for sid,dims,x,y in [('L',(40,100,100),0,0),('R',(40,100,100),60,0)]:
        c,_=place(item(sid,dims),ring,cfg,x=x,y=y);commit_candidate(c,ring)
    assert place(item('B'),ring,cfg,z=100)[1]=='com_outside_support'


def test_nonstackable_and_propagated_overload(cfg):
    cfg=generator_config(cfg);p=[]
    c,_=place(item(stackable=False),p,cfg);commit_candidate(c,p)
    assert place(item('B'),p,cfg,z=100)[1]=='non_stackable_support'
    p=[];c,_=place(item(cap=15),p,cfg);commit_candidate(c,p)
    c,_=place(item('B',mass=10),p,cfg,z=100);commit_candidate(c,p)
    assert p[0]['supported_load_kg']==10
    assert place(item('C',mass=10),p,cfg,z=200)[1]=='overload'
    assert place(item('C',mass=2000),[],cfg)[1]=='over_payload'


def test_independent_counterexamples(cfg):
    cfg=generator_config(cfg);p=[];base,_=place(item(cap=15),p,cfg);commit_candidate(base,p)
    b=item('B');candidate,_=place(b,p,cfg,z=100)
    case=dict(placed_items=visible_placed(p),available_items=[b])
    v=candidate['visible'];sc=dict(container=cfg['container'])
    assert check_candidate(case,sc,v)==[]
    broken=copy.deepcopy(v);broken['pose']['z_base_mm']=0
    assert 'overlap' in check_candidate(case,sc,broken)
    case['placed_items'][0]['stackable']=False
    assert 'non_stackable_support' in check_candidate(case,sc,v)
    case['placed_items'][0]['stackable']=True;case['placed_items'][0]['supported_load_kg']=10
    assert 'overload' in check_candidate(case,sc,v)


def test_oracle_rejects_size_and_yaw_mismatch(repo):
    dc=repo.get_decision_case('DC_00001');s=repo.get_scenario(dc['base_scenario_id'])
    c=repo.get_candidate_set(dc['candidate_set_id'])['candidates'][0]
    c['pose']['yaw_deg']=45
    assert check_candidate(dc,s,c)==['invalid_yaw']
    c['pose']['yaw_deg']=0;c['oriented_size_mm']=[1,1,1]
    assert check_candidate(dc,s,c)==['oriented_size_mismatch']
