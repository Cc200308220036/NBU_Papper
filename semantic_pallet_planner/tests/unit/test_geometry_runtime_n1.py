"""Limited N1 constructions, no order runner, selection, PCT or model imports."""
import copy
import json
import math
from pathlib import Path
import unittest
from decimal import Decimal
from fractions import Fraction
from unittest.mock import patch

from semantic_pallet_planner.jev_select import geometry_runtime_contracts as c
from semantic_pallet_planner.jev_select.geometry_runtime_input import (
    capture_current_public_snapshot_v1 as capture, validate_runtime_snapshot_v1 as validate,
    runtime_config,
)
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.packaging_runtime import INSTRUCTION
from semantic_pallet_planner.o4.extensions.e2.protocol import observation
from semantic_pallet_planner.planner.space_candidates.generator import generate, publish, _physical_number
from semantic_pallet_planner.planner.space_candidates.runtime_generator import generate_runtime_snapshot_v1 as runtime_generate
from semantic_pallet_planner.planner.space_candidates.contracts import GeometryError
from test_space_candidates_gp2 import SCENES, scene, item, placed, encode

IDENTITIES = {k:digest('N1_CONSTRUCTED_ONLY_' + k) for k in c.IDENTITY_KEYS}


def current_scene(source=None):
    """Direct hand state, not a replay or a real-source order."""
    source = copy.deepcopy(SCENES['empty'] if source is None else source)
    container = dict(source['container'],container_id='N1_constructed',coordinate_frame='container_bottom_center')
    def aliases(p):
        return dict(p,fragile=False,weight_class='light',product_category='general')
    boxes = [aliases(p) for p in source['placed_items']]
    pending = []
    for i,p in enumerate(source['buffer_items']):
        p.pop('arrival_index')
        pending.append({'item':aliases(p),'slot':i,'arrival_index':len(boxes)+i})
    objects = boxes + [p['item'] for p in pending]
    attrs = {p['item_id']:{'object_id':p['item_id'],'cargo_category':'general',
             'packaging':{'reinforced':False},'labels':{'no_top_load':not p['stackable'],
             'max_top_load_kg':p['top_load_limit_kg_synthetic']},
             'physical_top_load_limit_kg':p['top_load_limit_kg_synthetic']} for p in objects}
    return {'container':container,'buffer_capacity':3,'pending_items':pending,'placed_items':boxes,
            'arrived_ids':[p['item_id'] for p in objects],'attributes':attrs,
            'arrival_count':len(objects),'placed_count':len(boxes),'event_index':len(objects)+len(boxes),
            'end_of_stream':True}


def snapshot(s):
    return capture(s,observation(s,INSTRUCTION,[]),profile=c.PROFILE,identities=IDENTITIES)


def run_runtime(s):
    n,g,b = snapshot(s)
    return runtime_generate(g,native_snapshot_raw=n,binding=b,identities=IDENTITIES)


def rounded_ledger_scene():
    bases=[placed('s'+str(i),x,0,0,2,6,2) for i,x in enumerate((-2,0,2))]
    for base in bases:
        base['supported_load_kg']=round(1/3,3)
    top=placed('top',0,0,2,6,6,2)
    top['support_fractions']=[{'item_id':p['item_id'],'fraction':round(1/3,9)} for p in bases]
    return current_scene(scene(bases+[top]))


