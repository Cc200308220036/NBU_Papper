"""Small hand examples and independent finite-grid reference, no dispatch."""
import copy
from fractions import Fraction as F
import itertools
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

# Reuse the established no-transport/credential/LP audit guard, not its geometry.
import test_packaging_scenario_features as guard
from semantic_pallet_planner.jev_select import packaging_fs_geometry as g


def box(key, size=(2,2,1)):
    return dict(item_id=key,size_mm=list(map(str,size)))


def action(cid='a', key='pick', x=-2, y=-2, size=(2,2,1), z=0, yaw=0):
    return dict(candidate_id=cid,pick_item_id=key,
                pose=dict(x_mm=str(x),y_mm=str(y),z_base_mm=str(z),yaw_deg=str(yaw)),
                oriented_size_mm=list(map(str,size)))


def fixture():
    return dict(version=g.JM_FS_INPUT,coordinate=g.COORDINATE,precision='SAVED_LEXEMES',
        state=dict(container=dict(length_mm='6',width_mm='6',max_height_mm='6'),
                   buffer=[box('pick'),box('other',(4,3,1))],placed_objects=[]),
        pool=[action(),action('b',x=0,y=0)],
        descriptor_scope=dict(mode='HISTORICAL_AB',contrast=['a','b']),
        provenance=dict(state_sha256='0'*64,pool_sha256='1'*64))


def run(v):
    raw=json.dumps(v).encode()
    return g.evaluate(raw,expected_sha256=g.sha(raw))


def reference(domain, obstacles):
    """Independent raster-cell occupancy and exhaustive set inclusion.

    Allowed only for tiny integral fixtures. Production uses interval intersection
    and four neighbor tests; this reference uses unit cells and all-pairs inclusion.
    """
    xs=sorted({domain[0],domain[1]}|{v for b in obstacles for v in b[:2]})
    ys=sorted({domain[2],domain[3]}|{v for b in obstacles for v in b[2:]})
    blocked={(x,y) for x in range(domain[0],domain[1]) for y in range(domain[2],domain[3])
             if any(b[0]<=x<b[1] and b[2]<=y<b[3] for b in obstacles)}
    free=[]
    for a,b in itertools.combinations(xs,2):
        for c,d in itertools.combinations(ys,2):
            cells={(x,y) for x in range(a,b) for y in range(c,d)}
            if not cells & blocked: free.append(((a,b,c,d),cells))
    return sorted(r for r,c in free if not any(c<other for _,other in free))


