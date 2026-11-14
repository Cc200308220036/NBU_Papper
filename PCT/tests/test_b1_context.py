"""B11 construction tests: no order engine, candidate generation, transport or LP."""
import copy
import unittest
from pct_baseline.protocol import validate_observed


class ObservedBoundaryTests(unittest.TestCase):
    def observation(self):
        return {'buffer_context':{'capacity':1,'pending':[{'object_id':'CURRENT','slot':0,'arrival_index':4}],
                                 'end_of_stream':False},
                'available_objects':[{'object_id':'CURRENT'}],'placed_objects':[{'object_id':'PLACED'}]}

    def test_last_box_and_eos_after_last(self):
        observed=self.observation();validate_observed(observed)
        eos=copy.deepcopy(observed);eos['available_objects']=[];eos['buffer_context'].update(pending=[],end_of_stream=True)
        validate_observed(eos)
        observed['buffer_context']['end_of_stream']=True
        with self.assertRaisesRegex(ValueError,'EARLY_EOS'):validate_observed(observed)

    def test_capacity_pending_duplicate_order_rejected(self):
        for kind in ('capacity','pending','duplicate','slot','future'):
            observed=self.observation()
            if kind=='capacity':observed['buffer_context']['capacity']=3
            elif kind=='pending':observed['buffer_context']['pending'][0]['object_id']='OTHER'
            elif kind=='duplicate':observed['placed_objects'][0]['object_id']='CURRENT'
            elif kind=='slot':observed['buffer_context']['pending'][0]['slot']=1
            else:observed['available_objects'].append({'object_id':'FUTURE'})
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_observed(observed)
