"""Independent physical-only complete-order state machine, durable checkpoints."""
import copy
import math
import tempfile
from pathlib import Path
from ..evaluation.geometry_oracle import check_candidate
from ..evaluation.state import apply_candidate
from .common import O5Error, atomic, digest, read
from .config import validate as validate_config
from .candidates import generate, state_for, case_for, pool_fingerprint
from .public_request import build, parse_response, image_bytes
from .schemas import validate
from .selectors import Ledger, geometry_choice, direct_choice
from .metrics import summarize


def validate_task(task, config):
    if task['container'] != config['container'] or not 14 <= len(task['items']) <= 20:
        raise O5Error('INVALID_COMPLETE_ORDER')
    ids = [i['item_id'] for i in task['items']]
    if len(ids) != len(set(ids)):
        raise O5Error('DUPLICATE_ITEM')
    for i in task['items']:
        if (i['stackable'] is not True or i['top_load_limit_kg_synthetic'] != 100.
                or type(i['mass_kg']) not in (int, float) or not 0 < i['mass_kg'] <= 100
                or set(i['dimensions_mm']) != {'length', 'width', 'height'}
                or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in i['dimensions_mm'].values())):
            raise O5Error('INVALID_PHYSICAL_ITEM')


def verify_journal(journal, task, placed, cursor, config, nonce, job_id, directory):
    validate('DecisionJournal', journal)
    current = task['items'][cursor]
    pool, _ = generate(task['container'], placed, current, cursor, config)
    with tempfile.TemporaryDirectory(prefix='o5-rebuild-') as tmp:
        rebuilt, mapping = build(task['container'], placed, current, pool, config, [nonce, job_id, cursor], Path(tmp))
    if (rebuilt != journal['request'] or mapping != journal['private_mapping'] or placed != journal['before']
            or pool_fingerprint(pool) != journal['pool_fingerprint']):
        raise O5Error('JOURNAL_REBUILD_MISMATCH')
    from .public_request import envelope
    envelope(journal['request'], directory, config)
    response = journal['response']
    expected = copy.deepcopy(placed)
    proposal = None
    errors = []
    if response is not None:
        response = parse_response(response, rebuilt)
        if response['action'] == 'PLACE':
            proposal = mapping[response['candidate_id']]
            case = case_for(state_for(task['container'], placed, current, cursor))
            errors = check_candidate(case, {'container': task['container']}, proposal)
            if not errors:
                expected = apply_candidate(case, proposal)
    if proposal != journal['proposed_candidate'] or errors != journal['physical_errors']:
        raise O5Error('JOURNAL_PROPOSAL_CHANGED')
    committed = proposal if proposal is not None and not errors else None
    if committed != journal['committed_candidate'] or expected != journal['after']:
        raise O5Error('JOURNAL_TRANSITION_CHANGED')
    expected_reason = ('NO_PHYSICAL_CANDIDATE' if not pool else
                       'MODEL_STOP' if response and response['action'] == 'STOP' else
                       'PHYSICAL_REJECTION' if errors else 'PLACED' if committed else journal['reason'])
    if journal['reason'] != expected_reason:
        raise O5Error('JOURNAL_STOP_CHANGED')
    return expected


class _MissingSavedAttempt(BaseException):
    """Replay must never turn a missing stored attempt into a fresh call."""


class _ReplayTransport:
    offline_test_double = True

    def complete(self, body):
        raise _MissingSavedAttempt()


def verify_accounting(journal, method, config, directory, ledger, job_id, attempt_limit):
    """Validate a committed prefix against durable responses before continuing it."""
    req = journal['request']
    if not req['candidates']:
        if journal['response'] is not None or journal['attempt_ids'] or journal['reason'] != 'NO_PHYSICAL_CANDIDATE':
            raise O5Error('EMPTY_POOL_ACCOUNTING_MISMATCH')
        return
    if method == 'G0':
        if journal['attempt_ids'] or journal['response'] != geometry_choice(req, journal['private_mapping']):
            raise O5Error('G0_DECISION_CHANGED')
        return
    rows = [r for r in ledger['attempts'] if r['request_digest'] == digest(req)]
    if len(rows) > 2 or journal['attempt_ids'] != [r['attempt_id'] for r in rows if r['status'] == 'completed']:
        raise O5Error('ATTEMPT_JOURNAL_MISMATCH')
    with tempfile.TemporaryDirectory(prefix='o5-ledger-verify-') as tmp:
        path = Path(tmp)/'ledger.json'
        atomic(path, ledger)
        try:
            response, ids, failure = direct_choice(req, directory, config, _ReplayTransport(),
                                                 Ledger(path, job_id, attempt_limit))
        except _MissingSavedAttempt:
            raise O5Error('MISSING_SAVED_ATTEMPT') from None
    expected_reason = failure or ('MODEL_STOP' if response['action'] == 'STOP' else
                                  'PHYSICAL_REJECTION' if journal['physical_errors'] else 'PLACED')
    if (response, ids, expected_reason) != (journal['response'], journal['attempt_ids'], journal['reason']):
        raise O5Error('DECISION_LEDGER_RECOMPUTATION_MISMATCH')


