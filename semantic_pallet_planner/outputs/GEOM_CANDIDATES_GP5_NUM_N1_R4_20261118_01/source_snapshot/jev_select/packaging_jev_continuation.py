"""JM1-A2 constructed continuation; injected transport, no credential loader.

A1 binding bytes remain parents. Fresh execution roots only; stage recovery and
repeat slots are deliberately rejected until A3. No real execution admission.
"""
from __future__ import annotations

import copy
from pathlib import Path

from .contracts import DecisionContext, digest, validate_schema
from .ledger import exclusive, read, write
from .packaging_jev_forks import require, seal, check_seal, validate_start, validate_binding
from .packaging_remote import RequestLedger, PackagingRemoteSelector
from .packaging_versions import JM_CONTINUATION_VERSION


def policy(config):
    from .experiment import source_manifest
    from importlib.metadata import version
    import platform
    return {'version': 'jev_jm_no_memory_policy_v1', 'selector': 'jev_no_memory',
            'config_digest': digest(config), 'source_identity': digest(source_manifest()),
            'runtime_identity': copy.deepcopy(config['runtime_identity']),
            'model': config['model'], 'prompt_version': config['prompt_version'],
            'memories': [], 'retrieval': 'FORBIDDEN', 'retries': 0,
            'seed_support': 'UNKNOWN', 'python': platform.python_version(),
            'dependencies': {name: version(name) for name in ('jsonschema', 'numpy', 'scipy')}}


def freeze_execution(binding, *, max_sends):
    task, config = validate_start(binding['start'])
    validate_binding(binding, task, config, binding['branch_id'])
    require(binding['start']['evidence_scope'] == 'CONSTRUCTED_ONLY', 'jm_A2_constructed_only')
    # v12's MemoryDriver is intentionally not an A2 no-retrieval route. Future
    # real v3 execution needs an independently frozen protocol/admission.
    require(config['version'] == 'jev_packaging_remote_v6' and config['selector'] == 'jev_no_memory',
            'jm_A2_no_memory_envelope_required')
    remaining = len(task['items']) - binding['start']['snapshot']['state']['placed_count'] - 1
    require(type(max_sends) is int and 0 <= max_sends <= remaining, 'jm_A2_budget_invalid')
    value = seal({'version': JM_CONTINUATION_VERSION, 'scope': 'CONSTRUCTED_ONLY',
                  'binding': copy.deepcopy(binding), 'binding_digest': digest(binding),
                  'branch_id': binding['branch_id'], 'task_digest': digest(task),
                  'config_digest': digest(config), 'policy': policy(config),
                  'policy_digest': digest(policy(config)), 'max_sends': max_sends})
    validate_schema('jm_continuation_v1', value)
    return value


def validate_execution(value):
    """Saved-byte/identity validation only: no generation, model or solver."""
    validate_schema('jm_continuation_v1', value); check_seal(value)
    expected = freeze_execution(value['binding'], max_sends=value['max_sends'])
    require(value == expected, 'jm_A2_execution_changed')
    return validate_start(value['binding']['start'])


