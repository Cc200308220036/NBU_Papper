"""Stdlib arithmetic/provenance checks only; no production or generation imports."""
import copy,unittest
from gp4_common import *
def candidate(x=2,yaw=0):return {'pick_item_id':'a','oriented_size_mm':[2,2.0,3],'pose':{'yaw_deg':yaw,'x_mm':x,'y_mm':-0.0,'z_base_mm':0}}
class AnalysisContract(unittest.TestCase):
 def test_math_value_not_labels_or_lexical_number_shape(self):
  a=candidate(2);b=candidate(2.0);b['candidate_id']='different';b['ems_id']='private';self.assertEqual(action(a),action(b));b['pose']['y_mm']=0;self.assertEqual(action(a),action(b))
 def test_no_epsilon_and_box_size_pose_yaw_all_bind(self):
  a=candidate(.3);b=candidate(.1+.2);self.assertNotEqual(action(a),action(b))
  for field in ('box','size','yaw'):
   b=copy.deepcopy(a)
   if field=='box':b['pick_item_id']='b'
   elif field=='size':b['oriented_size_mm'][2]=4
   else:b['pose']['yaw_deg']=90
   self.assertNotEqual(action(a),action(b))
 def test_square_yaw_equivalence_is_separate(self):
  a,b=candidate(),candidate(yaw=90);self.assertNotEqual(action(a),action(b));self.assertEqual(action(a,True),action(b,True))
 def test_five_original_public_provenance_closed(self):
  for p in POINTS:
   s,o=adapt_saved(p);self.assertTrue(s['pending_items']);self.assertIsInstance(o['available_objects'],list)
 def test_nonfinite_bool_rejected(self):
  for v in (True,float('inf'),float('nan')):
   with self.assertRaises(ValueError):number(v)
if __name__=='__main__':unittest.main(verbosity=2)
