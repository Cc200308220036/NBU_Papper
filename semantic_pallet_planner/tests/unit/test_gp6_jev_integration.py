"""Offline production integration tests for GP6-F0 v18 (jev_no_memory over E2/EMS).

Uses synthetic fixtures and explicitly marked TEST_DOUBLE transport/monitor only.
Never reads credentials, never performs network calls, never runs real LP/kernel/freeze.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from semantic_pallet_planner.jev_select.contracts import JevSelectError, canonical, digest, validate_schema
from semantic_pallet_planner.jev_select.geometry_jev_execution import (
    GeometryJevRequestLedger,
    GeometryJevSelector,
    JevOrderStore,
    load_jev_config,
    run_jev_job,
    validate_jev_saved_checkpoint,
)
from semantic_pallet_planner.jev_select.geometry_jev_protocol import (
    GP6_DEVELOPMENT,
    GP6_MODEL,
    GP6_ORDER,
    development_binding,
    prepare_jev_plan,
)
from semantic_pallet_planner.jev_select.geometry_order_execution import validate_order_request
from semantic_pallet_planner.jev_select.packaging_geometry_protocol import adapt_task, synthetic_task
from semantic_pallet_planner.jev_select.packaging_versions import (
    DEFAULT_GEOMETRY_BACKEND,
    GEOMETRY_BACKENDS,
    GEOMETRY_JEV_VERSION,
)
from semantic_pallet_planner.jev_select.stability import exact_adapter, exact_contracts
from semantic_pallet_planner.jev_select.transport import outcome


DUMMY_DATA_ID = '0' * 64


def _adapted_synth(case: str) -> dict:
    raw = canonical(synthetic_task(case)).encode('utf-8')
    return adapt_task(raw, origin='SYNTHETIC_FIXED', expected_sha256=__import__('hashlib').sha256(raw).hexdigest())


def _fake_monitor_snapshot() -> dict:
    cfg = asdict(exact_contracts.load_config())
    schema_path = Path(__file__).resolve().parents[2] / 'src/semantic_pallet_planner/jev_select/schemas/config_v18.schema.json'
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    req_files = schema['properties']['stability_monitor']['properties']['algorithm_identity']['properties']['files_sha256']['required']
    files_sha256 = {name: 'a' * 64 for name in req_files}
    deps = {
        'numpy': '2.1.3',
        'scipy': '1.15.3',
        'highs_version': '1.8.0',
        'highs_core_sha256': 'e' * 64,
        'scipy_python_sha256': {'_linprog.py': '1' * 64, '_linprog_highs.py': '2' * 64},
    }
    return {
        'enabled': True,
        'algorithm': 'pct_exact_pose_network_v3',
        'kernel_config': cfg,
        'algorithm_identity': {
            'algorithm': 'pct_exact_pose_network_v3',
            'semantic_revision': 'exact_pose_contacts_global_equilibrium_v3',
            'upstream_commit': '5e7b4238b18310af4529e0f85157d17de605850c',
            'units': {'length': 'mm', 'mass': 'kg', 'moment': 'kg*mm'},
            'files_sha256': files_sha256,
            'source_digest': digest(files_sha256),
            'dependencies': deps,
            'dependency_digest': digest(deps),
        },
        'execution_environment': {
            'platform': 'TEST_DOUBLE',
            'python': 'TEST_DOUBLE',
            'executable': 'TEST_DOUBLE',
            'numpy': '2.1.3',
            'numpy_core_sha256': '3' * 64,
        },
    }


def _make_monitor_double(snapshot: dict, *, status_fn=None):
    calls: list[dict] = []

    def assess(state, candidate, config):
        x_mm, y_mm, z_base_mm = candidate.bottom_center_mm
        calls.append({'candidate_id': candidate.item_id, 'placed_count': len(state.placed)})
        status = 'STABLE' if status_fn is None else status_fn(len(calls), state, candidate)
        return exact_contracts.ExactResult(
            status=status,
            reason_code='TEST_DOUBLE_STABLE' if status == 'STABLE' else 'TEST_DOUBLE_UNSTABLE',
            state_digest=digest(asdict(state)),
            candidate_digest=digest(asdict(candidate)),
            candidate_id=candidate.item_id,
            config_digest=digest(snapshot['kernel_config']),
            algorithm_identity=copy.deepcopy(snapshot['algorithm_identity']),
            baseline_status='STABLE',
            first_bad_prefix=None if status == 'STABLE' else 'prefix_1',
            failed_item_id=None if status == 'STABLE' else candidate.item_id,
            height_delta_mm=0.0,
            evaluated_pose=None,
            kernel_calls=0,
            diagnostics={'TEST_DOUBLE': True},
            duration_s=0.001,
        )

    assess.geometry_test_double = True
    return assess, calls


class FakeChoiceTransport:
    """Explicit offline test_double transport; never touches network or credentials."""

    def __init__(self, *, origin='test_double', responder=None):
        self.origin = origin
        self._responder = responder
        self.bodies: list[dict] = []

    def complete(self, body: dict) -> dict:
        self.bodies.append(copy.deepcopy(body))
        if self._responder is not None:
            return self._responder(body, len(self.bodies))
        labels = sorted(body['questions']['next_action']['criteria'].keys())
        choice = labels[0]
        probs = {k: (1.0 if k == choice else 0.0) for k in labels}
        payload = {
            'model': body['model'],
            'answers': {'next_action': {'type': 'choice', 'choice': choice, 'probabilities': probs, 'confidence': 0.95}},
            'usage': {'input_tokens': 120, 'output_tokens': 12},
        }
        return outcome('OK', json.dumps(payload).encode('utf-8'), http_status=200, latency_s=0.01, network_attempted=False)


class _InterruptForRecovery(RuntimeError):
    pass


class TestGP6JevIntegration(unittest.TestCase):
    def setUp(self):
        self.snapshot = _fake_monitor_snapshot()
        self.k01 = _adapted_synth('K01')
        self.k02_int = _adapted_synth('K02_INT')

    def test_e2_and_ems_f0_no_memory_offline_success_and_exact_binding(self):
        plan = prepare_jev_plan([self.k01], data_identity=DUMMY_DATA_ID, scope=GP6_DEVELOPMENT, per_job_max_sends=4, shared_max_sends=8)
        binding = development_binding(plan)
        assess, monitor_calls = _make_monitor_double(self.snapshot)

        with tempfile.TemporaryDirectory() as td, patch.object(exact_adapter, 'assess_candidate', assess):
            root = Path(td)
            ledger = GeometryJevRequestLedger(root / 'req_ledger', plan_digest=digest(plan), per_job_max_sends=4, shared_max_sends=8)
            transport = FakeChoiceTransport()

            for job_id, expected_backend in [('G00', 'e2_original_v1'), ('G01', 'ems_surface_hybrid_v1')]:
                ep = run_jev_job(
                    plan, job_id, self.k01,
                    monitor_snapshot=self.snapshot, admission=binding,
                    root=root / 'run', transport=transport, ledger=ledger,
                )
                self.assertEqual(ep['checkpoint']['reason'], 'ALL_ITEMS_PLACED')
                self.assertTrue(ep['summary']['completed'])
                self.assertEqual(ep['summary']['candidate_backend'], expected_backend)
                self.assertEqual(ep['summary']['cost']['model_calls'], 0)
                self.assertEqual(ep['summary']['cost']['service_cost_usd'], 'NA_NO_SERVICE_CALL')
                self.assertEqual(ep['summary']['cost']['test_double_sends'], 1)
                self.assertEqual(ep['summary']['cost']['successful_selections'], 1)

                place_ev = next(e for e in ep['events'] if e['event'] == 'PLACE')
                # F0 public-only and empty memories
                body_str = canonical(place_ev['context']['request_body'])
                self.assertEqual(place_ev['context']['model_state']['memories'], [])
                for forbidden in ('e2_original_v1', 'ems_surface_hybrid_v1', 'EMS_STYLE_3D', 'SURFACE_CORNER', 'pct_exact_pose_network'):
                    self.assertNotIn(forbidden, body_str)
                # Exact action binding from Cxx to committed pose
                sel = place_ev['selection']
                self.assertEqual(sel['status'], 'selected')
                self.assertEqual(sel['source'], 'test_double')
                mapped = place_ev['context']['display_mapping'][sel['selected_display_id']]
                self.assertEqual(mapped['candidate_id'], sel['selected_candidate_id'])
                cand = next(c for c in place_ev['bundle']['physical_candidates'] if c['candidate_id'] == sel['selected_candidate_id'])
                self.assertEqual(place_ev['action'], place_ev['proposed_action'])
                self.assertEqual(ep['final_state']['placed_items'][0]['item_id'], cand['pick_item_id'])
                self.assertEqual(ep['final_state']['placed_items'][0]['pose'], cand['pose'])
                self.assertEqual(ep['final_state']['placed_items'][0]['oriented_size_mm'], cand['oriented_size_mm'])

            self.assertEqual(len(transport.bodies), 2)
            self.assertEqual(len(monitor_calls), 2)

    def test_singleton_bypass_zero_sends_still_monitored(self):
        # K02_INT has container 100x80x180 and two 100x80x60 boxes -> exact 1 candidate per step (SINGLETON_BYPASS)
        plan = prepare_jev_plan([self.k02_int], data_identity=DUMMY_DATA_ID, scope=GP6_DEVELOPMENT, per_job_max_sends=4, shared_max_sends=8)
        binding = development_binding(plan)
        assess, monitor_calls = _make_monitor_double(self.snapshot)

        with tempfile.TemporaryDirectory() as td, patch.object(exact_adapter, 'assess_candidate', assess):
            root = Path(td)
            ledger = GeometryJevRequestLedger(root / 'req_ledger', plan_digest=digest(plan), per_job_max_sends=4, shared_max_sends=8)
            transport = FakeChoiceTransport()
            ep = run_jev_job(
                plan, 'G01', self.k02_int,
                monitor_snapshot=self.snapshot, admission=binding,
                root=root / 'run', transport=transport, ledger=ledger,
            )
            self.assertEqual(ep['checkpoint']['reason'], 'ALL_ITEMS_PLACED')
            # Step 0 has 2 pending boxes (CHOICE_REQUIRED -> 1 send); Step 1 has 1 remaining box & 1 pose (SINGLETON_BYPASS -> 0 sends)
            self.assertEqual(len(transport.bodies), 1)
            self.assertEqual(ep['summary']['cost']['send_reservations'], 1)
            self.assertEqual(ep['summary']['cost']['singleton_bypasses'], 1)
            singleton_ev = [e for e in ep['events'] if e.get('route') == 'SINGLETON_BYPASS']
            self.assertEqual(len(singleton_ev), 1)
            self.assertEqual(singleton_ev[0]['selection']['source'], 'singleton')
            self.assertIsNotNone(singleton_ev[0]['monitor'])
            self.assertEqual(len(monitor_calls), 2)

    def test_invalid_label_budget_exhausted_instability_and_unauthorized_real_transport(self):
        plan = prepare_jev_plan([self.k01], data_identity=DUMMY_DATA_ID, scope=GP6_DEVELOPMENT, per_job_max_sends=1, shared_max_sends=2)
        binding = development_binding(plan)
        assess_ok, monitor_calls_ok = _make_monitor_double(self.snapshot)

        # 1. Invalid out-of-pool C99 label -> INVALID_RESPONSE stop, never falls back to local selector
        with tempfile.TemporaryDirectory() as td, patch.object(exact_adapter, 'assess_candidate', assess_ok):
            root = Path(td)
            ledger = GeometryJevRequestLedger(root / 'req_ledger', plan_digest=digest(plan), per_job_max_sends=1, shared_max_sends=2)

            def bad_label(body, _n):
                payload = {
                    'model': body['model'],
                    'answers': {'next_action': {'type': 'choice', 'choice': 'C99', 'probabilities': {'C99': 1.0}, 'confidence': 0.9}},
                }
                return outcome('OK', json.dumps(payload).encode('utf-8'), http_status=200, network_attempted=False)

            ep = run_jev_job(
                plan, 'G00', self.k01,
                monitor_snapshot=self.snapshot, admission=binding,
                root=root / 'run', transport=FakeChoiceTransport(responder=bad_label), ledger=ledger,
            )
            self.assertEqual(ep['checkpoint']['reason'], 'INVALID_RESPONSE')
            self.assertEqual(ep['summary']['placed_items'], 0)
            self.assertEqual(ep['summary']['cost']['send_reservations'], 1)
            self.assertEqual(ep['summary']['cost']['failed_requests'], 1)
            self.assertEqual(ep['summary']['cost']['usage_status'], 'UNKNOWN')
            self.assertEqual(ep['summary']['cost']['usage'], 'UNKNOWN')
            self.assertEqual(len(monitor_calls_ok), 0)

        # 2. Per-job budget exhaustion (pre-filled 1 send -> BUDGET_EXHAUSTED, 0 new sends)
        with tempfile.TemporaryDirectory() as td, patch.object(exact_adapter, 'assess_candidate', assess_ok):
            root = Path(td)
            ledger = GeometryJevRequestLedger(root / 'req_ledger', plan_digest=digest(plan), per_job_max_sends=1, shared_max_sends=2)
            # Exhaust G00 budget with a prior failed attempt
            raw = json.loads((root / 'req_ledger/requests.json').read_text(encoding='utf-8'))
            raw['requests'].append({
                'attempt_id': 'A000001', 'job_id': 'G00', 'decision_id': 'G00_PREV',
                'context_digest': '1' * 64, 'body_digest': '2' * 64, 'binding_digest': '3' * 64,
                'state_digest': '4' * 64, 'mapping_digest': '5' * 64,
                'origin': 'test_double', 'model': GP6_MODEL, 'send_started': True,
                'state': 'FAILED', 'history': [{'state': 'FAILED', 'at': 0.0}],
                'transport': outcome('PROVIDER_FAILURE', error='HTTP_500', network_attempted=False),
                'transport_digest': digest(outcome('PROVIDER_FAILURE', error='HTTP_500', network_attempted=False)),
                'selection': None, 'selection_digest': None,
            })
            raw['record_digest'] = digest({k: v for k, v in raw.items() if k != 'record_digest'})
            (root / 'req_ledger/requests.json').write_text(canonical(raw) + '\n', encoding='utf-8')
            t_budget = FakeChoiceTransport()
            ep = run_jev_job(
                plan, 'G00', self.k01,
                monitor_snapshot=self.snapshot, admission=binding,
                root=root / 'run', transport=t_budget, ledger=ledger,
            )
            self.assertEqual(ep['checkpoint']['reason'], 'BUDGET_EXHAUSTED')
            self.assertEqual(len(t_budget.bodies), 0)
            self.assertEqual(ep['summary']['placed_items'], 0)

        # 3. Monitor UNSTABLE -> stops immediately without placing or picking alternate candidate
        assess_bad, monitor_calls_bad = _make_monitor_double(self.snapshot, status_fn=lambda n, s, c: 'UNSTABLE')
        with tempfile.TemporaryDirectory() as td, patch.object(exact_adapter, 'assess_candidate', assess_bad):
            root = Path(td)
            ledger = GeometryJevRequestLedger(root / 'req_ledger', plan_digest=digest(plan), per_job_max_sends=1, shared_max_sends=2)
            t_unstab = FakeChoiceTransport()
            ep = run_jev_job(
                plan, 'G00', self.k01,
                monitor_snapshot=self.snapshot, admission=binding,
                root=root / 'run', transport=t_unstab, ledger=ledger,
            )
            self.assertEqual(ep['checkpoint']['reason'], 'PREDICTED_STATIC_INSTABILITY')
            self.assertEqual(ep['summary']['placed_items'], 0)
            self.assertEqual(len(t_unstab.bodies), 1)
            self.assertEqual(len(monitor_calls_bad), 1)

        # 4. Real 'jev' transport rejected without formal admission/authorization
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = GeometryJevRequestLedger(root / 'req_ledger', plan_digest=digest(plan), per_job_max_sends=1, shared_max_sends=2, allow_real_transport=False)
            real_like_transport = FakeChoiceTransport(origin='jev')
            with self.assertRaises(JevSelectError) as ctx:
                run_jev_job(
                    plan, 'G00', self.k01,
                    monitor_snapshot=self.snapshot, admission=binding,
                    root=root / 'run', transport=real_like_transport, ledger=ledger,
                )
            self.assertEqual(ctx.exception.code, 'gp6_real_transport_unauthorized')
            self.assertEqual(len(real_like_transport.bodies), 0)

    def test_four_recovery_protections_selected_unknown_send_monitored_committed(self):
        plan = prepare_jev_plan([self.k01], data_identity=DUMMY_DATA_ID, scope=GP6_DEVELOPMENT, per_job_max_sends=4, shared_max_sends=8)
        binding = development_binding(plan)

        # A. SELECTED, MONITORED, COMMITTED phase recoveries
        for hook_name, expected_phase, expect_monitor_reuses in [
            ('after_selected_checkpoint', 'SELECTED', 0),
            ('after_monitored_checkpoint', 'MONITORED', 1),
            ('after_commit_checkpoint', 'COMMITTED', 0),
        ]:
            assess, monitor_calls = _make_monitor_double(self.snapshot)
            transport = FakeChoiceTransport()
            saved_cp = {}

            def interrupt_hook(stage, payload):
                if stage == hook_name and not saved_cp:
                    saved_cp['cp'] = copy.deepcopy(payload)
                    raise _InterruptForRecovery(hook_name)

            with tempfile.TemporaryDirectory() as td, patch.object(exact_adapter, 'assess_candidate', assess):
                root = Path(td)
                ledger = GeometryJevRequestLedger(root / 'req_ledger', plan_digest=digest(plan), per_job_max_sends=4, shared_max_sends=8)
                with self.assertRaises(_InterruptForRecovery):
                    run_jev_job(
                        plan, 'G01', self.k01,
                        monitor_snapshot=self.snapshot, admission=binding,
                        root=root / 'run', transport=transport, ledger=ledger,
                        hook=interrupt_hook,
                    )
                self.assertEqual(saved_cp['cp']['phase'], expected_phase)
                sends_before = len(transport.bodies)
                monitors_before = len(monitor_calls)

                # Resume from saved checkpoint: must not resend, must not re-assess monitored, must not double-place
                ep = run_jev_job(
                    plan, 'G01', self.k01,
                    monitor_snapshot=self.snapshot, admission=binding,
                    root=root / 'run', transport=transport, ledger=ledger,
                    resume=saved_cp['cp'],
                )
                self.assertEqual(ep['checkpoint']['reason'], 'ALL_ITEMS_PLACED')
                self.assertEqual(ep['summary']['placed_items'], 1)
                self.assertEqual(len(transport.bodies), sends_before)  # no resend
                self.assertEqual(len(monitor_calls), 1)  # assessed exactly once total
                if expect_monitor_reuses:
                    self.assertEqual(monitors_before, 1)
                    place_ev = next(e for e in ep['events'] if e['event'] == 'PLACE')
                    self.assertEqual(place_ev['monitor_result_reuses'], 1)

        # B. UNKNOWN_SEND stops immediately and never implicitly retries on replay
        assess_u, monitor_calls_u = _make_monitor_double(self.snapshot)
        with tempfile.TemporaryDirectory() as td, patch.object(exact_adapter, 'assess_candidate', assess_u):
            root = Path(td)
            ledger = GeometryJevRequestLedger(root / 'req_ledger', plan_digest=digest(plan), per_job_max_sends=4, shared_max_sends=8)

            def raise_timeout(_b, _n):
                raise TimeoutError('simulated network timeout')

            t_timeout = FakeChoiceTransport(responder=raise_timeout)
            ep = run_jev_job(
                plan, 'G00', self.k01,
                monitor_snapshot=self.snapshot, admission=binding,
                root=root / 'run', transport=t_timeout, ledger=ledger,
            )
            self.assertEqual(ep['checkpoint']['reason'], 'UNKNOWN_IN_FLIGHT')
            self.assertEqual(ep['summary']['termination_class'], 'UNKNOWN_SEND')
            self.assertEqual(ep['summary']['cost']['unknown_sends'], 1)
            self.assertEqual(ep['summary']['cost']['send_reservations'], 1)
            self.assertEqual(len(t_timeout.bodies), 1)
            self.assertEqual(len(monitor_calls_u), 0)

            # Re-invoking selector on same decision must return UNKNOWN_IN_FLIGHT without retrying
            cfg = load_jev_config(plan, 'G00', monitor_snapshot=self.snapshot, admission=binding)
            sel_replay = GeometryJevSelector(cfg, ledger, 'G00', t_timeout)
            from semantic_pallet_planner.jev_select.contracts import DecisionContext
            stop_ev = next(e for e in ep['events'] if e.get('decision_id') == 'G00_D0000')
            res2 = sel_replay.select(DecisionContext.from_dict(stop_ev['context']), decision_id='G00_D0000')
            self.assertEqual(res2.data['status'], 'unknown_in_flight')
            self.assertEqual(len(t_timeout.bodies), 1)

    def test_identity_drift_rejected_and_gp5_v17_gates_unchanged(self):
        # Default EMS and explicit E2 intact
        self.assertEqual(DEFAULT_GEOMETRY_BACKEND, 'ems_surface_hybrid_v1')
        self.assertEqual(GEOMETRY_BACKENDS, ('e2_original_v1', 'ems_surface_hybrid_v1'))

        # Identity drift in v18 config rejected
        plan = prepare_jev_plan([self.k01], data_identity=DUMMY_DATA_ID, scope=GP6_DEVELOPMENT, per_job_max_sends=4, shared_max_sends=8)
        binding = development_binding(plan)
        cfg = load_jev_config(plan, 'G00', monitor_snapshot=self.snapshot, admission=binding)
        tampered = copy.deepcopy(cfg)
        tampered['per_job_max_sends'] = 2
        with self.assertRaises(JevSelectError):
            from semantic_pallet_planner.jev_select.geometry_jev_execution import preflight_jev
            preflight_jev(tampered)

        # GP5/v17 schema still rejects jev_no_memory & real model
        v17_bad = copy.deepcopy(cfg)
        v17_bad['version'] = 'jev_packaging_geometry_order_v17'
        with self.assertRaises(JevSelectError):
            validate_schema('config_v17', v17_bad)


if __name__ == '__main__':
    unittest.main()