class ContinuationLedger(RequestLedger):
    ledger_version = 'jev_jm_continuation_requests_v1'

    def __init__(self, root, execution, *, hook=None):
        self.execution = copy.deepcopy(execution)
        self.task, self.config = validate_execution(execution)
        root = Path(root); root.mkdir(parents=True, exist_ok=True)
        with exclusive(root):
            anchor = root / 'execution.json'
            if anchor.exists():
                require(read(anchor) == execution, 'jm_A2_execution_anchor_changed')
            else:
                require(not (root / 'requests.json').exists(), 'jm_A2_missing_execution_anchor')
                write(anchor, execution)
        super().__init__(root, max_sends=execution['max_sends'], hook=hook)

    def _load(self):
        require(read(self.root / 'execution.json') == self.execution, 'jm_A2_execution_anchor_changed')
        data = super()._load()
        for row in data['requests']:
            context = DecisionContext.from_dict(read(self.root / 'contexts' / (row['decision_id'] + '.json')))
            self.check_context(context, row['job_id'], row['decision_id'])
            require(row['origin'] == 'test_double' and row['model'] == self.config['model'], 'jm_A2_request_origin_changed')
            require(read(self.root / 'reservations' / (row['decision_id'] + '.json')) ==
                    self.reservation(context, row['job_id'], row['decision_id']), 'jm_A2_reservation_changed')
            require(all(row[k] == v for k, v in self.identity(context, row['job_id'], row['decision_id']).items()),
                    'jm_A2_saved_context_changed')
        return data

    def check_context(self, context, job_id, decision_id):
        from .context import validate_context
        validate_context(context, config=self.config)
        require(job_id == self.execution['branch_id'] and decision_id.startswith(job_id + '_D') and
                '/' not in decision_id and '\\' not in decision_id, 'jm_A2_branch_changed')
        body = context.data['request_body']
        require(body is not None and body['state']['memories'] == [] and
                context.data['model_state']['memories'] == [], 'jm_A2_body_memory_forbidden')
        require(not any(k in context.data for k in ('memory_view', 'retrieval_receipt', 'retrieval')),
                'jm_A2_retrieval_forbidden')
        self.identity(context, job_id, decision_id)

    def reservation(self, context, job_id, decision_id):
        return {'version': 'jev_jm_request_reservation_v1', 'unit': 'JM1-A2',
                'allocation_id': 'A2_CONSTRUCTED_ONLY_NO_HISTORICAL_BUDGET',
                'execution_digest': digest(self.execution), 'branch_id': self.execution['branch_id'],
                'job_id': job_id, 'decision_id': decision_id,
                'policy_digest': self.execution['policy_digest'], 'model': self.config['model'],
                **self.identity(context, job_id, decision_id)}

    def request(self, context, job_id, decision_id, transport):
        self.check_context(context, job_id, decision_id)
        require(transport is not None and transport.origin == 'test_double' and
                getattr(transport, 'scope', None) == 'CONSTRUCTED_FAKE_TRANSPORT',
                'jm_A2_fake_transport_required')
        # Persist full final body/context before even the INTENT reservation.
        path = self.root / 'contexts' / (decision_id + '.json')
        with exclusive(self.root):
            self._load()
            if path.exists():
                require(read(path) == context.data, 'jm_A2_context_overwrite')
            else:
                write(path, context.data)
            reservation_path = self.root / 'reservations' / (decision_id + '.json')
            reservation = self.reservation(context, job_id, decision_id)
            if reservation_path.exists():
                require(read(reservation_path) == reservation, 'jm_A2_reservation_changed')
            else:
                write(reservation_path, reservation)
        return super().request(context, job_id, decision_id, transport)

    def admit_request(self, job_id, decision_id):
        require(not any(r['state'] in ('SENDING', 'UNKNOWN_SEND', 'FAILED') or
                        (r['selection'] is not None and r['selection']['status'] != 'selected')
                        for r in self.data['requests']), 'jm_A2_execution_stopped')

    def admit_send(self, row):
        require(row['origin'] == 'test_double', 'jm_A2_real_send_forbidden')
        context = DecisionContext.from_dict(read(self.root / 'contexts' / (row['decision_id'] + '.json')))
        self.check_context(context, row['job_id'], row['decision_id'])
        require(all(row[k] == v for k, v in self.identity(context, row['job_id'], row['decision_id']).items()),
                'jm_A2_send_identity_changed')


def selector_factory(execution, *, ledger, transport):
    _, config = validate_execution(execution)
    require(type(ledger) is ContinuationLedger and ledger.execution == execution, 'jm_A2_ledger_binding')
    require(transport is not None and transport.origin == 'test_double' and
            getattr(transport, 'scope', None) == 'CONSTRUCTED_FAKE_TRANSPORT', 'jm_A2_fake_transport_required')
    return PackagingRemoteSelector(config, ledger, execution['branch_id'], transport)


def validate_route(execution, task, config, job_id, selector):
    saved_task, saved_config = validate_execution(execution)
    require(task == saved_task and config == saved_config and job_id == execution['branch_id'],
            'jm_A2_route_identity_changed')
    require(type(selector) is PackagingRemoteSelector and type(selector.ledger) is ContinuationLedger and
            selector.ledger.execution == execution and selector.config == config and selector.job_id == job_id,
            'jm_A2_selector_route_changed')
    require(selector.transport.origin == 'test_double' and
            getattr(selector.transport, 'scope', None) == 'CONSTRUCTED_FAKE_TRANSPORT', 'jm_A2_fake_transport_required')


