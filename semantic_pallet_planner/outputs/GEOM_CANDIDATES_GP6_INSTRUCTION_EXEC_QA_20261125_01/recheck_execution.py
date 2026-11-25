"""Independent execution checks. Use temporary paths and constructed responses only."""
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from semantic_pallet_planner.jev_select import instruction_probe_execution as execution
from semantic_pallet_planner.jev_select.transport import outcome


def forbidden(*args, **kwargs):
    raise AssertionError('native transport, network, or credentials forbidden')


def expect_rejection(callback, reason):
    try:
        callback()
    except Exception as error:
        assert reason in str(error), str(error)
    else:
        raise AssertionError(f'expected rejection: {reason}')


class Substitute:
    origin = 'test_double'

    def __init__(self, plan, *, unknown_at=None):
        self.plan = plan
        self.unknown_at = unknown_at
        self.calls = 0

    def complete(self, body):
        self.calls += 1
        slot = self.plan['slots'][self.calls - 1]
        ledger = execution.read(execution.RUN / 'requests.json')
        assert ledger['reservations'] == self.calls
        assert ledger['rows'][self.calls - 1]['status'] == 'SENDING'
        assert body == execution.read(execution.probe.OUTPUT / slot['request']['path'])
        if self.calls == self.unknown_at:
            return outcome('UNKNOWN_IN_FLIGHT', error='NETWORK_OUTCOME_UNKNOWN',
                           network_attempted=True)
        options = body['questions']['next_action']['criteria']
        label = next(iter(options))
        answer = {'type': 'choice', 'choice': label, 'confidence': 1,
                  'probabilities': {key: int(key == label) for key in options}}
        return outcome('OK', json.dumps({'model': body['model'],
                       'answers': {'next_action': answer}}).encode(), http_status=200)


def setup(root):
    plan = execution.prepare(root / 'package')
    auth = execution.read(root / 'package' / 'authorization.pending.json')
    auth.update(status='AUTHORIZED', authorization_id='QA_SUBSTITUTE_ONLY',
                approval_reference='temporary fixture, no real authorization')
    return plan, auth


def main():
    package = execution.PACKAGE
    plan = execution.read(package / 'execution_plan.json')
    manifest = execution.read(package / 'manifest.json')
    for name, info in manifest['files'].items():
        assert execution.sha(name) == info['sha256']
        assert Path(name).stat().st_size == info['bytes']
    receipt = execution.read(package / 'offline_receipt.json')
    pending = execution.read(package / 'authorization.pending.json')
    summary = execution.read(package / 'summary.json')
    digest = execution.digest(plan)
    assert pending['status'] == 'PENDING' and pending['authorization_id'] is None
    assert digest == pending['plan_digest'] == summary['plan_digest'] == receipt['execution_plan_digest']
    assert len(plan['slots']) == 18 and plan['max_reservations'] == 18
    assert not execution.RUN.exists()

    with (tempfile.TemporaryDirectory() as tmp,
          patch.object(execution.JevTransport, 'complete', forbidden),
          patch('semantic_pallet_planner.jev_select.transport.credential', forbidden),
          patch('urllib.request.OpenerDirector.open', forbidden)):
        _, contexts, bodies = execution.preflight(plan)
        assert len(contexts) == 3 and len(bodies) == 9
        expect_rejection(lambda: execution.validate_authorization(plan, pending),
                         'missing_authorization')
        root = Path(tmp)
        with patch.object(execution, 'RUN', root / 'run_ok'):
            local_plan, auth = setup(root / 'case_ok')
            invalid_auth = dict(auth, plan_digest='invalid')
            expect_rejection(lambda: execution.execute(local_plan, invalid_auth,
                             transport_factory=forbidden), 'authorization_plan_mismatch')
            changed = copy.deepcopy(local_plan)
            changed['slots'].reverse()
            expect_rejection(lambda: execution.execute(changed, auth,
                             transport_factory=forbidden), 'execution_slots_changed')
            assert not execution.RUN.exists()
            execution.RUN.mkdir()
            with execution.exclusive(execution.RUN):
                expect_rejection(lambda: execution.execute(local_plan, auth,
                                 transport_factory=forbidden), 'experiment_locked')
            transport = Substitute(local_plan)
            ledger = execution.execute(local_plan, auth, transport_factory=lambda: transport)
            assert ledger['status'] == 'FINISHED' and ledger['reservations'] == transport.calls == 18
            assert all(row['status'] == 'selected' for row in ledger['rows'])
            expect_rejection(lambda: execution.execute(local_plan, auth,
                             transport_factory=forbidden), 'authorization_already_started')

        with patch.object(execution, 'RUN', root / 'run_unknown'):
            local_plan, auth = setup(root / 'case_unknown')
            transport = Substitute(local_plan, unknown_at=2)
            ledger = execution.execute(local_plan, auth, transport_factory=lambda: transport)
            assert ledger['status'] == 'STOPPED_UNKNOWN_SEND'
            assert transport.calls == ledger['reservations'] == 2
            assert ledger['rows'][1]['status'] == 'UNKNOWN_SEND'
            assert sum(row['status'] == 'NOT_RUN' for row in ledger['rows']) == 16

        with patch.object(execution, 'RUN', root / 'run_error'):
            local_plan, auth = setup(root / 'case_error')
            transport = Substitute(local_plan)
            with patch.object(execution, 'parse_response', side_effect=RuntimeError('QA fixture')):
                ledger = execution.execute(local_plan, auth, transport_factory=lambda: transport)
            stats = execution.read(execution.RUN / 'statistics.json')
            assert ledger['status'] == 'STOPPED_ERROR' and transport.calls == 1
            assert ledger['rows'][0]['status'] == 'ERROR' and 'transport' in ledger['rows'][0]
            planned = sum(g['planned'] for g in stats['groups'].values())
            accounted = sum(sum(g['statuses'].values()) for g in stats['groups'].values())
            assert (planned, accounted) == (18, 17)

    assert not execution.RUN.exists()
    print(json.dumps({'plan_digest': digest, 'frozen_entries': len(plan['frozen_files']),
                      'delivery_manifest_files': len(manifest['files']), 'preflight': 'PASS',
                      'gates': ['pending_authorization', 'wrong_digest', 'slot_order',
                                'concurrent_lock', 'duplicate_launch'],
                      'completed_substitute_slots': 18, 'unknown_stop_at': 2,
                      'internal_error_summary': {'planned': planned,
                                                 'accounted': accounted, 'status': 'FAIL'},
                      'pytest': 'NOT_RUN_MISSING_DEPENDENCY', 'real_dispatches': 0},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
