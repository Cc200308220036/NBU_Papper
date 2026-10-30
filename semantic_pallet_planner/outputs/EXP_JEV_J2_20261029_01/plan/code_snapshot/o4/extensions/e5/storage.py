"""Durable atomic JSON and exclusive single-writer experiment/ledger locks."""
import contextlib
from contextvars import ContextVar
import fcntl
from functools import wraps
import json
import os
import tempfile
from pathlib import Path
from ...common import O4Error

_OUTPUT_CONTEXT = ContextVar('e5_owned_output_context', default=None)


def phase(name):
    context = _OUTPUT_CONTEXT.get()
    if context is not None:
        context['phase'] = name


def new_output(path, protected=()):
    # Register ownership only after the existing output guard has created the
    # directory. A rejected existing/concurrently-created output is never ours.
    from ..e2.experiment import new_output as create
    root = create(path, protected)
    context = _OUTPUT_CONTEXT.get()
    if context is not None:
        context['root'] = root
        context['phase'] = 'output_created'
    return root


def _optional_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _record_failure(context, error):
    root = context.get('root')
    if root is None or not root.is_dir() or (root/'delivery_manifest.json').exists():
        return
    jobs = _optional_json(root/'audit/jobs.json')
    jobs = jobs if isinstance(jobs, list) else []
    statuses = {s: sum(j.get('status') == s for j in jobs)
                for s in ('PASS', 'FAIL', 'PARTIAL', 'IN_PROGRESS', 'NOT_RUN')}
    unmaterialized = max(0, 240-len(jobs))
    ledger_path = root/'audit/ledger.json'
    ledger = _optional_json(ledger_path)
    attempts = ledger.get('attempts') if isinstance(ledger, dict) else None
    used = len(attempts) if isinstance(attempts, list) else None if ledger_path.exists() else 0
    real = 0 if isinstance(ledger, dict) and ledger.get('test_double') else used
    detail = {'operation': context['operation'], 'phase': context['phase'],
              'error_code': getattr(error, 'code', type(error).__name__), 'error': str(error),
              'expected_planned_jobs': 240, 'planned_jobs': 240, 'materialized_jobs': len(jobs),
              'unmaterialized_expected_jobs': unmaterialized,
              'not_run_jobs': statuses['NOT_RUN']+unmaterialized,
              'job_statuses': statuses, 'used_attempts': used, 'new_api_attempts': real,
              'scope': 'failure journal; no fabricated job identities or completed episodes'}
    atomic(root/'audit/initialization_error.json', detail)
    # Preserve a more specific runtime report produced by the actual scheduler.
    if not (root/'acceptance_report.json').exists():
        if not (root/'audit/jobs.json').exists():
            atomic(root/'audit/jobs.json', [])
        from . import VERSION
        recorded = sum((root/'episodes'/f"{job['job_id']}.json").is_file() for job in jobs if 'job_id' in job)
        report = {'scope': 'O4_E5_090_CURRENT_SCOPE', 'status': 'FAIL',
                  'offline_status': 'FAIL' if context['operation'] in ('prepare', 'offline-run') else 'NOT_RUN',
                  'real_compile_status': 'NOT_RUN', 'real_online_status': 'NOT_RUN',
                  'unseen_generalization': 'NOT_MEASURED', 'visual_increment': 'NOT_MEASURED',
                  'e3_status': 'DEFERRED', 'e4_status': 'OUT_OF_SCOPE',
                  'version': VERSION, 'recorded_episodes': recorded, **detail}
        atomic(root/'acceptance_report.json', report)
        if not (root/'manifest.json').exists():
            atomic(root/'manifest.json', {'version': VERSION, 'mode': 'failed_initialization',
                   'operation': context['operation'], 'current_status': 'acceptance_report.json'})
        if not (root/'README.md').exists():
            (root/'README.md').write_text('E5 failed initialization. Read acceptance_report.json and audit/initialization_error.json.\nNo completed delivery is claimed; keep this directory and use a new output for a new preparation.\n')


def record_failures(operation):
    """Journal failures only in a new directory owned by this invocation."""
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            context = {'operation': operation, 'phase': 'validating_before_output'}
            token = _OUTPUT_CONTEXT.set(context)
            try:
                return function(*args, **kwargs)
            except Exception as error:
                try:
                    _record_failure(context, error)
                except OSError as journal_error:
                    if hasattr(error, 'add_note'):
                        error.add_note('E5 failure journal could not be written: '+str(journal_error))
                raise
            finally:
                _OUTPUT_CONTEXT.reset(token)
        return run
    return decorate


def atomic(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+'\n'
    descriptor,temporary=tempfile.mkstemp(dir=path.parent,prefix='.'+path.name+'.')
    try:
        with os.fdopen(descriptor,'w') as stream:
            stream.write(payload);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        directory=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


@contextlib.contextmanager
def exclusive(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise O4Error('experiment_busy','single writer required') from None
        try:yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)
