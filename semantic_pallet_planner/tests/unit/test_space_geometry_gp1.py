"""Small GP1 constructions with hand boundaries and independent exact properties.

No geometry oracle/evaluate_pose, candidate generation, order or LP imports.
"""
import copy
from decimal import Decimal
from fractions import Fraction
import json
import unittest

from semantic_pallet_planner.planner.space_candidates import build_space_index, _build_space_index
from semantic_pallet_planner.planner.space_candidates.contracts import (
    AABB, Budget, DEFAULT_LIMITS, GeometryError, number, parse_input, text,
)
from semantic_pallet_planner.planner.space_candidates.empty_spaces import remove_redundancy


def box(name, x, y, z, sx, sy, sz, yaw=0):
    return {'item_id':name,'pose':{'x_mm':x,'y_mm':y,'z_base_mm':z,'yaw_deg':yaw},
            'oriented_size_mm':[sx,sy,sz]}


def scene(*boxes, length=10, width=10, height=10):
    return {'version':'geometry_space_input_v1',
            'container':{'length_mm':length,'width_mm':width,'max_height_mm':height},
            'placed_items':list(boxes)}


SCENES = {
    'empty': scene(),
    'same_height_platform': scene(box('left',-2,0,0,4,4,2),box('right',2,0,0,4,4,2)),
    'steps': scene(box('low',-2,0,0,4,4,2),box('high',2,0,0,4,4,6)),
    'overhead_cavity': scene(box('suspended',0,0,4,4,4,2)),
    'diagonal': scene(box('diagonal',-2,-2,0,4,4,2),length=8,width=8),
    'full': scene(box('full',0,0,0,10,10,10)),
}


def encode(value):
    return json.dumps(value, separators=(',',':')).encode()


def boundaries(result, source=None):
    return {tuple(Decimal(x) for x in s['bounds_mm']) for s in result['spaces']
            if source is None or source in s['source_types']}


