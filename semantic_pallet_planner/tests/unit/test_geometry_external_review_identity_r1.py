"""Pure review binding tests; fixtures deleted, no effective permits or real runs."""
import copy
import json
import socket
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select import geometry_kernel_completion as c
from semantic_pallet_planner.jev_select.contracts import canonical, digest, JevSelectError
from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields, wire

RECEIPTS = []


class ReviewIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='gp5_review_identity_')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.serial = 0
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ('stability.exact_adapter.assess_candidate',
                     'stability.balance_adapter.assess_candidate',
                     'stability.balance_network.solve_network',
                     'stability.balance_network.linprog', 'stability.monitor.freeze',
                     'stability.monitor.exact_freeze', 'episode.run_episode',
                     'geometry_order_meter.metered_run', 'candidates.CandidateProvider.build'):
            self.stack.enter_context(patch('semantic_pallet_planner.jev_select.' + name,
                                          side_effect=AssertionError('REAL_DISPATCH_FORBIDDEN:' + name)))
        self.stack.enter_context(patch.object(socket.socket, 'connect',
                                             side_effect=AssertionError('NETWORK_FORBIDDEN')))

    def ref(self, value):
        self.serial += 1
        path = self.root / (str(self.serial) + '.json')
        raw = canonical(value).encode()
        path.write_bytes(raw)
        return {'path': str(path), 'sha256': p.sha(raw)}

    def plan(self, native=True):
        tasks = []
        for case in ('K01', 'K02'):
            raw = canonical(p.synthetic_task(case)).encode()
            tasks.append(p.adapt_task(raw, origin='SYNTHETIC_FIXED', expected_sha256=p.sha(raw)))
        plan = p.prepare_order_plan(tasks, data_identity=digest('PURE_REVIEW_FIXTURE'),
                                    scope=p.ACCEPTANCE, native=native)
        # Temporary structural fixture only; never sent to run_order_job.
        plan.update(status='FROZEN', call_ledger_path=str(self.root / 'NEVER_CALLED.json'))
        return plan

    def launch(self, plan):
        snapshot = {'evidence': 'PURE_BINDING_ONLY_NOT_MONITOR_SNAPSHOT'}
        common = {**identity_fields(plan), 'scope': p.ACCEPTANCE,
                  'plan_digest': digest(plan), 'status': 'APPROVED'}
        authorization = {**common, 'version': wire(plan, 'geometry_scope_authorization_v1')}
        review = {**common, 'version': wire(plan, 'geometry_scope_review_v1')}
        launch = {**common, 'version': wire(plan, 'geometry_kernel_launch_v1'),
                  'source_identity': plan['source_identity'],
                  'environment_digest': plan['environment_digest'], 'monitor_digest': digest(snapshot),
                  'authorization': self.ref(authorization), 'review': self.ref(review)}
        return snapshot, launch, authorization, review

    def reject(self, name, function, code):
        with self.assertRaises(JevSelectError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)
        RECEIPTS.append({'case': name, 'status': 'EXPECTED_REJECTION',
                         'type': 'JevSelectError', 'code': code})

    def completion(self, plan):
        """Coverage-only metadata, not real records; callback will be a no-op."""
        coverage = c.required_coverage(plan)
        records = []
        for row in coverage['primary']:
            events = []
            state = {'placed_items': [], 'end_of_stream': True, 'pending_items': []}
            for index, pose in enumerate(row['poses']):
                before = copy.deepcopy(state)
                state['placed_items'].append({'item_id': str(index)})
                action = {'id': str(index)}
                events.append({'event': 'PLACE', 'bundle': {'physical_candidates': [
                    {'candidate_id': str(index), 'pose': pose,
                     'oriented_size_mm': [100, 80, 60] if pose['yaw_deg'] == 0 else [80, 100, 60]}]},
                    'selection': {'selected_candidate_id': str(index)}, 'action': action,
                    'proposed_action': action, 'monitor': {'status': 'STABLE',
                    'result': {'status': 'STABLE'}, 'result_digest': digest('PURE_COVERAGE_ONLY')},
                    'before': before, 'after': copy.deepcopy(state)})
            records.append({'checkpoint': {'job_id': row['job_id'], 'method': 'local_first_test_double',
                            'phase': 'TERMINATED', 'reason': 'ALL_ITEMS_PLACED', 'state': state,
                            'events': events}, 'config': {'order_task_identity': {'task_id': row['task_id']},
                            'candidate_backend': row['backend'], 'selector': 'local_first_test_double'}})
        receipt = {'records': [self.ref(r) for r in records], 'recovery': [],
                   'counter_log': self.ref({'PURE_COVERAGE_ONLY': True})}
        for row in coverage['recovery']:
            record = next(r for r in records if r['checkpoint']['job_id'] == row['job_id'])
            before = copy.deepcopy(record['checkpoint'])
            before.update(phase=row['phase'], pending_event=copy.deepcopy(before['events'][-1]))
            delta = {'selector_calls': 0, 'singleton_executions': 0,
                     'monitor_entries': int(row['phase'] == 'SELECTED'),
                     'monitor_reuses': int(row['phase'] == 'MONITORED'),
                     'commit_attempts': int(row['phase'] != 'COMMITTED'),
                     'commit_successes': int(row['phase'] != 'COMMITTED')}
            account = {**identity_fields(plan), 'version': wire(plan, 'geometry_order_accounting_v1'),
                       'plan_digest': digest(plan), 'job_id': row['job_id'],
                       'config_digest': digest(record['config']), 'invocations': [{'index': 0,
                       'resume_phase': row['phase'], 'status': 'RETURNED', 'delta': delta,
                       'resume_checkpoint_digest': digest(before),
                       'result_checkpoint_digest': digest(record['checkpoint'])}], 'cumulative': delta}
            receipt['recovery'].append({**row, 'before': self.ref(before),
                                       'after': self.ref(record), 'accounting': self.ref(account)})
        calls = []
        for row in coverage['primary']:
            for kind, count in (('assessment_entries', len(row['poses']) + int(row['task_id'].endswith('K01'))),
                                ('solver_calls', 1)):
                for _ in range(count):
                    calls.append({'kind': kind, 'state': 'DONE', 'index': len(calls), 'job_id': row['job_id']})
        review = {**identity_fields(plan), 'version': wire(plan, 'geometry_kernel_completion_review_v1'),
                  'scope': p.ACCEPTANCE, 'status': 'APPROVED', 'acceptance_plan_digest': digest(plan),
                  'records_digest': digest(receipt['records']), 'recovery_digest': digest(receipt['recovery']),
                  'counter_log': receipt['counter_log'], 'coverage_digest': digest(coverage)}
        receipt['review'] = self.ref(review)
        return receipt, {'calls': calls}, review

    def test_v17_authorization_and_start_review_identity(self):
        plan = self.plan()
        snapshot, launch, authorization, review = self.launch(plan)
        p.validate_admission(plan, snapshot, launch)
        RECEIPTS.append({'case': 'v17 authorization/start review matching', 'status': 'PASS_BINDING_ONLY'})
        for key, doc in (('authorization', authorization), ('review', review)):
            for field, value, code in (
                    ('publication_policy_digest', '0' * 64, 'geometry_external_approval_identity'),
                    ('runtime_version', 'jev_packaging_geometry_order_v16',
                     'invalid_' + wire(plan, 'geometry_scope_authorization_v1' if key == 'authorization' else 'geometry_scope_review_v1'))):
                bad = copy.deepcopy(doc)
                bad[field] = value
                trial = copy.deepcopy(launch)
                trial[key] = self.ref(bad)
                self.reject(key + '/' + field, lambda: p.validate_admission(plan, snapshot, trial), code)

    def test_v17_completion_review_identity(self):
        plan = self.plan()
        receipt, log, review = self.completion(plan)
        c.validate_completion(receipt, plan, log, lambda record: None)
        RECEIPTS.append({'case': 'v17 completion matching', 'status': 'PASS_COVERAGE_BINDING_ONLY',
                         'genuine_durable_validation': 'NOT_PERFORMED_NOOP_CALLBACK'})
        for field, value, code in (
                ('publication_policy_digest', '0' * 64, 'geometry_completion_review_binding'),
                ('runtime_version', 'jev_packaging_geometry_order_v16', 'invalid_geometry_kernel_completion_review_v2')):
            bad = copy.deepcopy(review)
            bad[field] = value
            trial = copy.deepcopy(receipt)
            trial['review'] = self.ref(bad)
            self.reject('completion/' + field, lambda: c.validate_completion(trial, plan, log, lambda record: None), code)

    def test_v16_approval_and_completion_compatibility(self):
        plan = self.plan(native=False)
        self.assertEqual(identity_fields(plan), {})
        snapshot, launch, _, _ = self.launch(plan)
        p.validate_admission(plan, snapshot, launch)
        receipt, log, review = self.completion(plan)
        self.assertNotIn('runtime_version', review)
        self.assertNotIn('publication_policy_digest', review)
        c.validate_completion(receipt, plan, log, lambda record: None)
        for row in receipt['recovery']:
            rec = json.loads(Path(row['after']['path']).read_bytes())
            rec['durable_root'] = str(Path(row['after']['path']).parent)
            row['after'] = self.ref(rec)
        review['recovery_digest'] = digest(receipt['recovery'])
        receipt['review'] = self.ref(review)
        c.validate_completion(receipt, plan, log, lambda record: None)
        RECEIPTS.append({'case': 'v16 legacy records', 'status': 'PASS_BINDING_AND_COVERAGE_ONLY'})

    def test_missing_references_and_existing_identity_protections(self):
        plan = self.plan()
        snapshot, launch, authorization, review = self.launch(plan)
        missing = {'path': str(self.root / 'MISSING'), 'sha256': '0' * 64}
        for key, doc in (('authorization', authorization), ('review', review)):
            trial = copy.deepcopy(launch)
            trial[key] = missing
            self.reject('missing/' + key, lambda: p.validate_admission(plan, snapshot, trial), 'geometry_missing_receipt')
            bad = copy.deepcopy(doc)
            bad['plan_digest'] = '0' * 64
            trial[key] = self.ref(bad)
            self.reject('plan mismatch/' + key, lambda: p.validate_admission(plan, snapshot, trial), 'geometry_external_approval')
        for field in ('source_identity', 'environment_digest'):
            bad = copy.deepcopy(plan)
            bad[field] = '0' * 64
            self.reject('plan drift/' + field, lambda: p.validate_order_plan(bad), 'geometry_order_plan_identity')
        bad = copy.deepcopy(launch)
        bad['source_identity'] = '0' * 64
        self.reject('launch drift', lambda: p.validate_admission(plan, snapshot, bad), 'geometry_admission_binding')
        receipt, log, _ = self.completion(plan)
        receipt['review'] = missing
        self.reject('missing completion review', lambda: c.validate_completion(receipt, plan, log, lambda record: None), 'geometry_missing_receipt')

    def test_completion_existing_coverage_bindings_remain(self):
        plan = self.plan()
        receipt, log, review = self.completion(plan)
        for field in ('acceptance_plan_digest', 'records_digest', 'recovery_digest', 'coverage_digest'):
            bad = copy.deepcopy(review)
            bad[field] = '0' * 64
            trial = copy.deepcopy(receipt)
            trial['review'] = self.ref(bad)
            self.reject('completion existing/' + field,
                        lambda: c.validate_completion(trial, plan, log, lambda record: None), 'geometry_completion_review_binding')
        # Existing nine-negative v16 pure coverage regression, no test setUp/loops.
        from test_geometry_order_r1 import Remediation
        case = Remediation('test_completion_contract_missing_duplicate_error_only_no_commit_recovery')
        case.tmp = type('T', (), {'name': str(self.root)})()
        case.evidence = None
        capture = {}
        case.save = lambda name, value: capture.update({name: value})
        case.test_completion_contract_missing_duplicate_error_only_no_commit_recovery()
        self.assertEqual(len(capture['completion_contract_results.json']['negative']), 9)
        RECEIPTS.append({'case': 'existing v16 completion nine negatives', 'status': 'PASS_PURE_CONTRACT_ONLY'})

    def test_test_double_cannot_be_real_completion(self):
        plan = self.plan()
        snapshot, launch, _, _ = self.launch(plan)
        receipt, _, _ = self.completion(plan)
        envelope = {**identity_fields(plan), 'version': wire(plan, 'geometry_real_kernel_receipt_v2'),
                    'scope': p.ACCEPTANCE, 'status': 'ACCEPTED', 'source_identity': plan['source_identity'],
                    'environment_digest': plan['environment_digest'], 'monitor_digest': digest(snapshot),
                    'acceptance_plan': self.ref(plan), 'launch': self.ref(launch), **receipt,
                    'counts': {'assessment_entries': 8, 'solver_calls': 8, 'test_double_assessments': 1}}
        self.reject('marked substitute', lambda: p.validate_real_kernel_receipt(envelope, plan, snapshot), 'geometry_real_counts')
        envelope['counts']['test_double_assessments'] = 0
        envelope['counter_log'] = self.ref({'counts': envelope['counts'], 'plan_digest': digest(plan), 'evidence': 'COUNTER_TEST'})
        self.reject('fake counter evidence', lambda: p.validate_real_kernel_receipt(envelope, plan, snapshot), 'geometry_real_counter_log')

    def test_both_backends_explicit_and_draft_non_executable(self):
        from semantic_pallet_planner.jev_select.candidate_backends import load_geometry_config
        plan = self.plan()
        for backend in ('e2_original_v1', 'ems_surface_hybrid_v1'):
            cfg = load_geometry_config(backend=backend, data_identity=digest('DATA'),
                                       task_identity=digest('TASK'), monitor_identity=digest('MONITOR'),
                                       method='local_first_test_double')
            self.assertEqual(cfg['candidate_backend'], backend)
        plan.update(status='DRAFT', call_ledger_path=None)
        self.reject('DRAFT gate', lambda: p.validate_admission(plan, {}, {}), 'geometry_order_draft_not_executable')


if __name__ == '__main__':
    unittest.main(verbosity=2, failfast=True)
