"""小规模 GOPT EMS 对照测试，不代表完整的 GOPT 实现或训练后基线。"""
import importlib.util
from pathlib import Path
import numpy as np
from semantic_pallet_planner.planner.constraints import candidate_points


def test_gopt_empty_and_single_box_floor_coverage():
    root=Path(__file__).resolve().parents[3]
    spec=importlib.util.spec_from_file_location('gopt_ems_reference',root/'GOPT-main/envs/Packing/ems.py')
    ems=importlib.util.module_from_spec(spec);spec.loader.exec_module(ems)
    empty=ems.compute_ems(np.zeros((10,10),dtype=int),10)
    assert empty
    # 将角点原点转换为底面中心后，容器角点应当对齐。
    ours=candidate_points([],2,2,dict(length_mm=10,width_mm=10))
    assert (-5.0,-5.0,0.0) in ours and (3.0,3.0,0.0) in ours
    hmap=np.zeros((10,10),dtype=int);hmap[:4,:4]=2
    spaces=ems.compute_ems(hmap,10)
    assert any(float(space[2])==2 for space in spaces)
    ours=candidate_points([dict(x0=-5.,x1=-1.,y0=-5.,y1=-1.,z1=2.)],2,2,dict(length_mm=10,width_mm=10))
    assert (-5.0,-5.0,2.0) in ours
