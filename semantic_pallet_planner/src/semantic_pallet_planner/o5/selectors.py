"""G0 and D0 contracts; durable attempts, one repair, no implicit fallback."""
import copy
import time
from ..planner.scoring import geometry_score
from ..o4.extensions.e2.candidates import key
from .common import O5Error, atomic, digest, read
from .schemas import validate
from .public_request import parse_response, envelope


def geometry_choice(req, mapping):
    if not mapping:
        raise O5Error('EMPTY_POOL')
    label = min(mapping, key=lambda label: (-geometry_score(mapping[label]), key(mapping[label])))
    return {'request_id': req['request_id'], 'state_hash': req['state_hash'], 'action': 'PLACE', 'candidate_id': label}


class Ledger:
    def __init__(self, path, job_id, attempt_limit):
        self.path = path
        if type(attempt_limit) is not int or attempt_limit < 0:
            raise O5Error('INVALID_BUDGET')
        if path.exists():
            self.data = validate('BudgetLedger', read(path))
            if self.data['job_id'] != job_id or self.data['attempt_limit'] != attempt_limit:
                raise O5Error('LEDGER_IDENTITY_CHANGED')
            ids = [r['attempt_id'] for r in self.data['attempts']]
            if len(ids) != len(set(ids)) or len(ids) > attempt_limit:
                raise O5Error('LEDGER_CORRUPTED')
        else:
            self.data = {'schema_version': 'o5_budget_ledger_v1', 'job_id': job_id,
                         'attempt_limit': attempt_limit, 'real_api_attempts': 0, 'test_double': True, 'attempts': []}
            self.save()

    def save(self):
        validate('BudgetLedger', self.data)
        atomic(self.path, self.data)

    def attempt(self, req, directory, config, transport, repair_error=None):
        if getattr(transport, 'offline_test_double', False) is not True:
            raise O5Error('REAL_TRANSPORT_FORBIDDEN_IN_S1')
        body = envelope(req, directory, config, repair_error)
        identity = req['request_id']+('R1' if repair_error else 'R0')
        rows = self.data['attempts']
        existing = next((r for r in rows if r['attempt_id'] == identity), None)
        if existing:
            if existing['request_digest'] != digest(req) or existing['envelope_digest'] != digest(body):
                raise O5Error('SAVED_REQUEST_CHANGED')
            if existing['status'] in ('sent', 'unknown'):
                existing['status'] = 'unknown'
                self.save()
                raise O5Error('UNKNOWN_IN_FLIGHT')
            if existing['status'] == 'failed':
                raise O5Error(existing['error'] or 'SERVICE_ERROR')
            if existing['status'] == 'completed':
                return copy.deepcopy(existing['response']), identity
            row = existing
        else:
            if len(rows) >= self.data['attempt_limit']:
                raise O5Error('BUDGET_EXHAUSTED')
            row = {'attempt_id': identity, 'request_digest': digest(req), 'repair': bool(repair_error),
                   'status': 'planned', 'envelope_digest': digest(body), 'response': None, 'error': None,
                   'latency_seconds': 0., 'usage': None, 'cost': None}
            rows.append(row)
            self.save()
        row['status'] = 'sent'
        self.save()
        started = time.perf_counter()
        try:
            response = transport.complete(copy.deepcopy(body))
        except Exception:
            # Test-double failures are definitive. A real transport is not available in S1.
            row.update(status='failed', error='SERVICE_ERROR', latency_seconds=time.perf_counter()-started)
            self.save()
            raise O5Error('SERVICE_ERROR') from None
        row.update(status='completed', response=response, latency_seconds=time.perf_counter()-started)
        self.save()
        return copy.deepcopy(response), identity


def direct_choice(req, directory, config, transport, ledger):
    attempts = []
    diagnostic = None
    for index in range(2):
        try:
            raw, identity = ledger.attempt(req, directory, config, transport, diagnostic)
        except O5Error as error:
            return None, attempts, error.code
        attempts.append(identity)
        try:
            return parse_response(raw, req), attempts, None
        except O5Error as error:
            if index:
                return None, attempts, error.code
            diagnostic = error.code  # Format/binding diagnostics only, never an answer.
    raise AssertionError('unreachable')
