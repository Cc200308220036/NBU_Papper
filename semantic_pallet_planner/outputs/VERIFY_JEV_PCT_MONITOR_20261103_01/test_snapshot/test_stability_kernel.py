"""Synthetic fixtures; expected physics chosen before running PCT. No orders."""
from dataclasses import asdict, replace
import copy
import json
from importlib.resources import files
import subprocess
import sys

import pytest

from semantic_pallet_planner.jev_select.stability import (
    BoxInput, PlacedState, StabilityConfig, assess_candidate)
from semantic_pallet_planner.jev_select.stability.contracts import digest
from semantic_pallet_planner.jev_select.stability.geometry import (
    to_kernel, from_corner, box_from_runtime, state_from_runtime)

C = (1000, 800, 1000)


def box(name, size=(100,100,100), mass=1, pos=(0,0,0), yaw=0):
    return BoxInput(name, size, mass, pos, yaw)


def cases():
    ground = box('ground')
    narrow = box('narrow', (60,200,100))
    shelf = box('shelf', (200,200,100), pos=(0,0,100))
    pair = (box('left',(80,100,100),pos=(-100,0,0)),
            box('right',(80,100,100),pos=(100,0,0)))
    three = tuple(box(f't{i}',(60,100,100),pos=(x,0,0)) for i,x in enumerate([-100,0,100]))
    tri = tuple(box(f'tri{i}',(40,40,100),pos=(*xy,0))
                for i,xy in enumerate([(-100,-80),(100,-80),(0,100)]))
    return {
        'floor': (PlacedState(C), ground, 'STABLE', 'PCT_STATIC_STABLE'),
        'single_center': (PlacedState(C,(ground,)), box('top',pos=(0,0,100)), 'STABLE','PCT_STATIC_STABLE'),
        # 10mm overlap, new center x=90 outside [40,50] contact.
        'single_outside': (PlacedState(C,(ground,)),box('out',pos=(90,0,100)), 'UNSTABLE','PCT_STATIC_INSTABILITY'),
        # shelf supported over [-30,30], shrunken to ~[-27,27]. Top center
        # x=60 lies inside its own contact [10,100]. Weighted shelf+top COM
        # is 60*10/11=54.55 (heavy) vs 60*.1/1.1=5.45 (light).
        'ancestor_heavy': (PlacedState(C,(narrow,shelf)),box('top',mass=10,pos=(60,0,200)), 'UNSTABLE','PCT_STATIC_INSTABILITY'),
        'ancestor_light': (PlacedState(C,(narrow,shelf)),box('top',mass=.1,pos=(60,0,200)), 'STABLE','PCT_STATIC_STABLE'),
        'bridge_two': (PlacedState(C,pair),box('bridge',(300,100,100),3,(0,0,100)), 'STABLE','PCT_STATIC_STABLE'),
        'three_direct': (PlacedState(C,three),box('bridge',(300,100,100),3,(0,0,100)), 'STABLE','PCT_STATIC_STABLE'),
        # Real upstream LS branch is defective: this physically balanced triangle
        # is retained as a counterexample, never relabelled a stable acceptance.
        'three_ls_counterexample': (PlacedState(C,tri),box('bridge',(260,240,100),3,(0,0,100)), 'ERROR','FLOW_MASS_NOT_CONSERVED'),
        'height_mismatch': (PlacedState(C,(ground,)),box('high',pos=(0,0,120)), 'UNASSESSABLE','POSE_HEIGHT_MISMATCH'),
        'baseline_unstable': (PlacedState(C,(ground,box('bad',pos=(90,0,100)))),box('later',pos=(-200,0,0)), 'UNASSESSABLE','BASELINE_UNSTABLE'),
        'baseline_wrong_order': (PlacedState(C,(shelf,narrow)),box('later'), 'UNASSESSABLE','BASELINE_POSE_HEIGHT_MISMATCH'),
        'boundary_touch_only': (PlacedState(C,(ground,)),box('edge',pos=(100,0,100)), 'UNASSESSABLE','POSE_HEIGHT_MISMATCH'),
    }


@pytest.mark.parametrize('name', list(cases()))
def test_real_kernel_cases(name):
    state,candidate,status,reason = cases()[name]
    before = copy.deepcopy((asdict(state),asdict(candidate)))
    result = assess_candidate(state,candidate)
    assert (result.status,result.reason_code) == (status,reason)
    assert (asdict(state),asdict(candidate)) == before
    assert result.failed_item_id is None  # no invented failure localization
    assert result.algorithm_identity['commit'] == '5e7b4238b18310af4529e0f85157d17de605850c'
    json.dumps(result.to_dict(), allow_nan=False)
    if name not in {'height_mismatch','baseline_wrong_order'}:
        assert result.kernel_calls > 0
    if status=='STABLE':
        assert result.diagnostics['global_conservation_checked']
        assert result.diagnostics['ground_mass_kg'] == pytest.approx(result.diagnostics['input_total_mass_kg'])
    if name=='baseline_unstable':
        assert result.baseline_status=='UNSTABLE' and result.first_bad_prefix=='bad'
    if name=='three_ls_counterexample':
        assert result.diagnostics['kernel_return'] is True  # upstream True rejected by guards
        assert result.diagnostics['raw_kernel'][-1]['outgoing_mass_kg']


