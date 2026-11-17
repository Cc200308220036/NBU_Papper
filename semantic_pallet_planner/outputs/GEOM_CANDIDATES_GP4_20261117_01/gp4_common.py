"""GP4 saved-state analysis only. Exact action arithmetic, no tolerance matching."""
import hashlib,json,math
from fractions import Fraction
from pathlib import Path
OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP4_20261117_01')
POINTS=['P01_ffcfcc6e4af4','P02_f17e03ef6116','P03_81c78da5f3a7','P04_53bacc63aa29','P05_392be366b95d']
BACKENDS=['e2_original_v1','ems_surface_hybrid_v1']
def read(p):return json.loads(Path(p).read_bytes())
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(canonical(v)).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')
def number(v):
 if type(v) is int:return Fraction(v)
 if type(v) is float and math.isfinite(v):return Fraction(repr(v))
 raise ValueError('finite native int/float required; no bool or epsilon')
def text(v):return str(number(v))
def action(c,yaw_equivalent=False):
 k=(c['pick_item_id'],*(text(v) for v in c['oriented_size_mm']),str(c['pose']['yaw_deg']),*(text(c['pose'][a]) for a in ('x_mm','y_mm','z_base_mm')))
 if yaw_equivalent and k[1]==k[2]:return (*k[:4],'SQUARE_YAW_EQUIVALENT',*k[5:])
 return k
def pointer(v,path):
 for key in path.lstrip('/').split('/') if path else []:
  key=key.replace('~1','/').replace('~0','~');v=v[int(key)] if isinstance(v,list) else v[key]
 return v
def leaves(v,path):
 if isinstance(v,dict) and v:
  return [p for k,x in v.items() for p in leaves(x,path+'/'+k.replace('~','~0').replace('/','~1'))]
 if isinstance(v,list) and v:return [p for i,x in enumerate(v) for p in leaves(x,path+'/'+str(i))]
 return [path]
def adapt_saved(point):
 """Only current public state/observation enter runtime; provenance is audit only."""
 p=OUT/'inputs'/point;s=read(p/'original_snapshot.json');mapping=read(p/'public_provenance.json')
 if set(s)!={'version','point_id','decision_id','current_public_state','public_observation','input_scope'} or s['point_id']!=point:raise ValueError('saved snapshot closed envelope/point mismatch')
 expected=set(leaves(s['current_public_state'],'/current_public_state')+leaves(s['public_observation'],'/public_observation'))
 rows=mapping['field_provenance'];assert {r['snapshot_pointer'] for r in rows}==expected
 assert len(rows)==len(expected)
 for r in rows:
  assert digest(pointer(s,r['snapshot_pointer']))==r['value_digest']
  base=mapping['state_pointer'] if r['snapshot_pointer'].startswith('/current_public_state') else mapping['observation_pointer']
  suffix=r['snapshot_pointer'].split('/',2)
  assert r['source_pointer']==base+('/'+suffix[2] if len(suffix)>2 else '')
 return s['current_public_state'],s['public_observation']
