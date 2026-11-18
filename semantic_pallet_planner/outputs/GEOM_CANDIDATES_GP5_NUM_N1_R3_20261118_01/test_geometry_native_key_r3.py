"""Pure metadata only: no candidate generator or shadow execution."""
import copy,json,unittest
from pathlib import Path
from semantic_pallet_planner.jev_select.geometry_native_shape_bridge import require_action_key_equivalence as check
from semantic_pallet_planner.jev_select.contracts import JevSelectError

class KeyContract(unittest.TestCase):
    def test_saved_and_orientations(self):
        raw=json.loads(Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N1_R2_QA_20261118_01/key_contract_review.json').read_text())['raw_key']
        before=copy.deepcopy(raw)
        for yaw in (0,90):
            a=raw.copy();a[4]=str(yaw);b=a.copy();b[4]=yaw
            check(a,b,'ems_surface_hybrid_v1')
            check(None,b,'e2_original_v1')
        self.assertEqual(raw,before)
    def test_strict_rejections(self):
        raw=['synth_1','100','80','60','0','0','0','0'];pub=raw.copy();pub[4]=0
        variants=[]
        for value in ('90','00','0.0','+0',' 0','-0','0e0',0,0.0,False,None):
            a=raw.copy();a[4]=value;variants.append((a,pub,'ems_surface_hybrid_v1'))
        for value in (0.0,False,'0',None,180):
            b=pub.copy();b[4]=value;variants.append((raw,b,'ems_surface_hybrid_v1'))
        for i in (0,1,2,3,5,6,7):
            a=raw.copy();a[i]='wrong';variants.append((a,pub,'ems_surface_hybrid_v1'))
            for v in (1,1.0,True,'00','0.0','-0'):
                b=pub.copy();b[i]=v
                if i==0 and type(v) is str:continue
                variants.append((raw,b,'ems_surface_hybrid_v1'))
        for text in ('00','1.0','+1','1e0','-0','NaN','Infinity',' 1'):
            a=raw.copy();b=pub.copy();a[1]=b[1]=text;variants.append((a,b,'ems_surface_hybrid_v1'))
        variants.extend([(None,pub,'ems_surface_hybrid_v1'),(raw,pub,'e2_original_v1'),(raw,pub,'unknown'),(raw[:-1],pub,'ems_surface_hybrid_v1')])
        for a,b,backend in variants:
            with self.subTest(a=a,b=b,backend=backend),self.assertRaises(JevSelectError):check(a,b,backend)

if __name__=='__main__':unittest.main()
