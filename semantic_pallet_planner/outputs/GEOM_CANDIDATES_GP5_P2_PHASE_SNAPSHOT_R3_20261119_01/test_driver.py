"""OFFLINE TEST DOUBLE and pure contract tests for GP5_P2_PHASE_SNAPSHOT_PARENT_EVIDENCE_CORRECTION_ONLY (R3).

Separates:
- Pure contract & accounting validation (parent evidence verification, post-seal parent drift/missing/failure/cross-run rejection,
  validate_completion parent-evidence check, CLI explicit --runtime directory & historical freeze refusal,
  authorization path+SHA binding, zero-ledger & 4-config preflight barriers).
- Metered monitor-substitute 4+6 orchestration (real run_order_job, OrderStore, geometry_order_accounting,
  validate_saved_checkpoint, and validate_completion over all 4 primary + 6 recovery runs with simulated LP counts).
No real kernel, LP, freeze, or model calls are executed.
"""
import copy
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

import driver as d
from semantic_pallet_planner.jev_select import geometry_execution as ge
from semantic_pallet_planner.jev_select import geometry_kernel_completion as completion
from semantic_pallet_planner.jev_select import geometry_order_accounting as accounting
from semantic_pallet_planner.jev_select import geometry_order_execution as order
from semantic_pallet_planner.jev_select import geometry_order_meter as meter
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.contracts import JevSelectError, canonical, digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields, wire
from semantic_pallet_planner.jev_select.stability import exact_adapter, exact_contracts

HOST_PREFLIGHT = d.read(
    Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_HOST_PREFLIGHT_20261119_01/host_preflight.json')
)
ARCHIVED_ORDER_ENV = HOST_PREFLIGHT['actual_order_environment']


class PhaseSnapshotParentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='gp5_p2_r3_')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)

        for name in (
            'exact_adapter.assess_candidate',
            'balance_adapter.assess_candidate',
            'balance_network.solve_network',
            'balance_network.linprog',
            'monitor.exact_freeze',
            'monitor.freeze',
        ):
            self.stack.enter_context(
                patch(
                    'semantic_pallet_planner.jev_select.stability.' + name,
                    side_effect=AssertionError('REAL_KERNEL_FORBIDDEN:' + name),
                )
            )
        self.stack.enter_context(
            patch.object(socket.socket, 'connect', side_effect=AssertionError('NETWORK_FORBIDDEN'))
        )
        for target in (
            'semantic_pallet_planner.jev_select.geometry_runtime_contracts.environment',
            'semantic_pallet_planner.jev_select.packaging_geometry_protocol.environment',
            'semantic_pallet_planner.jev_select.geometry_order_execution.environment',
            'semantic_pallet_planner.jev_select.geometry_execution.environment',
        ):
            self.stack.enter_context(patch(target, return_value=copy.deepcopy(ARCHIVED_ORDER_ENV)))

    def forbid_dispatch(self):
        def _forbidden(plan_arg, jid, adapted, *, root, resume=None, phase_credential=None, **kw):
            raise AssertionError('DISPATCH_FORBIDDEN')

        return patch.object(order, 'run_order_job', side_effect=_forbidden)

    def make_runtime_and_records(self, subdir='runtime'):
        """Build an isolated temporary new-freeze runtime directory aligned with live source_identity."""
        runtime = self.root / subdir
        runtime.mkdir(parents=True, exist_ok=True)
        snap = d.read(d.HISTORICAL_RUNTIME / 'monitor_snapshot.json')
        d.write(runtime / 'monitor_snapshot.json', snap)
        snap_ref = {
            'path': str(runtime / 'monitor_snapshot.json'),
            'sha256': p.sha((runtime / 'monitor_snapshot.json').read_bytes()),
        }

        files = source_manifest()
        d.write(
            runtime / 'source_manifest.json',
            {'source_files': len(files), 'source_identity': digest(files), 'files': files},
        )

        adapted = []
        for case in ('K01', 'K02'):
            raw = (d.HISTORICAL_RUNTIME / f'{case}_task.json').read_bytes()
            (runtime / f'{case}_task.json').write_bytes(raw)
            t = p.adapt_task(raw, origin='SYNTHETIC_FIXED', expected_sha256=p.sha(raw))
            adapted.append(t)

        base_plan = d.read(d.HISTORICAL_RUNTIME / 'acceptance_plan_FROZEN.json')
        plan = p.prepare_order_plan(adapted, data_identity=base_plan['data_identity'], scope=p.ACCEPTANCE, native=True)
        ledger_path = runtime / 'shared_call_ledger.json'
        plan.update(
            status='FROZEN',
            assessment_limit=8,
            solver_limit=128,
            model_calls_max=0,
            call_ledger_path=str(ledger_path),
        )
        d.write(runtime / 'acceptance_plan_FROZEN.json', plan)
        plan_ref = {
            'path': str(runtime / 'acceptance_plan_FROZEN.json'),
            'sha256': p.sha((runtime / 'acceptance_plan_FROZEN.json').read_bytes()),
        }

        d.write(
            ledger_path,
            {
                'version': 'geometry_call_ledger_v1',
                'plan_digest': digest(plan),
                'evidence': 'REAL_KERNEL',
                'limits': {'assessment_entries': 8, 'solver_calls': 128},
                'counts': {'assessment_entries': 0, 'solver_calls': 0, 'test_double_assessments': 0},
                'calls': [],
            },
        )

        common = {
            **identity_fields(plan),
            'scope': plan['scope'],
            'plan_digest': digest(plan),
            'status': 'APPROVED',
        }
        auth_doc = {**common, 'version': wire(plan, 'geometry_scope_authorization_v1')}
        auth_path = runtime / 'user_authorization.json'
        auth_path.write_text(canonical(auth_doc))
        auth_ref = {'path': str(auth_path), 'sha256': p.sha(auth_path.read_bytes())}

        auth_ref_file = self.root / f'{subdir}_authorization_reference.json'
        d.write(auth_ref_file, copy.deepcopy(auth_ref))

        req = d.read(d.HISTORICAL_RUNTIME / 'startup_review_request.json')
        req.update(
            plan_digest=digest(plan),
            monitor_digest=digest(snap),
            source_identity=plan['source_identity'],
            environment_digest=plan['environment_digest'],
            publication_policy_digest=plan['publication_policy_digest'],
            plan_reference=plan_ref,
            monitor_reference=snap_ref,
            authorization_reference=copy.deepcopy(auth_ref),
            shared_ledger_path=str(ledger_path),
        )
        d.write(runtime / 'startup_review_request.json', req)

        review_doc = {**common, 'version': wire(plan, 'geometry_scope_review_v1')}
        review_path = self.root / f'{subdir}_review.json'
        review_path.write_text(canonical(review_doc))
        review_ref = {'path': str(review_path), 'sha256': p.sha(review_path.read_bytes())}

        launch_doc = {
            **common,
            'version': wire(plan, 'geometry_kernel_launch_v1'),
            'monitor_digest': digest(snap),
            'source_identity': plan['source_identity'],
            'environment_digest': plan['environment_digest'],
            'authorization': copy.deepcopy(auth_ref),
            'review': copy.deepcopy(review_ref),
        }
        launch_path = self.root / f'{subdir}_launch.json'
        launch_path.write_text(canonical(launch_doc))
        return runtime, plan, snap, auth_path, auth_ref, auth_ref_file, review_path, launch_path, adapted

    def build_parent_and_snapshot_fixture(self, cfg, adapted_task, parent_name='parent_j00', snap_name='snap_j00', job_id='J00'):
        parent_root = self.root / parent_name / 'jobs' / job_id
        snap_root = self.root / snap_name / 'jobs' / job_id
        (parent_root / 'blobs').mkdir(parents=True, exist_ok=True)
        raw_bytes = adapted_task['raw']
        raw_sha = p.sha(raw_bytes)
        g_bytes = b'{"test_geometry_blob":true}'
        g_sha = p.sha(g_bytes)
        (parent_root / 'blobs' / raw_sha).write_bytes(raw_bytes)
        (parent_root / 'blobs' / g_sha).write_bytes(g_bytes)
        d.write(parent_root / 'config.json', cfg)
        d.write(parent_root / 'task_identity.json', cfg['order_task_identity'])

        cp_selected = {
            'phase': 'SELECTED',
            'job_id': job_id,
            'pending_event': {'geometry_ref': {'version': 'geometry_blob_ref_v1', 'sha256': g_sha}},
        }
        cp_terminal = {
            'phase': 'TERMINATED',
            'reason': 'ALL_ITEMS_PLACED',
            'job_id': job_id,
            'method': cfg['selector'],
            'config_digest': digest(cfg),
            'task_digest': cfg['order_task_identity']['runtime_digest'],
        }

        with accounting.invocation(parent_root / 'accounting.json', cfg, job_id, resume=None):
            accounting.tick(cfg, 'selector_calls')
            d.write(parent_root / 'checkpoint.json', cp_selected)
            shutil.copytree(parent_root, snap_root)
            accounting.tick(cfg, 'monitor_entries')
            accounting.tick(cfg, 'commit_attempts')
            accounting.tick(cfg, 'commit_successes')
            accounting.completed(cfg, cp_terminal)

        d.write(parent_root / 'checkpoint.json', cp_terminal)
        d.write(
            parent_root / 'record.json',
            {
                'checkpoint': cp_terminal,
                'config': cfg,
                'raw_task': {'path': str(parent_root / 'blobs' / raw_sha), 'sha256': raw_sha},
                'durable_root': str(parent_root),
            },
        )
        return parent_root, snap_root, cp_selected, cp_terminal

    # --- 1. GP5-P2-R2-PARENT-EVIDENCE-01 pure contract & accounting tests ---
    def test_parent_evidence_01_post_seal_parent_accounting_or_record_mutation_rejected(self):
        """Regression for QA probe: after a credential is genuinely sealed, mutating or deleting
        the parent final accounting or parent final record is rejected before recovery dispatch.
        """
        _, plan, snap, _, _, _, _, launch_path, adapted = self.make_runtime_and_records()
        with patch.object(order, 'validate_monitor_snapshot'), self.forbid_dispatch():
            cfg = order.load_order_config(plan, 'J00', monitor_snapshot=snap, admission=d.read(launch_path))

        parent_root, snap_root, cp_selected, cp_terminal = self.build_parent_and_snapshot_fixture(cfg, adapted[0])
        cred = accounting.seal_phase_snapshot_credential(
            parent_root,
            snap_root,
            cfg,
            'J00',
            'SELECTED',
            cp_selected,
            parent_result={'summary': {'completed': True}, 'checkpoint': cp_terminal},
        )
        # Valid before mutation
        accounting.validate_phase_snapshot_credential(cred, snap_root, cfg, 'J00', cp_selected)

        # Case A: Parent accounting.json mutated after credential was sealed (exact QA probe scenario)
        orig_parent_acc = (parent_root / 'accounting.json').read_bytes()
        d.write(parent_root / 'accounting.json', {**d.read(parent_root / 'accounting.json'), 'invocations': []})
        with self.assertRaises(JevSelectError) as ctx_acc_drift:
            accounting.validate_phase_snapshot_credential(cred, snap_root, cfg, 'J00', cp_selected)
        self.assertEqual(ctx_acc_drift.exception.code, 'geometry_receipt_bytes_drift')
        with self.assertRaises(JevSelectError) as ctx_inv_drift:
            with accounting.invocation(
                snap_root / 'accounting.json', cfg, 'J00', resume=cp_selected, phase_credential=cred
            ):
                pass
        self.assertEqual(ctx_inv_drift.exception.code, 'geometry_receipt_bytes_drift')

        # Case B: Parent accounting.json missing after credential was sealed
        (parent_root / 'accounting.json').unlink()
        with self.assertRaises(JevSelectError) as ctx_acc_missing:
            accounting.validate_phase_snapshot_credential(cred, snap_root, cfg, 'J00', cp_selected)
        self.assertEqual(ctx_acc_missing.exception.code, 'geometry_missing_receipt')
        (parent_root / 'accounting.json').write_bytes(orig_parent_acc)

        # Case C: Parent record.json mutated after credential was sealed
        orig_parent_rec = (parent_root / 'record.json').read_bytes()
        bad_rec = d.read(parent_root / 'record.json')
        bad_rec['checkpoint']['reason'] = 'TECHNICAL_FAILURE'
        d.write(parent_root / 'record.json', bad_rec)
        with self.assertRaises(JevSelectError) as ctx_rec_drift:
            accounting.validate_phase_snapshot_credential(cred, snap_root, cfg, 'J00', cp_selected)
        self.assertEqual(ctx_rec_drift.exception.code, 'geometry_receipt_bytes_drift')

        # Case D: Parent record.json missing after credential was sealed
        (parent_root / 'record.json').unlink()
        with self.assertRaises(JevSelectError) as ctx_rec_missing:
            accounting.validate_phase_snapshot_credential(cred, snap_root, cfg, 'J00', cp_selected)
        self.assertEqual(ctx_rec_missing.exception.code, 'geometry_missing_receipt')
        (parent_root / 'record.json').write_bytes(orig_parent_rec)

        # Case E: Cross-run mixing (credential points to another run's parent accounting/record path)
        other_parent, _, _, _ = self.build_parent_and_snapshot_fixture(
            cfg, adapted[0], parent_name='other_parent', snap_name='other_snap'
        )
        cross_cred = copy.deepcopy(cred)
        cross_cred['parent_invocation']['final_accounting_ref'] = {
            'path': str(other_parent / 'accounting.json'),
            'sha256': p.sha((other_parent / 'accounting.json').read_bytes()),
        }
        cross_cred['credential_digest'] = digest({k: v for k, v in cross_cred.items() if k != 'credential_digest'})
        with self.assertRaises(JevSelectError) as ctx_cross:
            accounting.validate_phase_snapshot_credential(cross_cred, snap_root, cfg, 'J00', cp_selected)
        self.assertEqual(ctx_cross.exception.code, 'geometry_phase_snapshot_parent_accounting_path_drift')

    def test_parent_evidence_01_rejections_and_legacy_started_refusal(self):
        """Verify ordinary STARTED refusal remains intact, and failed/incomplete/wrong-identity parent evidence is rejected."""
        _, plan, snap, _, _, _, _, launch_path, adapted = self.make_runtime_and_records()
        launch_doc = d.read(launch_path)
        with patch.object(order, 'validate_monitor_snapshot'), self.forbid_dispatch():
            cfg_j00 = order.load_order_config(plan, 'J00', monitor_snapshot=snap, admission=launch_doc)
            cfg_j01 = order.load_order_config(plan, 'J01', monitor_snapshot=snap, admission=launch_doc)

        parent_root = self.root / 'p_j00' / 'jobs' / 'J00'
        snap_root = self.root / 's_j00' / 'jobs' / 'J00'
        (parent_root / 'blobs').mkdir(parents=True, exist_ok=True)
        raw_bytes = adapted[0]['raw']
        raw_sha = p.sha(raw_bytes)
        g_bytes = b'{"test_geometry_blob":true}'
        g_sha = p.sha(g_bytes)
        (parent_root / 'blobs' / raw_sha).write_bytes(raw_bytes)
        (parent_root / 'blobs' / g_sha).write_bytes(g_bytes)
        d.write(parent_root / 'config.json', cfg_j00)
        d.write(parent_root / 'task_identity.json', cfg_j00['order_task_identity'])

        cp_selected = {
            'phase': 'SELECTED',
            'job_id': 'J00',
            'pending_event': {'geometry_ref': {'version': 'geometry_blob_ref_v1', 'sha256': g_sha}},
        }
        cp_terminal = {
            'phase': 'TERMINATED',
            'reason': 'ALL_ITEMS_PLACED',
            'job_id': 'J00',
            'method': cfg_j00['selector'],
            'config_digest': digest(cfg_j00),
            'task_digest': cfg_j00['order_task_identity']['runtime_digest'],
        }

        with accounting.invocation(parent_root / 'accounting.json', cfg_j00, 'J00', resume=None):
            accounting.tick(cfg_j00, 'selector_calls')
            d.write(parent_root / 'checkpoint.json', cp_selected)
            shutil.copytree(parent_root, snap_root)
            # In-run: parent has not returned yet -> attempting to seal credential must fail!
            with self.assertRaises(JevSelectError) as ctx_in_run:
                accounting.seal_phase_snapshot_credential(
                    parent_root,
                    snap_root,
                    cfg_j00,
                    'J00',
                    'SELECTED',
                    cp_selected,
                    parent_result={'summary': {'completed': True}, 'checkpoint': cp_terminal},
                )
            self.assertEqual(ctx_in_run.exception.code, 'geometry_phase_snapshot_parent_not_returned')
            accounting.tick(cfg_j00, 'monitor_entries')
            accounting.tick(cfg_j00, 'commit_attempts')
            accounting.tick(cfg_j00, 'commit_successes')
            accounting.completed(cfg_j00, cp_terminal)

        d.write(parent_root / 'checkpoint.json', cp_terminal)
        d.write(
            parent_root / 'record.json',
            {
                'checkpoint': cp_terminal,
                'config': cfg_j00,
                'raw_task': {'path': str(parent_root / 'blobs' / raw_sha), 'sha256': raw_sha},
                'durable_root': str(parent_root),
            },
        )

        # 1. Ordinary resume without phase_credential MUST still reject STARTED with geometry_accounting_unknown_dispatch
        before_bytes = (snap_root / 'accounting.json').read_bytes()
        with self.assertRaises(JevSelectError) as ctx_no_cred:
            with accounting.invocation(snap_root / 'accounting.json', cfg_j00, 'J00', resume=cp_selected):
                pass
        self.assertEqual(ctx_no_cred.exception.code, 'geometry_accounting_unknown_dispatch')
        self.assertEqual((snap_root / 'accounting.json').read_bytes(), before_bytes)

        # 2. Parent failed (summary.completed == False) or parent accounting status == 'ERROR' -> sealing rejected
        with self.assertRaises(JevSelectError) as ctx_not_comp:
            accounting.seal_phase_snapshot_credential(
                parent_root,
                snap_root,
                cfg_j00,
                'J00',
                'SELECTED',
                cp_selected,
                parent_result={'summary': {'completed': False}, 'checkpoint': cp_terminal},
            )
        self.assertEqual(ctx_not_comp.exception.code, 'geometry_phase_snapshot_parent_not_completed')

        err_parent = self.root / 'err_parent'
        shutil.copytree(parent_root, err_parent)
        err_acc = d.read(err_parent / 'accounting.json')
        err_acc['invocations'][0]['status'] = 'ERROR'
        d.write(err_parent / 'accounting.json', err_acc)
        err_rec = d.read(err_parent / 'record.json')
        err_rec['durable_root'] = str(err_parent)
        d.write(err_parent / 'record.json', err_rec)
        with self.assertRaises(JevSelectError) as ctx_err_parent:
            accounting.seal_phase_snapshot_credential(
                err_parent,
                snap_root,
                cfg_j00,
                'J00',
                'SELECTED',
                cp_selected,
                parent_result={'summary': {'completed': True}, 'checkpoint': cp_terminal},
            )
        self.assertEqual(ctx_err_parent.exception.code, 'geometry_phase_snapshot_parent_not_returned')

        # 3. Same root for parent and snapshot -> rejected
        with self.assertRaises(JevSelectError) as ctx_same_root:
            accounting.seal_phase_snapshot_credential(
                parent_root,
                parent_root,
                cfg_j00,
                'J00',
                'SELECTED',
                cp_selected,
                parent_result={'summary': {'completed': True}, 'checkpoint': cp_terminal},
            )
        self.assertEqual(ctx_same_root.exception.code, 'geometry_phase_snapshot_distinct_root_required')

        # 4. Seal valid credential and verify wrong config / tampered digest rejections
        cred = accounting.seal_phase_snapshot_credential(
            parent_root,
            snap_root,
            cfg_j00,
            'J00',
            'SELECTED',
            cp_selected,
            parent_result={'summary': {'completed': True}, 'checkpoint': cp_terminal},
        )
        bad_digest_cred = copy.deepcopy(cred)
        bad_digest_cred['credential_digest'] = '0' * 64
        with self.assertRaises(JevSelectError) as ctx_digest:
            with accounting.invocation(
                snap_root / 'accounting.json', cfg_j00, 'J00', resume=cp_selected, phase_credential=bad_digest_cred
            ):
                pass
        self.assertEqual(ctx_digest.exception.code, 'geometry_phase_snapshot_credential_digest_drift')

        with self.assertRaises(JevSelectError) as ctx_wrong_cfg:
            with accounting.invocation(
                snap_root / 'accounting.json', cfg_j01, 'J01', resume=cp_selected, phase_credential=cred
            ):
                pass
        self.assertEqual(ctx_wrong_cfg.exception.code, 'geometry_accounting_drift')

    def test_v16_legacy_phase_snapshot_credential_compatibility(self):
        """Verify v16 wire routing produces geometry_phase_snapshot_credential_v1 with parent references."""
        adapted = []
        for case in ('K01', 'K02'):
            raw = (d.HISTORICAL_RUNTIME / f'{case}_task.json').read_bytes()
            adapted.append(p.adapt_task(raw, origin='SYNTHETIC_FIXED', expected_sha256=p.sha(raw)))
        plan16 = p.prepare_order_plan(adapted, data_identity=digest('V16_TEST'), scope=p.DEVELOPMENT, native=False)
        self.assertEqual(wire(plan16, 'geometry_phase_snapshot_credential_v1'), 'geometry_phase_snapshot_credential_v1')
        adm16 = {
            'version': 'geometry_development_binding_v1',
            'scope': p.DEVELOPMENT,
            'evidence': 'TEST_DOUBLE',
            'plan_digest': digest(plan16),
        }
        snap = d.read(d.HISTORICAL_RUNTIME / 'monitor_snapshot.json')
        with patch.object(order, 'validate_monitor_snapshot'), self.forbid_dispatch():
            cfg16 = order.load_order_config(plan16, 'J00', monitor_snapshot=snap, admission=adm16)
        p_root, s_root, cp_sel, cp_term = self.build_parent_and_snapshot_fixture(
            cfg16, adapted[0], parent_name='v16_parent', snap_name='v16_snap'
        )
        cred16 = accounting.seal_phase_snapshot_credential(
            p_root,
            s_root,
            cfg16,
            'J00',
            'SELECTED',
            cp_sel,
            parent_result={'summary': {'completed': True}, 'checkpoint': cp_term},
        )
        self.assertEqual(cred16['version'], 'geometry_phase_snapshot_credential_v1')
        self.assertNotIn('runtime_version', cred16)
        accounting.validate_phase_snapshot_credential(cred16, s_root, cfg16, 'J00', cp_sel)

    # --- 2. GP5-P2-R2-RUNTIME-INPUT-01 CLI & explicit runtime directory tests ---
    def test_runtime_input_01_cli_requires_explicit_runtime_and_passes_to_execute(self):
        """Verify CLI requires --runtime and forwards the explicit runtime directory to execute without defaulting to historical freeze."""
        runtime, _, _, _, _, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records()
        # Missing --runtime on CLI must fail argparse before any execution
        with self.forbid_dispatch(), self.assertRaises(SystemExit):
            d.main(['--review', str(review_path), '--launch', str(launch_path), '--output', str(self.root / 'no_rt')])

        # Explicit --runtime on CLI is forwarded to execute
        called = {}

        def fake_execute(rt, rev, lch, out, *, authorization_reference=None):
            called.update(
                runtime=str(rt),
                review=str(rev),
                launch=str(lch),
                output=str(out),
                authorization_reference=str(authorization_reference),
            )

        with patch.object(d, 'execute', side_effect=fake_execute):
            d.main([
                '--runtime',
                str(runtime),
                '--review',
                str(review_path),
                '--launch',
                str(launch_path),
                '--output',
                str(self.root / 'cli_out'),
                '--authorization-reference',
                str(auth_ref_file),
            ])
        self.assertEqual(
            called,
            {
                'runtime': str(runtime),
                'review': str(review_path),
                'launch': str(launch_path),
                'output': str(self.root / 'cli_out'),
                'authorization_reference': str(auth_ref_file),
            },
        )

    def test_runtime_input_01_historical_stale_wrong_or_missing_runtime_rejected_before_dispatch(self):
        """Verify historical runtime directory, stale source_identity, wrong directory, missing files,
        or historical authorization reference are rejected before 4-config preflight and dispatch.
        """
        runtime, _, _, _, _, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records()

        # 1. Historical runtime directory passed to CLI -> rejected
        with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
            with self.assertRaisesRegex(AssertionError, 'HISTORICAL_RUNTIME_DIRECTORY_FORBIDDEN'):
                d.main([
                    '--runtime',
                    str(d.HISTORICAL_RUNTIME),
                    '--review',
                    str(review_path),
                    '--launch',
                    str(launch_path),
                    '--output',
                    str(self.root / 'out_hist_rt'),
                ])
            cfg.assert_not_called()
            run.assert_not_called()

        # 2. Non-existent directory -> rejected
        with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
            with self.assertRaisesRegex(AssertionError, 'RUNTIME_DIRECTORY_NOT_FOUND'):
                d.main([
                    '--runtime',
                    str(self.root / 'does_not_exist'),
                    '--review',
                    str(review_path),
                    '--launch',
                    str(launch_path),
                    '--output',
                    str(self.root / 'out_no_dir'),
                ])
            cfg.assert_not_called()
            run.assert_not_called()

        # 3. Missing required file in runtime directory -> rejected
        incomplete_rt = self.root / 'incomplete_rt'
        shutil.copytree(runtime, incomplete_rt)
        (incomplete_rt / 'shared_call_ledger.json').unlink()
        with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
            with self.assertRaisesRegex(AssertionError, 'RUNTIME_MISSING_REQUIRED_FILE:shared_call_ledger.json'):
                d.main([
                    '--runtime',
                    str(incomplete_rt),
                    '--review',
                    str(review_path),
                    '--launch',
                    str(launch_path),
                    '--output',
                    str(self.root / 'out_incomplete'),
                ])
            cfg.assert_not_called()
            run.assert_not_called()

        # 4. Copy of historical runtime at a new path (old source_identity) -> rejected
        stale_rt = self.root / 'stale_copied_rt'
        shutil.copytree(d.HISTORICAL_RUNTIME, stale_rt)
        with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
            with self.assertRaisesRegex(AssertionError, 'PLAN_SOURCE_IDENTITY_STALE_OR_MISMATCH'):
                d.main([
                    '--runtime',
                    str(stale_rt),
                    '--review',
                    str(review_path),
                    '--launch',
                    str(launch_path),
                    '--output',
                    str(self.root / 'out_stale'),
                ])
            cfg.assert_not_called()
            run.assert_not_called()

        # 5. New runtime directory attempting to point authorization to historical user_authorization.json -> rejected
        hist_auth_path = d.HISTORICAL_RUNTIME / 'user_authorization.json'
        hist_auth_ref = {'path': str(hist_auth_path), 'sha256': p.sha(hist_auth_path.read_bytes())}
        launch_hist_auth = d.read(launch_path)
        launch_hist_auth['authorization'] = hist_auth_ref
        launch_hist_path = self.root / 'launch_hist_auth.json'
        d.write(launch_hist_path, launch_hist_auth)
        with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
            with self.assertRaisesRegex(AssertionError, 'HISTORICAL_AUTHORIZATION_FORBIDDEN'):
                d.execute(
                    runtime,
                    review_path,
                    launch_hist_path,
                    self.root / 'out_hist_auth',
                    authorization_reference=hist_auth_ref,
                )
            cfg.assert_not_called()
            run.assert_not_called()

    # --- 3. Retained AUTH-01, LEDGER-01, capability & 4-config preflight barrier tests ---
    def test_auth_01_correct_binding_and_rejections(self):
        runtime, _, _, auth_path, auth_ref, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records()
        with patch.object(order, 'validate_monitor_snapshot'), self.forbid_dispatch():
            d.prepare(runtime, review_path, launch_path)
            d.prepare(runtime, review_path, launch_path, authorization_reference=auth_ref)
            d.prepare(runtime, review_path, launch_path, authorization_reference=auth_ref_file)

        # Same content, different path -> rejected
        alt_auth_path = self.root / 'alternate_authorization.json'
        alt_auth_path.write_bytes(auth_path.read_bytes())
        launch_doc = d.read(launch_path)
        launch_doc['authorization'] = {'path': str(alt_auth_path), 'sha256': p.sha(alt_auth_path.read_bytes())}
        d.write(launch_path, launch_doc)
        with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
            with self.assertRaisesRegex(AssertionError, 'AUTHORIZATION_REFERENCE_PATH_MISMATCH'):
                d.execute(
                    runtime,
                    review_path,
                    launch_path,
                    self.root / 'run_alt_path',
                    authorization_reference=auth_ref_file,
                )
            cfg.assert_not_called()
            run.assert_not_called()

        # Same path, drifted bytes AND re-signed launch.authorization.sha256 -> rejected
        runtime2, _, _, auth_path2, auth_ref2, auth_ref_file2, review_path2, launch_path2, _ = (
            self.make_runtime_and_records('runtime2')
        )
        auth_path2.write_bytes(auth_path2.read_bytes() + b'\n')
        launch_doc2 = d.read(launch_path2)
        launch_doc2['authorization']['sha256'] = p.sha(auth_path2.read_bytes())
        d.write(launch_path2, launch_doc2)
        for idx, spec in enumerate((None, auth_ref2, auth_ref_file2)):
            with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
                with self.assertRaisesRegex(AssertionError, 'AUTHORIZATION_FILE_BYTES_DRIFT'):
                    d.execute(
                        runtime2,
                        review_path2,
                        launch_path2,
                        self.root / f'run_resigned_{idx}',
                        authorization_reference=spec,
                    )
                cfg.assert_not_called()
                run.assert_not_called()

    def test_ledger_01_nonempty_prior_and_in_run_counter_drift_rejected(self):
        runtime, plan, _, _, _, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records()
        ledger_path = Path(plan['call_ledger_path'])
        for idx, state in enumerate(('DONE', 'STARTED', 'ERROR')):
            prior = {
                'version': 'geometry_call_ledger_v1',
                'plan_digest': digest(plan),
                'evidence': 'REAL_KERNEL',
                'limits': {'assessment_entries': 8, 'solver_calls': 128},
                'counts': {'assessment_entries': 1, 'solver_calls': 0, 'test_double_assessments': 0},
                'calls': [{'kind': 'assessment_entries', 'state': state, 'job_id': 'J00', 'index': 0}],
            }
            d.write(ledger_path, prior)
            before_bytes = ledger_path.read_bytes()
            with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
                with self.assertRaisesRegex(AssertionError, 'NONEMPTY_INITIAL_LEDGER_CALLS'):
                    d.execute(
                        runtime,
                        review_path,
                        launch_path,
                        self.root / f'run_nonempty_{idx}',
                        authorization_reference=auth_ref_file,
                    )
                cfg.assert_not_called()
                run.assert_not_called()
            self.assertEqual(ledger_path.read_bytes(), before_bytes)

    def test_capability_preflight_barrier_and_first_failure_stop(self):
        runtime, _, _, _, _, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records()
        # Missing snapshot capability -> stops before preflight
        with (
            patch.object(accounting, 'seal_phase_snapshot_credential', None),
            patch.object(order, 'load_order_config') as cfg,
            self.forbid_dispatch() as run,
        ):
            with self.assertRaisesRegex(AssertionError, 'PHASE_SNAPSHOT_SEALER_MISSING'):
                d.execute(runtime, review_path, launch_path, self.root / 'run_no_cap', authorization_reference=auth_ref_file)
            cfg.assert_not_called()
            run.assert_not_called()

        # Joint 4-config preflight failure on J02 -> 0 dispatches
        with (
            patch.object(order, 'load_order_config', side_effect=[{}, {}, RuntimeError('J02_PREFLIGHT_FAIL')]) as cfg,
            self.forbid_dispatch() as run,
        ):
            with self.assertRaisesRegex(RuntimeError, 'J02_PREFLIGHT_FAIL'):
                d.execute(runtime, review_path, launch_path, self.root / 'run_j02_fail', authorization_reference=auth_ref_file)
        self.assertEqual(cfg.call_count, 3)
        run.assert_not_called()

        # First primary failure -> stops immediately with 1 FAILED and 9 NOT_RUN
        def fail_first(plan_arg, jid, adapted, *, root, resume=None, phase_credential=None, **kw):
            raise RuntimeError('OFFLINE_PRIMARY_FAILURE')

        with (
            patch.object(order, 'validate_monitor_snapshot'),
            patch.object(order, 'run_order_job', side_effect=fail_first) as run,
        ):
            with self.assertRaisesRegex(RuntimeError, 'OFFLINE_PRIMARY_FAILURE'):
                d.execute(runtime, review_path, launch_path, self.root / 'run_first_fail', authorization_reference=auth_ref_file)
        self.assertEqual(run.call_count, 1)
        rows = d.read(self.root / 'run_first_fail/driver_receipt.json')['rows']
        self.assertEqual(rows[0]['status'], 'FAILED')
        self.assertEqual(sum(r['status'] == 'NOT_RUN' for r in rows), 9)

    # --- 4. Metered monitor-substitute 4+6 orchestration & completion review parent-evidence verification ---
    def test_dispatch_01_full_4_plus_6_with_parent_evidence_and_completion_validation(self):
        """Run CLI main() through real run_order_job, OrderStore, geometry_order_accounting,
        validate_saved_checkpoint, and validate_completion on all 4 primary + 6 recovery runs,
        using a monitor substitute and simulated LP counts (real kernel/LP calls = 0).
        Also verifies that validate_completion rejects post-run mutation of the retained parent accounting/record.
        """
        runtime, plan, snap, _, _, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records()
        entry_calls = []
        real_run_order_job = order.run_order_job

        def spy_run_order_job(
            p_arg,
            jid,
            adapted,
            *,
            monitor_snapshot,
            admission,
            root,
            kernel_receipt=None,
            resume=None,
            phase_credential=None,
            on_checkpoint=None,
            hook=None,
        ):
            entry_calls.append({
                'job_id': jid,
                'phase': resume['phase'] if resume else 'FRESH',
                'has_credential': phase_credential is not None,
                'root': str(root),
            })
            return real_run_order_job(
                p_arg,
                jid,
                adapted,
                monitor_snapshot=monitor_snapshot,
                admission=admission,
                root=root,
                kernel_receipt=kernel_receipt,
                resume=resume,
                phase_credential=phase_credential,
                on_checkpoint=on_checkpoint,
                hook=hook,
            )

        @contextmanager
        def offline_metered_substitute(p_arg, *, job_id, monitor_snapshot, admission, kernel_receipt=None):
            budget = meter.CallBudget(p_arg['call_ledger_path'], p_arg, evidence='REAL_KERNEL', job_id=job_id)

            def fake_assess_exact(state_obj, box_obj, cfg_obj):
                def _inner():
                    # Simulated LP solver counter increments (2 per assessment)
                    budget.call('solver_calls', lambda: None)
                    budget.call('solver_calls', lambda: None)
                    return exact_contracts.ExactResult(
                        status='STABLE',
                        reason_code='STABLE',
                        state_digest=digest(asdict(state_obj)),
                        candidate_digest=digest(asdict(box_obj)),
                        candidate_id=box_obj.item_id,
                        config_digest=digest(asdict(cfg_obj)),
                        algorithm_identity=copy.deepcopy(monitor_snapshot['algorithm_identity']),
                        baseline_status='STABLE',
                        first_bad_prefix=None,
                        failed_item_id=None,
                        height_delta_mm=0.0,
                        evaluated_pose=None,
                        kernel_calls=2,
                        diagnostics={},
                        duration_s=0.001,
                    )

                return budget.call('assessment_entries', _inner)

            token = meter._ACTIVE.set(budget)
            orig = exact_adapter.assess_candidate
            exact_adapter.assess_candidate = fake_assess_exact
            try:
                yield budget
            finally:
                exact_adapter.assess_candidate = orig
                meter._ACTIVE.reset(token)

        run_out = self.root / 'full_4_plus_6_out'
        with (
            patch.object(order, 'validate_monitor_snapshot'),
            patch('semantic_pallet_planner.jev_select.geometry_order_meter.metered_run', side_effect=offline_metered_substitute),
            patch.object(order, 'run_order_job', side_effect=spy_run_order_job),
        ):
            d.main([
                '--runtime',
                str(runtime),
                '--review',
                str(review_path),
                '--launch',
                str(launch_path),
                '--output',
                str(run_out),
                '--authorization-reference',
                str(auth_ref_file),
            ])

        # 1. Exact 4 + 6 = 10 run_order_job invocations
        self.assertEqual(len(entry_calls), 10)
        self.assertEqual(
            [(c['job_id'], c['phase'], c['has_credential']) for c in entry_calls[:4]],
            [('J00', 'FRESH', False), ('J01', 'FRESH', False), ('J02', 'FRESH', False), ('J03', 'FRESH', False)],
        )
        self.assertEqual(
            [(c['job_id'], c['phase'], c['has_credential']) for c in entry_calls[4:]],
            [(j, ph, True) for j in ('J00', 'J01') for ph in d.PHASES],
        )

        # 2. Build completion receipt over the retained primary and recovery artifacts and run validate_completion
        def file_ref(path):
            p_obj = Path(path)
            return {'path': str(p_obj), 'sha256': p.sha(p_obj.read_bytes())}

        records_refs = [file_ref(run_out / 'primary' / 'jobs' / f'J{i:02}' / 'record.json') for i in range(4)]
        recovery_rows = []
        for jid in ('J00', 'J01'):
            for phase in d.PHASES:
                saved_dir = run_out / 'saved' / jid / phase / 'jobs' / jid
                rec_dir = run_out / 'recovery' / jid / phase / 'jobs' / jid
                recovery_rows.append({
                    'job_id': jid,
                    'phase': phase,
                    'before': file_ref(saved_dir / 'checkpoint.json'),
                    'after': file_ref(rec_dir / 'record.json'),
                    'accounting': file_ref(rec_dir / 'accounting.json'),
                })
        counter_log_ref = file_ref(plan['call_ledger_path'])
        coverage = completion.required_coverage(plan)
        comp_review_doc = {
            **identity_fields(plan),
            'version': wire(plan, 'geometry_kernel_completion_review_v1'),
            'scope': p.ACCEPTANCE,
            'status': 'APPROVED',
            'acceptance_plan_digest': digest(plan),
            'records_digest': digest(records_refs),
            'recovery_digest': digest(recovery_rows),
            'counter_log': counter_log_ref,
            'coverage_digest': digest(coverage),
        }
        comp_review_path = self.root / 'completion_review.json'
        d.write(comp_review_path, comp_review_doc)
        comp_receipt = {
            'records': records_refs,
            'recovery': recovery_rows,
            'counter_log': counter_log_ref,
            'review': file_ref(comp_review_path),
        }
        log_doc = d.read(plan['call_ledger_path'])

        def validate_rec(record):
            cp = record['checkpoint']
            cfg = record['config']
            raw_ref = record['raw_task']
            p.read_reference(raw_ref)
            adapted_t = p.adapt_task(Path(raw_ref['path']).read_bytes(), origin='SYNTHETIC_FIXED', expected_sha256=raw_ref['sha256'])
            with patch.object(order, 'validate_monitor_snapshot'):
                store = order.OrderStore(
                    record['durable_root'],
                    plan=plan,
                    job_id=cp['job_id'],
                    adapted=adapted_t,
                    monitor_snapshot=snap,
                    admission=d.read(launch_path),
                )
                ge.validate_saved_checkpoint(cp, adapted_t['runtime'], cfg, cp['job_id'], cp['method'], store)

        # Must pass validate_completion (including parent-evidence trace on all 6 recovery snapshots)
        completion.validate_completion(comp_receipt, plan, log_doc, validate_rec)

        # Now mutate J00's retained parent accounting.json after completion -> validate_completion MUST reject!
        j00_parent_acc = run_out / 'primary' / 'jobs' / 'J00' / 'accounting.json'
        orig_j00_acc = j00_parent_acc.read_bytes()
        d.write(j00_parent_acc, {**d.read(j00_parent_acc), 'invocations': []})
        with self.assertRaises(JevSelectError) as ctx_comp_drift:
            completion.validate_completion(comp_receipt, plan, log_doc, validate_rec)
        self.assertEqual(ctx_comp_drift.exception.code, 'geometry_receipt_bytes_drift')
        j00_parent_acc.write_bytes(orig_j00_acc)


if __name__ == '__main__':
    unittest.main(verbosity=2)
