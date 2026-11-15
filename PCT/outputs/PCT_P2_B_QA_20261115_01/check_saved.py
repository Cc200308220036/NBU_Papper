# -*- coding: utf-8 -*-
"""Read saved artifacts and independently reconstruct geometry using stdlib only.
No NumPy/Torch/planner imports, inference, candidates, orders, LP or writes to input.
"""
import hashlib,json,math,struct
from pathlib import Path
Q=Path(__file__).parent;D=Path('PCT/outputs/PCT_P2_B_20261115_01');T=D/'attempt_06/tests'
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dg(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]
def flatten(x):
 if isinstance(x,list):
  for v in x:yield from flatten(v)
 else:yield x
def shape(x):return [len(x)]+(shape(x[0]) if x else []) if isinstance(x,list) else []
checks=[]
def encoding(ctx,e,candidates=None):
 state=ctx['model_state'];C=state['container'];L,W,H=[C[k] for k in ('length_mm','width_mm','max_height_mm')];ref=max(L,W,H)
 def corner(p,s):
  x,y,z=p['x_mm'],p['y_mm'],p['z_base_mm'];l,w,h=s
  return [x-l/2+L/2,y-w/2+W/2,z,x+l/2+L/2,y+w/2+W/2,z+h]
 nodes=[[0.]*9 for _ in range(57)];placed=state['placed_objects'];mapping=ctx['display_mapping'];rows=[];corners=[]
 if not placed:nodes[0][8]=1.
 for i,o in enumerate(placed):nodes[i][:6]=[v/ref for v in corner(o['pose'],o['oriented_size_mm'])];nodes[i][8]=1.
 for i,label in enumerate(mapping):
  c=ctx['criteria'][label];a=corner(c['pose'],c['oriented_size_mm']);corners.append(a)
  nodes[40+i][:6]=[v/ref for v in [*a[:5],H]];nodes[40+i][8]=1.
  rows.append(dict(leaf_index=i,display_label=label,**mapping[label],pose=c['pose'],oriented_size_mm=c['oriented_size_mm'],actual_top_mm=a[5]))
 dim=state['available_objects'][0]['dimensions_mm'];dims=sorted(dim[k] for k in ('length','width','height'))
 nodes[56][:6]=[v/ref for v in [1,0,0,*dims]];nodes[56][8]=1.
 packed=[[f32(v) for v in row] for row in nodes];valid=[row[8]==1 for row in packed]
 feature=dict(version='pct_adapted_geo_v1',packed=packed,valid_mask=valid)
 assert e['packed']==packed and e['valid_mask']==valid and e['feature_digest']==dg(feature)
 assert e['mapping']==rows and e['mapping_digest']==dg(rows) and e['Lref_mm']==ref and e['actual_leaf_corners_mm_float64']==corners
 assert e['placed_count']==len(placed) and e['candidate_count']==len(mapping) and e['empty_pool']==(not mapping)
 if candidates is not None:
  by={c['candidate_id']:c for c in candidates};assert len(by)==len(candidates)==len(rows)
  for r in rows:
   c=by[r['candidate_id']];assert dg(c)==r['candidate_digest'] and all(c[k]==r[k] for k in ('pose','oriented_size_mm','pick_item_id'))
 checks.append({'placed':len(placed),'candidates':len(rows),'empty':not rows})
def record(ctx,candidates,r):
 assert r['record_digest']==dg({k:v for k,v in r.items() if k!='record_digest'})
 assert r['context_digest']==dg(ctx) and r['local_binding_digest']==dg(ctx['local_binding'])
 assert r['model_manifest_sha256']==sha(D/'model_manifest.json') and r['weights_sha256']==sha(D/'weight_tensors.json')
 encoding(ctx,r['encoding'],candidates)
 o=r['output'];s=r['selection'];n=len(candidates)
 if o is None:assert n==1 and s['status']=='singleton' and s['source']=='singleton';index=0
 else:
  p=o['probabilities'];assert len(p)==16 and all(math.isfinite(x) and 0<=x<=1 for x in p)
  assert abs(sum(p)-1)<=1.1e-5 and p[n:]==[0.]*(16-n)
  index=p.index(max(p));assert type(o['leaf_index']) is int and o['leaf_index']==index<n
  assert math.isfinite(o['value']) and math.isfinite(o['entropy'])
  assert s['probabilities']=={row['display_label']:p[row['leaf_index']] for row in r['encoding']['mapping']}
  assert s['source']=='pct_local' and s['status']=='selected'
 row=r['encoding']['mapping'][index];assert r['selected_mapping']==row
 candidate=next(c for c in candidates if c['candidate_id']==row['candidate_id']);assert r['exact_candidate']==candidate
 assert s['selected_display_id']==row['display_label'] and s['selected_candidate_id']==row['candidate_id'] and s['local_binding_digest']==r['local_binding_digest']
