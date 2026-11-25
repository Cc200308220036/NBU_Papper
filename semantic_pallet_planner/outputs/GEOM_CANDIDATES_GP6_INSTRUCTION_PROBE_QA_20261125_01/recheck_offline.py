"""Reproduce the preparation and selected receipt checks with no network."""
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from semantic_pallet_planner.jev_select import instruction_probe as probe
from semantic_pallet_planner.jev_select.transport import outcome


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Substitute:
    origin = 'test_double'

    def __init__(self, plan, stop_at=None):
        self.plan = plan
        self.stop_at = stop_at
        self.calls = 0

    def complete(self, body):
        slot = self.plan['slots'][self.calls]
        self.calls += 1
        if self.calls == self.stop_at:
            return outcome('UNKNOWN_IN_FLIGHT', error='NETWORK_OUTCOME_UNKNOWN',
                           network_attempted=True)
        groups = self.plan['states'][slot['state']]['groups']
        side = 'other' if slot['condition'] == 'original' else slot['condition']
        label = groups[side][0]
        labels = body['questions']['next_action']['criteria']
        answer = {'choice': label, 'type': 'choice', 'confidence': 1,
                  'probabilities': {key: int(key == label) for key in labels}}
        return outcome('OK', json.dumps({'model': body['model'],
                       'answers': {'next_action': answer}}).encode(), http_status=200)


def forbid(*args, **kwargs):
    raise AssertionError('real transport or credential access forbidden')


def main():
    archived = probe.OUTPUT
    plan = read(archived / 'plan.json')
    receipt = read(archived / 'offline_receipt.json')
    assert receipt['plan_digest'] == probe.digest(plan)
    assert receipt['source_sha256'] == sha(probe.SOURCE) == plan['source_sha256']
    assert receipt['source_code_sha256'] == sha(Path(probe.__file__))
    assert receipt['test_sha256'] == sha(Path(
        'semantic_pallet_planner/tests/unit/test_gp6_instruction_probe.py'))
    assert plan['status'] == 'PREPARED_NOT_AUTHORIZED' and plan['real_calls'] == 0
    archived_events = {event['decision_id']: event['context'] for event in
                       read(probe.SOURCE)['events'] if event.get('context')}
    expected = (('original', 'left', 'right'), ('left', 'right', 'original'),
                ('right', 'original', 'left'))
    counts = {}
    for index, (state, spec) in enumerate(plan['states'].items()):
        context = read(archived / 'contexts' / f'{state}.json')
        assert context == archived_events[state]
        assert spec['context_digest'] == probe.digest(context)
        assert spec['mapping_digest'] == probe.digest(context['display_mapping'])
        assert spec['criteria_digest'] == probe.digest(context['criteria'])
        order = expected[index]
        assert [s['condition'] for s in plan['slots'] if s['state'] == state] == [
            *order, *reversed(order)]
        groups = dict(left=[], right=[], other=[])
        original = context['request_body']
        for label, option in original['questions']['next_action']['criteria'].items():
            x = option['pose']['x_mm']
            half = option['oriented_size_mm'][0] / 2
            left, right = abs(x - half + 600) <= 1e-6, abs(x + half - 600) <= 1e-6
            assert not (left and right)
            groups['left' if left else 'right' if right else 'other'].append(label)
        assert groups == {k: v for k, v in spec['groups'].items() if k != 'both'}
        counts[state] = {k: len(v) for k, v in groups.items()}
        for condition, item in spec['requests'].items():
            path = archived / item['path']
            assert sha(path) == item['sha256'] and path.stat().st_size == item['bytes']
            actual = read(path)
            question = actual['questions']['next_action']
            base = original['questions']['next_action']['instructions']
            assert question['instructions'] == item['instructions']
            if condition == 'original':
                assert question['instructions'] == base
            else:
                edge = 'minimum' if condition == 'left' else 'maximum'
                assert question['instructions'] == (
                    base + f'\nFor this decision, you must choose an offered action whose box '
                    f'touches the {condition} pallet edge ({edge} X). '
                    'Return exactly one of the provided Cxx labels.')
            question['instructions'] = base
            assert actual == original
    checks = {'obey': (18, 'selected'), 'wrong': (18, 'selected'),
              'failure': (18, 'provider_failure'), 'invalid': (18, 'invalid_response'),
              'unknown': (1, 'UNKNOWN_SEND'), 'raise': (1, 'UNKNOWN_SEND')}
    for name, (count, status) in checks.items():
        folder = archived / 'offline_evidence' / name
        ledger = read(folder / 'ledger.json')
        stats = read(folder / 'statistics.json')
        assert ledger['origin'] == 'test_double' and ledger['real_calls'] == 0
        assert ledger['plan_digest'] == probe.digest(plan)
        assert len(ledger['rows']) == ledger['reservations'] == count
        assert {row['status'] for row in ledger['rows']} == {status}
        assert sum(group['statuses']['NOT_RUN'] for group in stats['groups'].values()) == 18 - count
        assert sum(pair['reversed'] for pair in stats['pairs']) == (6 if name == 'obey' else 0)
    with (tempfile.TemporaryDirectory() as tmp,
          patch.object(probe.JevTransport, 'complete', forbid),
          patch('semantic_pallet_planner.jev_select.transport.credential', forbid)):
        root = Path(tmp)
        prepared = root / 'prepared'
        fresh = probe.prepare(prepared)
        assert fresh == plan
        for path in prepared.rglob('*'):
            if path.is_file():
                assert path.read_bytes() == (archived / path.relative_to(prepared)).read_bytes()
        obey = Substitute(fresh)
        rows = probe.run_offline(fresh, root / 'pass', obey, prepared_root=prepared)
        assert len(rows) == obey.calls == 18
        assert sum(p['reversed'] for p in probe.statistics(fresh, rows)['pairs']) == 6
        unknown = Substitute(fresh, stop_at=2)
        rows = probe.run_offline(fresh, root / 'unknown', unknown, prepared_root=prepared)
        assert unknown.calls == len(rows) == 2 and rows[-1]['status'] == 'UNKNOWN_SEND'
        stats = read(root / 'unknown/statistics.json')
        assert sum(g['statuses']['NOT_RUN'] for g in stats['groups'].values()) == 16
    print(json.dumps({'status': 'PASS', 'plan_digest': probe.digest(plan),
                      'fixed_candidate_counts': counts, 'request_bodies_verified': 9,
                      'archived_substitute_scenarios_verified': list(checks),
                      'fresh_preparation': 'BYTE_EQUAL', 'fresh_substitute_success': 18,
                      'fresh_unknown_stop': 2, 'fresh_unknown_remaining_not_run': 16,
                      'real_dispatches': 0, 'pytest': 'NOT_RUN_MISSING_DEPENDENCY'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
