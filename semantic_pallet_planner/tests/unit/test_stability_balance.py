"""R01–R10 physical acceptance of the independently versioned P1.1 solver.

References are analytic mass/moment identities and explicit feasible witnesses;
none calls the measured splitter to generate expected physical outcomes.
"""
from dataclasses import asdict, replace
import copy
import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

from semantic_pallet_planner.jev_select.stability import BoxInput, PlacedState
from semantic_pallet_planner.jev_select.stability.balance_adapter import assess_candidate, EquilibriumSpace
from semantic_pallet_planner.jev_select.stability.balance_contracts import BalancedConfig, load_config
from semantic_pallet_planner.jev_select.stability.balance_network import (
    Node, Contact, solve_network, BalanceUnsupported)
from semantic_pallet_planner.jev_select.stability.contracts import digest

C = (1000,800,1000)


def box(name,size=(40,40,100),mass=1,pos=(0,0,0),yaw=0):
    return BoxInput(name,size,mass,pos,yaw)


def fixture_cases():
    tri = ((-100,-80),(100,-80),(0,100))
    asym = ((-120,-60),(100,-60),(20,120))
    square = ((-100,-100),(-100,100),(100,-100),(100,100))
    six = ((-120,-80),(0,-80),(120,-80),(-120,80),(0,80),(120,80))
    line = ((-100,0),(0,0),(100,0))
    def pillars(points):
        return tuple(box('support_'+str(i),pos=(*p,0)) for i,p in enumerate(points))
    ground = box('base',(60,200,100))
    shelf = box('shelf',(240,200,100),4,(0,0,100))
    shared = (ground,shelf,box('left',(40,100,100),1,(-80,0,200)),
              box('right',(40,100,100),1,(80,0,200)))
    return {
        'original_three': (PlacedState(C,pillars(tri)),box('bridge',(260,240,100),3,(0,0,100)),
            'STABLE','analytic center witness: (5/6,5/6,4/3) kg; mass3, world moments(0,0)'),
        'asymmetric_three': (PlacedState(C,pillars(asym)),box('bridge',(300,260,100),7,(10,10,100)),
            'STABLE','unique positive center barycentric witness from independent 3x3 equilibrium equations'),
        'four': (PlacedState(C,pillars(square)),box('bridge',(300,300,100),9,(25,-30,100)),
            'STABLE','positive bilinear witness on square centers for COM(25,-30)'),
        'six': (PlacedState(C,pillars(six)),box('bridge',(340,260,100),11,(10,5,100)),
            'STABLE','positive corner-center bilinear witness, two interior-center supports may carry zero bridge load'),
        'outside_center_hull': (PlacedState(C,pillars(line)),box('bridge',(300,80,100),3,(0,10,100)),
            'STABLE','centers collinear y0, actual rectangle support reaches y20; y10 is inside retained y18'),
        'physical_edge': (PlacedState(C,pillars(line)),box('bridge',(300,80,100),3,(0,20,100)),
            'UNASSESSABLE','physical y20 contact boundary feasible; retained contraction only reaches y18'),
        'hull_edge': (PlacedState(C,pillars(line)),box('bridge',(300,80,100),3,(0,18,100)),
            'UNASSESSABLE','point exactly on retained hull y18; not a physical instability proof'),
        'shared_ancestor': (PlacedState(C,shared),box('top',(240,100,100),20,(0,0,300)),
            'STABLE','symmetric upper loads: shelf+two pillars+top total26kg at x0; one-branch temporary update would cross narrow base'),
        'heterogeneous_shared': (PlacedState(C,(
            box('gleft',(60,160,60),1,(-80,0,0)),box('gright',(60,160,60),1,(80,0,0)),
            box('slab',(240,160,40),2,(0,0,60)),box('cleft',(50,60,50),3,(-70,0,100)),
            box('cright',(50,60,50),5,(70,0,100)))),
            box('top',(200,100,40),4,(20,0,150)),
            'STABLE','total16kg, world moment x=220kg*mm; shared slab carries14kg, never double-counts top4kg'),
        'global_redistribution': (PlacedState(C,(
            box('gleft',(60,200,100),1,(-100,0,0)),
            box('gright',(200,200,100),1,(100,0,0)),
            box('pleft',(140,200,100),1,(-100,0,100)),
            box('pright',(140,200,100),1,(100,0,100)))),
            box('bridge',(140,100,100),4,(20,0,200)),
            'STABLE','feasible witness: left .75kg at x-42, right3.25kg at x111.5/3.25; center-point split1.6/2.4 overloads left moment but is not a global impossibility'),
        'ancestor_heavy': (PlacedState(C,(ground,box('shelf',(200,200,100),1,(0,0,100)))),
            box('top',(100,100,100),10,(60,0,200)),
            'UNSTABLE','upper cut COM=600/11=54.545mm outside physical narrow contact [-30,30]'),
        'ancestor_light': (PlacedState(C,(ground,box('shelf',(200,200,100),1,(0,0,100)))),
            box('top',(100,100,100),.1,(60,0,200)),
            'STABLE','upper cut COM=6/1.1=5.455mm inside support'),
        'single_outside': (PlacedState(C,(box('ground',(100,100,100)),)),
            box('top',(100,100,100),1,(90,0,100)),
            'UNSTABLE','new own center x90 outside only physical contact [40,50]'),
        'two_asymmetric': (PlacedState(C,(box('left',(80,100,100),2,(-100,0,0)),
            box('right',(80,100,100),7,(100,0,0)))),box('bridge',(300,100,100),5,(20,0,100)),
            'STABLE','center reactions (2,3)kg at -100,+100 give bridge moment100kg*mm'),
        'height_mismatch': (PlacedState(C,(box('ground',(100,100,100)),)),
            box('top',(100,100,100),1,(0,0,120)),
            'UNASSESSABLE','drop height100 differs from original120; never move candidate'),
    }


