# -*- coding: utf-8 -*-
"""Independent saved load encoding/ledger arithmetic, no network or planner imports."""
import hashlib,json,math,struct
from pathlib import Path
Q=Path(__file__).parent;D=Path('PCT/outputs/PCT_P2_C_20261115_01');T=D/'attempt_03/tests'
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dg(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def f32(v):return struct.unpack('<f',struct.pack('<f',v))[0]
def flatten(x):
 if isinstance(x,list):
  for v in x:yield from flatten(v)
 else:yield x
def shape(x):return [len(x)]+(shape(x[0]) if x else []) if isinstance(x,list) else []
cases=[]
def aggregate(changes,objects):
 rows=[]
 for c in changes:
  o=objects[c['object_id']];d=c['increment_top_load_kg'];b=c['before_top_load_kg'];a=c['after_top_load_kg'];cap=c['max_top_load_kg'];r=c['remaining_top_load_kg']
  assert d>=0 and abs(a-b-d)<=1e-9 and abs(b-o['current_top_load_kg'])<=1e-9 and cap==o['max_top_load_kg']
  assert abs(r-((cap if o['stackable'] else 0)-a))<=1e-9
  if d>0:assert cap>0 and o['stackable'];rows.append((a/cap,r))
 return [max(r[0] for r in rows),min(r[1] for r in rows)/9,1] if rows else [0,0,0]
def encode(ctx,e,candidates=None):
 s=ctx['model_state'];C=s['container'];L,W,H=[C[k] for k in ('length_mm','width_mm','max_height_mm')];ref=max(L,W,H)
 def corner(p,sz):
  x,y,z=p['x_mm'],p['y_mm'],p['z_base_mm'];l,w,h=sz
  return [x-l/2+L/2,y-w/2+W/2,z,x+l/2+L/2,y+w/2+W/2,z+h]
 def resource(o):
  m,cap,used,left=[o[k] for k in ('mass_kg','max_top_load_kg','current_top_load_kg','remaining_top_load_kg')]
  assert all(x>=0 for x in (m,cap,used,left)) and abs(used+left-(cap if o['stackable'] else 0))<=1e-9
  return [m/9,int(o['stackable']),cap/9,used/9,left/9]
 nodes=[[0.]*13 for _ in range(57)];placed=s['placed_objects'];objects={o['object_id']:o for o in placed};rows=[];corners=[]
 if not placed:nodes[0][12]=1
 for i,o in enumerate(placed):nodes[i][:11]=[*[x/ref for x in corner(o['pose'],o['oriented_size_mm'])],*resource(o)];nodes[i][12]=1
 cur=s['available_objects'][0];r=resource(cur);nodes[56][:6]=[*[cur['dimensions_mm'][k]/ref for k in ('length','width','height')],*r[:3]];nodes[56][12]=1
 for i,label in enumerate(ctx['display_mapping']):
  cr=ctx['criteria'][label];a=corner(cr['pose'],cr['oriented_size_mm']);corners.append(a);f=cr['features']
  nodes[40+i][:12]=[*[x/ref for x in a],f['support_ratio'],f['com_margin_mm']/ref,f['resulting_max_height_mm']/ref,*aggregate(cr['load_changes'],objects)];nodes[40+i][12]=1
  rows.append(dict(leaf_index=i,display_label=label,**ctx['display_mapping'][label],pose=cr['pose'],oriented_size_mm=cr['oriented_size_mm'],actual_top_mm=a[5]))
 packed=[[f32(x) for x in row] for row in nodes];mask=[r[12]==1 for r in packed]
 feature=dict(version='pct_adapted_load_v1',packed=packed,valid_mask=mask)
 assert packed==e['packed'] and mask==e['valid_mask'] and dg(feature)==e['feature_digest']
 assert rows==e['mapping'] and dg(rows)==e['mapping_digest'] and corners==e['actual_leaf_corners_mm_float64'] and ref==e['Lref_mm'] and e['Mref_kg']==9
 assert e['candidate_count']==len(rows) and e['placed_count']==len(placed) and e['empty_pool']==(not rows)
 if candidates is not None:
  by={c['candidate_id']:c for c in candidates};assert len(by)==len(rows)==len(candidates)
  for row in rows:
   c=by[row['candidate_id']];assert dg(c)==row['candidate_digest'] and all(c[k]==row[k] for k in ('pick_item_id','pose','oriented_size_mm'))
 cases.append(dict(placed=len(placed),leaves=len(rows)))
def output(e,o):
 p=o['probabilities'];n=e['candidate_count'];assert len(p)==16 and all(math.isfinite(x) and 0<=x<=1 for x in p)
 assert abs(sum(p)-1)<1.1e-5 and p[n:]==[0.]*(16-n) and o['leaf_index']==p.index(max(p))<n
 assert math.isfinite(o['value']) and math.isfinite(o['entropy'])
def main():
 man=read(D/'delivery_manifest.json');assert all(sha(r['path'])==r['sha256'] for r in man['files'])
 pre=read(D/'attempt_03/pre_execution_identity.json');assert all(sha(p)==h for p,h in pre['source_sha256'].items())
 mp=T/'model_manifest.json';wp=T/'weight_tensors.json';m=read(mp);weights=read(wp);identity=read(D/'identity.json')
 assert sha(mp)==identity['model_manifest_sha256'] and sha(wp)==identity['weights_sha256']==m['weights_sha256']
 assert all(sha(Path('PCT/src/pct_baseline')/p)==h for p,h in m['core_sha256'].items())
 for k,r in weights.items():
  assert r['dtype']=='torch.float32' and shape(r['values'])==r['shape']==m['parameters'][k]['shape']
  assert hashlib.sha256(b''.join(struct.pack('<f',v) for v in flatten(r['values']))).hexdigest()==m['parameters'][k]['sha256']
 for name in ('p0','nonzero','nonstackable_empty','capacity40'):
  v=read(T/(name+'.json'));encode(v['context'],v['encoding'],v.get('candidates'))
 v=read(T/'positive_set_only.json');assert aggregate(v['changes'],v['objects'])==v['aggregate']==[5/9,4/9,1]
 v=read(T/'b27.json');encode(v['base_context'],v['base']);geo=v['geometry'];variant_names=[]
 for r in v['variants']:
  encode(r['context'],r['encoding']);assert r['encoding']['mapping']==v['base']['mapping']
  if 'geometry' in r:assert r['geometry']['feature_digest']==geo['feature_digest'] and r['geometry']['packed']==geo['packed']
  if 'changed_fields' in r:
   changed=[[i,j] for i,(a,b) in enumerate(zip(v['base']['packed'],r['encoding']['packed'])) for j,(x,y) in enumerate(zip(a,b)) if x!=y]
   assert changed==r['changed_fields']
  variant_names.append(r['name'])
 v=read(T/'b28.json');encode(v['public_context'],v['encoding']);assert len(v['cases'])==7 and all(r['raw_projection_equal'] and r['entry_rejected'] for r in v['cases'])
 batch=read(T/'batch.json')
 for c,e,b,s in zip(batch['contexts'],batch['encodings'],batch['batch'],batch['singles']):
  encode(c,e);output(e,b);output(e,s);assert b['leaf_index']==s['leaf_index']
  assert all(abs(x-y)<=1e-6+1e-5*abs(y) for x,y in zip(b['probabilities'],s['probabilities']))
 for n in (0,1,3):
  v=read(T/f'route_{n}.json');r=v['record'];assert v['model_calls_delta']==int(n>1)
  if n==0:assert r is None;continue
  assert r['record_digest']==dg({k:x for k,x in r.items() if k!='record_digest'}) and r['context_digest']==dg(v['context']) and r['local_binding_digest']==dg(v['context']['local_binding'])
  assert r['model_manifest_sha256']==sha(mp) and r['weights_sha256']==sha(wp)
  encode(v['context'],r['encoding'],v['candidates'])
  if n==1:assert r['output'] is None;idx=0
  else:output(r['encoding'],r['output']);idx=r['output']['leaf_index']
  row=r['encoding']['mapping'][idx];assert r['selected_mapping']==row and r['exact_candidate']==next(c for c in v['candidates'] if c['candidate_id']==row['candidate_id'])
  assert r['selection']['selected_candidate_id']==row['candidate_id'] and r['selection']['selected_display_id']==row['display_label']
 repeat=read(T/'repeat_reload.json');encode(repeat['context'],repeat['encoding']);assert repeat['first']==repeat['again']==repeat['reloaded']
 rejects=read(T/'rejections.json');assert len(rejects)==52
 result=dict(status='PASS_SAVED_FACTS_ONLY',delivery_files=len(man['files']),pre_execution_sources=len(pre['source_sha256']),weight_tensors=len(weights),encodings_checked=len(cases),cases=cases,variants=variant_names,b28_private_field_cases=7,expected_rejections_archived=len(rejects),p0_aggregate=[5/9,4/9,1],new_network_calls=0,not_run=['inference','unit tests','orders','candidates','LP','training','install','remote calls'])
 (Q/'saved_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='cases'},ensure_ascii=False))
if __name__=='__main__':main()