def run_episode(task, method, config, directory, job_id, nonce, *, transport=None,
                attempt_limit=40, resume=False, stop_after=None, _runtime=None):
    validate_config(config)
    validate_task(task, config)
    if method not in ('G0', 'D0') or (_runtime is None and method == 'D0' and getattr(transport, 'offline_test_double', False) is not True):
        raise O5Error('INVALID_OFFLINE_METHOD')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    checkpoint = directory/'checkpoint.json'
    identity = digest([task, method, config, job_id, nonce, attempt_limit])
    if checkpoint.exists():
        if not resume:
            raise O5Error('CHECKPOINT_EXISTS')
        cp = read(checkpoint)
        if cp['identity'] != identity:
            raise O5Error('CHECKPOINT_IDENTITY_CHANGED')
        if not (directory/'ledger.json').is_file():
            raise O5Error('MISSING_LEDGER', 'recovery cannot reset a durable attempt budget')
        placed = []
        journals = []
        terminal_seen = False
        for cursor, checksum in enumerate(cp['journal_digests']):
            if terminal_seen:
                raise O5Error('EVENT_AFTER_TERMINAL')
            j = read(directory/f'decisions/{cursor:03d}/journal.json')
            if digest(j) != checksum:
                raise O5Error('CHECKPOINT_JOURNAL_CHANGED')
            placed = verify_journal(j, task, placed, cursor, config, nonce, job_id, directory/f'decisions/{cursor:03d}')
            terminal_seen = j['reason'] != 'PLACED'
            journals.append(j)
        if placed != cp['placed'] or cp['cursor'] != sum(j['reason'] == 'PLACED' for j in journals):
            raise O5Error('CHECKPOINT_STATE_CHANGED')
        reason = cp['reason']
        if terminal_seen and reason != journals[-1]['reason']:
            raise O5Error('CHECKPOINT_TERMINATION_CHANGED')
        if not terminal_seen and reason not in (None, 'ALL_ITEMS_PLACED'):
            raise O5Error('CHECKPOINT_TERMINATION_CHANGED')
        if reason == 'ALL_ITEMS_PLACED' and len(placed) != len(task['items']):
            raise O5Error('PREMATURE_SUCCESS')
    else:
        if resume:
            raise O5Error('MISSING_CHECKPOINT')
        placed, journals, reason = [], [], None
    ledger = (_runtime.ledger if _runtime is not None else
              Ledger(directory/'ledger.json', job_id, attempt_limit if method == 'D0' else 0))
    for index, journal in enumerate(journals):
        if _runtime is not None:
            _runtime.verify(journal, method, directory/f'decisions/{index:03d}')
        else:
            verify_accounting(journal, method, config, directory/f'decisions/{index:03d}',
                              ledger.data, job_id, attempt_limit)
    known_requests = {digest(j['request']) for j in journals}
    pending_request = directory/f'decisions/{len(placed):03d}/request.json'
    if reason is None and pending_request.is_file():
        known_requests.add(digest(read(pending_request)))
    if any(row['request_digest'] not in known_requests for row in ledger.data['attempts']):
        raise O5Error('UNACCOUNTED_ATTEMPT')
    def save():
        atomic(checkpoint, {'identity': identity, 'cursor': len(placed), 'placed': placed,
                            'reason': reason, 'journal_digests': [digest(j) for j in journals]})
    save()
    while reason is None and len(placed) < len(task['items']):
        cursor = len(placed)
        current = task['items'][cursor]  # Only this arrival reaches the backend/selector.
        pool, audit = generate(task['container'], placed, current, cursor, config)
        step = directory/f'decisions/{cursor:03d}'
        # Never overwrite persisted request images when recovering a pending decision.
        if (step/'request.json').exists():
            req = read(step/'request.json')
            with tempfile.TemporaryDirectory(prefix='o5-pending-') as tmp:
                rebuilt, rebuilt_mapping = build(task['container'], placed, current, pool, config, [nonce, job_id, cursor], Path(tmp))
            if rebuilt != req:
                raise O5Error('PENDING_REQUEST_CHANGED')
            if (step/'mapping.private.json').exists():
                mapping = read(step/'mapping.private.json')
                if rebuilt_mapping != mapping:
                    raise O5Error('PENDING_REQUEST_CHANGED')
            else:
                # A legacy write gap can be repaired deterministically against
                # the intact request; no model call or candidate change occurs.
                mapping = rebuilt_mapping
                atomic(step/'mapping.private.json', mapping)
        else:
            req, mapping = build(task['container'], placed, current, pool, config, [nonce, job_id, cursor], step)
            atomic(step/'mapping.private.json', mapping)
            atomic(step/'request.json', req)
        image_bytes(req, step)
        response, attempts, failure = None, [], None
        if not pool:
            failure = 'NO_PHYSICAL_CANDIDATE'
        elif method == 'G0':
            response = geometry_choice(req, mapping)
        else:
            response, attempts, failure = (_runtime.choose(req, step) if _runtime is not None else
                                           direct_choice(req, step, config, transport, ledger))
        if failure == 'UNKNOWN_IN_FLIGHT':
            save()
            raise O5Error('UNKNOWN_IN_FLIGHT', job_id)
        before = copy.deepcopy(placed)
        proposal, committed, errors = None, None, []
        if response is not None:
            if response['action'] == 'STOP':
                failure = 'MODEL_STOP'
            else:
                proposal = mapping[response['candidate_id']]
                case = case_for(state_for(task['container'], placed, current, cursor))
                errors = check_candidate(case, {'container': task['container']}, proposal)
                if errors:
                    failure = 'PHYSICAL_REJECTION'
                else:
                    placed = apply_candidate(case, proposal)
                    committed = proposal
        journal = {'schema_version': 'o5_decision_journal_v1', 'request': req, 'private_mapping': mapping,
                   'pool_fingerprint': pool_fingerprint(pool), 'candidate_audit': audit, 'attempt_ids': attempts,
                   'response': response, 'reason': failure or 'PLACED', 'before': before, 'after': copy.deepcopy(placed),
                   'proposed_candidate': proposal, 'committed_candidate': committed, 'physical_errors': errors}
        validate('DecisionJournal', journal)
        # Reconcile a journal persisted just before a crash but not checkpointed.
        if (step/'journal.json').exists():
            old = read(step/'journal.json')
            if any(old[k] != journal[k] for k in journal if k != 'candidate_audit'):
                raise O5Error('PENDING_JOURNAL_CHANGED')
            journal = old
        else:
            atomic(step/'journal.json', journal)
        journals.append(journal)
        reason = failure
        if len(placed) == len(task['items']):
            reason = 'ALL_ITEMS_PLACED'
        save()
        if stop_after is not None and len(journals) >= stop_after and reason is None:
            return {'execution_status': 'CHECKPOINTED', 'job_id': job_id, 'placed_items': len(placed)}
    if reason is None:
        reason = 'ALL_ITEMS_PLACED'
        save()
    result = {'schema_version': 'o5_episode_result_v1', 'job_id': job_id, 'task_id': task['task_id'],
              'source_cluster_id': task['source_cluster_id'], 'method': method, 'test_double': method == 'D0',
              'summary': summarize(task, placed, reason, journals),
              'decisions': [f'decisions/{i:03d}/journal.json' for i in range(len(journals))], 'final_state': placed}
    validate('EpisodeResult', result)
    if _runtime is not None:
        result['test_double'] = _runtime.test_double
        result['summary']['result_scope'] = _runtime.result_scope
    atomic(directory/'result.json', result)
    return result