def independently_check(state,candidate,result):
    """Read only input + returned forces, recompute equilibrium without solver helpers."""
    assert result.status=='STABLE'
    diag=result.diagnostics
    reactions=diag['reactions']
    boxes=(*state.placed,candidate)
    expected={b.item_id:b for b in boxes}
    assert all(math.isfinite(r['mass_kg']) and r['mass_kg']>=0 for r in reactions)
    def center(b):
        return (b.bottom_center_mm[0]+C[0]/2,b.bottom_center_mm[1]+C[1]/2)
    for b in boxes:
        outgoing=[r for r in reactions if r['upper']==b.item_id]
        incoming=[r for r in reactions if r['lower']==b.item_id]
        assert sum(r['mass_kg'] for r in outgoing)==pytest.approx(b.mass_kg+sum(r['mass_kg'] for r in incoming),abs=1e-8)
        for d in (0,1):
            left=math.fsum(r['mass_kg']*r['point_mm'][d] for r in outgoing)
            right=b.mass_kg*center(b)[d]+math.fsum(r['mass_kg']*r['point_mm'][d] for r in incoming)
            assert abs(left-right)<1e-6
        for r in outgoing:
            p=r['point_mm']; u=center(b)
            size=b.size_mm
            assert u[0]-size[0]/2-1e-6<=p[0]<=u[0]+size[0]/2+1e-6
            assert u[1]-size[1]/2-1e-6<=p[1]<=u[1]+size[1]/2+1e-6
            if r['lower'] is not None:
                lower=expected[r['lower']]; l=center(lower); s=lower.size_mm
                assert l[0]-s[0]/2-1e-6<=p[0]<=l[0]+s[0]/2+1e-6
                assert l[1]-s[1]/2-1e-6<=p[1]<=l[1]+s[1]/2+1e-6
    ground=[r for r in reactions if r['lower'] is None]
    assert sum(r['mass_kg'] for r in ground)==pytest.approx(sum(b.mass_kg for b in boxes),abs=1e-8)
    for d in (0,1):
        assert abs(math.fsum(r['mass_kg']*r['point_mm'][d] for r in ground)-math.fsum(b.mass_kg*center(b)[d] for b in boxes))<1e-6
    assert diag['global_conservation_checked']