def run_continuation(execution, *, root, transport, on_checkpoint=None):
    task, config = validate_execution(execution)
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    # A persistent activation marker rejects accidental restart even after an
    # exception. This is conservative stopping, not full A3 recovery/dedup.
    with exclusive(root):
        require(not (root / 'activation.json').exists(), 'jm_A2_resume_not_implemented_A3')
        require(not (root / 'ledger').exists() and not (root / 'stages').exists(), 'jm_A2_fresh_root_required')
        write(root / 'activation.json', execution)
    ledger = ContinuationLedger(root / 'ledger', execution)
    selector = selector_factory(execution, ledger=ledger, transport=transport)
    saved = []
    def persist(cp):
        saved.append(cp['phase'])
        write(root / 'stages' / f'{len(saved):04d}_{cp["phase"]}.json', cp)
        if on_checkpoint: on_checkpoint(copy.deepcopy(cp))
    from .episode import run_episode
    episode = run_episode(task, selector, config, job_id=execution['branch_id'], method='jev_no_memory',
                          training_fork=execution, on_checkpoint=persist)
    write(root / 'episode.json', episode)
    rows = ledger._load()['requests']
    selections = [e['selection'] for e in episode['events'] if e.get('selection')]
    counts = {'scope': 'CONSTRUCTED_FAKE_TRANSPORT_MONITOR_STUB',
              'forced_actions': sum(s['source'] == 'FORCED_FROM_FROZEN_POOL' for s in selections),
              'singleton_actions': sum(s['source'] == 'singleton' for s in selections),
              'constructed_requests': sum(r['send_started'] for r in rows),
              'constructed_selected_actions': sum(s['source'] == 'test_double' and s['status'] == 'selected' for s in selections),
              'real_model_calls': 0, 'unknown_sends': sum(r['state'] == 'UNKNOWN_SEND' for r in rows),
              'commits': sum(e['event'] == 'PLACE' for e in episode['events']),
              'monitored_actions': sum(e.get('monitor') is not None for e in episode['events']),
              'model_cost_usd': 'NOT_APPLICABLE_CONSTRUCTED'}
    write(root / 'counts.json', counts)
    return episode


def validate_saved_execution(root):
    """Read-only saved fact validation; never resumes or reconstructs a pool."""
    root = Path(root)
    execution = read(root / 'activation.json')
    task, config = validate_execution(execution)
    ledger = ContinuationLedger.__new__(ContinuationLedger)
    ledger.root = root / 'ledger'; ledger.path = ledger.root / 'requests.json'
    ledger.execution = execution; ledger.task = task; ledger.config = config
    ledger.max_sends = execution['max_sends']
    rows = ledger._load()['requests']
    episode = read(root / 'episode.json')
    require(episode['job_id'] == execution['branch_id'], 'jm_A2_saved_job_changed')
    for path in sorted((root / 'stages').glob('*.json')):
        cp = read(path)
        validate_schema('checkpoint_v6', cp)
        require(cp['record_digest'] == digest({k:v for k,v in cp.items() if k != 'record_digest'}),
                'jm_A2_checkpoint_changed')
        require(cp['job_id'] == execution['branch_id'] and cp['task_digest'] == digest(task) and
                cp['config_digest'] == digest(config), 'jm_A2_saved_stage_identity_changed')
    require(episode['checkpoint'] == cp and episode['events'] == cp['events'] and
            episode['final_state'] == cp['state'], 'jm_A2_saved_episode_changed')
    selections = [e['selection'] for e in episode['events'] if e.get('selection')]
    require(sum(s['source'] == 'FORCED_FROM_FROZEN_POOL' for s in selections) == 1,
            'jm_A2_saved_forced_count_changed')
    return {'version':'jev_jm_saved_continuation_check_v1', 'requests':len(rows),
            'states':[r['state'] for r in rows], 'scope':'SAVED_FACTS_ONLY_NOT_RESUME'}
