"""Check Git evidence and exercise only the offline plan/ledger budget gateways."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from unittest.mock import patch

TARGET = 'f3eab7b083e9052447dc6679d3c74681c749ba2b'
BASE = '3504604232508fb2e842e3a64de75d449bbb0429'
SOURCE = Path('semantic_pallet_planner/src/semantic_pallet_planner')
O = Path('semantic_pallet_planner/outputs')
DEV = O / 'GEOM_CANDIDATES_GP6_F0_BUDGET_REC_FIX_20261121_01'
PRIOR = O / 'GEOM_CANDIDATES_GP6_F0_EVIDENCE_APPLICABILITY_QA_20261121_01'
HIST = O / 'GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01'


def git(*args):
    return subprocess.check_output(['git', *map(str, args)])


def read(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(',', ':'), allow_nan=False).encode())


def tracked(commit, path):
    return git('show', f'{commit}:{path}')


def included(path):
    return path.suffix in ('.py', '.json') and not {'tests', '__pycache__'}.intersection(path.parts)


def inspect_source():
    with tarfile.open(fileobj=io.BytesIO(git('archive', TARGET, SOURCE))) as tar:
        tracked_hashes = {}
        for member in tar.getmembers():
            if member.isfile():
                rel = Path(member.name).relative_to(SOURCE)
                if included(rel):
                    tracked_hashes[rel.as_posix()] = sha(tar.extractfile(member).read())
    local = {p.relative_to(SOURCE).as_posix(): sha(p.read_bytes()) for p in SOURCE.rglob('*')
             if p.is_file() and included(p.relative_to(SOURCE))}
    identity = read(DEV / 'source_identity.json')
    assert local == tracked_hashes == identity['files']
    assert digest(local) == identity['source_identity']
    historic = read(HIST / 'source_manifest.json')
    prior_rows = read(PRIOR / 'source_delta_review.json')['changes']
    old = historic['files']
    rows = [{'path': p, 'before': old.get(p), 'after': local.get(p)}
            for p in sorted(old.keys() | local.keys()) if old.get(p) != local.get(p)]
    assert len(rows) == len(prior_rows) == 28
    assert [(d['path'], d['before']) for d in rows] == [(d['path'], d['before']) for d in prior_rows]
    mod = [x['path'] for x, p in zip(rows, prior_rows) if x['after'] != p['after']]
    assert mod == ['jev_select/geometry_jev_execution.py', 'jev_select/geometry_jev_protocol.py']
    assert git('diff', BASE, TARGET, '--', *(SOURCE / name for name in mod)) == (DEV / 'source_change.patch').read_bytes()
    return {'source_identity': digest(local), 'source_files': len(local), 'delta_digest': digest(rows),
            'delta_count': len(rows), 'changed_rows': mod, 'source_delta': rows}


def inspect_archives():
    files = read(DEV / 'delivery_manifest.json')['files']
    for path, expected in files.items():
        assert sha(tracked(TARGET, path)) == expected
    audit = read(O / 'GEOM_CANDIDATES_GP6_F0_KERNEL_BRIDGE_FIX_20261121_01' / 'historical_readonly_audit.json')
    refs = {p: row['expected'] for p, row in audit['reference_checks'].items()}
    refs[audit['receipt_path']] = audit['receipt_sha256']
    for path, expected in refs.items():
        assert sha(Path(path).read_bytes()) == sha(tracked(TARGET, path)) == expected
    assert not git('diff', '--name-only', BASE, TARGET, '--',
                   SOURCE / 'jev_select/schemas', SOURCE / 'jev_select/stability',
                   'semantic_pallet_planner/outputs/*GP5*')
    runs = read(DEV / 'checks_and_commands.json')['runs']
    all_cases = set()
    for run in runs:
        suite = ET.parse(run['receipt']).find('testsuite')
        assert run['exit_code'] == 0
        assert all(int(suite.attrib[k]) == run[k] for k in ('tests', 'failures', 'errors', 'skipped'))
        cases = [(c.attrib['classname'], c.attrib['name']) for c in suite.findall('testcase')]
        assert [name for _, name in cases] == run['cases']
        assert not all_cases.intersection(cases)
        assert all(len(c) == 0 for c in suite.findall('testcase'))
        all_cases.update(cases)
    return {'delivery_entries': len(files), 'historical_receipt_and_references': len(refs),
            'distinct_archived_passing_cases': len(all_cases), 'archived_run_counts': [r['tests'] for r in runs]}


def check_budget():
    sys.path.insert(0, str(SOURCE.parent.resolve()))
    from semantic_pallet_planner.jev_select.contracts import JevSelectError
    from semantic_pallet_planner.jev_select.geometry_jev_protocol import prepare_jev_plan, validate_jev_plan, GP6_ORDER
    from semantic_pallet_planner.jev_select.geometry_jev_execution import (
        GeometryJevRequestLedger, validate_jev_request_ledger_binding)
    from semantic_pallet_planner.jev_select.packaging_geometry_protocol import TASK_IDS

    class NoDispatch:
        origin = 'jev'

        def complete(self, _body):
            raise AssertionError('No dispatch is allowed')

    rows = []
    tasks = [{'identity': {'task_id': task, 'origin': 'EXPOSED_TRAIN',
                           'raw_sha256': '1' * 64, 'runtime_digest': '2' * 64,
                           'normalized_digest': '3' * 64, 'adapter_digest': '4' * 64,
                           'source_group_id': 'QA_ONLY'}}
             for task in TASK_IDS]
    with tempfile.TemporaryDirectory(prefix='gp6_budget_qa_') as tmp:
        for model, shared in ((1, 2), (2, 1), (1, 1)):
            root = Path(tmp) / f'budget-{model}-{shared}'
            plan = prepare_jev_plan(tasks, data_identity=digest('QA_ONLY'), scope=GP6_ORDER,
                                    shared_max_sends=shared, request_ledger_path=str(root / 'requests.json'))
            plan = copy.deepcopy(plan)
            plan['model_calls_max'] = model
            pd = digest(plan)
            ledger = GeometryJevRequestLedger(root, plan_digest=pd, per_job_max_sends=19,
                                             shared_max_sends=shared, allow_real_transport=True)
            cfg = {'plan_digest': pd, 'per_job_max_sends': 19, 'shared_max_sends': shared,
                   'transport_evidence': 'REAL_JEV'}
            outcomes = []
            for check in (lambda: validate_jev_plan(plan),
                          lambda: validate_jev_request_ledger_binding(plan, cfg, ledger, NoDispatch(), real_authorized=True)):
                try:
                    check()
                except JevSelectError as exc:
                    assert model != shared and exc.code == 'geometry_jev_formal_budget', exc
                    outcomes.append(exc.code)
                else:
                    assert model == shared
                    outcomes.append('PASS')
            assert ledger.statistics()['send_reservations'] == 0
            rows.append({'limits': [model, shared], 'plan_and_ledger': outcomes, 'send_reservations': 0})
    return rows


def check_recovery_gate():
    # Isolate the cross-check from the common transition validator. These are
    # synthetic records for the new branch, not executable checkpoints.
    from semantic_pallet_planner.jev_select import geometry_jev_execution as execution
    from semantic_pallet_planner.jev_select.contracts import JevSelectError

    class SavedRows:
        attempt = None

        def find_attempt(self, job, decision):
            assert (job, decision) == ('G00', 'G00_D0000')
            return self.attempt

    store = object.__new__(execution.JevOrderStore)
    store.validate_request = lambda task, cfg: {'job_id': 'G00'}
    store.request_ledger = SavedRows()
    context = {'fixture': 'QA_ONLY'}
    raw_digest = '5' * 64
    base = {'source': 'jev', 'attempt_ids': ['A000001'], 'raw_response_digest': raw_digest}

    def selection(status):
        return {**base, 'status': status}

    def attempt(status, state, transport):
        sel = selection(status)
        return {'context_digest': digest(context), 'selection': sel, 'selection_digest': digest(sel),
                'state': state, 'send_started': True, 'origin': 'jev', 'attempt_id': 'A000001',
                'transport': {'status': transport, 'raw_sha256': raw_digest}}

    valid = attempt('selected', 'SELECTION_SAVED', 'OK')
    cases = [
        ('selected', selection('selected'), valid, None),
        ('invalid_response', selection('invalid_response'),
         attempt('invalid_response', 'RESPONSE_SAVED', 'OK'), None),
        ('provider_failure', selection('provider_failure'),
         attempt('provider_failure', 'FAILED', 'PROVIDER_FAILURE'), None),
        ('saved_unknown', selection('unknown_in_flight'),
         attempt('unknown_in_flight', 'UNKNOWN_SEND', 'UNKNOWN_IN_FLIGHT'), None),
        ('missing_selection', selection('selected'), {**valid, 'selection': None},
         'geometry_jev_missing_ledger_selection'),
        ('wrong_digest', selection('selected'), {**valid, 'selection_digest': '0' * 64},
         'geometry_jev_ledger_selection_drift'),
        ('wrong_state', selection('selected'), {**valid, 'state': 'RESPONSE_SAVED'},
         'geometry_jev_ledger_selection_state_drift'),
        ('singleton', {'source': 'singleton'}, None, None),
        ('budget_no_send', selection('budget_exhausted'), None, None),
        ('ledger_ahead', None, valid, None),
        ('unresolved_unknown', None, {'state': 'UNKNOWN_SEND'}, 'geometry_jev_recovery_unknown_send_blocked'),
    ]
    outputs = {}
    with patch.object(execution, '_validate_saved_transitions') as common_validation:
        for name, sel, row, expected in cases:
            store.request_ledger.attempt = row
            cp = {'events': [], 'pending_event': {'decision_id': 'G00_D0000',
                                                  'selection': sel, 'context': context}}
            try:
                assert execution.validate_jev_saved_checkpoint(cp, {}, {}, 'G00', 'jev_no_memory', store) is cp
            except JevSelectError as exc:
                assert exc.code == expected, exc
                outputs[name] = exc.code
            else:
                assert expected is None, name
                outputs[name] = 'PASS'
        assert common_validation.call_count == len(cases)
    return outputs


if __name__ == '__main__':
    print(json.dumps({'target': TARGET, **inspect_source(), **inspect_archives(),
                      'local_budget_gateway_cases': check_budget(),
                      'local_recovery_cross_check_only': check_recovery_gate(),
                      'original_pytest': 'NOT_RUN', 'business_execution': 'NOT_RUN'},
                     ensure_ascii=False, indent=2))