def main():
 identity=read(D/'identity.json');manifest=read(D/'delivery_manifest.json')
 bad=[e['path'] for e in manifest['files'] if sha(e['path'])!=e['sha256']]
 src={**identity['source_sha256'],**identity['public_and_previous_code_sha256']};assert not bad
 assert all(sha(p)==h for p,h in src.items())
 pre=read(D/'attempt_06/pre_execution_identity.json');assert all(sha(p)==h for p,h in pre['source_sha256'].items())
 m=read(D/'model_manifest.json');assert sha(D/'model_manifest.json')==identity['model_manifest_sha256']
 assert all(sha(Path('PCT/src/pct_baseline')/p)==h for p,h in m['core_sha256'].items())
 weights=read(D/'weight_tensors.json');assert sha(D/'weight_tensors.json')==m['weights_sha256']
 for k,r in weights.items():
  assert r['dtype']=='torch.float32' and shape(r['values'])==r['shape']==m['parameters'][k]['shape']
  assert hashlib.sha256(b''.join(struct.pack('<f',v) for v in flatten(r['values']))).hexdigest()==m['parameters'][k]['sha256']
 for name in ('coordinates_False','coordinates_True','empty_pallet','identical_symmetric_leaves'):
  v=read(T/(name+'.json'));encoding(v['context'],v['encoding'],v['candidates'])
 v=read(T/'capacity40_and_display_order.json');encoding(v['context'],v['encoding']);encoding(v['reversed_context'],v['reversed_encoding'])
 v=read(T/'route_0.json');encoding(v['context'],v['encoding'],v['candidates']);assert v['selection'] is None and v['model_calls_delta']==0
 for n in (1,3):
  v=read(T/f'route_{n}.json');record(v['context'],v['candidates'],v['record'])
 inputs=read(T/'saved_public_inputs.json');record(inputs['context'],inputs['candidates'],read(T/'saved_selection.json'))
 v=read(T/'public_context_builder.json');record(v['context'],v['bundle']['physical_candidates'],v['record'])
 a,b=[read(D/f'attempt_06/repeat_{i}.json') for i in (0,1)];assert a['pid']!=b['pid'] and a['model_calls']==b['model_calls']==1
 for repeat in (a,b):
  record(v['context'],v['bundle']['physical_candidates'],repeat['record']);assert repeat['forbidden_calls']==[]
  for field in ('encoding','output','selected_mapping','exact_candidate','context_digest','model_manifest_sha256','weights_sha256'):assert repeat['record'][field]==v['record'][field]
 batch=read(T/'batch.json')
 for e,o,s in zip(batch['encodings'],batch['outputs'],batch['singles']):
  assert o['leaf_index']==s['leaf_index'] and o['probabilities'][e['candidate_count']:]==[0.]*(16-e['candidate_count'])
  assert all(abs(x-y)<=1e-6+1e-5*abs(y) for x,y in zip(o['probabilities'],s['probabilities']))
 rejection=read(T/'rejections.json');assert len(rejection)==65
 result={'status':'PASS_SAVED_GEOMETRY_ONLY','delivery_files':len(manifest['files']),'current_sources_and_public_files':len(src),'pre_execution_sources':len(pre['source_sha256']),'weight_tensors':len(weights),'geometry_records_checked':len(checks),'geometry_cases':checks,'rejections_archived':len(rejection),'fresh_process_pids':[a['pid'],b['pid']],'network_calls_this_QA':0,'not_run':['forward','business tests','orders','candidate generation','LP','install','training']}
 (Q/'saved_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='geometry_cases'},ensure_ascii=False))
if __name__=='__main__':main()
