"""Offline A2: saved coordinates, roles/outcomes, closed boundaries and old guard."""
import copy
import json
from pathlib import Path
import unittest
import test_packaging_scenario_features as guards  # installs no-dispatch guard first
from semantic_pallet_planner.jev_select import packaging_t_projection as m

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'semantic_pallet_planner/outputs/JEV_JM2_A2_20261115_01'
A1=ROOT/'semantic_pallet_planner/outputs/JEV_JM2_A1_20261115_01'


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.cards=json.loads((OUT/'case_snapshot_candidate.json').read_text())['cards']
        self.index=json.loads((OUT/'private_audit_index.json').read_text())['cards']

    def test_saved_coordinates_roles_and_all_results(self):
        for card,entry in zip(self.cards,self.index):
            h=json.loads((ROOT/entry['a1_input']['path']).read_text())
            for role in ('A','B'):
                first=entry['pairs'][0]['branches'][role]
                b=json.loads((ROOT/first['path']).read_text())
                a=card['actions'][role]
                for k in ('pose','oriented_size_mm'):
                    if k=='pose':self.assertEqual({x:float(v) for x,v in b['exact_action'][k].items()},a[k])
                    else:self.assertEqual(list(map(float,b['exact_action'][k])),a[k])
                box=next(x for x in card['structure']['buffer'] if x['box_role']==a['box_role'])
                self.assertEqual(box['size_mm'],[a['attributes'][k] for k in ('length_mm','width_mm','height_mm')])
            self.assertEqual(m.query_projection(h)['features'],card['features'])
            for row,pair in zip(card['observations'],entry['pairs']):
                for role in ('A','B'):
                    b=json.loads((ROOT/pair['branches'][role]['path']).read_text())
                    for k,v in row[role].items():self.assertEqual(v,b['metrics'][k])
                for k in m.METRICS:self.assertEqual(row['B'][k]-row['A'][k],row['delta_B_minus_A'][k])

    def test_conflict_neutral_negative_and_single_remain(self):
        self.assertEqual([c['evidence_grade'] for c in self.cards],[
            'CONFLICTING_LOCAL_OBSERVATIONS','REPLICATED_LOCAL_OBSERVATION',
            'REPLICATED_LOCAL_OBSERVATION','PROVISIONAL_CASE','REPLICATED_LOCAL_OBSERVATION'])
        self.assertTrue(self.cards[0]['repeat_conflict'])
        self.assertEqual(len(self.cards[3]['observations']),1)
        self.assertEqual([r['label'] for c in self.cards for r in c['observations']].count('degraded'),3)
        self.assertEqual([r['label'] for c in self.cards for r in c['observations']].count('neutral'),2)
        self.assertLess(self.cards[0]['observations'][0]['delta_B_minus_A']['actual_height_mm'],0)
        self.assertGreater(self.cards[0]['observations'][1]['delta_B_minus_A']['actual_height_mm'],0)
        self.assertTrue(all(c['cross_start_support']==0 and not c['execution_eligible'] for c in self.cards))

    def test_real_alias_relationship_matches_exact_object_identity(self):
        for c,e in zip(self.cards,self.index):
            h=json.loads((ROOT/e['a1_input']['path']).read_text())
            b=json.loads((ROOT/e['role_binding_diagnostic']['path']).read_text())
            self.assertEqual(c['actions']['A']['box_role']==c['actions']['B']['box_role'],
                             b['roles']['A']['exact_action']['pick_item_id']==b['roles']['B']['exact_action']['pick_item_id'])
            self.assertGreater(len(b['correspondence_pairs']),1)
            self.assertNotIn('correspondence_pairs',c)
            self.assertEqual(c['sufficiency_review'],'NOT_RUN_A3')

    def test_central_closed_schema_routes(self):
        try:
            from semantic_pallet_planner.jev_select.contracts import schema_validator
        except ModuleNotFoundError as e:
            if e.name=='jsonschema':self.skipTest('NOT_RUN missing jsonschema')
            raise
        for c in self.cards:schema_validator('jm_t_projection_v1').validate(c)
        h=json.loads((ROOT/self.index[0]['a1_input']['path']).read_text())
        q=m.query_projection(h);schema_validator('jm_t_query_v1').validate(q)
        for key in ('observations','future_boxes','test_score','pct_diagnostics','answer'):
            bad=copy.deepcopy(q);bad[key]=[]
            self.assertFalse(schema_validator('jm_t_query_v1').is_valid(bad))
        bad=copy.deepcopy(self.cards[0]);bad['trajectory']=[]
        self.assertFalse(schema_validator('jm_t_projection_v1').is_valid(bad))

    def test_coordinate_orientation_identity_and_result_tampering_refused(self):
        changes=[('coordinate',lambda c:c['actions']['A']['pose'].update(x_mm=123)),
                 ('orientation',lambda c:c['actions']['A']['pose'].update(yaw_deg=90)),
                 ('identity',lambda c:c['actions']['A'].update(box_role='unknown_box')),
                 ('direction',lambda c:c['observations'][0]['delta_B_minus_A'].update(placed_items=999)),
                 ('dimensions',lambda c:c['actions']['A'].update(oriented_size_mm=[1,2]))]
        for name,change in changes:
            with self.subTest(name=name):
                bad=copy.deepcopy(self.cards[0]);change(bad)
                with self.assertRaises(ValueError):m.validate(bad)

    def test_old_nonempty_guard_still_refuses(self):
        try:
            from semantic_pallet_planner.jev_select import packaging_experience as old
        except ModuleNotFoundError as e:
            if e.name=='jsonschema':self.skipTest('NOT_RUN missing jsonschema')
            raise
        attrs=dict(dimensions_mm=dict(length=10,width=20,height=10),mass_kg=1,stackable=True,top_load_limit_kg_synthetic=5)
        action=dict(item_attributes=attrs,oriented_size_mm=[10,20,10],pose=dict(x_mm=0,y_mm=0,z_base_mm=0,yaw_deg=0))
        o=dict(container=dict(length_mm=100,width_mm=100,max_height_mm=100,max_payload_kg=100),buffer_capacity=2,buffer=[attrs],placed=[{}],reference_action=action,alternative_action=action)
        row=dict(observable_conditions=o,**{k:{x:0 for x in old.RULE['historical_result_budget']['metrics']} for k in ('facts_reference','facts_alternative','facts_delta')})
        with self.assertRaisesRegex(old.JevSelectError,'memory_nonempty_history_projection_not_supported'):old.historical_fragment(row)

if __name__=='__main__':unittest.main()
