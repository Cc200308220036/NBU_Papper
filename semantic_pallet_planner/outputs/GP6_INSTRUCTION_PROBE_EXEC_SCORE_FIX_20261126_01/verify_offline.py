"""Reproduce GP6-IP-SCORE-02 with a substitute; never dispatch native requests."""
import argparse
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from semantic_pallet_planner.jev_select import instruction_probe_execution as execution
from semantic_pallet_planner.jev_select.transport import outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('before', 'after'), required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.relative_to(Path.cwd()) / 'offline' / args.phase
    assert not root.exists(), 'preserve prior evidence; use a new directory'
    native_run = execution.RUN
    assert not native_run.exists(), 'preserve real run location'
    forbidden_calls = []

    def forbidden(*args, **kwargs):
        forbidden_calls.append('native_transport_or_credentials_or_network')
        raise AssertionError(forbidden_calls[-1])

    calls = []
    saved = outcome('OK', b'{"offline_fixture":"response_saved_before_parser_error"}',
                    http_status=200)

    class Substitute:
        origin = 'test_double'

        def complete(self, body):
            ledger = execution.read(execution.RUN / 'requests.json')
            assert ledger['reservations'] == 1 and ledger['rows'][0]['status'] == 'SENDING'
            assert not calls
            calls.append(body)
            return saved

    def parser_error(*args, **kwargs):
        observed = execution.read(execution.RUN / 'requests.json')
        assert observed['rows'][0]['status'] == 'RESPONSE_SAVED'
        assert observed['rows'][0]['transport'] == saved
        execution.write(root / 'observed_response_saved.json', observed)
        raise RuntimeError('offline parser internal error fixture')

    with (patch.object(execution, 'RUN', root / 'run'),
          patch.object(execution.JevTransport, 'complete', forbidden),
          patch('semantic_pallet_planner.jev_select.transport.credential', forbidden),
          patch('urllib.request.OpenerDirector.open', forbidden)):
        plan = execution.prepare(root / 'fixture_package')
        auth = execution.read(root / 'fixture_package' / 'authorization.pending.json')
        auth.update(status='AUTHORIZED', authorization_id='OFFLINE_SUBSTITUTE_ONLY',
                    approval_reference='test fixture only; no real authorization')
        with patch.object(execution, 'parse_response', side_effect=parser_error):
            ledger = execution.execute(plan, auth, transport_factory=Substitute)
        assert ledger == execution.read(execution.RUN / 'requests.json')
        stats = execution.read(execution.RUN / 'statistics.json')
        assert ledger['status'] == 'STOPPED_ERROR'
        assert ledger['reservations'] == len(calls) == 1
        assert Counter(r['status'] for r in ledger['rows']) == {'ERROR': 1, 'NOT_RUN': 17}
        assert ledger['rows'][0]['transport'] == saved
        assert ledger['rows'][0]['error'] == 'RESPONSE_PROCESSING_ERROR'
        totals = Counter()
        condition_totals = {}
        for condition, group in stats['groups'].items():
            totals.update(group['statuses'])
            condition_totals[condition] = sum(group['statuses'].values())
            assert group['planned'] == 6
            assert group['valid'] == 0 and group['adherence'] is None
            assert sum(group['distribution'].values()) == 0
        expected_pairs = [(state, rnd) for state in execution.read(execution.probe.OUTPUT / 'plan.json')['states']
                          for rnd in (1, 2)]
        assert [(p['state'], p['round']) for p in stats['pairs']] == expected_pairs
        assert not any(p['valid'] or p['reversed'] or p['label_changed_without_reversal']
                       for p in stats['pairs'])
        if args.phase == 'before':
            assert sum(totals.values()) == 17 and totals['ERROR'] == 0
            assert condition_totals == {'original': 5, 'left': 6, 'right': 6}
        else:
            assert {status: count for status, count in totals.items() if count} == {'ERROR': 1, 'NOT_RUN': 17}
            assert condition_totals == {'original': 6, 'left': 6, 'right': 6}
        try:
            execution.execute(plan, auth, transport_factory=forbidden)
        except ValueError as error:
            assert str(error) == 'authorization_already_started'
        else:
            raise AssertionError('duplicate launch was allowed')
        assert not forbidden_calls
        receipt = {
            'version': 'gp6_instruction_score_fix_run_receipt_v1',
            'phase': args.phase, 'origin': 'test_double',
            'status': ledger['status'], 'reservations': ledger['reservations'],
            'substitute_calls': len(calls), 'real_jev_calls': 0,
            'credentials_accessed': False, 'native_network_attempts': 0,
            'source_sha256': execution.sha(Path(execution.probe.__file__)),
            'execution_source_sha256': execution.sha(Path(execution.__file__)),
            'fixture_plan_digest': execution.digest(plan),
            'ledger_status_counts': dict(Counter(r['status'] for r in ledger['rows'])),
            'statistics_status_counts': dict(totals),
            'planned_slots': 18, 'accounted_slots': sum(totals.values()),
            'condition_accounted_slots': condition_totals, 'planned_pairs': len(stats['pairs']),
            'response_saved_before_error': True, 'duplicate_launch': 'REJECTED',
            'GP6-IP-SCORE-02': 'REPRODUCED_FAIL' if args.phase == 'before' else 'PASS',
        }
        execution.write(root / 'run_receipt.json', receipt)
    assert not native_run.exists()
    print(execution.digest(receipt), receipt['status'], receipt['GP6-IP-SCORE-02'])


if __name__ == '__main__':
    main()
