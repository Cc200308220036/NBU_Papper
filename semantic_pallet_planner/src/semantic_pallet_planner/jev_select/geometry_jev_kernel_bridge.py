"""Versioned evidence applicability binding; never issues a permit or runs a kernel.

The external reviewer is the trust boundary, as with the existing file receipts.
A digest proves identity, not authority. GP6 authorization remains independent.
"""
from pathlib import Path
import subprocess
import sys

from .contracts import digest, validate_schema, JevSelectError
from .packaging_geometry_protocol import read_reference, require, sha


def target_binding(plan, monitor):
    return {**{k: plan[k] for k in ('runtime_version', 'source_identity',
            'environment_digest', 'publication_policy_digest')},
            'plan_digest': digest(plan), 'monitor_digest': digest(monitor),
            'algorithm_digest': digest(monitor['algorithm_identity'])}


def source_delta(before, after):
    """Complete source delta, not just the numerical algorithm's file set."""
    return [{'path': p, 'before': before.get(p), 'after': after.get(p)}
            for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)]


def validate_kernel_bridge(bridge, plan, monitor):
    from .experiment import source_manifest
    from .geometry_jev_protocol import validate_jev_plan

    validate_schema('geometry_jev_kernel_bridge_v1', bridge)
    validate_jev_plan(plan)
    require(bridge['target'] == target_binding(plan, monitor), 'geometry_bridge_target_drift')
    receipt = read_reference(bridge['evidence_receipt'])
    validate_schema('geometry_real_kernel_receipt_v3', receipt)
    historical = read_reference(bridge['historical_source_manifest'])
    files = historical['files']
    require(digest(files) == historical['source_identity'] == receipt['source_identity'],
            'geometry_bridge_historical_source_identity')
    root = Path(bridge['historical_package_root']).resolve()
    current = Path(__file__).resolve().parents[1]
    require(root != current, 'geometry_bridge_historical_tree_required')
    # Check the exact manifest before importing any historical code. No symlinks,
    # traversal or extra importable code is accepted in the historical package.
    for name, expected in files.items():
        rel = Path(name)
        require(not rel.is_absolute() and '..' not in rel.parts and rel.suffix in ('.py', '.json'),
                'geometry_bridge_source_path')
        path = root / rel
        require(path.resolve().is_relative_to(root) and path.is_file()
                and not any(p.is_symlink() for p in (path, *path.parents)),
                'geometry_bridge_source_path')
        require(sha(path.read_bytes()) == expected, 'geometry_bridge_source_bytes')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*')
              if p.is_file() and p.suffix in ('.py', '.json')
              and not {'tests', '__pycache__'}.intersection(p.relative_to(root).parts)}
    require(actual == set(files), 'geometry_bridge_source_manifest_set')
    old_monitor = read_reference(bridge['historical_monitor'])
    require(digest(old_monitor) == receipt['monitor_digest'], 'geometry_bridge_evidence_monitor')
    review = read_reference(bridge['applicability_review'])
    validate_schema('geometry_jev_kernel_applicability_review_v1', review)
    for key in ('evidence_receipt', 'historical_source_manifest', 'historical_monitor', 'target'):
        require(review[key] == bridge[key], 'geometry_bridge_review_binding')
    delta = source_delta(files, source_manifest())
    require(review['diff_digest'] == digest(delta)
            and [{k: r[k] for k in ('path', 'before', 'after')} for r in review['changes']] == delta,
            'geometry_bridge_diff_review')
    # Identical algorithms are necessary for this minimal bridge, never sufficient:
    # the independently approved complete delta review above is also mandatory.
    require(old_monitor == monitor, 'geometry_bridge_monitor_changed_requires_new_evidence')
    worker = Path(__file__).with_name('geometry_jev_kernel_evidence_worker.py')
    result = subprocess.run([sys.executable, '-B', str(worker), str(root),
                             bridge['evidence_receipt']['path'], bridge['historical_monitor']['path']],
                            env={'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True)
    if result.returncode != 0 or result.stdout.strip() != 'GP5_V17_EVIDENCE_VALID':
        raise JevSelectError('geometry_bridge_historical_validation_failed', result.stderr[-2000:])
