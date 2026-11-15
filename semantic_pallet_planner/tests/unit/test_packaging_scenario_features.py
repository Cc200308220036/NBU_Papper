"""JM2-A1 pure-public tests. No candidate generation, episode, network or solver."""
import copy
import importlib.abc
import json
import math
from pathlib import Path
import sys
import unittest


BLOCKED=('semantic_pallet_planner.o4','semantic_pallet_planner.planner',
         'semantic_pallet_planner.jev_select.episode','semantic_pallet_planner.jev_select.transport',
         'semantic_pallet_planner.jev_select.execution','semantic_pallet_planner.jev_select.selector',
         'semantic_pallet_planner.jev_select.packaging_runtime',
         'semantic_pallet_planner.jev_select.stability','numpy','scipy')


class NoDispatchImports(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==p or fullname.startswith(p+'.') for p in BLOCKED):
            raise AssertionError('FORBIDDEN_IMPORT:'+fullname)


sys.meta_path.insert(0,NoDispatchImports())


def no_side_effects(event,args):
    if event in ('socket.connect','socket.bind','subprocess.Popen','os.system'):
        raise AssertionError('FORBIDDEN_DISPATCH:'+event)
    if event=='open' and isinstance(args[0],(str,bytes)):
        path=str(args[0]).lower()
        if any(k in path for k in ('api_key.md','api key.md','credentials','.aws/')):
            raise AssertionError('FORBIDDEN_CREDENTIAL_READ')


sys.addaudithook(no_side_effects)
from semantic_pallet_planner.jev_select import packaging_scenario_features as m

ROOT=Path(__file__).resolve().parents[3]
C1=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_C1_REAL_BASELINES_20261112_01'
B2=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01'


def fixture():
    box=lambda key:dict(item_id=key,size_mm=[10,20,10],mass_kg=1,max_top_load_kg=5,stackable=True)
    p1=box('p1')|dict(pose=dict(x_mm=-40,y_mm=0,z_base_mm=0,yaw_deg=0),oriented_size_mm=[10,20,10],area_current_top_load_kg=0,area_remaining_top_load_kg=5)
    p2=box('p2')|dict(pose=dict(x_mm=-20,y_mm=0,z_base_mm=0,yaw_deg=0),oriented_size_mm=[10,20,10],area_current_top_load_kg=0,area_remaining_top_load_kg=5)
    state=dict(container=dict(length_mm=200,width_mm=200,max_height_mm=200,max_payload_kg=100),buffer=[box('a'),box('b')],placed_objects=[p1,p2])
    def action(cid,key,x,z=0,yaw=0):
        return dict(candidate_id=cid,pick_item_id=key,pose=dict(x_mm=x,y_mm=0,z_base_mm=z,yaw_deg=yaw),oriented_size_mm=[10,20,10] if yaw==0 else [20,10,10])
    pool=[action('a0','a',0),action('a1','a',10),action('b0','b',0,30),action('ar','a',0,0,90)]
    return m.make_input(state,pool,expected_pool_count=len(pool),expected_pool_digest=m.digest(pool))


def remake(view):
    return m.make_input(view['state'],view['pool'],expected_pool_count=len(view['pool']) if view['pool'] is not None else None,expected_pool_digest=m.digest(view['pool']) if view['pool'] is not None else None)


