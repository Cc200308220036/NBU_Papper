"""Independent small shapes verify the diagnostic area/adjacency calculations."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    'o3_attribution', Path(__file__).resolve().parents[2]/'scripts/analyze_o3_failures.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def box(identifier, x, y, z, size, *, stackable=True, fragile=False):
    return {'item_id':identifier, 'pose':{'x_mm':x,'y_mm':y,'z_base_mm':z,'yaw_deg':0},
            'oriented_size_mm':size,'mass_kg':1.,'stackable':stackable,'fragile':fragile,
            'weight_class':'light','product_category':'general',
            'top_load_limit_kg_synthetic':10., 'supported_load_kg':999.}


def test_l_shape_rectangle_is_not_component_area():
    # 3x4 rectangle with a 2x3 corner missing: area 6, largest rectangle area 4.
    free=np.array([[True,True],[True,False]])
    xs=[0,1,3];ys=[0,1,4]
    assert analysis.components(free,xs,ys)==[6]
    area,rect=analysis.largest_rectangle(free,xs,ys)
    assert area==4
    assert rect==[0,1,0,4]


def test_corner_touch_is_not_connected():
    areas=analysis.components(np.array([[True,False],[False,True]]),[0,1,2],[0,1,2])
    assert sorted(areas)==[1,1]


def test_skyline_hides_covered_top_and_reconstructs_load():
    container={'length_mm':10,'width_mm':10,'max_height_mm':10}
    bottom=box('bottom',-2.5,0,0,[5,10,2],fragile=True)
    top=box('top',-2.5,0,2,[5,10,2],stackable=False)
    metrics=analysis.surface_metrics(container,[bottom,top])
    assert metrics['floor_clear_column_area_mm2']==50
    assert metrics['largest_floor_clear_rectangle_mm2']==50
    assert metrics['exposed_stackable_area_mm2']==0
    assert metrics['exposed_fragile_top_area_mm2']==0
    assert metrics['empty_volume_mm3']==800
    assert metrics['max_height_mm']==4
    assert metrics['min_exposed_stackable_remaining_physical_kg'] is None
    single=analysis.surface_metrics(container,[bottom])
    assert single['min_exposed_stackable_remaining_physical_kg']==10


def test_adjacent_different_height_supports_are_separate():
    container={'length_mm':10,'width_mm':10,'max_height_mm':10}
    ps=[box('a',-2.5,0,0,[5,10,2]),box('b',2.5,0,0,[5,10,3])]
    metrics=analysis.surface_metrics(container,ps)
    assert metrics['exposed_stackable_area_mm2']==100
    assert metrics['largest_exposed_stackable_component_mm2']==50
    assert metrics['exposed_stackable_component_count']==2
    assert metrics['floor_clear_component_count']==0