class GeometryTests(unittest.TestCase):
    def test_hand_rotation_identity_and_sets(self):
        s=run(fixture())['semantic']
        self.assertEqual(s['status'],'VALUE')
        self.assertEqual(s['contrast']['direction'],'A_STRICT_SUPERSET')
        self.assertEqual(s['actions'][0]['fit_ids'],['other'])
        a=s['actions'][0]['members'][0]['orientations']
        self.assertTrue(any(o['fits'] for o in a))
        v=fixture();v['state']['buffer'].append(box('twin',(4,3,1)))
        self.assertEqual(run(v)['semantic']['actions'][0]['fit_ids'],['other','twin'])
        for a,b,d in [([],['x'],'B_STRICT_SUPERSET'),(['x'],['y'],'TRADEOFF'),(['x'],['x'],'NO_DIRECTION'),(None,[],'UNKNOWN')]:
            self.assertEqual(g.direction(a,b),d)

    def test_reference_all_maximal_and_ties(self):
        rng=random.Random(71)
        domain=(-3,3,-3,3)
        for _ in range(24):
            cells=rng.sample([(x,x+1,y,y+1) for x in range(-3,3) for y in range(-3,3)],rng.randrange(5))
            occ=[tuple(map(F,b))+(F(0),F(1)) for b in cells]
            d=g._descriptor(tuple(map(F,domain)),occ,F(1))
            c=dict(enumerated_rectangles=0,emptiness_tests=0,intersection_tests=0)
            got=g._rectangles(d,c,100000)
            self.assertEqual(got,reference(domain,cells))
            self.assertLessEqual(c['emptiness_tests'],5*d['q'])
            self.assertLessEqual(c['intersection_tests'],5*d['q']*max(1,d['m']))
            areas=[(r[1]-r[0])*(r[3]-r[2]) for r in got]
            expected=reference(domain,cells)
            best=max(((r[1]-r[0])*(r[3]-r[2]) for r in expected),default=0)
            self.assertEqual(max(areas,default=0),best)
            self.assertEqual([r for r,a in zip(got,areas) if a==best],
                             [r for r in expected if (r[1]-r[0])*(r[3]-r[2])==best])

    def test_suspended_clearance_touching_and_height(self):
        v=fixture();v['descriptor_scope']=dict(mode='FULL_POOL',contrast=None)
        v['state']['placed_objects']=[dict(box('s',(2,2,1)),pose=action(x=2,y=2,z=2)['pose'],oriented_size_mm=['2','2','1'])]
        self.assertEqual(run(v)['semantic']['status'],'VALUE')
        occ=[(F(1),F(3),F(1),F(3),F(2),F(3))]
        self.assertEqual(g.clearance((F(1),F(3),F(1),F(3)),occ,F(6)),2)
        self.assertIsNone(g.clearance((F(1),F(1),F(0),F(1)),occ,F(6)))
        self.assertEqual(g.clearance((F(-3),F(1),F(-3),F(1)),occ,F(6)),6)
        self.assertEqual(len(g._descriptor(tuple(map(F,[-3,3,-3,3])),occ,F(2))['obstacles']),0)
        self.assertEqual(len(g._descriptor(tuple(map(F,[-3,3,-3,3])),occ,F('2.00000000000000000000001'))['obstacles']),1)
        v['state']['buffer'][1]['size_mm'][2]='7'
        rows=run(v)['semantic']['actions']
        self.assertFalse(any(o['fits'] for o in rows[0]['members'][0]['orientations']))
        v['state']['buffer']=v['state']['buffer'][:1]
        self.assertEqual(run(v)['semantic']['actions'][0]['fit_ids'],[])
        v['state']['buffer']=[];v['pool']=[]
        self.assertEqual(run(v)['semantic']['status'],'VALUE')

    def test_precision_and_no_floor_snap(self):
        raw=b'{"n":1.0000000000000000000000000000000000001}'
        x=g.parse_saved(raw,g.sha(raw))['n']
        self.assertGreater(g.number(x),1)
        self.assertEqual(g.text(g.number(x)), '1.0000000000000000000000000000000000001')
        v=fixture();v['pool'][0]['pose']['z_base_mm']='0.0000000000000000000000000000000001'
        self.assertEqual(run(v)['semantic']['contrast']['status'],'NOT_APPLICABLE')
        v=fixture();v['pool'][0]['pose']['x_mm']='-2.0000000000000000000000000000000001'
        self.assertEqual(run(v)['semantic']['reason'],'OUT_OF_CONTAINER')

    def test_invalid_missing_unknown_and_bindings(self):
        for mutate in [lambda v:v['state']['container'].pop('width_mm'),
                       lambda v:v['state']['container'].update(width_mm='NaN'),
                       lambda v:v['pool'][0]['pose'].update(yaw_deg='45'),
                       lambda v:v['pool'][0].update(pick_item_id='absent'),
                       lambda v:v['pool'][0].update(oriented_size_mm=['1','2','1']),
                       lambda v:v['state']['container'].update(width_mm=True),
                       lambda v:v['state']['buffer'][1].update(size_mm=['0','2','1']),
                       lambda v:v.update(private_future=[]),
                       lambda v:v['descriptor_scope'].update(contrast=['a','absent'])]:
            v=fixture();mutate(v)
            self.assertEqual(run(v)['semantic']['status'],'INVALID_INPUT')
        v=fixture();v['state']['buffer'][1]['size_mm']=None
        self.assertEqual(run(v)['semantic']['status'],'UNKNOWN')
        v=fixture();del v['state']['buffer'][1]['size_mm']
        self.assertEqual(run(v)['semantic']['status'],'INVALID_INPUT')
        v=fixture();v['state']['placed_objects']=[dict(box('p'),pose=action()['pose'],oriented_size_mm=['2','2','1'])]
        self.assertEqual(run(v)['semantic']['reason'],'ACTION_OVERLAP')
        for raw in [b'{"x":NaN}',b'{"x":Infinity}',b'{"x":1,"x":2}']:
            self.assertEqual(g.evaluate(raw,expected_sha256=g.sha(raw))['semantic']['status'],'INVALID_INPUT')
        self.assertEqual(g.evaluate(b'{}',expected_sha256='0'*64)['semantic']['reason'],'INPUT_DIGEST_MISMATCH')

    def test_order_cache_and_scope_atomic_budget(self):
        v=fixture();v['descriptor_scope']['mode']='FULL_POOL'
        v['pool'].append(action('duplicate'))
        a=run(v)['semantic'];v['pool'].reverse();v['state']['buffer'].reverse()
        b=run(v)['semantic']
        self.assertEqual(a['semantic_digest'],b['semantic_digest'])
        self.assertEqual(a['descriptors'],b['descriptors'])
        self.assertGreater(a['cost']['cache_reuses'],0)
        with patch.object(g,'_descriptor_items',lambda d:list(reversed(sorted(d.items())))):
            reverse_cache=run(v)['semantic']
        self.assertEqual(a['semantic_digest'],reverse_cache['semantic_digest'])
        self.assertEqual(a['descriptors'],reverse_cache['descriptors'])
        for key in ['per_descriptor_q','scope_q','intersection_bound','maximal_rectangles']:
            with patch.dict(g.BUDGET,{key:0}):
                s=run(v)['semantic'];v['pool'].reverse();t=run(v)['semantic']
                self.assertEqual(s['status'],'UNKNOWN')
                self.assertEqual(s['semantic_digest'],t['semantic_digest'])
                self.assertEqual(s['actions'],[])
                self.assertEqual(s['descriptors'],[])
                self.assertEqual(s['contrast']['direction'],'UNKNOWN')
                if key!='maximal_rectangles':self.assertEqual(s['cost']['enumerated_rectangles'],0)

    def test_result_maximum_ties_and_rotation_only_fit(self):
        v=fixture();v['state']['buffer'][1]['size_mm']=['3','4','1']
        s=run(v)['semantic']
        orientations=s['actions'][0]['members'][0]['orientations']
        self.assertTrue(any(o['fits'] for o in orientations))
        for d in s['descriptors']:
            rects=[tuple(map(F,r)) for r in d['maximal_rectangles']]
            best=max(((r[1]-r[0])*(r[3]-r[2]) for r in rects),default=F(0))
            self.assertEqual(F(d['maximum_area_mm2']),best)
            self.assertEqual(d['maximum_rectangles'],[[g.text(x) for x in r] for r in rects if (r[1]-r[0])*(r[3]-r[2])==best])
        v=fixture();v['state']['buffer'][0]['size_mm']=['3','6','1']
        v['state']['buffer'][1]['size_mm']=['4','3','1']
        v['pool']=[action(x='-1.5',y=0,size=(3,6,1))]
        v['descriptor_scope']=dict(mode='FULL_POOL',contrast=None)
        orientations=run(v)['semantic']['actions'][0]['members'][0]['orientations']
        self.assertEqual([o['fits'] for o in orientations],[False,True])
        v=fixture();v['pool'][1]['pose']['yaw_deg']='0.000'
        self.assertEqual(run(v)['semantic']['contrast']['status'],'VALUE')

    def test_native_budget_and_unknown_does_not_mask_invalid(self):
        v=fixture();v['state']['container']=dict(length_mm='100',width_mm='100',max_height_mm='100')
        v['pool']=[action(x=-49,y=-49)]
        v['descriptor_scope']=dict(mode='FULL_POOL',contrast=None)
        for i in range(22):
            a=action(x=-45+4*i,y=-45+4*i,size=(1,1,1))
            v['state']['placed_objects'].append(dict(box('p'+str(i),(1,1,1)),pose=a['pose'],oriented_size_mm=['1','1','1']))
        result=run(v)['semantic']
        self.assertEqual(result['reason'],'COMPUTE_BOUND_EXCEEDED')
        self.assertEqual(result['cost']['enumerated_rectangles'],0)
        v=fixture();v['state']['placed_objects']=[dict(box('p'),pose=action(z=-1)['pose'],oriented_size_mm=None)]
        self.assertEqual(run(v)['semantic']['status'],'INVALID_INPUT')
        v=fixture();v['precision']='UNKNOWN'
        self.assertEqual(run(v)['semantic']['status'],'UNKNOWN')

    def test_saved_adapter_and_raw_precision(self):
        original=guard.fixture()
        rawstate=json.dumps(original['state']).encode()
        rawpool=json.dumps(original['pool']).encode()
        # Native JSON numeric lexeme has more precision than binary float.
        rawstate=rawstate.replace(b'200,',b'200.000000000000000000000000000000001,',1)
        raw,identity=g.from_saved_public(rawstate,rawpool,state_sha256=g.sha(rawstate),pool_sha256=g.sha(rawpool),mode='HISTORICAL_AB',contrast=['a0','a1'])
        self.assertIn(b'200.000000000000000000000000000000001',raw)
        self.assertEqual(g.evaluate(raw,expected_sha256=identity)['semantic']['status'],'VALUE')
        with self.assertRaises(g.GeometryError):
            g.from_saved_public(rawstate,rawpool,state_sha256='0'*64,pool_sha256=g.sha(rawpool))

    def test_output_schema_and_old_interfaces(self):
        from semantic_pallet_planner.jev_select import contracts
        from semantic_pallet_planner.jev_select import packaging_experience_contract as e
        s=run(fixture());g.validate_schema(s,'jm_fs_result_v1')
        contracts.validate_schema('jm_fs_result_v1',s)
        with self.assertRaises(Exception):
            contracts.validate_schema('jm_fs_input_v1',dict(fixture(),future=[]))
        self.assertEqual(e.rules_contract()['real_admission'],'CLOSED_IN_THIS_LIMITED_UNIT')
        self.assertEqual(guard.m.bind_contrast(guard.fixture(),'a0','a1')['scope'],guard.m.SCOPE)
        self.assertFalse(any(name.startswith(p) for p in guard.BLOCKED for name in sys.modules))


if __name__=='__main__': unittest.main()