class ScenarioTests(unittest.TestCase):
    def test_real_saved_and_current_share_function_and_entire_population(self):
        plan=json.loads((C1/'fork_plan.json').read_text())
        for point in plan['points']:
            with self.subTest(point=point['point_id']):
                location=point['public_evidence_location'];state=json.loads(Path(location['prefix_ref']['path']).read_text());pool=json.loads(Path(location['pool_ref']['path']).read_text())
                historic=m.from_saved_public(state,pool,expected_pool_count=len(pool),expected_raw_pool_digest=m.digest(pool))
                baseline=Path(location['export_root']).name
                context=json.loads((B2/'materials/future_runs'/baseline/'ledger/contexts'/(point['decision_id']+'.json')).read_text())
                current=m.from_current_public(context['model_state'],context['criteria'],expected_candidate_labels=list(context['display_mapping']))
                a=m.build_signature(historic);b=m.build_signature(current)
                self.assertEqual(a['features'],b['features']);self.assertEqual(a['stage'],'NONEMPTY')
                self.assertEqual(a['features']['candidate_count']['value'],len(pool))
                expected=sum(c['pose']['z_base_mm']+c['oriented_size_mm'][2] for c in pool)/len(pool)
                self.assertEqual(a['features']['candidate_mean_top_mm']['value'],expected)
                self.assertEqual(set(a['features']),set(m.feature_spec()['features']))
                binding=m.bind_contrast(historic,point['branches'][0]['candidate_id'],point['branches'][1]['candidate_id'],current=current)
                self.assertIn(binding['status'],('BOUND_DIAGNOSTIC_ONLY','AMBIGUOUS_DIAGNOSTIC'))
                self.assertIn({'A':point['branches'][0]['label'],'B':point['branches'][1]['label']},binding['correspondence_pairs'])
                self.assertFalse(binding['execution_eligible'])

    def test_equal_buffer_means_different_structure(self):
        a=fixture();b=copy.deepcopy(a);b['state']['placed_objects'][1]['pose'].update(x_mm=-40,z_base_mm=10)
        sa,sb=m.build_signature(a),m.build_signature(b)
        for key in sa['features']:
            if key.startswith('buffer_'):self.assertEqual(sa['features'][key],sb['features'][key])
        self.assertEqual(sa['features']['placed_exact_face_contact_count']['value'],0)
        self.assertEqual(sb['features']['placed_exact_face_contact_count']['value'],1)
        self.assertNotEqual(sa['features']['placed_projection_union_ratio'],sb['features']['placed_projection_union_ratio'])
        self.assertEqual(m.bind_contrast(a,'a0','a1',current=b)['status'],'STRUCTURE_MISMATCH')

    def test_missing_structure_is_missing_and_refused(self):
        v=fixture();del v['state']['placed_objects'][0]['pose']
        s=m.build_signature(v)
        self.assertEqual(s['features']['placed_projection_union_ratio']['status'],'MISSING')
        self.assertIsNone(s['features']['placed_projection_union_ratio']['value'])
        self.assertEqual(m.bind_contrast(v,'a0','a1')['status'],'MISSING_REQUIRED_FEATURE')

    def test_missing_pool_differs_from_empty_and_subset_is_rejected(self):
        v=fixture();subset=copy.deepcopy(v);subset['pool']=subset['pool'][:2]
        with self.assertRaisesRegex(m.ScenarioError,'INCOMPLETE_OR_CHANGED_POOL'):m.build_signature(subset)
        missing=m.make_input(v['state'],None);s=m.build_signature(missing)
        self.assertEqual(s['features']['candidate_count']['status'],'MISSING')
        self.assertIsNone(s['features']['candidate_count']['value'])
        empty=m.make_input(v['state'],[],expected_pool_count=0,expected_pool_digest=m.digest([]))
        self.assertEqual(m.build_signature(empty)['features']['candidate_count']['value'],0)
        self.assertEqual(m.build_signature(empty)['features']['candidate_mean_top_mm']['status'],'NOT_APPLICABLE')

    def test_full_pool_statistics_are_not_two_action_statistics(self):
        v=fixture();s=m.build_signature(v)
        self.assertEqual(s['features']['candidate_mean_top_mm']['value'],17.5)
        self.assertNotEqual(s['features']['candidate_mean_top_mm']['value'],10)

    def test_current_effective_permission_is_not_area_capacity(self):
        state=dict(container=fixture()['state']['container'],available_objects=[],
                   placed_objects=[dict(object_id='P',dimensions_mm=dict(length=10,width=20,height=10),
                     mass_kg=1,max_top_load_kg=5,current_top_load_kg=0,
                     remaining_top_load_kg=0,effective_top_permission_kg=0,stackable=False,
                     oriented_size_mm=[10,20,10],pose=dict(x_mm=0,y_mm=0,z_base_mm=0,yaw_deg=0))],
                   coordinate_convention=m.COORDINATE)
        v=m.from_current_public(state,{},expected_candidate_labels=[])
        self.assertEqual(v['state']['placed_objects'][0]['area_remaining_top_load_kg'],5)
        self.assertEqual(m.build_signature(v)['features']['placed_gross_stackable_face_area_mm2']['value'],0)
        del state['placed_objects'][0]['current_top_load_kg']
        v=m.from_current_public(state,{},expected_candidate_labels=[])
        self.assertEqual(m.build_signature(v)['features']['placed_area_remaining_top_load_sum_kg']['status'],'MISSING')

    def test_intervention_identity_rotation_translation_and_cross_box(self):
        v=fixture()
        self.assertEqual(m.bind_contrast(v,'a0','a1')['intervention'],'SAME_BOX_TRANSLATION')
        self.assertEqual(m.bind_contrast(v,'a0','ar')['intervention'],'SAME_BOX_ROTATION')
        both=copy.deepcopy(v);both['pool'][3]['pose']['x_mm']=20;both=remake(both)
        self.assertEqual(m.bind_contrast(both,'a0','ar')['intervention'],'SAME_BOX_TRANSLATION_AND_ROTATION')
        self.assertEqual(m.bind_contrast(v,'a0','b0')['intervention'],'CROSS_BOX_SELECTION')
        self.assertEqual(m.bind_contrast(v,'a0','a0')['intervention'],'IDENTICAL_ACTION')
        current=copy.deepcopy(v);current['pool']=[v['pool'][0],v['pool'][2]];current=remake(current)
        self.assertEqual(m.bind_contrast(v,'a0','a1',current=current)['status'],'NO_CORRESPONDENCE')

    def test_same_attributes_distinct_box_roles_and_alias_invariance(self):
        v=fixture();out=m.bind_contrast(v,'a0','b0')
        self.assertNotEqual(out['roles']['A']['box_role'],out['roles']['B']['box_role'])
        renamed=copy.deepcopy(v)
        for b in renamed['state']['buffer']:b['item_id']='anon_'+b['item_id']
        for c in renamed['pool']:c['pick_item_id']='anon_'+c['pick_item_id']
        renamed=remake(renamed)
        self.assertEqual(m.build_signature(v)['features'],m.build_signature(renamed)['features'])
        duplicate=copy.deepcopy(v);duplicate['state']['buffer'][1]['item_id']='a'
        with self.assertRaisesRegex(m.ScenarioError,'DUPLICATE_OBJECT_ID'):m.build_signature(duplicate)

    def test_all_correspondences_and_no_input_mutation(self):
        v=fixture();extra=copy.deepcopy(v['pool'][0]);extra['candidate_id']='a2';extra['pose']['x_mm']=20;v['pool'].append(extra);v=remake(v)
        before=copy.deepcopy(v);out=m.bind_contrast(v,'a0','a1')
        self.assertEqual(v,before);self.assertTrue(out['ambiguity'])
        self.assertIn(dict(A='a0',B='a1'),out['correspondence_pairs'])
        self.assertIn(dict(A='a1',B='a2'),out['correspondence_pairs'])
        self.assertEqual(out['corresponding_candidates']['A'],['a0','a1'])

    def test_missing_role_attributes_and_public_only_boundary(self):
        v=fixture();del v['state']['buffer'][0]['stackable'];s=m.build_signature(v)
        self.assertIsNone(s['features']['buffer_stackable_fraction']['value'])
        self.assertEqual(m.bind_contrast(v,'a0','b0')['status'],'MISSING_REQUIRED_FEATURE')
        for field in ('future_items','pct_reactions','terminal_metrics'):
            v=fixture();v['state'][field]=[]
            with self.assertRaises(m.ScenarioError):m.build_signature(v)

    def test_numeric_coordinate_schema_and_immutability_guards(self):
        for change in ('nan','extra','coordinate','unknown_version'):
            v=fixture()
            if change=='nan':v['state']['buffer'][0]['mass_kg']=float('nan')
            elif change=='extra':v['pool'][0]['pct_status']='STABLE'
            elif change=='coordinate':v['coordinate']='corner_origin'
            else:v['version']='unregistered'
            with self.assertRaises(m.ScenarioError):m.build_signature(v)

    def test_rotation_invalid_shapes_refused(self):
        for key,value in [('yaw_deg',45),('yaw_deg',90)]:
            v=fixture();v['pool'][0]['pose'][key]=value
            with self.assertRaises(m.ScenarioError):remake(v)

    def test_empty_scene_and_unimplemented_features_are_not_rules(self):
        v=fixture();v['state']['placed_objects']=[];v['state']['buffer']=[];v['pool']=[];v=remake(v)
        out=m.build_signature(v);self.assertEqual(out['stage'],'OPENING')
        self.assertEqual(out['features']['placed_projection_union_ratio']['value'],0)
        self.assertEqual(out['features']['buffer_mean_mass_kg']['status'],'NOT_APPLICABLE')
        self.assertFalse(set(m.UNIMPLEMENTED)&set(m.STRUCTURAL_KEYS))
        self.assertTrue(all(x['excluded_from_rules'] for x in m.feature_spec()['not_implemented'].values()))

    def test_central_schema_route_and_legacy_nonempty_guard(self):
        from semantic_pallet_planner.jev_select.contracts import validate_schema,JevSelectError
        from semantic_pallet_planner.jev_select import packaging_experience as old
        v=fixture();s=m.build_signature(v);b=m.bind_contrast(v,'a0','a1')
        for value in (v,s,b):validate_schema(m.JM_SCENARIO_SCHEMAS[value['version']],value)
        bad=copy.deepcopy(s);bad['features']['candidate_count']['value']=None
        with self.assertRaises(JevSelectError):validate_schema('jm_scenario_signature_v1',bad)
        attrs=dict(dimensions_mm=dict(length=10,width=20,height=10),mass_kg=1,stackable=True,top_load_limit_kg_synthetic=5)
        action=dict(item_attributes=attrs,oriented_size_mm=[10,20,10],pose=dict(x_mm=0,y_mm=0,z_base_mm=0,yaw_deg=0))
        facts={k:0 for k in old.RULE['historical_result_budget']['metrics']}
        row=dict(observable_conditions=dict(container=v['state']['container'],buffer_capacity=3,buffer=[attrs],placed=[{}],reference_action=action,alternative_action=action),facts_reference=facts,facts_alternative=facts,facts_delta=facts)
        with self.assertRaisesRegex(JevSelectError,'memory_nonempty_history_projection_not_supported'):old.historical_fragment(row)


if __name__=='__main__':unittest.main()
