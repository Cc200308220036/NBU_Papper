"""OFFLINE TEST DOUBLE and pure contract tests for GP5_P2_PHASE_SNAPSHOT_ACCOUNTING_IMPLEMENTATION_ONLY.

Exercises real geometry_order_accounting phase-snapshot credential sealing/consumption,
real validate_saved_checkpoint durable validation, explicit independent authorization SHA binding,
initial zero-ledger gating, 4+6 (10 total) run_order_job invocations, and negative regressions.
All tests inject archived environment metadata so they are portable across machines.
No real kernel, LP, freeze, or model calls are executed.
"""
import copy
import json
import socket
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import driver as d
from semantic_pallet_planner.jev_select import geometry_execution as ge
from semantic_pallet_planner.jev_select import geometry_order_accounting as accounting
from semantic_pallet_planner.jev_select import geometry_order_execution as order
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.contracts import JevSelectError, canonical, digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields, wire

HOST_PREFLIGHT = d.read(
    Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_HOST_PREFLIGHT_20261119_01/host_preflight.json')
)
ARCHIVED_ORDER_ENV = HOST_PREFLIGHT['actual_order_environment']
ARCHIVED_MONITOR_ENV = HOST_PREFLIGHT['actual_monitor_environment']
LIVE_SOURCE_IDENTITY = digest(source_manifest())


class PhaseSnapshotAccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='gp5_p2_r2_')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)

        # Hard guards against any accidental real kernel, LP, freeze, or network activity.
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
        # Inject archived order environment for cross-machine portability (GP5-P2-R1-PORTABILITY-01).
        for target in (
            'semantic_pallet_planner.jev_select.geometry_runtime_contracts.environment',
            'semantic_pallet_planner.jev_select.packaging_geometry_protocol.environment',
            'semantic_pallet_planner.jev_select.geometry_order_execution.environment',
            'semantic_pallet_planner.jev_select.geometry_execution.environment',
        ):
            self.stack.enter_context(patch(target, return_value=copy.deepcopy(ARCHIVED_ORDER_ENV)))

    def make_runtime_and_records(self):
        """Build an isolated temporary runtime directory aligned with current source_identity and archived environment."""
        runtime = self.root / 'runtime'
        runtime.mkdir(parents=True, exist_ok=True)
        snap = d.read(d.R / 'monitor_snapshot.json')
        d.write(runtime / 'monitor_snapshot.json', snap)
        snap_ref = {'path': str(runtime / 'monitor_snapshot.json'), 'sha256': p.sha((runtime / 'monitor_snapshot.json').read_bytes())}

        adapted = []
        for case in ('K01', 'K02'):
            raw = (d.R / f'{case}_task.json').read_bytes()
            (runtime / f'{case}_task.json').write_bytes(raw)
            t = p.adapt_task(raw, origin='SYNTHETIC_FIXED', expected_sha256=p.sha(raw))
            adapted.append(t)

        base_plan = d.read(d.R / 'acceptance_plan_FROZEN.json')
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

        auth_ref_file = self.root / 'authorization_reference.json'
        d.write(auth_ref_file, copy.deepcopy(auth_ref))

        req = d.read(d.R / 'startup_review_request.json')
        req.update(
            plan_digest=digest(plan),
            monitor_digest=digest(snap),
            source_identity=plan['source_identity'],
            environment_digest=plan['environment_digest'],
            plan_reference=plan_ref,
            monitor_reference=snap_ref,
            authorization_reference=copy.deepcopy(auth_ref),
            shared_ledger_path=str(ledger_path),
        )
        d.write(runtime / 'startup_review_request.json', req)

        review_doc = {**common, 'version': wire(plan, 'geometry_scope_review_v1')}
        review_path = self.root / 'review.json'
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
        launch_path = self.root / 'launch.json'
        launch_path.write_text(canonical(launch_doc))
        return runtime, plan, snap, auth_path, auth_ref, auth_ref_file, review_path, launch_path, adapted

    def forbid_dispatch(self):
        def _forbidden(plan_arg, jid, adapted, *, root, resume=None, phase_credential=None, **kw):
            raise AssertionError('DISPATCH_FORBIDDEN')
        return patch.object(order, 'run_order_job', side_effect=_forbidden)

    # --- 1. GP5-P2-DRIVER-AUTH-01 tests ---
    def test_auth_01_correct_binding_passes_prepare_with_dict_and_reference_file(self):
        runtime, _, _, _, auth_ref, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records()
        with patch.object(order, 'validate_monitor_snapshot'):
            d.prepare(runtime, review_path, launch_path)
            d.prepare(runtime, review_path, launch_path, authorization_reference=auth_ref)
            d.prepare(runtime, review_path, launch_path, authorization_reference=auth_ref_file)

    def test_auth_01_same_content_different_path_rejected_before_preflight(self):
        runtime, _, _, auth_path, _, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records()
        alt_auth_path = self.root / 'alternate_authorization.json'
        alt_auth_path.write_bytes(auth_path.read_bytes())
        launch_doc = d.read(launch_path)
        launch_doc['authorization'] = {
            'path': str(alt_auth_path),
            'sha256': p.sha(alt_auth_path.read_bytes()),
        }
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
        rows = d.read(self.root / 'run_alt_path' / 'driver_receipt.json')['rows']
        self.assertTrue(all(r['status'] == 'NOT_RUN' for r in rows))

    def test_auth_01_same_path_drifted_bytes_and_resigned_launch_rejected_in_all_modes(self):
        runtime, _, _, auth_path, auth_ref, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records()
        original_bytes = auth_path.read_bytes()
        # Mutate file bytes (trailing newline: same JSON value, different file SHA-256)
        auth_path.write_bytes(original_bytes + b'\n')
        self.assertEqual(d.read(auth_path), json.loads(original_bytes))
        # Synchronously update launch['authorization']['sha256']
        launch_doc = d.read(launch_path)
        launch_doc['authorization']['sha256'] = p.sha(auth_path.read_bytes())
        d.write(launch_path, launch_doc)

        # Must be rejected before load_order_config or run_order_job in default mode, dict mode, and reference-file mode
        for idx, spec in enumerate((None, auth_ref, auth_ref_file)):
            out_dir = self.root / f'run_resigned_drift_{idx}'
            with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
                with self.assertRaisesRegex(AssertionError, 'AUTHORIZATION_FILE_BYTES_DRIFT'):
                    d.execute(runtime, review_path, launch_path, out_dir, authorization_reference=spec)
                cfg.assert_not_called()
                run.assert_not_called()
            rows = d.read(out_dir / 'driver_receipt.json')['rows']
            self.assertTrue(all(r['status'] == 'NOT_RUN' for r in rows))

        # Passing a raw bare path (without an independent SHA record) to authorization_reference must also be rejected
        with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
            with self.assertRaisesRegex(AssertionError, 'AUTHORIZATION_SPECIFIED_REFERENCE_CONTRACT'):
                d.execute(
                    runtime,
                    review_path,
                    launch_path,
                    self.root / 'run_bare_path',
                    authorization_reference=auth_path,
                )
            cfg.assert_not_called()
            run.assert_not_called()

    # --- 2. GP5-P2-DRIVER-LEDGER-01 tests ---
    def test_ledger_01_nonempty_prior_done_started_error_rejected_and_preserved(self):
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
            rows = d.read(self.root / f'run_nonempty_{idx}' / 'driver_receipt.json')['rows']
            self.assertTrue(all(r['status'] == 'NOT_RUN' for r in rows))

    def test_unknown_overlimit_and_counter_drift(self):
        _, plan, _, _, _, _, _, _, _ = self.make_runtime_and_records()
        path = Path(plan['call_ledger_path'])
        base = d.read(path)
        for change in ('unknown', 'overlimit', 'drift'):
            v = copy.deepcopy(base)
            if change == 'unknown':
                v['calls'] = [{'state': 'STARTED', 'kind': 'solver_calls', 'index': 0, 'job_id': 'J00'}]
                v['counts']['solver_calls'] = 1
            elif change == 'overlimit':
                v['counts']['assessment_entries'] = 9
            else:
                v['plan_digest'] = 'bad'
            d.write(path, v)
            with self.assertRaises(AssertionError):
                d.check_counts(plan)

    # --- 3. GP5-P2-DRIVER-DISPATCH-01 & Real Accounting / Recovery Validation tests ---
    def test_dispatch_01_full_4_plus_6_with_real_accounting_and_saved_checkpoint_validation(self):
        """Run driver.execute through real run_order_job, real OrderStore, real geometry_order_accounting,
        real candidate generation/publication/selection, and real validate_saved_checkpoint on all 6 phase snapshots,
        using only a metered test-double inside metered_run so real exact_adapter/linprog are never called.
        """
        runtime, plan, snap, _, _, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records()
        from semantic_pallet_planner.jev_select import geometry_order_meter as meter
        from semantic_pallet_planner.jev_select.stability import exact_contracts

        entry_calls = []
        real_run_order_job = order.run_order_job

        def spy_run_order_job(p_arg, jid, adapted, *, monitor_snapshot, admission, root, kernel_receipt=None, resume=None, phase_credential=None, on_checkpoint=None, hook=None):
            entry_calls.append({
                'job_id': jid,
                'phase': resume['phase'] if resume else 'FRESH',
                'has_credential': phase_credential is not None,
                'root': str(root),
            })
            return real_run_order_job(
                p_arg, jid, adapted, monitor_snapshot=monitor_snapshot, admission=admission, root=root, kernel_receipt=kernel_receipt, resume=resume, phase_credential=phase_credential, on_checkpoint=on_checkpoint, hook=hook
            )

        from contextlib import contextmanager

        @contextmanager
        def offline_metered_run(p_arg, *, job_id, monitor_snapshot, admission, kernel_receipt=None):
            budget = meter.CallBudget(p_arg['call_ledger_path'], p_arg, evidence='REAL_KERNEL', job_id=job_id)

            def fake_assess(state_obj, box_obj, cfg_obj):
                def _inner():
                    # Record 2 synthetic solver calls in the shared budget to test LP metering without calling scipy linprog
                    budget.call('solver_calls', lambda: None)
                    budget.call('solver_calls', lambda: None)
                    return exact_contracts.ExactResult(
                        status='STABLE',
                        reason_code='STABLE',
                        state_digest=digest(
                            {
                                'container': state_obj.container.__dict__,
                                'placed': [b.__dict__ for b in state_obj.placed],
                            }
                        ),
                        candidate_digest=digest(box_obj.__dict__),
                        candidate_id=box_obj.item_id,
                        config_digest=digest(cfg_obj.__dict__),
                        algorithm_identity=copy.deepcopy(monitor_snapshot['algorithm_identity']),
                        baseline_status='STABLE',
                        first_bad_prefix=None,
                        failed_item_id=None,
                        height_delta_mm=0.0,
                        evaluated_pose={
                            'x_mm': box_obj.x_mm,
                            'y_mm': box_obj.y_mm,
                            'z_base_mm': box_obj.z_base_mm,
                            'l_mm': box_obj.l_mm,
                            'w_mm': box_obj.w_mm,
                            'h_mm': box_obj.h_mm,
                        },
                        kernel_calls=2,
                        diagnostics={'offline_metered_substitute': True},
                        duration_s=0.001,
                    )

                return budget.call('assessment_entries', _inner)

            from semantic_pallet_planner.jev_select.stability import exact_adapter
            from dataclasses import asdict

            def fake_assess_exact(state_obj, box_obj, cfg_obj):
                def _inner():
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
            patch('semantic_pallet_planner.jev_select.geometry_order_meter.metered_run', side_effect=offline_metered_run),
            patch.object(order, 'run_order_job', side_effect=spy_run_order_job),
        ):
            d.execute(
                runtime,
                review_path,
                launch_path,
                run_out,
                authorization_reference=auth_ref_file,
            )

        # 1. Verify exact 4 + 6 = 10 run_order_job invocations
        self.assertEqual(len(entry_calls), 10)
        self.assertEqual(
            [(c['job_id'], c['phase'], c['has_credential']) for c in entry_calls[:4]],
            [('J00', 'FRESH', False), ('J01', 'FRESH', False), ('J02', 'FRESH', False), ('J03', 'FRESH', False)],
        )
        self.assertEqual(
            [(c['job_id'], c['phase'], c['has_credential']) for c in entry_calls[4:]],
            [(j, ph, True) for j in ('J00', 'J01') for ph in d.PHASES],
        )

        # 2. Verify primary accounting stayed clean (single invocation with status == 'RETURNED')
        for jid in ('J00', 'J01', 'J02', 'J03'):
            p_acc = d.read(run_out / 'primary' / 'jobs' / jid / 'accounting.json')
            self.assertEqual(len(p_acc['invocations']), 1)
            self.assertEqual(p_acc['invocations'][0]['status'], 'RETURNED')
            self.assertEqual(p_acc['invocations'][0]['resume_phase'], 'FRESH')

        # 3. Verify all 6 saved snapshots kept in-run status == 'STARTED' (never rewritten to RETURNED)
        #    and all 6 recovery runs appended a 2nd invocation with status == 'RETURNED' and exact deltas,
        #    and both before/after checkpoints pass real validate_saved_checkpoint!
        for jid in ('J00', 'J01'):
            for phase in d.PHASES:
                saved_job = run_out / 'saved' / jid / phase / 'jobs' / jid
                saved_acc = d.read(saved_job / 'accounting.json')
                self.assertEqual(len(saved_acc['invocations']), 1)
                self.assertEqual(saved_acc['invocations'][0]['status'], 'STARTED')
                self.assertIsNone(saved_acc['invocations'][0]['result_checkpoint_digest'])

                cred = d.read(saved_job / 'phase_snapshot_credential.json')
                self.assertEqual(cred['status'], 'SEALED_FOR_RECOVERY')
                self.assertEqual(cred['phase'], phase)
                self.assertEqual(cred['parent_invocation']['in_run_status'], 'STARTED')
                self.assertEqual(cred['parent_invocation']['final_status'], 'RETURNED')

                rec_job = run_out / 'recovery' / jid / phase / 'jobs' / jid
                rec_acc = d.read(rec_job / 'accounting.json')
                self.assertEqual(len(rec_acc['invocations']), 2)
                self.assertEqual(rec_acc['invocations'][0]['status'], 'STARTED')
                self.assertEqual(rec_acc['invocations'][1]['status'], 'RETURNED')
                self.assertEqual(rec_acc['invocations'][1]['resume_phase'], phase)
                expected_delta = {
                    'selector_calls': 0,
                    'singleton_executions': 0,
                    'monitor_entries': int(phase == 'SELECTED'),
                    'monitor_reuses': int(phase == 'MONITORED'),
                    'commit_attempts': int(phase != 'COMMITTED'),
                    'commit_successes': int(phase != 'COMMITTED'),
                }
                self.assertEqual(rec_acc['invocations'][1]['delta'], expected_delta)

                # Real validate_saved_checkpoint on both saved snapshot and recovered terminal record
                cfg = d.read(rec_job / 'config.json')
                raw_bytes = (runtime / 'K01_task.json').read_bytes()
                adapted_k01 = p.adapt_task(raw_bytes, origin='SYNTHETIC_FIXED', expected_sha256=p.sha(raw_bytes))
                with patch.object(order, 'validate_monitor_snapshot'):
                    store_saved = order.OrderStore(
                        saved_job,
                        plan=plan,
                        job_id=jid,
                        adapted=adapted_k01,
                        monitor_snapshot=snap,
                        admission=d.read(launch_path),
                    )
                    ge.validate_saved_checkpoint(
                        d.read(saved_job / 'checkpoint.json'),
                        adapted_k01['runtime'],
                        cfg,
                        jid,
                        cfg['selector'],
                        store_saved,
                    )
                    store_rec = order.OrderStore(
                        rec_job,
                        plan=plan,
                        job_id=jid,
                        adapted=adapted_k01,
                        monitor_snapshot=snap,
                        admission=d.read(launch_path),
                    )
                    ge.validate_saved_checkpoint(
                        d.read(rec_job / 'checkpoint.json'),
                        adapted_k01['runtime'],
                        cfg,
                        jid,
                        cfg['selector'],
                        store_rec,
                    )

        receipt = d.read(run_out / 'driver_receipt.json')
        self.assertEqual(receipt['status'], 'COMPLETE')
        self.assertEqual(receipt['primary_dispatches'], 4)
        self.assertEqual(receipt['recovery_dispatches'], 6)
        self.assertEqual(
            receipt['final_counts'],
            {'assessment_entries': 8, 'solver_calls': 16, 'test_double_assessments': 0},
        )

    def test_phase_snapshot_credential_rejections_and_legacy_started_refusal(self):
        """Verify ordinary STARTED refusal remains intact, and tampered/failed/wrong-identity credentials fail."""
        runtime, plan, snap, _, _, _, _, launch_path, adapted = self.make_runtime_and_records()
        launch_doc = d.read(launch_path)
        with patch.object(order, 'validate_monitor_snapshot'):
            cfg_j00 = order.load_order_config(plan, 'J00', monitor_snapshot=snap, admission=launch_doc)
            cfg_j01 = order.load_order_config(plan, 'J01', monitor_snapshot=snap, admission=launch_doc)

        parent_root = self.root / 'parent_j00' / 'jobs' / 'J00'
        snap_root = self.root / 'snap_j00' / 'jobs' / 'J00'
        parent_root.mkdir(parents=True, exist_ok=True)

        raw_bytes = adapted[0]['raw']
        raw_sha = p.sha(raw_bytes)
        g_bytes = b'{"test_geometry_blob":true}'
        g_sha = p.sha(g_bytes)
        (parent_root / 'blobs').mkdir(parents=True, exist_ok=True)
        (parent_root / 'blobs' / raw_sha).write_bytes(raw_bytes)
        (parent_root / 'blobs' / g_sha).write_bytes(g_bytes)
        d.write(parent_root / 'config.json', cfg_j00)
        d.write(parent_root / 'task_identity.json', cfg_j00['order_task_identity'])

        cp_selected = {
            'phase': 'SELECTED',
            'job_id': 'J00',
            'pending_event': {'geometry_ref': {'version': 'geometry_blob_ref_v1', 'sha256': g_sha}},
        }
        cp_terminal = {'phase': 'TERMINATED', 'reason': 'ALL_ITEMS_PLACED', 'job_id': 'J00'}

        with accounting.invocation(parent_root / 'accounting.json', cfg_j00, 'J00', resume=None):
            accounting.tick(cfg_j00, 'selector_calls')
            d.write(parent_root / 'checkpoint.json', cp_selected)
            import shutil

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

        # 4. Seal valid credential after parent normal completion
        cred = accounting.seal_phase_snapshot_credential(
            parent_root,
            snap_root,
            cfg_j00,
            'J00',
            'SELECTED',
            cp_selected,
            parent_result={'summary': {'completed': True}, 'checkpoint': cp_terminal},
        )

        # 5. Tampered credential digest -> rejected
        bad_digest_cred = copy.deepcopy(cred)
        bad_digest_cred['credential_digest'] = '0' * 64
        with self.assertRaises(JevSelectError) as ctx_digest:
            with accounting.invocation(
                snap_root / 'accounting.json', cfg_j00, 'J00', resume=cp_selected, phase_credential=bad_digest_cred
            ):
                pass
        self.assertEqual(ctx_digest.exception.code, 'geometry_phase_snapshot_credential_digest_drift')

        # 6. Wrong config / wrong job_id / wrong phase -> rejected
        with self.assertRaises(JevSelectError) as ctx_wrong_cfg:
            with accounting.invocation(
                snap_root / 'accounting.json', cfg_j01, 'J01', resume=cp_selected, phase_credential=cred
            ):
                pass
        self.assertEqual(ctx_wrong_cfg.exception.code, 'geometry_accounting_drift')

        wrong_phase_cp = copy.deepcopy(cp_selected)
        wrong_phase_cp['phase'] = 'MONITORED'
        with self.assertRaises(JevSelectError) as ctx_wrong_phase:
            accounting.validate_phase_snapshot_credential(cred, snap_root, cfg_j00, 'J00', wrong_phase_cp)
        self.assertEqual(ctx_wrong_phase.exception.code, 'geometry_phase_snapshot_credential_binding_drift')

        # 7. Tampered prefix accounting on disk -> rejected
        tampered_snap = self.root / 'tampered_snap'
        shutil.copytree(snap_root, tampered_snap)
        t_acc = d.read(tampered_snap / 'accounting.json')
        t_acc['invocations'][0]['delta']['selector_calls'] = 2
        t_acc['cumulative']['selector_calls'] = 2
        d.write(tampered_snap / 'accounting.json', t_acc)
        with self.assertRaises(JevSelectError) as ctx_tampered_acc:
            with accounting.invocation(
                tampered_snap / 'accounting.json', cfg_j00, 'J00', resume=cp_selected, phase_credential=cred
            ):
                pass
        self.assertEqual(ctx_tampered_acc.exception.code, 'geometry_phase_snapshot_accounting_drift')

        # 8. Valid credential allows clean recovery invocation and appends 2nd RETURNED entry
        with accounting.invocation(
            snap_root / 'accounting.json', cfg_j00, 'J00', resume=cp_selected, phase_credential=cred
        ):
            accounting.tick(cfg_j00, 'monitor_entries')
            accounting.tick(cfg_j00, 'commit_attempts')
            accounting.tick(cfg_j00, 'commit_successes')
            accounting.completed(cfg_j00, cp_terminal)
        after_acc = d.read(snap_root / 'accounting.json')
        self.assertEqual(len(after_acc['invocations']), 2)
        self.assertEqual(after_acc['invocations'][0]['status'], 'STARTED')
        self.assertEqual(after_acc['invocations'][1]['status'], 'RETURNED')

    def test_v16_legacy_phase_snapshot_credential_compatibility(self):
        """Verify v16 wire routing produces geometry_phase_snapshot_credential_v1 and preserves v16 contracts."""
        adapted = []
        for case in ('K01', 'K02'):
            raw = (d.R / f'{case}_task.json').read_bytes()
            adapted.append(p.adapt_task(raw, origin='SYNTHETIC_FIXED', expected_sha256=p.sha(raw)))
        plan16 = p.prepare_order_plan(adapted, data_identity=digest('V16_TEST'), scope=p.DEVELOPMENT, native=False)
        self.assertEqual(wire(plan16, 'geometry_phase_snapshot_credential_v1'), 'geometry_phase_snapshot_credential_v1')
        adm16 = {'version': 'geometry_development_binding_v1', 'scope': p.DEVELOPMENT, 'evidence': 'TEST_DOUBLE', 'plan_digest': digest(plan16)}
        snap = d.read(d.R / 'monitor_snapshot.json')
        with patch.object(order, 'validate_monitor_snapshot'):
            cfg16 = order.load_order_config(plan16, 'J00', monitor_snapshot=snap, admission=adm16)
        self.assertEqual(cfg16['version'], 'jev_packaging_geometry_order_v16')

        p_root = self.root / 'v16_parent'
        s_root = self.root / 'v16_snap'
        (p_root / 'blobs').mkdir(parents=True, exist_ok=True)
        raw_sha = adapted[0]['identity']['raw_sha256']
        (p_root / 'blobs' / raw_sha).write_bytes(adapted[0]['raw'])
        g_bytes = b'{"v16_blob":1}'
        g_sha = p.sha(g_bytes)
        (p_root / 'blobs' / g_sha).write_bytes(g_bytes)
        d.write(p_root / 'config.json', cfg16)
        d.write(p_root / 'task_identity.json', cfg16['order_task_identity'])
        cp_sel = {'phase': 'SELECTED', 'job_id': 'J00', 'pending_event': {'geometry_ref': {'version': 'geometry_blob_ref_v1', 'sha256': g_sha}}}
        cp_term = {'phase': 'TERMINATED', 'reason': 'ALL_ITEMS_PLACED', 'job_id': 'J00'}
        with accounting.invocation(p_root / 'accounting.json', cfg16, 'J00', resume=None):
            accounting.tick(cfg16, 'selector_calls')
            d.write(p_root / 'checkpoint.json', cp_sel)
            import shutil

            shutil.copytree(p_root, s_root)
            accounting.completed(cfg16, cp_term)
        cred16 = accounting.seal_phase_snapshot_credential(
            p_root, s_root, cfg16, 'J00', 'SELECTED', cp_sel, parent_result={'summary': {'completed': True}, 'checkpoint': cp_term}
        )
        self.assertEqual(cred16['version'], 'geometry_phase_snapshot_credential_v1')
        self.assertNotIn('runtime_version', cred16)
        accounting.validate_phase_snapshot_credential(cred16, s_root, cfg16, 'J00', cp_sel)

    # --- 4. Capability gate, preflight barrier, and first-failure stop tests ---
    def test_missing_phase_snapshot_capability_stops_before_first_dispatch(self):
        runtime, _, _, _, _, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records()
        with (
            patch.object(accounting, 'seal_phase_snapshot_credential', None),
            patch.object(order, 'load_order_config') as cfg,
            patch.object(order, 'run_order_job') as run,
        ):
            with self.assertRaisesRegex(AssertionError, 'PHASE_SNAPSHOT_SEALER_MISSING'):
                d.execute(
                    runtime,
                    review_path,
                    launch_path,
                    self.root / 'run_no_cap',
                    authorization_reference=auth_ref_file,
                )
            cfg.assert_not_called()
            run.assert_not_called()
        rows = d.read(self.root / 'run_no_cap' / 'driver_receipt.json')['rows']
        self.assertTrue(all(r['status'] == 'NOT_RUN' for r in rows))

    def test_missing_records_and_identity_drift_stop_before_dispatch(self):
        runtime, _, _, _, _, _, _, _, _ = self.make_runtime_and_records()
        with self.forbid_dispatch() as run:
            with self.assertRaises(FileNotFoundError):
                d.execute(runtime, self.root / 'missing_review', self.root / 'missing_launch', self.root / 'run_missing')
        run.assert_not_called()
        self.assertTrue(all(r['status'] == 'NOT_RUN' for r in d.read(self.root / 'run_missing/driver_receipt.json')['rows']))

        req = d.read(runtime / 'startup_review_request.json')
        req['plan_digest'] = '0' * 64
        d.write(runtime / 'startup_review_request.json', req)
        with self.forbid_dispatch() as run:
            with self.assertRaisesRegex(AssertionError, 'STARTUP_REQUEST_DRIFT:plan_digest'):
                d.execute(runtime, 'unused', 'unused', self.root / 'run_drift')
        run.assert_not_called()

    def test_joint_preflight_failure_prevents_dispatch(self):
        runtime, _, _, _, _, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records()
        with (
            patch.object(order, 'load_order_config', side_effect=[{}, {}, RuntimeError('J02_PREFLIGHT_FAIL')]) as cfg,
            self.forbid_dispatch() as run,
        ):
            with self.assertRaisesRegex(RuntimeError, 'J02_PREFLIGHT_FAIL'):
                d.execute(
                    runtime,
                    review_path,
                    launch_path,
                    self.root / 'run_j02_fail',
                    authorization_reference=auth_ref_file,
                )
        self.assertEqual(cfg.call_count, 3)
        run.assert_not_called()
        rows = d.read(self.root / 'run_j02_fail/driver_receipt.json')['rows']
        self.assertTrue(all(r['status'] == 'NOT_RUN' for r in rows))

    def test_first_failure_keeps_remaining_not_run(self):
        runtime, _, _, _, _, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records()
        def fail_first(plan_arg, jid, adapted, *, root, resume=None, phase_credential=None, **kw):
            raise RuntimeError('OFFLINE_PRIMARY_FAILURE')
        with (
            patch.object(order, 'validate_monitor_snapshot'),
            patch.object(order, 'run_order_job', side_effect=fail_first) as run,
        ):
            with self.assertRaisesRegex(RuntimeError, 'OFFLINE_PRIMARY_FAILURE'):
                d.execute(
                    runtime,
                    review_path,
                    launch_path,
                    self.root / 'run_first_fail',
                    authorization_reference=auth_ref_file,
                )
        self.assertEqual(run.call_count, 1)
        rows = d.read(self.root / 'run_first_fail/driver_receipt.json')['rows']
        self.assertEqual(rows[0]['status'], 'FAILED')
        self.assertEqual(sum(r['status'] == 'NOT_RUN' for r in rows), 9)


if __name__ == '__main__':
    unittest.main(verbosity=2)