@pytest.mark.parametrize('yaw',[0,90])
def test_geometry_round_trip_and_density(yaw):
    b=box('rot',(180,70,50),7,(110,-90,0),yaw)
    geo=to_kernel(b,C)
    assert from_corner(geo['corner_mm'],geo['size_mm'],C)==b.bottom_center_mm
    r=assess_candidate(PlacedState(C),b)
    assert r.status=='STABLE'
    row=r.diagnostics['boxes'][0]
    assert row['mass_kg']==pytest.approx(7)
    assert row['center_mm']==pytest.approx(geo['center_mm'])
    assert row['vertex_high_mm']==pytest.approx([a+s for a,s in zip(geo['corner_mm'],b.size_mm)])
    heavy=replace(b,mass_kg=14)
    assert to_kernel(heavy,C)['density_kg_mm3']==2*geo['density_kg_mm3']


def test_repeat_reverse_no_pollution():
    state=cases()['ancestor_heavy'][0]
    candidates=[cases()[name][1] for name in ['ancestor_heavy','ancestor_light']]
    original=digest(asdict(state))
    def evaluate(order):
        results={}
        for c in order:
            r=assess_candidate(state,c).to_dict();r.pop('duration_s');results[c.mass_kg]=r
        return results
    first=evaluate(candidates)
    assert evaluate(candidates)==first==evaluate(list(reversed(candidates)))
    assert digest(asdict(state))==original


@pytest.mark.parametrize('change',[
    {'mass_kg':-1},{'mass_kg':0},{'mass_kg':float('nan')},
    {'mass_kg':float('inf')},{'dimensions_mm':(0,100,100)},
    {'dimensions_mm':(100,-1,100)},{'yaw_deg':45},
    {'bottom_center_mm':(float('nan'),0,0)}])
def test_invalid_input(change):
    r=assess_candidate(PlacedState(C),replace(box('bad'),**change))
    assert r.status=='UNASSESSABLE' and r.reason_code=='INVALID_INPUT'
    assert r.kernel_calls==0
    json.dumps(r.to_dict(),allow_nan=False)


def test_config_bypass_rejected():
    for kwargs in [{'setting':2},{'setting':True},{'height_tolerance_mm':.1}]:
        with pytest.raises(ValueError): StabilityConfig(**kwargs)
    with pytest.raises(ValueError): assess_candidate(PlacedState(C),box('g'),{'setting':2})


def test_runtime_bridge_exact_fields():
    obj={'item_id':'real','dimensions_mm':{'length':180,'width':70,'height':50},
         'mass_kg':4,'pose':{'x_mm':0,'y_mm':0,'z_base_mm':0,'yaw_deg':90},
         'oriented_size_mm':[70,180,50], 'current_top_load_kg':999}
    b=box_from_runtime(obj)
    state=state_from_runtime({'container':dict(length_mm=1000,width_mm=800,max_height_mm=1000),
                              'placed_items':[obj]})
    assert b.mass_kg==4 and state.placed==(b,)
    r=assess_candidate(state,box('next',pos=(0,0,50)))
    assert r.status=='STABLE' and r.diagnostics['input_total_mass_kg']==5
    obj['oriented_size_mm']=[180,70,50]
    with pytest.raises(ValueError,match='ORIENTED_SIZE_MISMATCH'):box_from_runtime(obj)