@pytest.mark.parametrize('name',list(fixture_cases()))
def test_physical_fixtures(name):
    state,candidate,expected,_=fixture_cases()[name]
    before=copy.deepcopy((asdict(state),asdict(candidate)))
    result=assess_candidate(state,candidate)
    assert result.status==expected,(name,result.reason_code,result.diagnostics)
    assert (asdict(state),asdict(candidate))==before
    assert result.version=='pct_stability_result_v2'
    assert result.algorithm_identity['algorithm']=='pct_contact_network_v2'
    if expected=='STABLE':independently_check(state,candidate,result)
    if name=='height_mismatch':
        assert 'reactions' not in result.diagnostics
        assert result.diagnostics['evaluated_scope']=='geometry_precheck'
    if name=='shared_ancestor':
        slab=next(n for n in result.diagnostics['nodes'] if n['item_id']=='shelf')
        assert slab['equivalent_mass_kg']==pytest.approx(26)
        assert slab['equivalent_center_xy_mm'][0]==pytest.approx(500,abs=1e-6)
    if name=='heterogeneous_shared':
        slab=next(n for n in result.diagnostics['nodes'] if n['item_id']=='slab')
        assert slab['outgoing_mass_kg']==pytest.approx(14)
    if expected=='UNSTABLE':
        cert=result.diagnostics['infeasibility_certificate']
        assert cert['verified'] and cert['separation_gap']>BalancedConfig().certificate_gap
        assert cert['rhs_dot']<sum(min(v,0) for v in cert['column_projections'])-1e-8


def test_analytic_witness_for_original_and_asymmetric():
    for name,xy,com,mass in [
        ('original_three',[[-100,-80],[100,-80],[0,100]],[0,0],3),
        ('asymmetric_three',[[-120,-60],[100,-60],[20,120]],[10,10],7)]:
        # Analytic statics reference; not a call to any measured splitter.
        a=np.vstack([np.ones(3),np.array(xy).T])
        loads=np.linalg.solve(a,np.r_[mass,mass*np.array(com)])
        assert np.min(loads)>0
        assert abs(sum(loads)-mass)<1e-12
        assert np.max(abs(np.array(xy).T@loads-mass*np.array(com)))<1e-10
        state,candidate,*_=fixture_cases()[name]
        independently_check(state,candidate,assess_candidate(state,candidate))
        if name=='original_three':assert loads==pytest.approx([5/6,5/6,4/3])


def test_analytic_alternative_to_locally_bad_split():
    # Explicit witness chosen without consulting the solver output.
    left_mass,right_mass=.75,3.25
    left_x,right_x=-42,111.5/3.25
    assert left_mass+right_mass==4
    assert left_mass*left_x+right_mass*right_x==pytest.approx(80)
    left_result=(-100+left_mass*left_x)/(1+left_mass)
    right_result=(100+right_mass*right_x)/(1+right_mass)
    assert -127<left_result<-73 and 37<right_result<163
    # The center-point split is one failing selection, not a proof of instability.
    assert (-100+1.6*(-40))/(1+1.6)>-73
    s,c,*_=fixture_cases()['global_redistribution']
    independently_check(s,c,assess_candidate(s,c))


def test_contacts_permutation_and_repeat_exact(monkeypatch):
    import semantic_pallet_planner.jev_select.stability.balance_adapter as adapter
    state,candidate,*_=fixture_cases()['four']
    before=digest(asdict(state))
    def clean(r):
        d=r.to_dict();d.pop('duration_s');return d
    normal=clean(assess_candidate(state,candidate))
    real=adapter.solve_network
    def reverse(nodes,contacts,*a,**kw):return real(nodes,list(reversed(contacts)),*a,**kw)
    monkeypatch.setattr(adapter,'solve_network',reverse)
    assert clean(assess_candidate(state,candidate))==normal
    assert clean(assess_candidate(state,candidate))==normal
    assert digest(asdict(state))==before


def test_candidate_reverse_and_mass_effect():
    state,heavy,*_=fixture_cases()['ancestor_heavy'];light=replace(heavy,mass_kg=.1)
    def evaluate(order):
        out={}
        for b in order:
            d=assess_candidate(state,b).to_dict();d.pop('duration_s');out[b.mass_kg]=d
        return out
    assert evaluate([heavy,light])==evaluate([light,heavy])


@pytest.mark.parametrize('name',['original_three','two_asymmetric','ancestor_light'])
def test_no_legacy_impact_shortcuts(monkeypatch,name):
    from semantic_pallet_planner.jev_select.stability.vendor.pct.space import Box
    def forbidden(*a,**k):raise AssertionError('legacy split must never run')
    monkeypatch.setattr(Box,'calculated_impact',forbidden)
    monkeypatch.setattr(Box,'calculated_impact_virtual',forbidden)
    state,candidate,*_=fixture_cases()[name]
    assert assess_candidate(state,candidate).status=='STABLE'


