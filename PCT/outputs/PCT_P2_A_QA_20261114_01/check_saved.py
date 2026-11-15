"""Stdlib QA: recompute saved tensor comparisons; no Torch/planner/model imports."""
import ast,hashlib,json,math,struct,subprocess
from pathlib import Path
Q=Path(__file__).parent;D=Path('PCT/outputs/PCT_P2_A_20261114_01')
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def flat(x):
 if isinstance(x,list):
  for v in x:yield from flat(v)
 else:yield x
def shape(x):
 if not isinstance(x,list):return []
 s=[len(x)]+(shape(x[0]) if x else [])
 assert all(shape(v)==s[1:] for v in x)
 return s
def compare(a,b,close=True):
 assert shape(a)==shape(b)
 aa=list(flat(a));bb=list(flat(b));assert len(aa)==len(bb)
 assert all(math.isfinite(v) for v in aa+bb)
 error=max((abs(x-y) for x,y in zip(aa,bb)),default=0)
 if close:assert all(abs(x-y)<=1e-6+1e-5*abs(y) for x,y in zip(aa,bb)),error
 return error
def main():
 manifest=read(D/'delivery_manifest.json');identity=read(D/'identity.json')
 bad=[r['path'] for r in manifest['files'] if sha(r['path'])!=r['sha256']]
 src=[p for p,h in identity['source_sha256'].items() if sha(p)!=h]
 assert not bad and not src,(bad,src)
 up=read('PCT/src/pct_baseline/vendor/pct/upstream_manifest.json')
 for r in up['files']:
  assert sha(r['source'])==r['source_sha256']
  if r['raw_copy']:assert sha(r['raw_copy'])==r['source_sha256']
  if r['consumed_copy']:assert sha(r['consumed_copy'])==r['consumed_sha256']
 assert subprocess.check_output(['git','-C','Online-3D-BPP-PCT','rev-parse','HEAD'],text=True).strip()==up['commit']
 assert Path('Online-3D-BPP-PCT/LICENSE').read_bytes()==Path('PCT/src/pct_baseline/vendor/pct/LICENSE').read_bytes()
 # AST function-body equivalence, no execution.
 original=ast.parse(Path('Online-3D-BPP-PCT/tools.py').read_text());copy=ast.parse(Path('PCT/src/pct_baseline/vendor/pct/tools.py').read_text())
 for name in ('init','observation_decode_leaf_node'):
  a=next(n for n in original.body if isinstance(n,ast.FunctionDef) and n.name==name)
  b=next(n for n in copy.body if isinstance(n,ast.FunctionDef) and n.name==name)
  assert ast.dump(a,include_attributes=False)==ast.dump(b,include_attributes=False)
 weights=read(D/'weight_tensors.json');wi=read(D/'weight_identity.json')
 for name,t in weights.items():
  assert t['dtype']=='torch.float32' and shape(t['values'])==t['shape']==wi['tensors'][name]['shape']
  assert hashlib.sha256(b''.join(struct.pack('<f',v) for v in flat(t['values']))).hexdigest()==wi['tensors'][name]['sha256']
 rows=[];comparisons=0;deltas=0;maximum=0;allvalid_safe=0
 fixtures=read(D/'numerical_summary.json')['fixtures'];allresults={}
 for f in fixtures:
  inp=read(D/(f+'_input.json'))['input'];payloads={k:read(D/(k+'_'+f+'_results.json')) for k in ('native','compat','safe')};allresults[f]=payloads
  assert len({p['pid'] for p in payloads.values()})==3
  assert all(p['parameter_keys']==list(weights) for p in payloads.values())
  assert all(p['weights_sha256']==wi['file_sha256'] for p in payloads.values())
  assert len({p['input_sha256'] for p in payloads.values()})==1
  assert payloads['compat']['global_methods_changed']==payloads['safe']['global_methods_changed']==[]
  for kind in ('compat','safe'):
   close=kind=='compat' or f.startswith('all_valid');mx=0
   for flag,r in payloads['native']['results'].items():
    for group in ('tensors','gradients'):
     other=payloads[kind]['results'][flag][group];assert set(r[group])==set(other)
     for name,a in r[group].items():
      b=other[name]
      if a is None or b is None:assert a is b
      else:mx=max(mx,compare(a,b,close))
      if close:comparisons+=1
      else:deltas+=1
   if close:maximum=max(maximum,mx)
   if kind=='safe' and f.startswith('all_valid'):allvalid_safe=max(allvalid_safe,mx)
   rows.append(dict(fixture=f,kind=kind,must_match=close,max_absolute_error=mx))
  for flag,r in payloads['safe']['results'].items():
   probs=r['tensors']['probabilities'];assert shape(probs)==[len(inp),16]
   for b,p in enumerate(probs):
    assert abs(sum(p)-1)<1e-6 and all(v>=0 for v in p)
    assert all(p[j]==0 for j in range(16) if inp[b][40+j][8]==0)
   if f=='exact_tie_b1' and 'deterministic_True' in flag:assert list(flat(r['tensors']['selected']))==[0]
 for flag,a in allresults['padded_b1']['safe']['results'].items():
  b=allresults['padded_payload_b1']['safe']['results'][flag]
  for group in ('tensors','gradients'):
   for name,v in a[group].items():
    if v is None:assert b[group][name] is None
    else:compare(v,b[group][name])
 result=dict(status='PASS_SAVED_TENSORS_ONLY',delivery_files=len(manifest['files']),source_files=len(identity['source_sha256']),upstream_files=len(up['files']),weight_tensors=len(weights),checked_comparison_records=comparisons,explicit_difference_records=deltas,max_required_absolute_error=maximum,max_safe_all_valid_error=allvalid_safe,comparisons=rows,zero_padding_and_payload_invariance='PASS',no_model_or_torch_import=True)
 (Q/'saved_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k!='comparisons'},ensure_ascii=False))
if __name__=='__main__':main()
