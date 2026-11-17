"""GP2 hand constructions; real physics except explicitly named fault doubles."""
import copy
import json
import unittest
from unittest.mock import patch
from fractions import Fraction
from semantic_pallet_planner.planner.space_candidates.generator import generate, _generate, publish
from semantic_pallet_planner.planner.space_candidates.reduction import coverage, reduce_candidates


def item(name='pick', l=2,w=4,h=2,mass=1,capacity=100,stackable=True,arrival=0):
    return dict(item_id=name,dimensions_mm=dict(length=l,width=w,height=h),mass_kg=mass,
                top_load_limit_kg_synthetic=capacity,stackable=stackable,arrival_index=arrival)


def placed(name,x,y,z,l,w,h,**kw):
    p=item(name,l,w,h,**kw);p.pop('arrival_index')
    p.update(pose=dict(x_mm=x,y_mm=y,z_base_mm=z,yaw_deg=0),oriented_size_mm=[l,w,h],
             supported_load_kg=0,support_fractions=[])
    return p


def scene(boxes=(),buffer=None,length=10,width=10,height=10):
    return dict(version='geometry_physical_input_v1',container=dict(length_mm=length,width_mm=width,
                max_height_mm=height,max_payload_kg=1000),placed_items=list(boxes),
                buffer_items=[item()] if buffer is None else buffer)


def encode(s): return json.dumps(s,allow_nan=False).encode()


SCENES={
 'empty':scene(),
 'platform':scene([placed('left',-2,0,0,4,8,2),placed('right',2,0,0,4,8,2)], [item(l=8,w=8)]),
 'steps':scene([placed('low',-2,0,0,4,8,2),placed('high',2,0,0,4,8,6)]),
 'nonstackable':scene([placed('base',0,0,0,8,8,2,stackable=False)]),
 'tight':scene([placed('base',0,0,0,8,8,2,capacity=0)]),
 'three':scene([placed('a',-3,-3,0,2,2,2),placed('b',0,0,0,2,2,4),placed('c',3,3,0,2,2,6)],
                [item('p'+str(i),arrival=i) for i in range(3)]),
 'noninteger':scene(buffer=[item(l=2.002,w=4.002)],length=10.002,width=10.002),
 'normalization_reject':scene(buffer=[item(l=2.003,w=4.003)],length=10.002,width=10.002),
 'hollow':scene([placed('left',-3.2,0,0,3.6,10,2),placed('right',3.2,0,0,3.6,10,2)],
                [item(l=10,w=10)]),
 'seventy':scene([placed('base',-1.5,0,0,7,10,2)], [item(l=10,w=10)]),
}