class RuntimeN1(unittest.TestCase):
    def rejected(self, call, code=None):
        with self.assertRaises(GeometryError) as raised:
            call()
        if code:
            self.assertEqual(raised.exception.code,code)
        return raised.exception

    def test_native_bits_types_and_closed_projection(self):
        s = current_scene(scene([placed('base',0.0,-0.0,0,2,2,2)]))
        s['extra_environment_private'] = {'ignored':True}
        s['placed_items'][0]['internal_debug'] = 'discard'
        before = c.encode(s)
        n,g,b = snapshot(s)
        self.assertEqual(c.encode(s),before)
        v = validate(n,g,b,identities=IDENTITIES,current_state=s,observation=observation(s,INSTRUCTION,[]))
        self.assertEqual(v['geometry']['payload']['placed_items'][0]['pose']['y_mm'],'0')
        self.assertTrue(c.same_native(c.decode(n)['current_state']['placed_items'][0]['pose']['y_mm'],-0.0))
        self.assertFalse(c.same_native(-0.0,0.0));self.assertFalse(c.same_native(1,1.0))
        self.assertEqual(c.encode(c.decode(n)),n)
        bad=c.decode(n);bad['unknown']=True
        self.rejected(lambda:validate(c.encode(bad),g,b,identities=IDENTITIES))
        bad=c.decode(n);bad['current_state']['placed_items'][0]['unknown']=True
        self.rejected(lambda:validate(c.encode(bad),g,b,identities=IDENTITIES))

    def test_missing_wrong_types_and_no_defaults(self):
        req=observation(current_scene(),INSTRUCTION,[])
        for key in ('mass_kg','stackable','top_load_limit_kg_synthetic'):
            s=current_scene();del s['pending_items'][0]['item'][key]
            self.rejected(lambda:capture(s,req,profile=c.PROFILE,identities=IDENTITIES),'RUNTIME_INPUT_MISSING_FIELD')
        for value in (True,float('inf'),float('nan'),Decimal('1'),2**53+1):
            s=current_scene();s['pending_items'][0]['item']['mass_kg']=value
            self.rejected(lambda:capture(s,req,profile=c.PROFILE,identities=IDENTITIES))
        for value in (0.0,True):
            s=current_scene();s['pending_items'][0]['arrival_index']=value
            self.rejected(lambda:capture(s,req,profile=c.PROFILE,identities=IDENTITIES))
        s=current_scene();s['pending_items'][0]['item']['dimensions_mm']['future']=2
        self.rejected(lambda:capture(s,req,profile=c.PROFILE,identities=IDENTITIES))

    def test_duplicate_keys_and_numeric_conversion_boundaries(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":{"y":0,"y":1}}',b'{"x":NaN}'):
            self.rejected(lambda:c.decode(raw))
        self.rejected(lambda:c.decode(b'{"x":1e-999}'),'RUNTIME_NUMBER_UNREPRESENTABLE')
        self.rejected(lambda:c.decode(b'{"x":1e999}'),'RUNTIME_NUMBER_UNREPRESENTABLE')
        self.rejected(lambda:c.native_number(2**53+1),'RUNTIME_NUMBER_UNREPRESENTABLE')
        self.assertEqual(c.native_number(2**54),2**54)
        self.assertEqual(float(c.numeric_text(math.ulp(0.0))),math.ulp(0.0))
        n,g,b=snapshot(current_scene())
        self.rejected(lambda:validate(n[:-1]+b',"version":"duplicate"}',g,b,identities=IDENTITIES))
        self.rejected(lambda:validate(n,g+b' ',b,identities=IDENTITIES),'RUNTIME_SNAPSHOT_MISMATCH')

    def test_profile_identity_and_each_frozen_dimension_drift(self):
        s=current_scene();n,g,b=snapshot(s)
        for key in c.BINDING_KEYS-{'version','record_digest'}:
            bad=copy.deepcopy(b);bad[key]='different'
            self.rejected(lambda:validate(n,g,bad,identities=IDENTITIES),'RUNTIME_SNAPSHOT_MISMATCH')
        for key in IDENTITIES:
            changed=dict(IDENTITIES);changed[key]=digest('changed')
            self.rejected(lambda:validate(n,g,b,identities=changed),'RUNTIME_SNAPSHOT_MISMATCH')
        bad=c.decode(g);bad['profile']='geometry_runtime_binary64_exact_v1'
        self.rejected(lambda:validate(n,c.encode(bad),b,identities=IDENTITIES))
        config=runtime_config();config['generator']['budgets']['active_spaces']+=1
        self.rejected(lambda:validate(n,g,b,identities=IDENTITIES,config=config))

    def test_leaf_derivation_even_with_rehashed_geometry(self):
        n,g,b=snapshot(current_scene())
        for mutate in (lambda x:x['payload']['buffer_items'][0].update(mass_kg='2'),
                       lambda x:x['payload']['buffer_items'][0].update(future='1'),
                       lambda x:x['payload']['buffer_items'][0].update(arrival_index=0.0),
                       lambda x:x['payload']['buffer_items'][0]['dimensions_mm'].update(length='2.0')):
            bad=c.decode(g);mutate(bad);raw=c.encode(bad);binding=copy.deepcopy(b)
            binding['geometry_input_sha256']=c.sha(raw)
            binding['record_digest']=digest({k:v for k,v in binding.items() if k!='record_digest'})
            self.rejected(lambda:validate(n,raw,binding,identities=IDENTITIES),'RUNTIME_SNAPSHOT_MISMATCH')

    def test_external_state_type_sign_and_ulp_drift(self):
        s=current_scene(scene([placed('base',-0.0,0,0,2,2,2)]));n,g,b=snapshot(s)
        for change in ('sign','type','ulp','load'):
            fresh=copy.deepcopy(s)
            if change=='sign':fresh['placed_items'][0]['pose']['x_mm']=0.0
            if change=='type':fresh['container']['length_mm']=10.0
            if change=='ulp':fresh['pending_items'][0]['item']['mass_kg']=math.nextafter(1.0,math.inf)
            if change=='load':fresh['placed_items'][0]['supported_load_kg']=0.0001
            self.rejected(lambda:validate(n,g,b,identities=IDENTITIES,current_state=fresh,
                                          observation=observation(fresh,INSTRUCTION,[])),'RUNTIME_SNAPSHOT_MISMATCH')

    def test_profile_math_without_snapping(self):
        self.assertEqual(c.numeric_text(0.0005),'0.0005')
        self.assertEqual(publish(Fraction(Decimal(c.numeric_text(0.0005)))),0)
        self.assertEqual(publish(Fraction(0.0005)),Fraction('0.001'))
        self.assertNotEqual(c.numeric_text(0.1+0.2),c.numeric_text(0.3))

    def test_runtime_generation_and_original_entry_is_not_used(self):
        s=current_scene();before=c.encode(s);n,g,b=snapshot(s)
        with patch('semantic_pallet_planner.planner.space_candidates.generator.adapt',side_effect=AssertionError('old adapt called')):
            r=runtime_generate(g,native_snapshot_raw=n,binding=b,identities=IDENTITIES)
        self.assertEqual(r['status'],'OK',r['error']);self.assertEqual(len(r['candidates']),10)
        self.assertEqual(c.encode(s),before)
        self.assertTrue(all(x['candidate_id'].startswith('GR1_') for x in r['candidates']))
        self.assertEqual(r,runtime_generate(g,native_snapshot_raw=n,binding=b,identities=IDENTITIES))
        self.assertEqual(generate(g)['status'],'ERROR')

    def test_empty_and_real_height_error_not_fallback(self):
        empty=run_runtime(current_scene(scene(buffer=[item(mass=1001)])))
        self.assertEqual(empty['status'],'OK_EMPTY');self.assertEqual(empty['candidates'],[])
        failed=run_runtime(current_scene(scene(buffer=[item(h=2.0004)])))
        self.assertEqual(failed['status'],'ERROR')
        self.assertEqual(failed['error']['code'],'PHYSICAL_CHECK_DISAGREEMENT')
        self.assertEqual(failed['candidates'],[])

    def test_real_core_numeric_underflow_and_invalid_binding_are_errors(self):
        # Exercise the actual exact->physics boundary, not a forced checker.
        # A smallest-subnormal scene need not reach this boundary: prior original
        # checks may reject its proposals normally. Do not label that an error.
        self.rejected(lambda:_physical_number(Fraction(1,10**400),True),
                      'RUNTIME_NUMBER_UNREPRESENTABLE')
        n,g,b=snapshot(current_scene())
        for config in ({},dict(runtime_config(),profile='other')):
            r=runtime_generate(g,native_snapshot_raw=n,binding=b,identities=IDENTITIES,config=config)
            self.assertEqual(r['status'],'ERROR');self.assertEqual(r['candidates'],[])
        bad=dict(b,record_digest=float('nan'))
        r=runtime_generate(g,native_snapshot_raw=n,binding=bad,identities=IDENTITIES)
        self.assertEqual(r['status'],'ERROR');self.assertEqual(r['candidates'],[])
        c.encode(r)

    def test_exact_prefix_conflict_rejected_without_changing_old_tolerance(self):
        a=placed('a',0,0,0,4,4,2)
        b=placed('b',0,0,1.9999999999999998,4,4,2)
        b['support_fractions']=[{'item_id':'a','fraction':1.0}]
        a['supported_load_kg']=1
        s=current_scene(scene([a,b]));req=observation(s,INSTRUCTION,[])
        self.rejected(lambda:capture(s,req,profile=c.PROFILE,identities=IDENTITIES),
                      'RUNTIME_EXACT_STATE_CONFLICT')

    def test_old_entry_complete_saved_semantics_order_and_audit(self):
        root=Path(__file__).resolve().parents[2]/'outputs/GEOM_CANDIDATES_GP2_20261117_01'
        for name in ('empty','platform','noninteger'):
            with self.subTest(name=name):
                raw=(root/'constructed'/f'{name}_input.json').read_bytes()
                expected=json.loads((root/'constructed'/f'{name}_result.json').read_bytes())
                self.assertEqual(c.encode(generate(raw)),c.encode(expected))

    def test_saved_and_rebuilt_ledger_are_separate(self):
        rounded=rounded_ledger_scene();original=c.encode(rounded)
        result=run_runtime(rounded)
        self.assertNotEqual(result['status'],'ERROR',result['error'])
        views=result['audit']['ledger_views']
        self.assertEqual(views['saved'][0]['supported_load_kg'],0.333)
        self.assertEqual(views['rebuilt'][0]['supported_load_kg'],1/3)
        self.assertEqual(c.encode(rounded),original)
        base=placed('base',0,0,0,8,8,2);base['supported_load_kg']=1
        top=placed('top',0,0,2,8,8,2)
        top['support_fractions']=[{'item_id':'base','fraction':1.0}]
        s=current_scene(scene([base,top]));before=c.encode(s)
        r=run_runtime(s)
        self.assertNotEqual(r['status'],'ERROR',r['error'])
        self.assertEqual(c.encode(s),before)
        self.assertIn('saved',r['audit']['ledger_views']);self.assertIn('rebuilt',r['audit']['ledger_views'])
        s['placed_items'][0]['supported_load_kg']=7
        r=run_runtime(s)
        self.assertEqual(r['status'],'ERROR');self.assertEqual(r['candidates'],[])


if __name__=='__main__':unittest.main()