class SpaceGeometryGP1(unittest.TestCase):
    def run_scene(self, value):
        before = copy.deepcopy(value)
        raw = encode(value)
        result = build_space_index(raw)
        self.assertEqual(value, before)
        self.assertNotEqual(result['status'],'ERROR',result['error'])
        self.assertEqual(build_space_index(raw), result)
        # Independent direct endpoint property check; no implementation predicates.
        c = value['container']
        for s in result['spaces']:
            a = tuple(Decimal(x) for x in s['bounds_mm'])
            self.assertTrue(all(a[d] < a[d+3] for d in range(3)))
            self.assertTrue(-Decimal(c['length_mm'])/2 <= a[0] < a[3] <= Decimal(c['length_mm'])/2)
            self.assertTrue(-Decimal(c['width_mm'])/2 <= a[1] < a[4] <= Decimal(c['width_mm'])/2)
            self.assertTrue(0 <= a[2] < a[5] <= c['max_height_mm'])
            for p in value['placed_items']:
                x,y,z=(Decimal(p['pose'][k]) for k in ('x_mm','y_mm','z_base_mm'))
                l,w,h=map(Decimal,p['oriented_size_mm'])
                lo=(x-l/2,y-w/2,z);hi=(x+l/2,y+w/2,z+h)
                self.assertTrue(any(a[d+3]<=lo[d] or hi[d]<=a[d] for d in range(3)),(s,p))
        ems=boundaries(result,'EMS_STYLE_3D')
        for a in ems:
            self.assertFalse(any(a!=b and all(b[d]<=a[d] and a[d+3]<=b[d+3] for d in range(3)) for b in ems))
        self.assertEqual(len(result['spaces']),len(boundaries(result)))
        self.assertEqual([s['bounds_mm'] for s in result['spaces']],
                         sorted([s['bounds_mm'] for s in result['spaces']],key=lambda b:tuple(map(Decimal,b))))
        return result

    def test_empty_and_source_merge(self):
        r=self.run_scene(SCENES['empty'])
        self.assertEqual(boundaries(r),{(-5,-5,0,5,5,10)})
        self.assertEqual(r['spaces'][0]['source_types'],['EMS_STYLE_3D','SURFACE_CORNER'])
        self.assertEqual(len(r['surface']['seeds']),4)  # four container corners
        self.assertEqual(r['budget_usage']['used']['surface_event_cells'],1)
        self.assertEqual(r['budget_usage']['used']['active_spaces'],1)  # interned, no copies

    def test_exact_noninteger_slot_no_rounding(self):
        raw=b'''{"version":"geometry_space_input_v1","container":{"length_mm":10.0002,"width_mm":10,"max_height_mm":10},"placed_items":[{"item_id":"edge","pose":{"x_mm":-1.0001,"y_mm":0,"z_base_mm":0,"yaw_deg":0},"oriented_size_mm":[8,10,10]}]}'''
        r=build_space_index(raw)
        self.assertEqual(r['status'],'OK')
        self.assertEqual(boundaries(r),{(Decimal('2.9999'),-5,0,Decimal('5.0001'),5,10)})
        self.assertIn('2.9999',r['spaces'][0]['bounds_mm'])
        self.assertEqual(text(Decimal('-0.000')), '0')
        self.assertEqual(text(Decimal('0.123456789012345678901234567890')), '0.12345678901234567890123456789')
        with self.assertRaises(GeometryError):number(0.1)

    def test_single_occupied_cube_six_hand_slabs(self):
        r=self.run_scene(SCENES['overhead_cavity'])
        expected={(-5,-5,0,-2,5,10),(2,-5,0,5,5,10),(-5,-5,0,5,-2,10),
                  (-5,2,0,5,5,10),(-5,-5,0,5,5,4),(-5,-5,6,5,5,10)}
        self.assertEqual(boundaries(r,'EMS_STYLE_3D'),expected)
        self.assertIn((-5,-5,0,5,5,4),boundaries(r))
        # Top surface cannot represent this lower cavity, retained by EMS.
        self.assertNotIn((-5,-5,0,5,5,4),boundaries(r,'SURFACE_CORNER'))

    def test_same_height_platform_crosses_box_boundary(self):
        r=self.run_scene(SCENES['same_height_platform'])
        self.assertIn((-5,-5,2,5,5,10),boundaries(r,'SURFACE_CORNER'))
        # x=0 is an event due to the two boxes, not a height-changing edge.
        self.assertFalse(any(s['vertex_mm']==['0','-2'] and s['seed_z_mm']=='2' for s in r['surface']['seeds']))

    def test_steps_and_taller_obstacle(self):
        r=self.run_scene(SCENES['steps'])
        low=[b for b in boundaries(r,'SURFACE_CORNER') if b[2]==2]
        self.assertTrue(low)
        self.assertTrue(all(b[3]<=0 or b[4]<=-2 or b[1]>=2 for b in low))
        self.assertIn((-5,-5,6,5,5,10),boundaries(r,'SURFACE_CORNER'))

    def test_diagonal_corner_omission_and_boundary(self):
        r=self.run_scene(SCENES['diagonal'])
        center=[s for s in r['surface']['seeds'] if s['vertex_mm']==['0','0']]
        # SW high has both neighbours different; NE floor sees only diagonal high
        # and is deliberately omitted by the frozen finite quadrant rule.
        self.assertEqual([(s['quadrant'],s['seed_z_mm']) for s in center],[([-1,-1],'2')])
        self.assertTrue(any(s['vertex_mm']==['4','4'] for s in r['surface']['seeds']))

    def test_axis_orders_have_expected_different_expansions(self):
        # Floor seed at outer SW: xy sweeps bottom then left; yx left then bottom.
        v=scene(box('obstacle',2,2,0,2,2,4))
        r=self.run_scene(v)
        seed=next(s for s in r['surface']['seeds'] if s['vertex_mm']==['-5','-5'])
        spaces={s['space_id']:tuple(map(Decimal,s['bounds_mm'])) for s in r['spaces']}
        self.assertEqual([spaces[e['space_id']] for e in seed['expansions']],
                         [(-5,-5,0,5,1,10),(-5,-5,0,1,5,10)])

    def test_deduplicate_then_containment_and_transient_peak(self):
        budget=Budget()
        large=(Fraction(0),)*3+(Fraction(4),)*3
        small=(Fraction(1),)*3+(Fraction(3),)*3
        records=[budget.acquire(large,'EMS_STYLE_3D'),budget.acquire(large,'EMS_STYLE_3D'),budget.acquire(small,'EMS_STYLE_3D')]
        r=remove_redundancy(records,budget)
        self.assertEqual([x.box.bounds for x in r],[large])
        self.assertEqual(budget.used['active_spaces'],2)
        self.assertEqual(budget.used['space_containment_comparisons'],2)
        self.assertEqual(len(budget.arena),1)

    def test_invalid_inputs_are_atomic_errors(self):
        cases=[]
        duplicate=scene(box('a',0,0,0,2,2,2),box('a',3,3,0,2,2,2));cases.append(encode(duplicate))
        cases.append(encode(scene(box('a',0,0,0,2,2,2),box('b',0,0,1,2,2,2))))
        cases.append(encode(scene(box('out',5,0,0,2,2,2))))
        bad=scene();bad['container']['length_mm']=True;cases.append(encode(bad))
        bad=scene(box('yaw',0,0,0,2,2,2,45));cases.append(encode(bad))
        cases.extend([b'{}',b'{"x":1,"x":2}',b'NaN',b'\xff',encode(scene(height=0))])
        for raw in cases:
            with self.subTest(raw=raw):
                r=build_space_index(raw)
                self.assertEqual(r['status'],'ERROR')
                self.assertEqual(r['spaces'],[])
                self.assertIsNone(r['surface'])
                self.assertEqual(r['error']['code'],'INVALID_GEOMETRY_INPUT')
        self.assertEqual(build_space_index(scene())['status'],'ERROR')

    def test_budget_boundaries_and_all_error_paths(self):
        self.assertEqual(DEFAULT_LIMITS,dict(active_spaces=4096,space_containment_comparisons=2000000,
            surface_event_cells=16384,surface_expansion_cell_checks=2000000,raw_point_attempts_per_item=32768))
        for key in ('space_containment_comparisons','surface_event_cells','surface_expansion_cell_checks'):
            b=Budget();b.charge(key,DEFAULT_LIMITS[key])
            with self.assertRaises(GeometryError):b.charge(key)
            self.assertEqual(b.used[key],DEFAULT_LIMITS[key])
        # Explicit reduced-limit test doubles; production entry has no override.
        for key in ('active_spaces','space_containment_comparisons','surface_event_cells','surface_expansion_cell_checks'):
            limits=dict(DEFAULT_LIMITS);limits[key]=0
            r=_build_space_index(encode(SCENES['overhead_cavity']),Budget(limits))
            self.assertEqual(r['status'],'ERROR',(key,r))
            self.assertEqual(r['error']['code'],'GEOMETRY_BUDGET_EXCEEDED')
            self.assertEqual(r['spaces'],[])
            self.assertIsNone(r['surface'])
            self.assertLessEqual(r['budget_usage']['used'][key],0)

    def test_shared_arena_and_ems_parent_counted_before_release(self):
        # Interior box has parent + six new distinct slabs simultaneously.
        r=self.run_scene(SCENES['overhead_cavity'])
        self.assertGreaterEqual(r['budget_usage']['used']['active_spaces'],7)
        limits=dict(DEFAULT_LIMITS);limits['active_spaces']=6
        failed=_build_space_index(encode(SCENES['overhead_cavity']),Budget(limits))
        self.assertEqual(failed['error']['code'],'GEOMETRY_BUDGET_EXCEEDED')
        # Floor expansion counter accumulates across four seeds and two orders.
        empty=self.run_scene(SCENES['empty'])
        self.assertEqual(empty['budget_usage']['observed']['surface_proposals'],8)
        self.assertEqual(empty['budget_usage']['observed']['duplicate_space_references'],8)
        one=dict(DEFAULT_LIMITS);one['active_spaces']=1
        self.assertEqual(_build_space_index(encode(SCENES['empty']),Budget(one))['status'],'OK')
        # Both sources share one arena; a later surface failure discards EMS too.
        used=r['budget_usage']['used']['surface_expansion_cell_checks']
        self.assertGreater(used,1)
        exact=dict(DEFAULT_LIMITS);exact['surface_expansion_cell_checks']=used
        self.assertEqual(_build_space_index(encode(SCENES['overhead_cavity']),Budget(exact))['status'],'OK')
        exact['surface_expansion_cell_checks']=used-1
        failed=_build_space_index(encode(SCENES['overhead_cavity']),Budget(exact))
        self.assertEqual(failed['status'],'ERROR')
        self.assertEqual(failed['spaces'],[])
        self.assertIsNone(failed['surface'])

    def test_full_container_and_order_determinism(self):
        r=self.run_scene(SCENES['full'])
        self.assertEqual(r['status'],'OK_EMPTY')
        self.assertEqual(r['spaces'],[])
        v=copy.deepcopy(SCENES['steps']);a=build_space_index(encode(v))
        v['placed_items'].reverse();b=build_space_index(encode(v))
        self.assertNotEqual(a['source_bytes_sha256'],b['source_bytes_sha256'])
        self.assertEqual({k:v for k,v in a.items() if k!='source_bytes_sha256'},
                         {k:v for k,v in b.items() if k!='source_bytes_sha256'})


if __name__=='__main__':
    unittest.main()