def verify_episode(task, method, config, directory, job_id, nonce, attempt_limit=40):
    """Read-only audit through the recovery path in an isolated copy, never calls a model."""
    import shutil
    original = read(Path(directory)/'result.json')
    with tempfile.TemporaryDirectory(prefix='o5-verify-') as tmp:
        copied = Path(tmp)/'job'
        shutil.copytree(directory, copied)
        rebuilt = run_episode(task, method, config, copied, job_id, nonce,
                              transport=_ReplayTransport(), attempt_limit=attempt_limit, resume=True)
    if rebuilt != original:
        raise O5Error('RESULT_RECOMPUTATION_MISMATCH')
    # Cross-check completed responses against the independently persisted attempt ledger.
    ledger = validate('BudgetLedger', read(Path(directory)/'ledger.json'))
    if ledger['job_id'] != job_id or ledger['attempt_limit'] != (attempt_limit if method == 'D0' else 0):
        raise O5Error('LEDGER_IDENTITY_CHANGED')
    for name in original['decisions']:
        journal = read(Path(directory)/name)
        verify_accounting(journal, method, config, (Path(directory)/name).parent, ledger, job_id, attempt_limit)
    referenced = {identity for name in original['decisions']
                  for identity in read(Path(directory)/name)['attempt_ids']}
    completed_ids = {row['attempt_id'] for row in ledger['attempts'] if row['status'] == 'completed'}
    request_digests = {digest(read(Path(directory)/name)['request']) for name in original['decisions']}
    if (referenced != completed_ids or any(row['request_digest'] not in request_digests or
            row['status'] in ('planned', 'sent', 'unknown') for row in ledger['attempts'])):
        raise O5Error('UNACCOUNTED_ATTEMPT')
    return {'status': 'PASS', 'decisions': len(original['decisions']), 'new_api_attempts': 0}
