"""Fresh process worker: no environments, credentials, orders, solvers or optimizers."""
import ast
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import types


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kind', choices=['native', 'compat', 'safe', 'prepare'], required=True)
    ap.add_argument('--directory', type=Path, required=True)
    ap.add_argument('--fixture', default='all_valid_b1')
    args = ap.parse_args()
    import torch
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(0)
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root/'PCT/configs/network_p2a_v1.json').read_text())
    params = types.SimpleNamespace(**config)
    before = {c: {m: getattr(getattr(torch.distributions, c), m, None)
                  for m in ['sample', 'log_prob', 'entropy', 'mode', 'log_probs']}
              for c in ['Categorical', 'Normal', 'Bernoulli']}
    if args.kind == 'native':
        ref = args.directory/'reference'
        # Exact source functions only, avoiding unrelated tools Gym/CLI imports.
        tree = ast.parse((ref/'tools.py').read_text())
        tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name in ['init', 'observation_decode_leaf_node']]
        module = types.ModuleType('tools')
        exec(compile(tree, str(ref/'tools.py'), 'exec'), module.__dict__)
        sys.modules['tools'] = module
        sys.path.insert(0, str(args.directory/'reference_runtime'))
        from model import DRL_GAT
    else:
        from pct_baseline.vendor.pct.model import DRL_GAT
        if args.kind == 'safe':
            from pct_baseline.network_safety import PaddingSafeDRLGAT as DRL_GAT
    model = DRL_GAT(params).cpu().float().eval()
    if args.kind == 'prepare':
        torch.save(model.state_dict(), args.directory/'weights.pt')
        g = torch.Generator().manual_seed(20261114)
        fixtures = {}
        for b in [1, 3]:
            x = torch.rand(b, 57, 9, generator=g, dtype=torch.float32)
            x[:, :, 8] = 1
            x[:, 40:56, 5] = 1  # upstream leaf H, not box top
            x[:, 40:56, 6:8] = 0
            x[:, -1, :3] = torch.tensor([1., 0., 0.])
            x[:, -1, 3:6] = torch.sort(x[:, -1, 3:6], dim=-1).values
            fixtures[f'all_valid_b{b}'] = x
            p = x.clone(); p[:, 2:40] = 0; p[:, 43:56] = 0
            fixtures[f'padded_b{b}'] = p
        # A nonzero payload in padding must not influence valid outputs.
        q = fixtures['padded_b1'].clone()
        q[:, 2:40, :8] = 1e3; q[:, 43:56, :8] = -1e3
        fixtures['padded_payload_b1'] = q
        q = fixtures['all_valid_b1'].clone()
        q[:, 40:56] = q[:, 40:41]
        fixtures['exact_tie_b1'] = q
        q = fixtures['padded_b1'].clone(); q[:, 41:56] = 0
        fixtures['single_leaf_b1'] = q
        for name, value in fixtures.items():
            torch.save({'input':value, 'actions':torch.zeros(value.shape[0], 1, dtype=torch.long)},
                       args.directory/(name+'.pt'))
        (args.directory/'environment.json').write_text(json.dumps({
            'python':sys.version, 'executable':sys.executable,
            'executable_sha256':digest(Path(sys.executable)), 'torch':torch.__version__,
            'torch_config':torch.__config__.show(), 'platform':sys.platform,
            'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()},
            'torch_file':torch.__file__, 'torch_file_sha256':digest(Path(torch.__file__)),
            'pid':os.getpid(), 'config':config}, indent=2)+'\n')
        print('Prepared random engineering weights and packed fixtures')
        return
    weights = torch.load(args.directory/'weights.pt', map_location='cpu', weights_only=True)
    model.load_state_dict(weights, strict=True)
    fixture = torch.load(args.directory/(args.fixture+'.pt'), weights_only=True)
    x, actions = fixture['input'], fixture['actions']
    results = {}
    # Full Cartesian flags: .eval() remains set; gradients explicitly enabled.
    for evaluate in [False, True]:
        for deterministic in [False, True]:
            torch.manual_seed(11)
            model.zero_grad(set_to_none=True)
            lp, selected, entropy, hidden, dist = model.actor(
                x.clone(), deterministic=deterministic, normFactor=1, evaluate=evaluate)
            value = model.critic(hidden)
            fixed = dist.log_probs(actions)
            loss = fixed.sum() + value.sum()
            loss.backward()
            tensors = {'probabilities':dist.probs.detach(), 'value':value.detach(),
                       'fixed_logprob':fixed.detach(), 'selected':selected.detach(),
                       'entropy':entropy.detach(), 'action_logprob':lp.detach()}
            grads = {k:None if p.grad is None else p.grad.detach().clone()
                     for k,p in model.named_parameters()}
            for k,v in tensors.items():
                if not torch.isfinite(v).all(): raise AssertionError('nonfinite '+k)
            for k,v in grads.items():
                if v is not None and not torch.isfinite(v).all(): raise AssertionError('nonfinite gradient '+k)
            assert dist.probs.shape == (x.shape[0],16)
            assert value.shape == fixed.shape == selected.shape == (x.shape[0],1)
            results[f'evaluate_{evaluate}_deterministic_{deterministic}'] = {'tensors':tensors, 'gradients':grads}
    after = {c:{m:getattr(getattr(torch.distributions,c),m,None) for m in before[c]} for c in before}
    changed = [c+'.'+m for c in before for m in before[c] if before[c][m] is not after[c][m]]
    if args.kind != 'native': assert not changed, changed
    payload = {'kind':args.kind, 'fixture':args.fixture, 'pid':os.getpid(),
               'weights_sha256':digest(args.directory/'weights.pt'),
               'input_sha256':digest(args.directory/(args.fixture+'.pt')),
               'results':results, 'global_methods_changed':changed,
               'parameter_keys':list(weights), 'config':config}
    torch.save(payload, args.directory/(args.kind+'_'+args.fixture+'_results.pt'))
    print(json.dumps({'kind':args.kind,'fixture':args.fixture,'pid':os.getpid(),
                      'global_methods_changed':changed,'flag_combinations':len(results)}))


if __name__ == '__main__':
    main()
