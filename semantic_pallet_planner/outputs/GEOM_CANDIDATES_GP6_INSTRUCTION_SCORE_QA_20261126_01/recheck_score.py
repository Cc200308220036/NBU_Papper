"""Read original evidence and exercise the formal error path with a local substitute."""
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from semantic_pallet_planner.jev_select import instruction_probe_execution as execution
from semantic_pallet_planner.jev_select.transport import outcome

DELIVERY = Path('semantic_pallet_planner/outputs/GP6_INSTRUCTION_PROBE_EXEC_SCORE_FIX_20261126_01')
SCORE_SOURCE = 'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/instruction_probe.py'


def forbid(*args, **kwargs):
    raise AssertionError('native transport, networking and credentials are disabled')


def rollup(stats):
    counts = Counter()
    for group in stats['groups'].values():
        counts.update(group['statuses'])
    return {key: count for key, count in counts.items() if count}


class Substitute:
    origin = 'test_double'
    calls = 0

    def complete(self, body):
        self.calls += 1
        ledger = execution.read(execution.RUN / 'requests.json')
        assert ledger['reservations'] == 1 and ledger['rows'][0]['status'] == 'SENDING'
        return outcome('OK', b'{}', http_status=200)


def main():
    manifest = execution.read(DELIVERY / 'manifest.json')
    for name, item in manifest['files'].items():
        raw = Path(name).read_bytes()
        assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256']
    receipt = execution.read(DELIVERY / 'offline_receipt.json')
    handoff = execution.read(DELIVERY / 'handoff.json')
    plan_path = DELIVERY / 'pending_execution/execution_plan.json'
    plan = execution.read(plan_path)
    old_plan = execution.read(execution.PACKAGE / 'execution_plan.json')
    assert execution.digest(plan) == manifest['execution_plan_digest'] == handoff['execution_plan_digest']
    changes = {key for key in plan if plan[key] != old_plan[key]}
    assert changes == {'frozen_files'}
    old_files, new_files = old_plan['frozen_files'], plan['frozen_files']
    assert old_files.keys() == new_files.keys()
    assert {key for key in new_files if new_files[key] != old_files[key]} == {SCORE_SOURCE}
    assert handoff['real_jev_calls'] == 0
    pending = execution.read(DELIVERY / 'pending_execution/authorization.pending.json')
    assert pending['status'] == 'PENDING' and pending['plan_digest'] == execution.digest(plan)
    assert not execution.RUN.exists()
    expected = {'NOT_RUN': 17, 'ERROR': 1}
    before = execution.read(DELIVERY / 'offline/before/run/statistics.json')
    after = execution.read(DELIVERY / 'offline/after/run/statistics.json')
    assert rollup(before) == {'NOT_RUN': 17}
    assert rollup(after) == expected

    with (tempfile.TemporaryDirectory() as tmp,
          patch.object(execution.JevTransport, 'complete', forbid),
          patch('semantic_pallet_planner.jev_select.transport.credential', forbid),
          patch('urllib.request.OpenerDirector.open', forbid)):
        _, contexts, bodies = execution.preflight(plan)
        assert (len(contexts), len(bodies), len(plan['slots'])) == (3, 9, 18)
        try:
            execution.validate_authorization(plan, pending)
        except ValueError as error:
            assert str(error) == 'missing_authorization'
        else:
            raise AssertionError('Pending authorization accepted')
        root = Path(tmp)
        substitute = Substitute()
        with patch.object(execution, 'RUN', root / 'run'):
            local_plan = execution.prepare(root / 'prepared')
            local_auth = execution.read(root / 'prepared/authorization.pending.json')
            local_auth.update(status='AUTHORIZED', authorization_id='LOCAL_SUBSTITUTE',
                              approval_reference='fixture only; no authorization for real calls')

            def parser_error(*args):
                ledger = execution.read(execution.RUN / 'requests.json')
                assert ledger['rows'][0]['status'] == 'RESPONSE_SAVED'
                raise RuntimeError('local substitute parser failure')

            with patch.object(execution, 'parse_response', parser_error):
                ledger = execution.execute(local_plan, local_auth, transport_factory=lambda: substitute)
            stats = execution.read(execution.RUN / 'statistics.json')
            assert ledger['status'] == 'STOPPED_ERROR' and substitute.calls == ledger['reservations'] == 1
            assert Counter(row['status'] for row in ledger['rows']) == expected
            assert ledger['rows'][0]['transport']['http_status'] == 200
            assert rollup(stats) == expected
            assert all(sum(g['statuses'].values()) == 6 and not g['valid']
                       and g['adherence'] is None for g in stats['groups'].values())
            assert len(stats['pairs']) == 6 and not any(p['valid'] for p in stats['pairs'])
            try:
                execution.execute(local_plan, local_auth, transport_factory=forbid)
            except ValueError as error:
                assert str(error) == 'authorization_already_started'
            else:
                raise AssertionError('Duplicate launch accepted')

    assert not execution.RUN.exists()
    print(json.dumps({'status':'PASS', 'plan_digest':execution.digest(plan),
                      'manifest_files':len(manifest['files']), 'frozen_entries':len(new_files),
                      'changed_runtime_files':[SCORE_SOURCE], 'preflight':'PASS',
                      'real_authorization':'PENDING_REJECTED', 'fixture_status':ledger['status'],
                      'fixture_ledger_and_summary':expected, 'slots_per_condition':6,
                      'planned_pairs':len(stats['pairs']), 'duplicate_rejected':True,
                      'real_dispatches':0, 'pytest':'NOT_RUN_MISSING_DEPENDENCY'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
