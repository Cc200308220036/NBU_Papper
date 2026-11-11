"""Bounded constructed saved-point semantic probe; never sample/build/execute/solve."""
import copy,hashlib,importlib.abc,json,shutil,socket,sys,tempfile
from pathlib import Path
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(x in fullname for x in ('packaging_remote','selector','transport','episode','stability','planning','numpy','scipy')):
   raise AssertionError('forbidden business import: '+fullname)
sys.meta_path.insert(0,Guard())
def forbidden(*a,**kw):raise AssertionError('forbidden dispatch')
socket.socket=forbidden
from semantic_pallet_planner.jev_select import packaging_jev_training_template as b2
from semantic_pallet_planner.jev_select import packaging_jev_sampling as b1
b1.sample=forbidden
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
B=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_20261111_01'
def mapping(root):return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
original=mapping(B);results=[]
with tempfile.TemporaryDirectory() as temp:
 root=Path(temp);shutil.copytree(B/'constructed_evidence',root,dirs_exist_ok=True)
 t=json.loads((B/'constructed_template.json').read_text())
 baseline=b2.validate_template(t,root=root)
 for name in ('invalid_native_lexeme','contradictory_gap','false_orientation','invalid_stratum'):
  case=copy.deepcopy(t);selected=b2.read_saved(t['points'][0]['selected_point_ref'],root=root)
  if name=='invalid_native_lexeme':selected['branches'][1]['native_lexeme']='NOT_A_PROBABILITY'
  elif name=='contradictory_gap':selected['branches'][1]['relative_gap']={'numerator':999,'denominator':1}
  elif name=='false_orientation':selected['branches'][1]['orientation_changed']=True
  else:selected['stratum']='UNREGISTERED_STRATUM'
  target=root/'qa_altered_selected_point.json';target.write_text(json.dumps(selected))
  case['points'][0]['selected_point_ref']=b2.saved_ref(target.name,root=root)
  before=mapping(root)
  try:
   result=b2.validate_template(case,root=root)
   observation={'status':result['status'],'jobs':len(result['jobs']),'global_send_upper':result['global_send_upper'],'accepted':True}
  except Exception as exc:observation={'accepted':False,'exception_type':type(exc).__name__,'reason':str(exc)}
  assert mapping(root)==before
  results.append({'case':name,'mutated_selected_point':selected,'observation':observation})
assert mapping(B)==original
receipt={'version':'jm1_b2_qa_semantic_probe_v1','scope':'CONSTRUCTED_ONLY: copy archived B2 constructed_evidence; change selected-point semantic value and bind its actual new file hash; original raw/projection/pool/action/metadata unchanged; production schema and entry unchanged','baseline':{'status':baseline['status'],'jobs':len(baseline['jobs']),'global_send_upper':baseline['global_send_upper']},'cases':results,'original_package_unchanged':True,'validation_readonly':True,'sampler_engine_model_solver_dispatches':0,'boundary':'Demonstrates under-validation of supplied constructed selected point; does not alter a frozen original manifest or demonstrate formal execution bypass. Formal gate always refuses.'}
(OUT/'semantic_probe.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'baseline':receipt['baseline'],'cases':[{'case':r['case'],**r['observation']} for r in results],'original_package_unchanged':True},ensure_ascii=False))
