"""OFFLINE TEST DOUBLE evidence only for GP5_P2_OFFLINE_DRIVER_CORRECTION_ONLY.

No real runner, kernel, LP, freeze, or model calls.
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
import probe_dispatch_01 as probe
from semantic_pallet_planner.jev_select.contracts import JevSelectError, canonical
from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields, wire


class DriverCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = d.read(d.R / 'acceptance_plan_FROZEN.json')
        self.snap = d.read(d.R / 'monitor_snapshot.json')
        self.req = d.read(d.R / 'startup_review_request.json')
        self.jobs = self.plan['jobs']
        self.calls = []
        self.addCleanup(patch.stopall)
        patch.object(d, 'check_success').start()
        patch.object(socket.socket, 'connect', side_effect=AssertionError('NETWORK_FORBIDDEN')).start()

    def write_zero_ledger(self, path=None, plan=None):
        target_plan = self.plan if plan is None else plan
        if path is not None:
            target_plan['call_ledger_path'] = str(path)
        ledger_path = Path(target_plan['call_ledger_path'])
        value = {
            'version': 'geometry_call_ledger_v1',
            'plan_digest': d.digest(target_plan),
            'evidence': 'REAL_KERNEL',
            'limits': {'assessment_entries': 8, 'solver_calls': 128},
            'counts': {'assessment_entries': 0, 'solver_calls': 0, 'test_double_assessments': 0},
            'calls': [],
        }
        d.write(ledger_path, value)
        return ledger_path

    def make_runtime_and_records(self):
        runtime = self.root / 'runtime'
        runtime.mkdir(parents=True, exist_ok=True)
        for name in (
            'acceptance_plan_FROZEN.json',
            'monitor_snapshot.json',
            'startup_review_request.json',
            'user_authorization.json',
            'K01_task.json',
            'K02_task.json',
        ):
            (runtime / name).write_bytes((d.R / name).read_bytes())
        common = {
            **identity_fields(self.plan),
            'scope': self.plan['scope'],
            'plan_digest': d.digest(self.plan),
            'status': 'APPROVED',
        }
        auth_path = runtime / 'user_authorization.json'
        auth_ref = {'path': str(auth_path), 'sha256': d.p.sha(auth_path.read_bytes())}
        req = d.read(runtime / 'startup_review_request.json')
        req['authorization_reference'] = copy.deepcopy(auth_ref)
        d.write(runtime / 'startup_review_request.json', req)

        review_doc = {**common, 'version': wire(self.plan, 'geometry_scope_review_v1')}
        review_path = self.root / 'review.json'
        review_path.write_text(canonical(review_doc))
        review_ref = {'path': str(review_path), 'sha256': d.p.sha(review_path.read_bytes())}

        launch_doc = {
            **common,
            'version': wire(self.plan, 'geometry_kernel_launch_v1'),
            'monitor_digest': d.digest(self.snap),
            'source_identity': self.plan['source_identity'],
            'environment_digest': self.plan['environment_digest'],
            'authorization': copy.deepcopy(auth_ref),
            'review': copy.deepcopy(review_ref),
        }
        launch_path = self.root / 'launch.json'
        launch_path.write_text(canonical(launch_doc))
        return runtime, auth_path, review_path, launch_path, common

    # --- 1. GP5-P2-DRIVER-AUTH-01 tests ---
    def test_auth_01_correct_binding_passes_prepare(self):
        runtime, auth_path, review_path, launch_path, _ = self.make_runtime_and_records()
        with ExitStack() as mocks:
            mocks.enter_context(patch.object(d.p, 'validate_order_plan'))
            cfg = mocks.enter_context(patch.object(d.order, 'load_order_config', return_value={}))
            run = mocks.enter_context(patch.object(d.order, 'run_order_job', side_effect=AssertionError('NO_DISPATCH')))
            d.prepare(runtime, review_path, launch_path, authorization_path=auth_path)
            self.assertEqual(cfg.call_count, 4)
            run.assert_not_called()

    def test_auth_01_same_content_different_path_rejected_before_preflight(self):
        runtime, auth_path, review_path, launch_path, _ = self.make_runtime_and_records()
        alt_auth_path = self.root / 'alternate_authorization.json'
        alt_auth_path.write_bytes(auth_path.read_bytes())
        launch_doc = d.read(launch_path)
        launch_doc['authorization'] = {
            'path': str(alt_auth_path),
            'sha256': d.p.sha(alt_auth_path.read_bytes()),
        }
        d.write(launch_path, launch_doc)
        with ExitStack() as mocks:
            mocks.enter_context(patch.object(d.p, 'validate_order_plan'))
            cfg = mocks.enter_context(patch.object(d.order, 'load_order_config', return_value={}))
            run = mocks.enter_context(patch.object(d.order, 'run_order_job'))
            with self.assertRaisesRegex(AssertionError, 'AUTHORIZATION_REFERENCE_PATH_MISMATCH'):
                d.execute(runtime, review_path, launch_path, self.root / 'run_alt_path', authorization=auth_path)
            cfg.assert_not_called()
            run.assert_not_called()
        rows = d.read(self.root / 'run_alt_path' / 'driver_receipt.json')['rows']
        self.assertTrue(all(r['status'] == 'NOT_RUN' for r in rows))

    def test_auth_01_same_path_drifted_bytes_rejected_before_preflight(self):
        runtime, auth_path, review_path, launch_path, _ = self.make_runtime_and_records()
        # Case A: file bytes mutated on disk after launch record was created (same path, drifted bytes vs launch['authorization']['sha256'])
        drifted = d.read(auth_path)
        drifted['extra_whitespace_or_change'] = 'DRIFT'
        auth_path.write_text(json.dumps(drifted))
        with ExitStack() as mocks:
            mocks.enter_context(patch.object(d.p, 'validate_order_plan'))
            cfg = mocks.enter_context(patch.object(d.order, 'load_order_config', return_value={}))
            run = mocks.enter_context(patch.object(d.order, 'run_order_job'))
            with self.assertRaisesRegex(AssertionError, 'AUTHORIZATION_REFERENCE_SHA256_MISMATCH'):
                d.execute(runtime, review_path, launch_path, self.root / 'run_drift_bytes', authorization=auth_path)
            cfg.assert_not_called()
            run.assert_not_called()
        rows = d.read(self.root / 'run_drift_bytes' / 'driver_receipt.json')['rows']
        self.assertTrue(all(r['status'] == 'NOT_RUN' for r in rows))

        # Case B: file bytes mutated AND launch['authorization']['sha256'] re-signed to match the drifted file,
        # rejected against startup_review_request.json's authorization_reference.sha256
        launch_doc = d.read(launch_path)
        launch_doc['authorization']['sha256'] = d.p.sha(auth_path.read_bytes())
        d.write(launch_path, launch_doc)
        with ExitStack() as mocks:
            mocks.enter_context(patch.object(d.p, 'validate_order_plan'))
            cfg = mocks.enter_context(patch.object(d.order, 'load_order_config', return_value={}))
            run = mocks.enter_context(patch.object(d.order, 'run_order_job'))
            with self.assertRaisesRegex(AssertionError, 'AUTHORIZATION_FILE_BYTES_DRIFT'):
                d.execute(runtime, review_path, launch_path, self.root / 'run_resigned_drift')
            cfg.assert_not_called()
            run.assert_not_called()
        rows2 = d.read(self.root / 'run_resigned_drift' / 'driver_receipt.json')['rows']
        self.assertTrue(all(r['status'] == 'NOT_RUN' for r in rows2))

    def test_ledger_01_nonempty_initial_ledger_stops_execute_before_preflight(self):
        runtime, auth_path, review_path, launch_path, _ = self.make_runtime_and_records()
        plan = d.read(runtime / 'acceptance_plan_FROZEN.json')
        nonempty_ledger = self.root / 'nonempty_initial_ledger.json'
        d.write(nonempty_ledger, {
            'version': 'geometry_call_ledger_v1',
            'plan_digest': d.digest(plan),
            'evidence': 'REAL_KERNEL',
            'limits': {'assessment_entries': 8, 'solver_calls': 128},
            'counts': {'assessment_entries': 1, 'solver_calls': 0, 'test_double_assessments': 0},
            'calls': [{'kind': 'assessment_entries', 'state': 'DONE', 'job_id': 'J00', 'index': 0}],
        })
        before_bytes = nonempty_ledger.read_bytes()
        orig_read = d.read
        def redirected_read(path):
            if Path(path) == Path(plan['call_ledger_path']):
                return orig_read(nonempty_ledger)
            return orig_read(path)
        with ExitStack() as mocks:
            mocks.enter_context(patch.object(d.p, 'validate_order_plan'))
            mocks.enter_context(patch.object(d.p, 'validate_admission'))
            mocks.enter_context(patch.object(d, 'read', side_effect=redirected_read))
            cfg = mocks.enter_context(patch.object(d.order, 'load_order_config', return_value={}))
            run = mocks.enter_context(patch.object(d.order, 'run_order_job'))
            with self.assertRaisesRegex(AssertionError, 'NONEMPTY_INITIAL_LEDGER_CALLS'):
                d.execute(runtime, review_path, launch_path, self.root / 'run_nonempty_ledger', authorization=auth_path)
            cfg.assert_not_called()
            run.assert_not_called()
        self.assertEqual(nonempty_ledger.read_bytes(), before_bytes)
        rows = d.read(self.root / 'run_nonempty_ledger' / 'driver_receipt.json')['rows']
        self.assertTrue(all(r['status'] == 'NOT_RUN' for r in rows))

    # --- 2. GP5-P2-DRIVER-LEDGER-01 tests ---
    def test_ledger_01_nonempty_prior_done_started_error_rejected_and_preserved(self):
        probe_plan = copy.deepcopy(self.plan)
        ledger_path = self.root / 'shared_ledger.json'
        probe_plan['call_ledger_path'] = str(ledger_path)

        for state in ('DONE', 'STARTED', 'ERROR'):
            prior = {
                'version': 'geometry_call_ledger_v1',
                'plan_digest': d.digest(probe_plan),
                'evidence': 'REAL_KERNEL',
                'limits': {'assessment_entries': 8, 'solver_calls': 128},
                'counts': {'assessment_entries': 1, 'solver_calls': 0, 'test_double_assessments': 0},
                'calls': [{'kind': 'assessment_entries', 'state': state, 'job_id': 'J00', 'index': 0}],
            }
            d.write(ledger_path, prior)
            before_bytes = ledger_path.read_bytes()
            with self.assertRaisesRegex(AssertionError, 'NONEMPTY_INITIAL_LEDGER_CALLS'):
                d.check_initial_zero_ledger(probe_plan)
            # Ledger must be preserved on disk, never cleared
            self.assertEqual(ledger_path.read_bytes(), before_bytes)

    def test_ledger_01_incremental_accounting_and_coverage_verification(self):
        probe_plan = copy.deepcopy(self.plan)
        ledger_path = self.write_zero_ledger(self.root / 'incremental_ledger.json', plan=probe_plan)
        probe_plan['call_ledger_path'] = str(ledger_path)
        state = d.check_initial_zero_ledger(probe_plan)

        def append_calls(jid, assessments, solvers):
            doc = d.read(ledger_path)
            for _ in range(assessments):
                doc['calls'].append({
                    'kind': 'assessment_entries',
                    'state': 'DONE',
                    'job_id': jid,
                    'index': len(doc['calls']),
                })
                doc['counts']['assessment_entries'] += 1
            for _ in range(solvers):
                doc['calls'].append({
                    'kind': 'solver_calls',
                    'state': 'DONE',
                    'job_id': jid,
                    'index': len(doc['calls']),
                })
                doc['counts']['solver_calls'] += 1
            d.write(ledger_path, doc)

        # 4 primaries: J00 (1), J01 (1), J02 (2), J03 (2) => 6 assessments
        for jid, a_cnt, s_cnt in (('J00', 1, 2), ('J01', 1, 2), ('J02', 2, 4), ('J03', 2, 4)):
            append_calls(jid, a_cnt, s_cnt)
            state, delta = d.check_counts(
                probe_plan,
                previous=state,
                job_id=jid,
                expected_assessment_delta=a_cnt,
                require_solver_delta=True,
            )
            self.assertEqual(delta, {'assessment_entries': a_cnt, 'solver_calls': s_cnt, 'test_double_assessments': 0})
        self.assertEqual(state['counts']['assessment_entries'], 6)

        # 6 recoveries: J00/J01 x SELECTED (+1), MONITORED (+0), COMMITTED (+0) => +2 assessments, total 8
        for jid in ('J00', 'J01'):
            for phase in d.PHASES:
                exp_a = int(phase == 'SELECTED')
                exp_s = 2 if exp_a else 0
                append_calls(jid, exp_a, exp_s)
                state, delta = d.check_counts(
                    probe_plan,
                    previous=state,
                    job_id=jid,
                    expected_assessment_delta=exp_a,
                    require_solver_delta=(exp_a > 0),
                )
                self.assertEqual(delta['assessment_entries'], exp_a)
                self.assertEqual(delta['solver_calls'], exp_s)

        coverage = d.required_coverage(probe_plan)
        final_counts = d.verify_final_ledger_coverage(probe_plan, coverage)
        self.assertEqual(final_counts, {'assessment_entries': 8, 'solver_calls': 16, 'test_double_assessments': 0})

    def test_unknown_overlimit_and_counter_drift(self):
        probe_plan = copy.deepcopy(self.plan)
        path = self.write_zero_ledger(self.root / 'bad_ledger.json', plan=probe_plan)
        probe_plan['call_ledger_path'] = str(path)
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
                d.check_counts(probe_plan)

    # --- 3. GP5-P2-DRIVER-DISPATCH-01 tests ---
    def test_dispatch_01_four_primary_plus_six_recovery_exact_10_entry_calls(self):
        probe_plan = copy.deepcopy(self.plan)
        ledger_path = self.write_zero_ledger(self.root / 'run_ledger.json', plan=probe_plan)
        probe_plan['call_ledger_path'] = str(ledger_path)
        initial_ledger = d.check_initial_zero_ledger(probe_plan)

        def append_ledger(jid, assessments, solvers):
            doc = d.read(ledger_path)
            for _ in range(assessments):
                doc['calls'].append({
                    'kind': 'assessment_entries',
                    'state': 'DONE',
                    'job_id': jid,
                    'index': len(doc['calls']),
                })
                doc['counts']['assessment_entries'] += 1
            for _ in range(solvers):
                doc['calls'].append({
                    'kind': 'solver_calls',
                    'state': 'DONE',
                    'job_id': jid,
                    'index': len(doc['calls']),
                })
                doc['counts']['solver_calls'] += 1
            d.write(ledger_path, doc)

        def fake_run_order_job(plan, jid, task, *, root, resume=None, on_checkpoint=None, hook=None, **kw):
            self.calls.append((jid, resume['phase'] if resume else 'FRESH', str(root)))
            root = Path(root)
            job_dir = root / 'jobs' / jid
            job_dir.mkdir(parents=True, exist_ok=True)
            if resume is None:
                # Primary run: emit all checkpoints in one single run without exception cuts
                for ph in d.PHASES:
                    cp = {
                        'phase': ph,
                        'job_id': jid,
                        'pending_event': {
                            'selection': 'OFFLINE_SELECTION',
                            'proposed_action': 'ARCHIVED_TEST_ONLY',
                            'monitor': {'result_digest': 'SAVED_RESULT'} if ph != 'SELECTED' else None,
                        },
                    }
                    # Simulate a clean snapshot saved during the run
                    d.write(job_dir / 'accounting.json', {'invocations': [{'status': 'RETURNED'}]})
                    d.write(job_dir / 'checkpoint.json', cp)
                    if on_checkpoint:
                        on_checkpoint(cp)
                a_cnt = 1 if jid in ('J00', 'J01') else 2
                append_ledger(jid, a_cnt, 2 * a_cnt)
                delta = {
                    'selector_calls': 1,
                    'singleton_executions': int(a_cnt == 2),
                    'monitor_entries': a_cnt,
                    'monitor_reuses': 0,
                    'commit_attempts': a_cnt,
                    'commit_successes': a_cnt,
                }
            else:
                ph = resume['phase']
                if ph == 'MONITORED':
                    self.assertEqual(resume['pending_event']['monitor']['result_digest'], 'SAVED_RESULT')
                exp_a = int(ph == 'SELECTED')
                append_ledger(jid, exp_a, 2 * exp_a)
                delta = {
                    'selector_calls': 0,
                    'singleton_executions': 0,
                    'monitor_entries': int(ph == 'SELECTED'),
                    'monitor_reuses': int(ph == 'MONITORED'),
                    'commit_attempts': int(ph != 'COMMITTED'),
                    'commit_successes': int(ph != 'COMMITTED'),
                }
            d.write(job_dir / 'record.json', {})
            return {
                'checkpoint': {
                    'events': [{
                        'selection': 'OFFLINE_SELECTION',
                        'proposed_action': 'ARCHIVED_TEST_ONLY',
                        'monitor': {'result_digest': 'SAVED_RESULT'},
                    }]
                },
                'summary': {'completed': True, 'accounting': {'invocation_delta': delta}},
            }

        fixture = (
            probe_plan,
            {},
            {},
            {j['task_id']: {} for j in self.jobs},
            [{}] * 4,
            initial_ledger,
        )
        with patch.object(d, 'prepare', return_value=fixture), patch.object(
            d.order, 'run_order_job', side_effect=fake_run_order_job
        ):
            d.execute(d.R, 'TEST_ONLY', 'TEST_ONLY', self.root / 'run_10')

        # Directly assert total entrypoint invocations == 10 (4 primary FRESH + 6 recovery phases)
        self.assertEqual(len(self.calls), 10)
        primary_calls = [(j, ph) for j, ph, r in self.calls if '/recovery/' not in r]
        recovery_calls = [(j, ph) for j, ph, r in self.calls if '/recovery/' in r]
        self.assertEqual(primary_calls, [(f'J{i:02}', 'FRESH') for i in range(4)])
        self.assertEqual(recovery_calls, [(j, ph) for j in ('J00', 'J01') for ph in d.PHASES])

        receipt = d.read(self.root / 'run_10' / 'driver_receipt.json')
        self.assertEqual(receipt['primary_dispatches'], 4)
        self.assertEqual(receipt['recovery_dispatches'], 6)
        self.assertEqual(receipt['final_counts'], {'assessment_entries': 8, 'solver_calls': 16, 'test_double_assessments': 0})
        self.assertEqual(len(receipt['rows']), 10)
        self.assertTrue(all(r['status'] == 'COMPLETE' for r in receipt['rows']))

    def test_dispatch_01_public_interface_started_accounting_blocker_probe(self):
        result = probe.run_probe()
        for phase in d.PHASES:
            obs = result['single_primary_run_accounting_trace']['in_run_snapshots'][phase]
            self.assertEqual(obs['accounting_last_status'], 'STARTED')
            self.assertFalse(obs['resumable_without_mutation'])
            self.assertEqual(obs['blocker_code_if_resumed_as_is'], 'geometry_accounting_unknown_dispatch')
        for attempt in result['unmutated_in_run_resume_attempts']:
            self.assertEqual(attempt['resume_outcome'], 'REJECTED_BY_PUBLIC_ACCOUNTING_GATE')
            self.assertEqual(attempt['error_code'], 'geometry_accounting_unknown_dispatch')
            self.assertTrue(attempt['bytes_unchanged'])

    # --- 4. Preflight barrier & first-failure stop tests ---
    def test_missing_records_stops_before_dispatch(self):
        with patch.object(d.order, 'run_order_job', side_effect=AssertionError('DISPATCH_FORBIDDEN')) as run:
            with self.assertRaises(FileNotFoundError):
                d.execute(d.R, self.root / 'missing_review', self.root / 'missing_launch', self.root / 'run')
        run.assert_not_called()
        self.assertTrue(all(r['status'] == 'NOT_RUN' for r in d.read(self.root / 'run/driver_receipt.json')['rows']))

    def test_identity_drift_stops_before_dispatch(self):
        runtime = self.root / 'runtime_drift'
        runtime.mkdir()
        for name in ('acceptance_plan_FROZEN.json', 'monitor_snapshot.json', 'startup_review_request.json'):
            (runtime / name).write_bytes((d.R / name).read_bytes())
        req = d.read(runtime / 'startup_review_request.json')
        req['plan_digest'] = '0' * 64
        d.write(runtime / 'startup_review_request.json', req)
        with patch.object(d.order, 'run_order_job') as run:
            with self.assertRaises(AssertionError):
                d.execute(runtime, 'unused', 'unused', self.root / 'run_drift')
        run.assert_not_called()

    def test_joint_preflight_failure_prevents_dispatch(self):
        runtime, auth_path, review_path, launch_path, _ = self.make_runtime_and_records()
        with patch.object(d.p, 'validate_admission'), patch.object(
            d.order, 'load_order_config', side_effect=[{}, {}, RuntimeError('J02_PREFLIGHT_FAIL')]
        ) as cfg, patch.object(d.order, 'run_order_job') as run:
            with self.assertRaisesRegex(RuntimeError, 'J02_PREFLIGHT_FAIL'):
                d.execute(runtime, review_path, launch_path, self.root / 'run_j02_fail', authorization=auth_path)
        self.assertEqual(cfg.call_count, 3)
        run.assert_not_called()

    def test_first_failure_keeps_remaining_not_run(self):
        probe_plan = copy.deepcopy(self.plan)
        ledger_path = self.write_zero_ledger(self.root / 'fail_ledger.json', plan=probe_plan)
        probe_plan['call_ledger_path'] = str(ledger_path)
        initial_ledger = d.check_initial_zero_ledger(probe_plan)
        fixture = (probe_plan, {}, {}, {j['task_id']: {} for j in self.jobs}, [{}] * 4, initial_ledger)
        with patch.object(d, 'prepare', return_value=fixture), patch.object(
            d.order, 'run_order_job', side_effect=RuntimeError('OFFLINE_FAILURE')
        ) as run:
            with self.assertRaises(RuntimeError):
                d.execute(d.R, 'fixture', 'fixture', self.root / 'run_first_fail')
        self.assertEqual(run.call_count, 1)
        rows = d.read(self.root / 'run_first_fail/driver_receipt.json')['rows']
        self.assertEqual(rows[0]['status'], 'FAILED')
        self.assertEqual(sum(r['status'] == 'NOT_RUN' for r in rows), 9)


if __name__ == '__main__':
    unittest.main(verbosity=2)