def test_virtual_and_bypass_paths_rejected():
    space=EquilibriumSpace(*C,holder=2)
    with pytest.raises(BalanceUnsupported,match='VIRTUAL_PATH_UNSUPPORTED'):space.drop_box_virtual(None)
    with pytest.raises(BalanceUnsupported,match='VIRTUAL_PATH_UNSUPPORTED'):space.check_box(0,None,1,True)
    space.pending_id='fixture'
    for flag,setting in [(False,2),(True,1),(False,True)]:
        with pytest.raises(BalanceUnsupported,match='FORBIDDEN_KERNEL_PATH'):
            space.drop_box((10,10,10),(0,0),flag,1,setting)
    for kwargs in [{'setting':2},{'solver_tolerance':1e-5},{'mass_atol_kg':1}]:
        with pytest.raises(ValueError):BalancedConfig(**kwargs)


def test_degenerate_duplicate_and_invalid_topology():
    n=Node('a',1,(0,0,0))
    with pytest.raises(BalanceUnsupported,match='DEGENERATE_CONTACT'):
        solve_network([n],[Contact('a',None,(0,0,0,1))],100)
    with pytest.raises(BalanceUnsupported,match='DUPLICATE_CONTACT'):
        solve_network([n],[Contact('a',None,(-1,-1,1,1))]*2,100)
    with pytest.raises(BalanceUnsupported,match='NON_ACYCLIC'):
        solve_network([n],[Contact('a','a',(-1,-1,1,1))],100)
    r=assess_candidate(PlacedState(C,(box('a'),box('same_center'))),box('top',pos=(0,0,100)))
    assert r.status=='UNASSESSABLE' and r.reason_code=='BASELINE_POSE_HEIGHT_MISMATCH'


@pytest.mark.parametrize('solver_status',[1,3,4])
def test_solver_failure_is_error(monkeypatch,solver_status):
    from scipy.optimize import OptimizeResult
    from semantic_pallet_planner.jev_select.stability import balance_network
    monkeypatch.setattr(balance_network,'linprog',lambda *a,**k:OptimizeResult(status=solver_status,message='injected failure',nit=0))
    r=assess_candidate(PlacedState(C),box('floor'))
    assert r.status=='ERROR' and r.reason_code=='SOLVER_FAILURE:'+str(solver_status)


@pytest.mark.parametrize('fault',['negative','nan','residual'])
def test_solver_success_cannot_hide_bad_reactions(monkeypatch,fault):
    from semantic_pallet_planner.jev_select.stability import balance_network
    real=balance_network.linprog
    def corrupt(*a,**kw):
        r=real(*a,**kw)
        if fault=='negative':r.x[0]=-1e-12
        elif fault=='nan':r.x[0]=float('nan')
        else:r.x[0]+=.01
        return r
    monkeypatch.setattr(balance_network,'linprog',corrupt)
    r=assess_candidate(PlacedState(C),box('floor'))
    assert r.status=='ERROR'
    assert r.diagnostics['solver_phases'][-1]['status']==0
    assert 'raw_solver_vector' in r.diagnostics
    assert r.reason_code=={'negative':'NEGATIVE_REACTION','nan':'NONFINITE_NETWORK','residual':'EQUALITY_RESIDUAL'}[fault]


def test_uncertified_infeasibility_not_unstable(monkeypatch):
    from scipy.optimize import OptimizeResult
    from semantic_pallet_planner.jev_select.stability import balance_network
    real=balance_network.linprog;calls=0
    def false_infeasible(*a,**kw):
        nonlocal calls
        calls+=1
        if calls==1:return OptimizeResult(status=2,message='injected false infeasible',nit=0)
        return real(*a,**kw)
    monkeypatch.setattr(balance_network,'linprog',false_infeasible)
    r=assess_candidate(PlacedState(C),box('floor'))
    assert (r.status,r.reason_code)==('UNASSESSABLE','NETWORK_INFEASIBILITY_UNCERTIFIED')


@pytest.mark.parametrize('bad_mass',[0,-1,float('nan'),float('inf')])
def test_invalid_mass_not_solver_failure(bad_mass):
    r=assess_candidate(PlacedState(C),box('bad',mass=bad_mass))
    assert r.status=='UNASSESSABLE' and r.reason_code=='INVALID_INPUT' and r.kernel_calls==0


