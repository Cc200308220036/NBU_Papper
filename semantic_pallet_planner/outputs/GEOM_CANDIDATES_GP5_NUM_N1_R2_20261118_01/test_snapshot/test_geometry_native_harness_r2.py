"""Pure assertion regression cases; no candidates generated or monitors run."""
import copy
import unittest
from geometry_native_assertions_r2 import assert_event_shape,same_native


def event_for(values,yaw,order):
    source={'item_id':'chosen_second','dimensions_mm':{k:values[k] for k in order}}
    axes=('length','width','height') if yaw==0 else ('width','length','height')
    candidate={'candidate_id':'fixed_literal_candidate','pick_item_id':source['item_id'],'pose':{'x_mm':-0.0,'y_mm':2.0,'z_base_mm':0,'yaw_deg':yaw},'oriented_size_mm':[values[k] for k in axes]}
    return {'event':'PLACE','selection':{'selected_candidate_id':candidate['candidate_id']},'bundle':{'physical_candidates':[{'candidate_id':'unchosen','pick_item_id':'first'},candidate]},
        'before':{'pending_items':[{'item':{'item_id':'first','dimensions_mm':{'length':9,'width':8,'height':7}}},{'item':source}]},
        'after':{'placed_items':[{'item_id':source['item_id'],'dimensions_mm':copy.deepcopy(source['dimensions_mm']),'oriented_size_mm':list(candidate['oriented_size_mm']),'pose':copy.deepcopy(candidate['pose'])}]},
        'action':{'literal':'same'},'proposed_action':{'literal':'same'}}

class NativeHarnessR2(unittest.TestCase):
    def test_named_axes_orders_yaws_and_selected_source(self):
        for values in ({'length':100,'width':80,'height':60},{'length':100,'width':80.5,'height':60.0}):
            for yaw in (0,90):
                for order in (('height','length','width'),('width','height','length'),('length','width','height')):
                    with self.subTest(values=values,yaw=yaw,order=order):
                        e=event_for(values,yaw,order);row=assert_event_shape(e)
                        self.assertEqual(row['pick_item_id'],'chosen_second')
                        self.assertTrue(same_native(row['expected_oriented_size_mm'],[values[k] for k in (('length','width','height') if yaw==0 else ('width','length','height'))]))
    def test_type_bit_source_and_yaw_mutations_rejected(self):
        original=event_for({'length':100,'width':80.0,'height':60},0,('height','width','length'))
        for name in ('size_type','pose_sign','wrong_source','wrong_yaw'):
            e=copy.deepcopy(original)
            if name=='size_type':e['bundle']['physical_candidates'][1]['oriented_size_mm'][0]=100.0
            if name=='pose_sign':e['after']['placed_items'][0]['pose']['x_mm']=0.0
            if name=='wrong_source':e['bundle']['physical_candidates'][1]['pick_item_id']='missing'
            if name=='wrong_yaw':e['bundle']['physical_candidates'][1]['pose']['yaw_deg']=90
            with self.assertRaises(AssertionError,msg=name):assert_event_shape(e)
        self.assertFalse(same_native(100,100.0));self.assertFalse(same_native(-0.0,0.0))

if __name__=='__main__':unittest.main(verbosity=2)
