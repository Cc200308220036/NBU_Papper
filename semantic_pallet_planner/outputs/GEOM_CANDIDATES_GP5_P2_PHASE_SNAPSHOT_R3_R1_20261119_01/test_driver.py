"""OFFLINE TEST DOUBLE and pure contract tests for GP5_P2_R3_FREEZE_BINDING_AND_COMPLETION_COMPATIBILITY_CORRECTION_ONLY (R3_R1).

Separates:
- Pure contract & accounting validation:
  1. GP5-P2-R3-MONITOR-BINDING-01: dynamic monitor snapshot binding from --runtime directory (snapshot digest different
     from historical fixed digest reaches 4-config preflight; any drift in raw file reference, startup request,
     independent launch record, or actual monitor identity aborts with 0 dispatches).
  2. GP5-P2-R3-LEGACY-COMPLETION-01: explicit protocol/credential-mode discrimination between ordinary legacy recovery
     records (with durable_root) and phase-snapshot recovery records (requiring phase_snapshot_credential.json and
     retained parent final record + final accounting verification).
  3. Retained GP5-P2-R2-PARENT-EVIDENCE-01, GP5-P2-R2-RUNTIME-INPUT-01, GP5-P2-DRIVER-AUTH-01,
     GP5-P2-DRIVER-LEDGER-01, GP5-P2-R1-PORTABILITY-01, and 4-config preflight / first-failure stop barriers.
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
import subprocess
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
from test_geometry_external_review_identity_r1 import ReviewIdentity

HOST_PREFLIGHT = d.read(
    Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_HOST_PREFLIGHT_20261119_01/host_preflight.json')
)
ARCHIVED_ORDER_ENV = HOST_PREFLIGHT['actual_order_environment']
HISTORICAL_MONITOR_DIGEST = HOST_PREFLIGHT['monitor_digest']


class PhaseSnapshotParentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='gp5_p2_r3_r1_')
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

    def make_runtime_and_records(self, subdir='runtime', *, monitor_mutate=None):
        """Build an isolated temporary new-freeze runtime directory aligned with live source_identity."""
        runtime = self.root / subdir
        runtime.mkdir(parents=True, exist_ok=True)
        snap = d.read(d.HISTORICAL_RUNTIME / 'monitor_snapshot.json')
        if monitor_mutate is not None:
            monitor_mutate(snap)
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

    # --- 1. GP5-P2-R3-MONITOR-BINDING-01 pure contract tests ---
    def test_r3_monitor_binding_01_new_digest_reaches_four_config_preflight_and_any_drift_has_zero_dispatches(self):
        """Regression for GP5-P2-R3-MONITOR-BINDING-01:
        1. No EXPECTED_MONITOR_DIGEST historical constant exists in driver.
        2. A temporary new-freeze snapshot whose digest differs from the historical monitor digest,
           when bound consistently across monitor_snapshot.json, startup_review_request.json,
           and launch.json, passes admission and enters the 4-job config preflight (4 calls to load_order_config).
        3. Any drift in raw file reference, startup request, independent launch record, or actual monitor identity
           is rejected before config preflight with 0 dispatches.
        """
        self.assertFalse(hasattr(d, 'EXPECTED_MONITOR_DIGEST'))

        runtime, plan, snap, _, auth_ref, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records(
            'new_monitor_rt',
            monitor_mutate=lambda s: s['execution_environment'].update(
                platform=s['execution_environment']['platform'] + ' NEW_FREEZE_FIXTURE'
            ),
        )
        new_digest = digest(snap)
        self.assertNotEqual(new_digest, HISTORICAL_MONITOR_DIGEST)

        # (A) Exact QA probe scenario: changed monitor digest matched in request, raw file, and launch
        # MUST pass driver monitor binding, call validate_admission, and reach all 4 load_order_config preflights!
        with (
            patch.object(
                order,
                'validate_monitor_snapshot',
                side_effect=lambda s: self.assertEqual(digest(s), new_digest),
            ) as val_mon,
            patch.object(p, 'validate_admission', wraps=p.validate_admission) as val_adm,
            patch.object(order, 'load_order_config', wraps=order.load_order_config) as load_cfg,
            self.forbid_dispatch() as run,
        ):
            _, prep_snap, _, _, configs, _ = d.prepare(
                runtime, review_path, launch_path, authorization_reference=auth_ref
            )
        self.assertEqual(digest(prep_snap), new_digest)
        self.assertEqual(val_adm.call_count, 1)
        self.assertEqual(load_cfg.call_count, 4)
        self.assertEqual(len(configs), 4)
        self.assertTrue(all(c['runtime_identity']['monitor_identity'] == new_digest for c in configs))
        self.assertEqual(val_mon.call_count, 4)
        run.assert_not_called()

        # (B) Drift cases: any reference or identity drift MUST stop before 4-config preflight with 0 dispatches
        def clone_case(name):
            rt_copy = self.root / f'drift_{name}'
            shutil.copytree(runtime, rt_copy)
            req_doc = d.read(rt_copy / 'startup_review_request.json')
            req_doc['plan_reference']['path'] = str(rt_copy / 'acceptance_plan_FROZEN.json')
            req_doc['monitor_reference']['path'] = str(rt_copy / 'monitor_snapshot.json')
            req_doc['shared_ledger_path'] = str(rt_copy / 'shared_call_ledger.json')
            p_doc = d.read(rt_copy / 'acceptance_plan_FROZEN.json')
            p_doc['call_ledger_path'] = str(rt_copy / 'shared_call_ledger.json')
            d.write(rt_copy / 'acceptance_plan_FROZEN.json', p_doc)
            req_doc['plan_digest'] = digest(p_doc)
            req_doc['plan_reference']['sha256'] = p.sha((rt_copy / 'acceptance_plan_FROZEN.json').read_bytes())
            l_doc = d.read(launch_path)
            l_doc['plan_digest'] = digest(p_doc)
            r_doc = d.read(review_path)
            r_doc['plan_digest'] = digest(p_doc)
            a_doc = d.read(rt_copy / 'user_authorization.json')
            a_doc['plan_digest'] = digest(p_doc)
            (rt_copy / 'user_authorization.json').write_text(canonical(a_doc))
            a_ref = {
                'path': str(rt_copy / 'user_authorization.json'),
                'sha256': p.sha((rt_copy / 'user_authorization.json').read_bytes()),
            }
            req_doc['authorization_reference'] = copy.deepcopy(a_ref)
            d.write(rt_copy / 'startup_review_request.json', req_doc)
            r_path = self.root / f'drift_{name}_review.json'
            r_path.write_text(canonical(r_doc))
            l_doc['authorization'] = copy.deepcopy(a_ref)
            l_doc['review'] = {'path': str(r_path), 'sha256': p.sha(r_path.read_bytes())}
            l_path = self.root / f'drift_{name}_launch.json'
            l_path.write_text(canonical(l_doc))
            led_doc = d.read(rt_copy / 'shared_call_ledger.json')
            led_doc['plan_digest'] = digest(p_doc)
            d.write(rt_copy / 'shared_call_ledger.json', led_doc)
            return rt_copy, r_path, l_path, a_ref

        # Case 1: Raw file monitor_reference.sha256 drift in startup_review_request.json
        rt1, rev1, lch1, aref1 = clone_case('raw_sha')
        req1 = d.read(rt1 / 'startup_review_request.json')
        req1['monitor_reference']['sha256'] = '0' * 64
        d.write(rt1 / 'startup_review_request.json', req1)
        with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
            with self.assertRaisesRegex(AssertionError, 'STARTUP_MONITOR_REF_SHA256_DRIFT'):
                d.execute(rt1, rev1, lch1, self.root / 'out_drift_raw_sha', authorization_reference=aref1)
            cfg.assert_not_called()
            run.assert_not_called()

        # Case 2: monitor_reference.path points outside active runtime directory (e.g. historical monitor_snapshot.json)
        rt2, rev2, lch2, aref2 = clone_case('outside_ref')
        req2 = d.read(rt2 / 'startup_review_request.json')
        req2['monitor_reference'] = {
            'path': str(d.HISTORICAL_RUNTIME / 'monitor_snapshot.json'),
            'sha256': p.sha((d.HISTORICAL_RUNTIME / 'monitor_snapshot.json').read_bytes()),
        }
        d.write(rt2 / 'startup_review_request.json', req2)
        with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
            with self.assertRaisesRegex(AssertionError, 'STARTUP_MONITOR_REF_OUTSIDE_RUNTIME'):
                d.execute(rt2, rev2, lch2, self.root / 'out_drift_outside', authorization_reference=aref2)
            cfg.assert_not_called()
            run.assert_not_called()

        # Case 3: startup_review_request.monitor_digest drift
        rt3, rev3, lch3, aref3 = clone_case('req_digest')
        req3 = d.read(rt3 / 'startup_review_request.json')
        req3['monitor_digest'] = HISTORICAL_MONITOR_DIGEST
        d.write(rt3 / 'startup_review_request.json', req3)
        with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
            with self.assertRaisesRegex(AssertionError, 'STARTUP_REQUEST_DRIFT:monitor_digest'):
                d.execute(rt3, rev3, lch3, self.root / 'out_drift_req_digest', authorization_reference=aref3)
            cfg.assert_not_called()
            run.assert_not_called()

        # Case 4: launch.monitor_digest drift (e.g. launch record still bound to historical monitor digest)
        rt4, rev4, lch4, aref4 = clone_case('launch_digest')
        l_doc4 = d.read(lch4)
        l_doc4['monitor_digest'] = HISTORICAL_MONITOR_DIGEST
        lch4.write_text(canonical(l_doc4))
        with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
            with self.assertRaisesRegex(AssertionError, 'LAUNCH_MONITOR_DIGEST_DRIFT'):
                d.execute(rt4, rev4, lch4, self.root / 'out_drift_launch_digest', authorization_reference=aref4)
            cfg.assert_not_called()
            run.assert_not_called()

        # Case 5: monitor_snapshot.algorithm_identity internal source_digest drift
        rt5, rev5, lch5, aref5 = clone_case('identity_source_digest')
        s5 = d.read(rt5 / 'monitor_snapshot.json')
        s5['algorithm_identity']['source_digest'] = 'f' * 64
        d.write(rt5 / 'monitor_snapshot.json', s5)
        req5 = d.read(rt5 / 'startup_review_request.json')
        req5['monitor_digest'] = digest(s5)
        req5['monitor_reference']['sha256'] = p.sha((rt5 / 'monitor_snapshot.json').read_bytes())
        d.write(rt5 / 'startup_review_request.json', req5)
        l_doc5 = d.read(lch5)
        l_doc5['monitor_digest'] = digest(s5)
        lch5.write_text(canonical(l_doc5))
        with patch.object(order, 'load_order_config') as cfg, self.forbid_dispatch() as run:
            with self.assertRaisesRegex(AssertionError, 'MONITOR_SNAPSHOT_SOURCE_DIGEST_DRIFT'):
                d.execute(rt5, rev5, lch5, self.root / 'out_drift_id_source', authorization_reference=aref5)
            cfg.assert_not_called()
            run.assert_not_called()

        # Case 6: Production host monitor check (validate_monitor_snapshot) rejects kernel file hash mismatch during 4-config preflight -> 0 dispatches
        rt6, rev6, lch6, aref6 = clone_case('host_kernel_file_drift')
        s6 = d.read(rt6 / 'monitor_snapshot.json')
        s6['algorithm_identity']['files_sha256']['exact_adapter.py'] = 'e' * 64
        s6['algorithm_identity']['source_digest'] = digest(s6['algorithm_identity']['files_sha256'])
        d.write(rt6 / 'monitor_snapshot.json', s6)
        req6 = d.read(rt6 / 'startup_review_request.json')
        req6['monitor_digest'] = digest(s6)
        req6['monitor_reference']['sha256'] = p.sha((rt6 / 'monitor_snapshot.json').read_bytes())
        d.write(rt6 / 'startup_review_request.json', req6)
        l_doc6 = d.read(lch6)
        l_doc6['monitor_digest'] = digest(s6)
        lch6.write_text(canonical(l_doc6))
        with self.forbid_dispatch() as run:
            with self.assertRaises(JevSelectError) as ctx_host_kernel:
                d.execute(rt6, rev6, lch6, self.root / 'out_drift_host_kernel', authorization_reference=aref6)
            self.assertEqual(ctx_host_kernel.exception.code, 'geometry_order_kernel_source_drift')
            run.assert_not_called()

    # --- 2. GP5-P2-R3-LEGACY-COMPLETION-01 pure contract tests ---
    def test_r3_legacy_completion_01_legacy_with_durable_root_passes_and_phase_snapshot_missing_or_drifted_rejected(self):
        """Regression for GP5-P2-R3-LEGACY-COMPLETION-01:
        1. Legacy v16 ordinary recovery records carrying `durable_root` (single RETURNED invocation, no phase snapshot)
           pass both baseline and current `validate_completion`.
        2. Phase-snapshot recovery records (v17 native recovery with `durable_root`, or `[STARTED, RETURNED]` invocation
           accounting, or explicit `phase_credential` / `phase_snapshot_credential.json`) MUST verify the credential
           and retained parent final record + final accounting; missing credential or parent evidence drift is rejected.
        """
        helper = ReviewIdentity('test_v16_approval_and_completion_compatibility')
        helper.setUp()
        self.addCleanup(helper.doCleanups)

        # (1) Exact QA LegacyCompletionProbe scenario: v16 legacy completion fixture with durable_root on all recovery records
        plan_v16 = helper.plan(native=False)
        receipt_v16, log_v16, review_v16 = helper.completion(plan_v16)
        for row in receipt_v16['recovery']:
            rec = d.read(Path(row['after']['path']))
            rec['durable_root'] = str(Path(row['after']['path']).parent)
            row['after'] = helper.ref(rec)
        review_v16['recovery_digest'] = digest(receipt_v16['recovery'])
        receipt_v16['review'] = helper.ref(review_v16)

        # Verify against retained baseline implementation from b5de450cc51aedff536b478aee30ffe92d07e58b
        old_source = subprocess.check_output([
            'git',
            'show',
            'b5de450cc51aedff536b478aee30ffe92d07e58b:semantic_pallet_planner/src/semantic_pallet_planner/jev_select/geometry_kernel_completion.py',
        ])
        old_ns = {'__name__': 'qa_baseline_completion', '__package__': completion.__package__}
        exec(compile(old_source, '<retained completion implementation>', 'exec'), old_ns)
        old_ns['validate_completion'](receipt_v16, plan_v16, log_v16, lambda record: None)

        # Current implementation MUST also pass ordinary v16 recovery with durable_root!
        completion.validate_completion(receipt_v16, plan_v16, log_v16, lambda record: None)

        # (2) If a v16 recovery record has phase-snapshot accounting ([STARTED, RETURNED]) but lacks phase_snapshot_credential.json -> REJECTED!
        snap_v16_receipt = copy.deepcopy(receipt_v16)
        snap_v16_review = copy.deepcopy(review_v16)
        acc0 = d.read(Path(snap_v16_receipt['recovery'][0]['accounting']['path']))
        ret_inv = copy.deepcopy(acc0['invocations'][0])
        ret_inv['index'] = 1
        started_inv = {
            'index': 0,
            'resume_phase': 'FRESH',
            'status': 'STARTED',
            'delta': accounting.zero(),
            'resume_checkpoint_digest': None,
            'result_checkpoint_digest': None,
        }
        acc0['invocations'] = [started_inv, ret_inv]
        snap_v16_receipt['recovery'][0]['accounting'] = helper.ref(acc0)
        snap_v16_review['recovery_digest'] = digest(snap_v16_receipt['recovery'])
        snap_v16_receipt['review'] = helper.ref(snap_v16_review)
        with self.assertRaises(JevSelectError) as ctx_v16_missing_cred:
            completion.validate_completion(snap_v16_receipt, plan_v16, log_v16, lambda record: None)
        self.assertEqual(ctx_v16_missing_cred.exception.code, 'geometry_completion_recovery_credential_missing')

        # (3) New v17 native recovery with durable_root missing phase_snapshot_credential.json -> REJECTED!
        plan_v17 = helper.plan(native=True)
        receipt_v17, log_v17, review_v17 = helper.completion(plan_v17)
        for row in receipt_v17['recovery']:
            rec = d.read(Path(row['after']['path']))
            rec_dir = self.root / f"v17_no_cred_{row['job_id']}_{row['phase']}"
            rec_dir.mkdir(parents=True, exist_ok=True)
            rec['durable_root'] = str(rec_dir)
            row['after'] = helper.ref(rec)
        review_v17['recovery_digest'] = digest(receipt_v17['recovery'])
        receipt_v17['review'] = helper.ref(review_v17)
        with self.assertRaises(JevSelectError) as ctx_v17_missing_cred:
            completion.validate_completion(receipt_v17, plan_v17, log_v17, lambda record: None)
        self.assertEqual(ctx_v17_missing_cred.exception.code, 'geometry_completion_recovery_credential_missing')

    # --- 3. GP5-P2-R2-PARENT-EVIDENCE-01 pure contract & accounting tests ---
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

    # --- 4. GP5-P2-R2-RUNTIME-INPUT-01 CLI & explicit runtime directory tests ---
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

    # --- 5. Retained AUTH-01, LEDGER-01, capability & 4-config preflight barrier tests ---
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

    # --- 6. Metered monitor-substitute 4+6 orchestration & completion review parent-evidence verification ---
    def test_dispatch_01_full_4_plus_6_with_parent_evidence_and_completion_validation(self):
        """Run CLI main() through real run_order_job, OrderStore, geometry_order_accounting,
        validate_saved_checkpoint, and validate_completion on all 4 primary + 6 recovery runs,
        using a new-digest monitor snapshot, a monitor substitute, and simulated LP counts (real kernel/LP calls = 0).
        Also verifies that validate_completion rejects missing credential or post-run mutation of the retained parent accounting/record.
        """
        runtime, plan, snap, _, _, auth_ref_file, review_path, launch_path, _ = self.make_runtime_and_records(
            'full_4_plus_6_rt',
            monitor_mutate=lambda s: s['execution_environment'].update(
                platform=s['execution_environment']['platform'] + ' NEW_FREEZE_4P6'
            ),
        )
        self.assertNotEqual(digest(snap), HISTORICAL_MONITOR_DIGEST)
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

        # Missing phase_snapshot_credential.json on a new phase-snapshot recovery record -> validate_completion MUST reject!
        j00_sel_cred = run_out / 'recovery' / 'J00' / 'SELECTED' / 'jobs' / 'J00' / 'phase_snapshot_credential.json'
        orig_sel_cred = j00_sel_cred.read_bytes()
        j00_sel_cred.unlink()
        with self.assertRaises(JevSelectError) as ctx_missing_cred:
            completion.validate_completion(comp_receipt, plan, log_doc, validate_rec)
        self.assertEqual(ctx_missing_cred.exception.code, 'geometry_completion_recovery_credential_missing')
        j00_sel_cred.write_bytes(orig_sel_cred)

        # Mutate J00's retained parent accounting.json after completion -> validate_completion MUST reject!
        j00_parent_acc = run_out / 'primary' / 'jobs' / 'J00' / 'accounting.json'
        orig_j00_acc = j00_parent_acc.read_bytes()
        d.write(j00_parent_acc, {**d.read(j00_parent_acc), 'invocations': []})
        with self.assertRaises(JevSelectError) as ctx_comp_drift:
            completion.validate_completion(comp_receipt, plan, log_doc, validate_rec)
        self.assertEqual(ctx_comp_drift.exception.code, 'geometry_receipt_bytes_drift')
        j00_parent_acc.write_bytes(orig_j00_acc)


if __name__ == '__main__':
    unittest.main(verbosity=2)