def test_baseline_failure_not_candidate_attribution():
    state,candidate,*_=fixture_cases()['ancestor_heavy']
    r=assess_candidate(PlacedState(C,(*state.placed,candidate)),box('later',pos=(-300,0,0)))
    assert r.status=='UNASSESSABLE' and r.reason_code=='BASELINE_UNSTABLE'
    assert r.first_bad_prefix=='top' and r.baseline_status=='UNSTABLE'


def test_v2_schemas_and_frozen_resource():
    from importlib.resources import files
    from jsonschema import Draft202012Validator
    root=files('semantic_pallet_planner.jev_select.stability')
    cfg=json.loads(root.joinpath('configs/pct_contact_network_v2.json').read_text())
    assert cfg==asdict(BalancedConfig())==asdict(load_config())
    for name,value in [('config',cfg),('result',assess_candidate(PlacedState(C),box('floor')).to_dict())]:
        schema=json.loads(root.joinpath(f'schemas/stability_{name}_v2.schema.json').read_text())
        Draft202012Validator.check_schema(schema);Draft202012Validator(schema).validate(value)


@pytest.mark.parametrize('yaw',[0,90])
def test_v2_rotation_pose_mass_and_runtime_ledger(yaw):
    from semantic_pallet_planner.jev_select.stability.geometry import box_from_runtime
    obj={'item_id':'floor','dimensions_mm':{'length':180,'width':70,'height':50},
         'mass_kg':7,'pose':{'x_mm':110,'y_mm':-90,'z_base_mm':0,'yaw_deg':yaw},
         'stackable':False,'current_top_load_kg':999,'top_load_limit_kg_synthetic':0}
    before=copy.deepcopy(obj)
    c=box_from_runtime(obj);state=PlacedState(C)
    r=assess_candidate(state,c)
    independently_check(state,c,r)
    assert obj==before
    assert r.diagnostics['boxes'][0]['mass_kg']==pytest.approx(7)
    assert r.diagnostics['boxes'][0]['center_mm']==pytest.approx([610,310,25])


def test_strict_reaction_boundary_is_explicitly_unassessable():
    # Abstract equilibrium load on a physical rectangle edge: two corner
    # reactions must be zero. This is a selector boundary, not instability.
    n=Node('edge_load',1,(0,0,0))
    r=solve_network([n],[Contact('edge_load',None,(0,-1,2,1))],100)
    assert (r['status'],r['reason_code'])==('UNASSESSABLE','NETWORK_INTERIOR_BOUNDARY')
    assert r['diagnostics']['physical_feasibility_witness']['status']=='FEASIBLE'


def test_v2_holder_limit_is_explicit():
    space=EquilibriumSpace(*C,holder=1);space.pending_id='first'
    assert space.drop_box((10,10,10),(0,0),False,.001,1)
    space.pending_id='second'
    with pytest.raises(BalanceUnsupported,match='HOLDER_CAPACITY_EXCEEDED'):
        space.drop_box((10,10,10),(20,0),False,.001,1)


def test_v2_dynamic_capacity_and_real_commit_order():
    placed=tuple(box(f'floor_{i}',(10,10,10),1,(i*12-360,0,0)) for i in range(61))
    candidate=box('floor_61',(10,10,10),2,(372,0,0));state=PlacedState(C,placed)
    before=digest(asdict(state));r=assess_candidate(state,candidate)
    independently_check(state,candidate,r)
    assert r.kernel_calls==62 and len(r.diagnostics['boxes'])==62
    assert r.diagnostics['restored_order']==[b.item_id for b in (*placed,candidate)]
    assert r.diagnostics['ground_mass_kg']==pytest.approx(63)
    assert digest(asdict(state))==before


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Synthetic v2 physical fixtures only; no orders')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    rows=[]
    for name,(state,candidate,status,basis) in fixture_cases().items():
        r=assess_candidate(state,candidate)
        assert r.status==status,(name,r.reason_code)
        if status=='STABLE':independently_check(state,candidate,r)
        record=dict(fixture=name,origin='CONSTRUCTED_NOT_ORDER',expected_status=status,
            independent_basis=basis,state=asdict(state),candidate=asdict(candidate),result=r.to_dict(),
            independent_physical_checks_passed=status=='STABLE',expectation_matched=True)
        (args.output/f'{name}.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n')
        rows.append(dict(fixture=name,status=r.status,reason=r.reason_code,basis=basis))
    (args.output/'index.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps({'fixtures':len(rows),'all_expectations_matched':True}))
