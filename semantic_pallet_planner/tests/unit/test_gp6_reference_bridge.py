"""Offline v2 policy tests; no historical worker, credentials, network or solver."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from semantic_pallet_planner.jev_select import geometry_jev_kernel_bridge as bridge_module
from semantic_pallet_planner.jev_select.contracts import canonical, digest, JevSelectError
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_jev_protocol import environment
from semantic_pallet_planner.jev_select.geometry_jev_protocol import validate_jev_admission
from semantic_pallet_planner.jev_select.packaging_geometry_protocol import sha

OUT = Path('semantic_pallet_planner/outputs')


def reference(path, value):
    path.write_text(canonical(value))
    return {'path': str(path), 'sha256': sha(path.read_bytes())}


@pytest.fixture
def binding(tmp_path):
    qa = OUT / 'GEOM_CANDIDATES_GP6_F0_FORMAL_ADMISSION_QA_20261122_01'
    frozen = OUT / 'GEOM_CANDIDATES_GP6_F0_FINAL_FREEZE_20261122_01'
    plan = json.loads((frozen / 'gp6_f0_order_plan_FROZEN.json').read_text())
    plan.update(source_identity=digest(source_manifest()), environment_digest=digest(environment()))
    monitor = json.loads((OUT / 'GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01/monitor_snapshot.json').read_text())
    b = json.loads((qa / 'kernel_bridge_APPROVED.json').read_text())
    b.pop('historical_package_root')
    b.update(version='geometry_jev_kernel_bridge_v2',
             validation_mode='REFERENCE_BINDINGS_ONLY_NO_HISTORICAL_EXECUTION',
             target=bridge_module.target_binding(plan, monitor))
    historical = json.loads(Path(b['historical_source_manifest']['path']).read_text())
    delta = bridge_module.source_delta(historical['files'], source_manifest())
    review = json.loads(Path(b['applicability_review']['path']).read_text())
    review.update(target=b['target'], diff_digest=digest(delta),
                  changes=[{**r, 'rationale': 'SYNTHETIC_ONLY offline policy test'} for r in delta])
    b['applicability_review'] = reference(tmp_path / 'applicability.json', review)
    a = json.loads((qa / 'order_admission_APPROVED.json').read_text())
    a.update(plan_digest=digest(plan), source_identity=plan['source_identity'],
             environment_digest=plan['environment_digest'])
    for key in ('authorization', 'review'):
        a[key] = reference(tmp_path / (key + '.json'),
                           {'scope': plan['scope'], 'status': 'APPROVED', 'plan_digest': digest(plan)})
    return plan, monitor, a, b


def test_v2_admission_repeated_without_historical_io(binding):
    plan, monitor, admission, b = binding
    # Both calls recheck references, but neither may execute or copy historical code.
    with patch.object(bridge_module.subprocess, 'run', side_effect=AssertionError('worker forbidden')), \
         patch.object(bridge_module.tempfile, 'TemporaryDirectory', side_effect=AssertionError('copy forbidden')):
        assert validate_jev_admission(plan, monitor, admission, b) is True
        assert validate_jev_admission(plan, monitor, admission, b) is True


@pytest.mark.parametrize('case', ['target', 'mode', 'extra_root', 'reference_bytes', 'monitor'])
def test_v2_rejects_drift(binding, case, tmp_path):
    plan, monitor, admission, b = copy.deepcopy(binding)
    if case == 'target':
        b['target']['plan_digest'] = '0' * 64
    elif case == 'mode':
        b['validation_mode'] = 'UNKNOWN'
    elif case == 'extra_root':
        b['historical_package_root'] = '/tmp/unneeded'
    elif case == 'reference_bytes':
        p = Path(b['applicability_review']['path'])
        p.write_text(p.read_text() + ' ')
    else:
        monitor['enabled'] = False
    with pytest.raises(JevSelectError):
        validate_jev_admission(plan, monitor, admission, b)


def test_v1_and_unknown_versions_keep_legacy_gate():
    for version in ('geometry_jev_kernel_bridge_v1', 'unknown'):
        with patch.object(bridge_module, '_validate_historical_bridge') as old:
            b = {'version': version}
            bridge_module.validate_kernel_bridge(b, {}, {})
            old.assert_called_once_with(b, {}, {})