class GP2(unittest.TestCase):
    def run_scene(self,s):
        before=copy.deepcopy(s); raw=encode(s)
        r=generate(raw)
        self.assertEqual(s,before)
        self.assertNotEqual(r['status'],'ERROR',r['error'])
        self.assertEqual(r,generate(raw))
        self.assertEqual(r['audit']['space_index_builds'],1)
        self.assertLessEqual(len(r['candidates']),48)
        for ia in r['audit']['items']:
            self.assertLessEqual(ia['final_candidates'],16)
            hosts={x['space_id']:[Fraction(v) for v in x['bounds_mm']] for x in r['audit']['spaces']}
            for record in ia['raw_valid_candidates']:
                k=record['action_key'];l,w,h=map(Fraction,k[1:4]);x,y,z=map(Fraction,k[5:])
                low=(x-l/2,y-w/2,z); high=(x+l/2,y+w/2,z+h)
                for sid in record['host_ids']:
                    b=hosts[sid]
                    self.assertTrue(all(b[d]<=low[d] and high[d]<=b[d+3] for d in range(3)))
                self.assertEqual(set(record['sources']),{p['source_type'] for p in record['proposal_refs']})
            keys=[tuple(x['action_key']) for x in ia['raw_valid_candidates']]
            self.assertEqual(len(keys),len(set(keys)))
            pool=ia['raw_valid_candidates']; final={tuple(k) for k in ia['final_action_keys']}
            for yaw,level in ia['coverage']['required_groups']:
                matching=[x for x in pool if int(x['action_key'][4])==yaw and ('floor' if Fraction(x['action_key'][7])==0 else 'upper')==level]
                best=min(matching,key=lambda x:(-x['geometry_score'],(x['action_key'][0],*(Fraction(v) for v in x['action_key'][1:]))))
                self.assertIn(tuple(best['action_key']),final)
        return r

    def test_empty_corners_center_and_sources(self):
        r=self.run_scene(SCENES['empty']);ia=r['audit']['items'][0]
        # 10x10 container, 2x4 pick: x centers +-4, y centers +-3.
        a={(c['pose']['x_mm'],c['pose']['y_mm'],c['pose']['yaw_deg']) for c in r['candidates']}
        expected={(x,y,0) for x in (-4,4) for y in (-3,3)}|{(0,0,0)}
        expected|={(x,y,90) for x in (-3,3) for y in (-4,4)}|{(0,0,90)}
        self.assertEqual(a,expected)
        self.assertEqual(ia['raw_point_attempts'],20)
        self.assertEqual(ia['unique_actions'],10)
        self.assertTrue(all(len(x['sources'])==2 for x in ia['raw_valid_candidates']))

    def test_square_yaw_distinct(self):
        r=self.run_scene(scene(buffer=[item(l=2,w=2)]));ia=r['audit']['items'][0]
        self.assertEqual(ia['raw_valid_count'],10)
        self.assertEqual(ia['geometric_equivalence_count'],5)

    def test_noninteger_and_half_even(self):
        r=self.run_scene(SCENES['noninteger'])
        self.assertTrue(any(c['pose']['x_mm']==4 for c in r['candidates']))
        self.assertEqual(publish(Fraction('0.0005')),0)
        self.assertEqual(publish(Fraction('0.0015')),Fraction('0.002'))
        r=self.run_scene(SCENES['normalization_reject'])
        self.assertGreater(r['audit']['items'][0]['rejection_counts'].get('POSE_REPRESENTATION_REJECTED',0),0)

    def test_platform(self):
        r=self.run_scene(SCENES['platform'])
        upper=[c for c in r['candidates'] if c['pose']['z_base_mm']==2]
        self.assertTrue(upper)
        self.assertTrue(any(set(c['support']['support_item_ids'])=={'left','right'} and c['support']['support_ratio']==1 for c in upper))

    def test_steps_no_snap(self):
        r=self.run_scene(SCENES['steps'])
        self.assertTrue(all(c['pose']['z_base_mm'] in (0,2,6) for c in r['candidates']))

    def test_support_and_capacity_rejects(self):
        for name,reason in [('nonstackable','non_stackable_support'),('tight','overload'),('hollow','com_outside_support')]:
            with self.subTest(name=name):
                r=self.run_scene(SCENES[name]); self.assertGreater(r['audit']['items'][0]['rejection_counts'].get(reason,0),0)
        r=self.run_scene(SCENES['seventy'])
        self.assertTrue(any(c['support']['support_ratio']==0.7 for c in r['candidates']))

    def test_three_compression(self):
        r=self.run_scene(SCENES['three'])
        self.assertEqual(len(r['candidates']),48)
        self.assertTrue(all(x['raw_valid_count']>16 for x in r['audit']['items']))
        # Independently replay greedy maximum marginal full-tuple coverage.
        for ia in r['audit']['items']:
            pool={tuple(x['action_key']):x for x in ia['raw_valid_candidates']}; seen=set()
            for step in ia['coverage']['selection_order']:
                key=tuple(step['action_key']); x=pool.pop(key)
                if step['reason']!='REQUIRED_YAW_LEVEL':
                    gain=len(coverage(x)-seen)
                    self.assertTrue(all(len(coverage(y)-seen)<=gain for y in pool.values()))
                seen|=coverage(x)

    def test_joint_tuple_reducer_hand_fixture(self):
        # Explicit reducer-only fixture, not a physical admission claim.
        # A and B share all dimensions except source. C introduces an entire
        # new tuple on an already seen yaw; flattening dimensions is incorrect.
        def rec(x,score,sources,yaw=0,z='0'):
            return dict(action_key=['p','2','2','2',str(yaw),str(x),'0',z],
                        geometry_score=score,sources=sources,
                        candidate={'support':{'support_item_ids':[]}})
        pool=[rec(i,100-i,['EMS_STYLE_3D']) for i in range(20)]
        pool.append(rec(-1,0,['EMS_STYLE_3D','SURFACE_CORNER']))
        pool.append(rec(30,1,['EMS_STYLE_3D'],yaw=90))
        final,audit=reduce_candidates(pool)
        self.assertEqual(audit['selection_order'][0]['action_key'],pool[0]['action_key'])
        self.assertEqual(audit['selection_order'][1]['action_key'],pool[-1]['action_key'])
        self.assertEqual(audit['selection_order'][2]['action_key'],pool[-2]['action_key'])
        self.assertEqual(len(final),16)
        self.assertEqual(len(audit['raw_joint_keys']),4)
        self.assertEqual(audit['uncovered_joint_keys'],[])

    def test_atomic_budget_fault_double(self):
        r=_generate(encode(SCENES['empty']),_point_limit=19)
        self.assertEqual(r['error']['code'],'GEOMETRY_BUDGET_EXCEEDED'); self.assertEqual(r['candidates'],[])
        self.assertEqual(r['audit']['items'][0]['raw_point_attempts'],19)
        self.assertNotEqual(_generate(encode(SCENES['empty']),_point_limit=20)['status'],'ERROR')

    def test_real_height_check_disagreement(self):
        # Original evaluate_pose rounds max_height to 3 decimals; independent
        # oracle compares to the unrounded 2.0004 height at 1e-6 tolerance.
        # Preserve both originals: this must be ERROR, never a filtered pool.
        r=generate(encode(scene(buffer=[item(h=2.0004)])))
        self.assertEqual(r['error']['code'],'PHYSICAL_CHECK_DISAGREEMENT')
        self.assertIn('max_height_mismatch',r['audit']['items'][0]['check_disagreement']['errors'])
        self.assertEqual(r['candidates'],[])

    def test_atomic_oracle_fault_double(self):
        with patch('semantic_pallet_planner.planner.space_candidates.generator.check_candidate',return_value=['INJECTED_TEST_ONLY']):
            r=generate(encode(SCENES['empty']))
        self.assertEqual(r['error']['code'],'PHYSICAL_CHECK_DISAGREEMENT');self.assertEqual(r['candidates'],[])

    def test_cavity_and_multilayer_load(self):
        left=placed('left',-2,0,0,6,8,2,capacity=2)
        right=placed('right',4,0,0,2,8,2,capacity=2)
        bridge=placed('bridge',0,0,2,10,8,2)
        left['supported_load_kg']=0.75
        right['supported_load_kg']=0.25
        bridge['support_fractions']=[dict(item_id='left',fraction=0.75),dict(item_id='right',fraction=0.25)]
        s=scene([left,right,bridge],[item(l=2,w=2,h=1,mass=4)])
        r=self.run_scene(s)
        # Width-2 cavity between pillars, floor at 0, roof at 2. No drop.
        self.assertTrue(any(c['pose']['x_mm']==2 and c['pose']['z_base_mm']==0 for c in r['candidates']))
        self.assertGreater(r['audit']['items'][0]['rejection_counts'].get('overload',0),0)
        s=scene([placed('base',-2,0,0,6,10,2)],[item(l=10,w=10)])
        r=self.run_scene(s)
        self.assertGreater(r['audit']['items'][0]['rejection_counts'].get('insufficient_support',0),0)

    def test_input_rejection(self):
        for field in ('mass_kg','top_load_limit_kg_synthetic','stackable'):
            s=copy.deepcopy(SCENES['empty']);del s['buffer_items'][0][field]
            self.assertEqual(generate(encode(s))['status'],'ERROR')
        self.assertEqual(generate(SCENES['empty'])['status'],'ERROR')
        self.assertEqual(generate(b'{"version":1e9999999999999999999999999}')['status'],'ERROR')
        s=copy.deepcopy(SCENES['empty']);s['future_items']=[]
        self.assertEqual(generate(encode(s))['status'],'ERROR')

if __name__=='__main__': unittest.main()