def test_packaged_schemas():
    from jsonschema import Draft202012Validator
    root=files('semantic_pallet_planner.jev_select.stability')
    result=assess_candidate(PlacedState(C),box('floor')).to_dict()
    for stem,value in [('result',result),('config',asdict(StabilityConfig()))]:
        schema=json.loads(root.joinpath(f'schemas/stability_{stem}_v1.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(value)


def test_import_is_lazy():
    code="import sys; import semantic_pallet_planner.jev_select.stability; assert 'numpy' not in sys.modules; assert not any('.vendor.pct' in s for s in sys.modules)"
    subprocess.run([sys.executable,'-c',code],check=True)


def test_numeric_guards_no_repair():
    # Direct audit guard fault injection is separate from real fixture acceptance.
    from semantic_pallet_planner.jev_select.stability.pct_adapter import audit, NumericalFailure
    from semantic_pallet_planner.jev_select.stability.vendor.pct.space import Box, DownEdge, Stack
    import numpy as np
    g1=Box(100,100,100,0,0,0,1e-6);g2=Box(100,100,100,200,0,0,1e-6)
    top=Box(300,100,100,0,0,100,1e-6)
    for g in [g1,g2]:
        e=DownEdge(g);top.bottom_edges.append(e)
    for weights, reason in [([-1,4],'NEGATIVE_FLOW'),([1,1],'FLOW_MASS_NOT_CONSERVED'),([float('nan'),3],'NONFINITE_FLOW')]:
        for g,m in zip([g1,g2],weights):g.up_edges[top]=Stack(np.array([0.,0.,0.]),m)
        with pytest.raises(NumericalFailure,match=reason):audit([g1,g2,top],StabilityConfig(),False)
        assert np.isnan(g1.up_edges[top].mass) if reason=='NONFINITE_FLOW' else g1.up_edges[top].mass==weights[0]


def test_degenerate_guard_and_error_classification(monkeypatch):
    from semantic_pallet_planner.jev_select.stability import pct_adapter
    monkeypatch.setattr(pct_adapter.Space,'scale_down',lambda self,points:[[0,0],[1,0],[2,0]])
    state=PlacedState(C,(box('g'),))
    r=assess_candidate(state,box('top',pos=(0,0,100)))
    assert (r.status,r.reason_code)==('UNASSESSABLE','DEGENERATE_SUPPORT')


def test_kernel_numeric_exception_is_error(monkeypatch):
    from semantic_pallet_planner.jev_select.stability import pct_adapter
    def fail(*a,**k):raise FloatingPointError('fixture injected')
    monkeypatch.setattr(pct_adapter.Space,'drop_box',fail)
    r=assess_candidate(PlacedState(C),box('floor'))
    assert r.status=='ERROR' and r.reason_code=='KERNEL_NUMERICAL_ERROR'


def test_real_multisupport_baseline_error_is_not_candidate_instability():
    s,c,_,_=cases()['three_ls_counterexample']
    r=assess_candidate(PlacedState(C,(*s.placed,c)),box('later',pos=(-300,0,0)))
    assert r.status=='ERROR' and r.baseline_status=='ERROR'
    assert r.first_bad_prefix=='bridge' and r.kernel_calls==4


def test_coincident_support_prefix_cannot_be_restored():
    r=assess_candidate(PlacedState(C,(box('first'),box('coincident'))),box('top',pos=(0,0,100)))
    assert (r.status,r.reason_code)==('UNASSESSABLE','BASELINE_POSE_HEIGHT_MISMATCH')
    assert r.first_bad_prefix=='coincident'


@pytest.mark.parametrize('pos',[(-500,0,0),(500,0,0),(0,-400,0),(0,0,-1),(0,0,1000)])
def test_out_of_bounds_is_not_unstable(pos):
    r=assess_candidate(PlacedState(C),box('outside',pos=pos))
    assert (r.status,r.reason_code)==('UNASSESSABLE','OUT_OF_BOUNDS')
    assert r.kernel_calls==0


def test_dynamic_holder_restores_more_than_upstream_default():
    # Upstream allocates only 60 slots by default. 61 disjoint floor boxes
    # plus this candidate require the adapter's explicit dynamic allocation.
    placed=tuple(box(f'floor_{i}',(10,10,10),1,(i*12-360,0,0)) for i in range(61))
    candidate=box('floor_61',(10,10,10),2,(372,0,0))
    state=PlacedState(C,placed)
    before=digest(asdict(state))
    result=assess_candidate(state,candidate)
    assert result.status=='STABLE' and result.kernel_calls==62
    assert len(result.diagnostics['boxes'])==62
    assert result.diagnostics['input_total_mass_kg']==63
    assert result.diagnostics['ground_mass_kg']==63
    assert result.diagnostics['restored_order']==[b.item_id for b in placed]
    assert digest(asdict(state))==before


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser(description='Only synthetic PCT fixtures; no orders or model calls')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    summaries=[]
    for name,(state,candidate,status,reason) in cases().items():
        result=assess_candidate(state,candidate)
        assert (result.status,result.reason_code)==(status,reason),name
        data={'fixture':name,'origin':'CONSTRUCTED_NOT_ORDER','state':asdict(state),
              'candidate':asdict(candidate),'expected_status':status,'expected_reason':reason,
              'result':result.to_dict(),'expectation_matched':True,
              'physical_stable_acceptance':result.status=='STABLE',
              'known_algorithm_counterexample':name=='three_ls_counterexample'}
        (args.output/f'{name}.json').write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
        summaries.append({k:data[k] for k in ['fixture','expected_status','expectation_matched','known_algorithm_counterexample']})
    (args.output/'index.json').write_text(json.dumps(summaries,indent=2)+'\n')
    print(json.dumps({'fixtures':len(summaries),'expected_outcomes_matched':True,
        'multisupport_ls_reliability':'NOT_ESTABLISHED_COUNTEREXAMPLE_SAVED',
        'monitor_integration_status':'NOT_RUN','order_runs':0}))
