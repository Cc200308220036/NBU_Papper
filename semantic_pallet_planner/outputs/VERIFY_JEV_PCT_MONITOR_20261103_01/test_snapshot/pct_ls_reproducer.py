"""Direct fixed-upstream counterexample audit; no adapter or order execution.

Run from repository root with PYTHONPATH=semantic_pallet_planner/src:
python semantic_pallet_planner/tests/unit/pct_ls_reproducer.py --output <new ignored directory>
The analytic reference is explanatory only, never substituted for PCT output.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import types

import numpy as np


def raw_upstream_space(repo):
    root = repo / 'Online-3D-BPP-PCT/pct_envs/PctContinuous0'
    package_name = '_pct_readonly_audit'
    package = types.ModuleType(package_name)
    package.__path__ = [str(root)]
    sys.modules[package_name] = package
    hashes = {}
    for name in ['convex_hull', 'PctTools', 'space']:
        path = root / f'{name}.py'
        raw = path.read_bytes()
        hashes[str(path.relative_to(repo))] = hashlib.sha256(raw).hexdigest()
        source = raw.replace(b'np.float)', b'float)') if name == 'convex_hull' else raw
        module = types.ModuleType(f'{package_name}.{name}')
        module.__package__ = package_name
        sys.modules[module.__name__] = module
        exec(compile(source, str(path), 'exec'), module.__dict__)
    return module.Space, hashes


def probe(space_class):
    space = space_class(1000, 800, 1000, holder=6)
    # Explicit nonnegative corners; no project geometry conversion is called.
    for x, y in [(380, 300), (580, 300), (480, 480)]:
        assert space.drop_box((40, 40, 100), (x, y), False, 1/(40*40*100), 1)
    accepted = space.drop_box((260, 240, 100), (370, 280), False, 3/(260*240*100), 1)
    assert accepted  # upstream result; its numerical validity is checked below
    top = space.boxes[-1]
    flows = [edge.box.up_edges[top].mass for edge in top.bottom_edges]
    centers = [edge.centre2D.tolist() for edge in top.bottom_edges]
    coefficient = np.zeros((4, 3))
    rhs = np.array([[0.], [0.], [0.], [1.]])
    count = 0
    for i in range(2):
        for j in range(i+1, 3):
            axis = np.array(centers[i])-centers[j]
            denominator = np.dot(top.thisStack.centre[:2]-centers[i], axis)
            if denominator != 0:
                ratio = abs(np.dot(top.thisStack.centre[:2]-centers[j], axis))/denominator
                coefficient[count, i] = 1
                coefficient[count, j] = -ratio
            count += 1
    coefficient[-1, :] = 1
    fractions = np.linalg.lstsq(coefficient, rhs, rcond=None)[0].ravel()
    assert np.allclose(np.array(flows)/top.mass, fractions, atol=1e-12, rtol=0)
    assert not np.isclose(sum(flows), top.mass, atol=1e-9, rtol=1e-9)
    return {'upstream_return': bool(accepted), 'input_mass_kg': float(top.mass),
            'support_centers_kernel_mm': centers, 'flows_kg': flows,
            'flow_sum_kg': sum(flows), 'mass_deficit_kg': top.mass-sum(flows),
            'coefficient': coefficient.tolist(), 'rhs': rhs.ravel().tolist(),
            'fractions': fractions.tolist(), 'fraction_sum': float(sum(fractions)),
            'residual': (coefficient@fractions-rhs.ravel()).tolist()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from semantic_pallet_planner.jev_select.stability.vendor.pct.space import Space
    args.output.mkdir(parents=True, exist_ok=False)
    raw_class, hashes = raw_upstream_space(args.repo.resolve())
    raw_result, vendored_result = probe(raw_class), probe(Space)
    assert raw_result == vendored_result
    # At world centers (-100,-80),(100,-80),(0,100), positive fractions
    # (5/18,5/18,4/9) sum to one and have zero x/y moment around COM=(0,0).
    analytic = np.array([5/18, 5/18, 4/9])
    assert np.isclose(sum(analytic), 1)
    assert np.allclose(analytic@np.array([[-100,-80],[100,-80],[0,100]]), [0,0])
    evidence = {'status': 'DEFECT_CONFIRMED_WITHOUT_ADAPTER',
        'upstream_source_sha256': hashes, 'in_memory_compatibility_only': 'np.float -> float in convex_hull; no original files edited',
        'raw_upstream': raw_result, 'vendored': vendored_result,
        'exact_raw_vendor_agreement': True,
        'analytic_reference_not_runtime_algorithm': {'fractions': analytic.tolist(), 'flows_kg': (3*analytic).tolist(),
            'sum_fraction': float(sum(analytic)), 'world_xy_moment_per_kg': (analytic@np.array([[-100,-80],[100,-80],[0,100]])).tolist()},
        'cause': 'First pair constraint requires positive fractions f0+f1=0. Inconsistent constraints and soft least-squares sum row permit fraction sum !=1.',
        'semantic_fix_in_scope': False,
        'resolution': 'P1 general multisupport remains incomplete; no sign correction, hard-constrained solver or normalization applied.'}
    (args.output/'direct_upstream_ls_audit.json').write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status': evidence['status'], 'mass_deficit_kg': raw_result['mass_deficit_kg'], 'raw_vendor_agreement': True}))


if __name__ == '__main__':
    main()
