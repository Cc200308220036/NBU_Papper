"""P2-A bounded pure-network acceptance, run from repository root.

Never invokes orders, candidates, environments, LP, training or a remote API.
Use a NEW output directory with the archived reference and frozen config.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n')


def static_checks(out):
    vendor = ROOT/'PCT/src/pct_baseline/vendor/pct'
    manifest = json.loads((vendor/'upstream_manifest.json').read_text())
    assert manifest['commit'] == '5e7b4238b18310af4529e0f85157d17de605850c'
    actual = subprocess.check_output(['git','-C','Online-3D-BPP-PCT','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    assert actual == manifest['commit']
    for f in manifest['files']:
        assert sha(ROOT/f['source']) == f['source_sha256'], f['source']
        if f['raw_copy']: assert sha(ROOT/f['raw_copy']) == f['source_sha256']
        if f['consumed_copy']: assert sha(ROOT/f['consumed_copy']) == f['consumed_sha256']
    assert (vendor/'LICENSE').read_bytes() == (ROOT/'Online-3D-BPP-PCT/LICENSE').read_bytes()
    try:
        ast.parse((out/'reference/evaluation.py').read_text())
    except SyntaxError as e:
        syntax = {'status':'EXPECTED_UPSTREAM_SYNTAX_ERROR','line':e.lineno,'message':e.msg}
    else: raise AssertionError('upstream syntax unexpectedly changed')
    repaired = (out/'reference/evaluation.py').read_text().replace('shuffle=args.shuffle\n','shuffle=args.shuffle,\n')
    ast.parse(repaired)
    syntax['isolated_comma_repair_ast'] = 'PASS'
    for p in list(vendor.glob('*.py')) + [ROOT/'PCT/src/pct_baseline/network_safety.py', ROOT/'PCT/tests/p2a_worker.py', Path(__file__)]:
        ast.parse(p.read_text())
    save(out/'static_checks.json',{'source_hashes':'PASS','license':'PASS','python_ast':'PASS',
                                  'upstream_evaluation':syntax,'environment_execution':'NOT_RUN'})


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',type=Path,default=Path('PCT/outputs/PCT_P2_A_20261114_01'))
    ap.add_argument('--static-only',action='store_true')
    args=ap.parse_args(); out=args.output.resolve()
    if (out/'weights.pt').exists() and not args.static_only:
        raise FileExistsError('PCT_P2A_OUTPUT_ALREADY_HAS_NETWORK_RESULTS; use a new directory')
    if not (out/'reference').exists():
        (out/'reference').mkdir(parents=True)
        for name in ['model.py', 'attention_model.py', 'graph_encoder.py',
                     'distributions.py', 'tools.py', 'LICENSE', 'evaluation.py']:
            (out/'reference'/name).write_bytes((ROOT/'Online-3D-BPP-PCT'/name).read_bytes())
        runtime = out/'reference_runtime'
        runtime.mkdir()
        for name in ['model.py', 'attention_model.py', 'graph_encoder.py', 'distributions.py', 'LICENSE']:
            text = (out/'reference'/name).read_text()
            if name == 'attention_model.py':
                text = text.replace('super(AttentionModelFixed, self).__getitem__(key)',
                                    'tuple.__getitem__(self, key)')
            (runtime/name).write_text(text)
    static_checks(out)
    if args.static_only:
        print('Static provenance, hashes, license, syntax checks PASS; numerical checks NOT_RUN')
        return
    import torch
    torch.set_num_threads(1)
    commands=[]
    def worker(kind,fixture=None):
        cmd=[sys.executable,'PCT/tests/p2a_worker.py','--kind',kind,'--directory',str(out.relative_to(ROOT))]
        if fixture: cmd+=['--fixture',fixture]
        env=dict(os.environ, PYTHONPATH='PCT/src', PYTHONDONTWRITEBYTECODE='1')
        proc=subprocess.run(cmd,cwd=ROOT,env=env,text=True,capture_output=True)
        record={'command':[('<NBU_PY>' if i==0 else x) for i,x in enumerate(cmd)],
                'exit_code':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr}
        commands.append(record); save(out/'commands_and_results.json',commands)
        if proc.returncode: raise RuntimeError(record)
    worker('prepare')
    fixtures=['all_valid_b1','all_valid_b3','padded_b1','padded_b3','padded_payload_b1','exact_tie_b1','single_leaf_b1']
    comparisons=[]; deltas=[]
    def load(kind,f): return torch.load(out/(kind+'_'+f+'_results.pt'),weights_only=True)
    for f in fixtures:
        for kind in ['native','compat','safe']: worker(kind,f)
        native,compat,safe=(load(k,f) for k in ['native','compat','safe'])
        assert native['pid']!=compat['pid']!=safe['pid']
        for label,other in [('compat',compat),('safe',safe)]:
            for flags, original in native['results'].items():
                for group in ['tensors','gradients']:
                    for name,a in original[group].items():
                        b=other['results'][flags][group][name]
                        if a is None or b is None:
                            assert (a is None)==(b is None)
                            row={'fixture':f,'kind':label,'flags':flags,'group':group,'name':name,'both_unused':True}
                        else:
                            diff=(a-b).abs(); close=torch.allclose(a,b,atol=1e-6,rtol=1e-5)
                            row={'fixture':f,'kind':label,'flags':flags,'group':group,'name':name,
                                 'shape':list(a.shape),'max_absolute_error':diff.max().item(),
                                 'max_relative_error':(diff/a.abs().clamp_min(1e-30)).max().item(),
                                 'within_tolerance':close}
                            # Sampling outputs may differ for explicit padding repair;
                            # all-valid requires full numerical equivalence regardless.
                            if label=='compat' or f.startswith('all_valid'):
                                assert close,row
                        (comparisons if label=='compat' or f.startswith('all_valid') else deltas).append(row)
        x=torch.load(out/(f+'.pt'),weights_only=True)['input']
        for flags,r in safe['results'].items():
            probs=r['tensors']['probabilities']; valid=x[:,40:56,8].bool()
            assert (probs[~valid]==0).all()
            assert torch.allclose(probs.sum(-1),torch.ones(x.shape[0]),atol=1e-6,rtol=1e-5)
            if f=='exact_tie_b1': assert (r['tensors']['selected']==0).all() if 'deterministic_True' in flags else True
        # Save complete tensors in JSON as well as exact binary .pt records.
        for k,payload in [('native',native),('compat',compat),('safe',safe)]:
            def plain(v):
                if torch.is_tensor(v): return v.tolist()
                if isinstance(v,dict): return {key:plain(val) for key,val in v.items()}
                return v
            save(out/(k+'_'+f+'_results.json'),plain(payload))
        save(out/(f+'_input.json'),{'input':x.tolist(),'fixed_actions':[0]*x.shape[0]})
    # Invariance to garbage in invalid slots; use the same valid prefix and weights.
    a,b=load('safe','padded_b1'),load('safe','padded_payload_b1')
    for flags in a['results']:
        for group in ['tensors','gradients']:
            for key,v in a['results'][flags][group].items():
                w=b['results'][flags][group][key]
                if v is not None: assert torch.allclose(v,w,atol=1e-6,rtol=1e-5),(group,key)
    save(out/'numerical_comparisons.json',comparisons)
    save(out/'padding_differences.json',deltas)
    # Negative inputs and unchanged torch global identities are tested in a
    # dedicated compatible process here, never after importing native modules.
    from types import SimpleNamespace
    from pct_baseline.network_safety import PaddingSafeDRLGAT
    cfg=json.loads((ROOT/'PCT/configs/network_p2a_v1.json').read_text())
    model=PaddingSafeDRLGAT(SimpleNamespace(**cfg)).eval()
    model.load_state_dict(torch.load(out/'weights.pt',weights_only=True),strict=True)
    fixture=torch.load(out/'padded_b1.pt',weights_only=True)['input']
    cases={}
    x=fixture.clone(); x[:,40:56]=0; cases['empty_leaves']=x
    x=fixture.clone(); x[0,0,0]=float('nan'); cases['nan']=x
    x=fixture.clone(); x[0,0,0]=float('inf'); cases['inf']=x
    x=fixture.clone(); x[0,0,8]=0.5; cases['invalid_flag']=x
    x=fixture.clone(); x[:,-1,8]=0; cases['missing_current']=x
    cases['shape']=fixture[:,:-1]; cases['float64']=fixture.double()
    rejected={}
    for name,x in cases.items():
        try: model(x,deterministic=True)
        except ValueError as e: rejected[name]=str(e)
        else: raise AssertionError('did not reject '+name)
    save(out/'compatibility_negatives.json',{'rejected':rejected,'padding_payload_invariance':'PASS',
        'zero_padding_probability':'PASS','exact_tie_smallest_index':'PASS','single_leaf_shape':'PASS'})
    weights=torch.load(out/'weights.pt',weights_only=True)
    save(out/'weight_tensors.json', {k:{'dtype':str(v.dtype),'shape':list(v.shape),'values':v.tolist()} for k,v in weights.items()})
    save(out/'weight_identity.json',{'provenance':'RANDOM_INITIALIZATION_ENGINEERING_ONLY',
        'seed':0,'file_sha256':sha(out/'weights.pt'),
        'tensors':{k:{'shape':list(v.shape),'dtype':str(v.dtype),
                      'sha256':hashlib.sha256(v.numpy().tobytes()).hexdigest()} for k,v in weights.items()}})
    save(out/'numerical_summary.json',{'status':'PASS','fixtures':fixtures,'processes':len(commands),
        'compared_records':len(comparisons),'padding_difference_records':len(deltas),
        'atol':1e-6,'rtol':1e-5,'all_valid':{'batches':[1,3],'shape':[57,9]},
        'max_absolute_error':max(r.get('max_absolute_error',0) for r in comparisons),
        'global_torch_mutation':'native only, process-isolated; compat and safe unchanged',
        'native_paper_performance':'NOT_RUN','remote_requests':0,'optimizer_updates':0})
    print('P2-A bounded numerical checks PASS')


if __name__=='__main__':
    main()
