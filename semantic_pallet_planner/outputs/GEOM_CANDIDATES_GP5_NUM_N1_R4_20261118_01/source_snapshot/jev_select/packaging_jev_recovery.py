"""JM1-A3 constructed recovery and preregistered independent repeat allocations.

No credentials, transport creation, candidate generation or physical replay.
The caller must retain the schedule root across invocations and processes.
"""
from __future__ import annotations

import copy
from pathlib import Path

from . import packaging_jev_continuation as a2
from .contracts import CandidateBundle, DecisionContext, digest, validate_schema
from .ledger import exclusive, read, write
from .packaging_jev_forks import require, seal, check_seal, bind_branch, bootstrap
from .packaging_remote import RequestLedger, PackagingRemoteSelector
from .packaging_versions import JM_RECOVERY_VERSION


def freeze_execution(binding, *, repeat_slot, max_sends):
    require(isinstance(repeat_slot, str) and bool(repeat_slot), 'jm_A3_invalid_slot')
    allocation = digest({'binding': binding, 'repeat_slot': repeat_slot})
    job = binding['branch_id'] + '_R' + allocation[:16]
    bound = bind_branch(binding['start'], branch_id=job, forced_display_id=binding['forced_display_id'])
    value = a2.freeze_execution(bound, max_sends=max_sends)
    value.update(version=JM_RECOVERY_VERSION, repeat_slot=repeat_slot,
                 original_branch_id=binding['branch_id'], allocation_id=allocation)
    seal(value); validate_schema('jm_recovery_v1', value)
    return value


def validate_execution(value):
    validate_schema('jm_recovery_v1', value); check_seal(value)
    original = bind_branch(value['binding']['start'], branch_id=value['original_branch_id'],
                           forced_display_id=value['binding']['forced_display_id'])
    require(value == freeze_execution(original, repeat_slot=value['repeat_slot'], max_sends=value['max_sends']),
            'jm_A3_execution_changed')
    return a2.validate_start(value['binding']['start'])


def freeze_schedule(rows, *, root):
    from . import packaging_jev_forks as jm
    storage = Path(root).resolve()
    require(storage.is_relative_to(jm.REPO.resolve()), 'jm_A3_storage_outside_repository')
    executions = [freeze_execution(r['binding'], repeat_slot=r['repeat_slot'], max_sends=r['max_sends']) for r in rows]
    value = seal({'version': 'jev_jm_repeat_schedule_v1', 'executions': executions, 'storage_root': storage.relative_to(jm.REPO.resolve()).as_posix(),
                  'total_max_sends': sum(e['max_sends'] for e in executions)})
    validate_schedule(value)
    return value


def validate_schedule(schedule):
    validate_schema('jm_repeat_schedule_v1', schedule); check_seal(schedule)
    keys = set()
    for e in schedule['executions']:
        validate_execution(e)
        key = (e['original_branch_id'], e['repeat_slot'])
        require(key not in keys, 'jm_A3_duplicate_slot'); keys.add(key)
    require(schedule['total_max_sends'] == sum(e['max_sends'] for e in schedule['executions']),
            'jm_A3_schedule_budget_changed')


class RecoveryLedger(a2.ContinuationLedger):
    ledger_version = 'jev_jm_recovery_requests_v1'

    def __init__(self, root, execution, *, hook=None):
        self.execution = copy.deepcopy(execution)
        self.task, self.config = validate_execution(execution)
        root = Path(root); root.mkdir(parents=True, exist_ok=True)
        with exclusive(root):
            anchor = root / 'execution.json'
            if anchor.exists():
                require(read(anchor) == execution, 'jm_A3_execution_anchor_changed')
                require((root / 'requests.json').exists(), 'jm_A3_missing_requests')
            else:
                require(not any(p.name != '.writer.lock' for p in root.iterdir()), 'jm_A3_missing_anchor')
                write(anchor, execution)
                # Anchor and empty ledger initialization are independently durable.
                self.root = root; self.path = root / 'requests.json'
                self._save({'version': self.ledger_version, 'max_sends': execution['max_sends'], 'requests': []})
        RequestLedger.__init__(self, root, max_sends=execution['max_sends'], hook=hook)

    def reservation(self, context, job_id, decision_id):
        value = super().reservation(context, job_id, decision_id)
        value.update(version='jev_jm_recovery_reservation_v1', unit='JM1-A3',
                     allocation_id=self.execution['allocation_id'], repeat_slot=self.execution['repeat_slot'])
        return value

    def admit_send(self, row):
        # RequestLedger calls this for BOTH new and recovered INTENTs under lock.
        self.admit_request(row['job_id'], row['decision_id'])
        require(row['state'] == 'INTENT' and row['send_started'] is False,
                'jm_A3_unsafe_send_state')
        require(sum(r['send_started'] for r in self.data['requests']) < self.max_sends,
                'jm_A3_budget_exhausted')
        validate_execution(self.execution)
        super().admit_send(row)

    def request(self, context, job_id, decision_id, transport):
        # A2's durable context/reservation checks are reused unchanged. These
        # extra hooks expose the two pre-INTENT interruption boundaries.
        def boundary_write():
            self.check_context(context, job_id, decision_id)
            path = self.root / 'contexts' / (decision_id + '.json')
            rp = self.root / 'reservations' / (decision_id + '.json')
            with exclusive(self.root):
                self._load(); self.check_context(context, job_id, decision_id)
                require(transport.origin == 'test_double' and
                        getattr(transport, 'scope', None) == 'CONSTRUCTED_FAKE_TRANSPORT',
                        'jm_A3_fake_transport_required')
                if path.exists(): require(read(path) == context.data, 'jm_A3_context_changed')
                else:
                    write(path, context.data)
                    if self.hook: self.hook('CONTEXT_SAVED', {'decision_id': decision_id})
                reservation = self.reservation(context, job_id, decision_id)
                if rp.exists(): require(read(rp) == reservation, 'jm_A3_reservation_changed')
                else:
                    write(rp, reservation)
                    if self.hook: self.hook('RESERVATION_SAVED', {'decision_id': decision_id})
        boundary_write()
        return super().request(context, job_id, decision_id, transport)


def selector_factory(execution, *, ledger, transport):
    _, config = validate_execution(execution)
    require(type(ledger) is RecoveryLedger and ledger.execution == execution, 'jm_A3_ledger_binding')
    require(transport is not None and transport.origin == 'test_double' and
            getattr(transport, 'scope', None) == 'CONSTRUCTED_FAKE_TRANSPORT', 'jm_A3_fake_transport_required')
    return PackagingRemoteSelector(config, ledger, execution['branch_id'], transport)


def validate_route(execution, task, config, job_id, selector):
    t, c = validate_execution(execution)
    require(t == task and c == config and job_id == execution['branch_id'], 'jm_A3_route_changed')
    require(type(selector) is PackagingRemoteSelector and type(selector.ledger) is RecoveryLedger and
            selector.ledger.execution == execution and selector.config == c and selector.job_id == job_id,
            'jm_A3_selector_changed')
    selector_factory(execution, ledger=selector.ledger, transport=selector.transport)


def initial_checkpoint(execution):
    task, config = validate_execution(execution)
    cp = bootstrap(execution['binding'], task, config, execution['branch_id'])
    cp['version'] = 'jev_jm_recovery_checkpoint_v1'
    return seal(cp)


def validate_saved_checkpoint(cp, execution, *, _validated=None, _checked_events=None):
    """Validate saved structure/bindings, never replay committed physics."""
    task, config = _validated if _validated is not None else validate_execution(execution)
    validate_schema('jm_recovery_checkpoint_v1', cp); check_seal(cp)
    require(cp['job_id'] == execution['branch_id'] and cp['method'] == config['selector'] and
            cp['task_digest'] == digest(task) and cp['config_digest'] == digest(config) and
            cp['runtime_identity'] == config['runtime_identity'], 'jm_A3_checkpoint_identity_changed')
    from semantic_pallet_planner.o4.buffer.buffer_state import invariant
    from .context import validate_context, resolve_display_id
    from semantic_pallet_planner.o4.extensions.e2.planning import action_for
    from .stability.monitor import validate_monitor, TERMINATIONS
    invariant(cp['state'])
    require(cp['cursor'] == cp['state']['arrival_count'] and
            cp['state']['arrived_ids'] == [x['item_id'] for x in task['items'][:cp['cursor']]],
            'jm_A3_cursor_changed')
    state = execution['binding']['start']['snapshot']['state']
    decisions = 0; forced = 0
    for event in cp['events'] + ([cp['pending_event']] if cp['pending_event'] else []):
        require(event['before'] == state, 'jm_A3_history_discontinuous')
        invariant(event['after'])
        event_key = digest(event)
        if event.get('context') is not None and (_checked_events is None or event_key not in _checked_events):
            ctx = DecisionContext.from_dict(event['context']); bundle = CandidateBundle.from_dict(event['bundle'])
            validate_context(ctx, event['observation'], bundle, config)
            require(event['decision_id'] == f'{execution["branch_id"]}_D{decisions:04d}' and
                    ctx.data['local_binding']['job_id'] == execution['branch_id'] and
                    ctx.data['local_binding']['decision_id'] == event['decision_id'], 'jm_A3_decision_changed')
            selected = event['selection']
            if selected is not None:
                require(selected['local_binding_digest'] == digest(ctx.data['local_binding']), 'jm_A3_selection_changed')
                if selected['status'] in ('selected', 'singleton'):
                    chosen = resolve_display_id(ctx, selected['selected_display_id'], event['observation'], bundle, config)
                    require(chosen['candidate_id'] == selected['selected_candidate_id'] and
                            event['proposed_action'] == action_for(event['observation'], bundle.data['physical_candidates'], chosen),
                            'jm_A3_action_changed')
                    if selected['source'] == 'FORCED_FROM_FROZEN_POOL':
                        from .packaging_jev_forks import validate_forced_selection
                        validate_forced_selection(selected, ctx, chosen, config)
                        require(decisions == 0 and event['proposed_action'] == execution['binding']['exact_action'],
                                'jm_A3_forced_changed')
                    if event['monitor'] is not None:
                        validate_monitor(event['monitor'], event['before'], chosen, event, config,
                                         require_stable=event['event'] == 'PLACE')
                        if event['monitor']['status'] in TERMINATIONS:
                            require(event['reason'] == TERMINATIONS[event['monitor']['status']] if event is not cp['pending_event'] else
                                    event['reason'] in (None, TERMINATIONS[event['monitor']['status']]), 'jm_A3_stop_changed')
            if event['event'] == 'PLACE':
                require(event['monitor'] is not None and event['monitor']['status'] == 'STABLE' and
                        event['action'] == event['proposed_action'] and
                        event['after']['placed_count'] == event['before']['placed_count'] + 1,
                        'jm_A3_commit_changed')
            else:
                require(event['after'] == event['before'] and event['action'] is None, 'jm_A3_failure_mutated')
            if _checked_events is not None: _checked_events.add(event_key)
        if event.get('context') is not None:
            require(event['decision_id'] == f'{execution["branch_id"]}_D{decisions:04d}', 'jm_A3_decision_changed')
            forced += int(bool(event.get('selection')) and event['selection']['source'] == 'FORCED_FROM_FROZEN_POOL')
            if event is not cp['pending_event']: decisions += 1
        state = event['after']
    require(state == cp['state'] and decisions == cp['decision'] and forced == 1, 'jm_A3_progress_changed')
    pending = cp['pending_event']; phase = cp['phase']
    require((pending is None) == (phase in ('READY', 'TERMINATED')), 'jm_A3_pending_missing')
    if pending:
        require((pending['selection'] is None) == (phase == 'DECISION_READY'), 'jm_A3_selection_phase')
        require((pending['monitor'] is not None) == (phase in ('MONITORED', 'COMMITTED')), 'jm_A3_monitor_phase')
        require((pending['event'] == 'PLACE') == (phase == 'COMMITTED'), 'jm_A3_commit_phase')
    if phase == 'TERMINATED': require(cp['reason'] is not None, 'jm_A3_terminal_reason_missing')
    return cp


def _ledger_readonly(root, execution, *, _validated=None):
    task, config = _validated if _validated is not None else validate_execution(execution)
    obj = RecoveryLedger.__new__(RecoveryLedger)
    obj.root = root; obj.path = root / 'requests.json'; obj.max_sends = execution['max_sends']
    obj.execution = execution; obj.task = task; obj.config = config
    obj._load()
    return obj


def validate_saved_execution(root, *, expected_execution=None):
    """Pure saved validation including partial activations, never dispatches."""
    root = Path(root); activation = read(root / 'activation.json')
    validate_schema('jm_activation_v1', activation); check_seal(activation)
    execution = activation['execution']; task_config = validate_execution(execution)
    if expected_execution is not None: require(execution == expected_execution, 'jm_A3_activation_changed')
    checked_events = set()
    cp = activation['initial_checkpoint']; validate_saved_checkpoint(cp, execution, _validated=task_config, _checked_events=checked_events)
    require(cp['events'] == [] and cp['phase'] == 'SELECTED' and cp['decision'] == 0 and
            cp['state'] == execution['binding']['start']['snapshot']['state'], 'jm_A3_initial_changed')
    previous = digest(activation); paths = sorted((root / 'stages').glob('*.json'))
    for i, path in enumerate(paths, 1):
        require(path.name == f'{i:06d}.json', 'jm_A3_stage_missing')
        row = read(path); validate_schema('jm_checkpoint_journal_v1', row); check_seal(row)
        require(row['sequence'] == i and row['previous_digest'] == previous and
                row['execution_digest'] == digest(execution), 'jm_A3_stage_chain_changed')
        next_cp = row['checkpoint']; validate_saved_checkpoint(next_cp, execution, _validated=task_config, _checked_events=checked_events)
        require(next_cp['events'][:len(cp['events'])] == cp['events'], 'jm_A3_events_overwritten')
        cp = next_cp; previous = digest(row)
    head_path = root / 'checkpoint_head.json'
    if paths or head_path.exists():
        require(read(head_path) == {'sequence': len(paths), 'digest': previous}, 'jm_A3_checkpoint_head_changed')
    ledger_root = root / 'ledger'
    rows = []
    if ledger_root.exists():
        obj = _ledger_readonly(ledger_root, execution, _validated=task_config)
        rows = obj.data['requests']
        contexts = {p.stem: read(p) for p in (ledger_root / 'contexts').glob('*.json')}
        reservations = {p.stem: read(p) for p in (ledger_root / 'reservations').glob('*.json')}
        for did, data in contexts.items():
            context = DecisionContext.from_dict(data); obj.check_context(context, execution['branch_id'], did)
            require(did in reservations or (cp['phase'] == 'DECISION_READY' and cp['pending_event']['context'] == data),
                    'jm_A3_missing_reservation')
            if did in reservations:
                require(reservations[did] == obj.reservation(context, execution['branch_id'], did), 'jm_A3_reservation_changed')
        require(set(reservations) <= set(contexts), 'jm_A3_missing_context')
        # Every prepared/requested decision must be explained by saved progress,
        # not just every checkpoint selection by the ledger. In particular an
        # activation-only forced SELECTED cannot explain any suffix request.
        choice_events = {}
        for event in cp['events'] + ([cp['pending_event']] if cp['pending_event'] else []):
            selected = event.get('selection')
            if event.get('context') and event['context']['route'] == 'CHOICE_REQUIRED' and not (
                    selected and selected['source'] == 'FORCED_FROM_FROZEN_POOL'):
                choice_events[event['decision_id']] = event
        require(set(contexts) <= set(choice_events), 'jm_A3_unexplained_context_progress')
        for did, data in contexts.items():
            require(data == choice_events[did]['context'], 'jm_A3_saved_context_changed')
        for row in rows:
            event = choice_events.get(row['decision_id'])
            require(event is not None, 'jm_A3_unexplained_request_progress')
            # A response/selection may precede the public SELECTED checkpoint
            # only for the currently persisted DECISION_READY decision.
            current_ready = cp['phase'] == 'DECISION_READY' and event is cp['pending_event']
            require(current_ready or (event.get('selection') is not None and
                    row['selection'] == event['selection']), 'jm_A3_request_ahead_of_checkpoint')
        for event in cp['events'] + ([cp['pending_event']] if cp['pending_event'] else []):
            selected = event.get('selection')
            if event.get('context') and event['context']['route'] == 'CHOICE_REQUIRED' and not (
                    selected and selected['source'] == 'FORCED_FROM_FROZEN_POOL'):
                require(contexts.get(event['decision_id']) == event['context'] or
                        (cp['phase'] == 'DECISION_READY' and event == cp['pending_event'] and event['decision_id'] not in contexts),
                        'jm_A3_saved_context_changed')
                if selected:
                    matches = [r for r in rows if r['decision_id'] == event['decision_id']]
                    require(len(matches) == 1 and matches[0]['selection'] == selected, 'jm_A3_saved_selection_changed')
    else:
        require(not paths, 'jm_A3_missing_ledger')
    if not paths:
        require(not (root / 'episode.json').exists() and not (root / 'counts.json').exists(),
                'jm_A3_missing_progress_journal')
    if (root / 'episode.json').exists():
        episode = read(root / 'episode.json')
        require(episode['checkpoint'] == cp and episode['events'] == cp['events'] and
                episode['final_state'] == cp['state'], 'jm_A3_episode_changed')
    return {'version': 'jev_jm_saved_recovery_check_v2', 'checkpoint': cp, 'requests': len(rows),
            'states': [r['state'] for r in rows], 'sequence': len(paths), 'previous_digest': previous}


def run_repeat(schedule, *, branch_id, repeat_slot, root, transport, on_checkpoint=None, ledger_hook=None):
    """Execute/resume exactly one frozen slot at its deterministic allocation root."""
    validate_schedule(schedule)
    matches = [e for e in schedule['executions'] if e['original_branch_id'] == branch_id and e['repeat_slot'] == repeat_slot]
    require(len(matches) == 1, 'jm_A3_unregistered_slot'); execution = matches[0]
    from .packaging_jev_forks import _path
    root = Path(root).resolve()
    require(root == _path(schedule['storage_root']), 'jm_A3_storage_root_changed')
    root.mkdir(parents=True, exist_ok=True)
    # Whole-schedule writer lock prevents overlapping slot writers as well as
    # concurrent resumes; remaining allocation cannot be borrowed by other slots.
    with exclusive(root):
        anchor = root / 'schedule.json'
        if anchor.exists(): require(read(anchor) == schedule, 'jm_A3_schedule_changed')
        else:
            require(not (root / 'slots').exists(), 'jm_A3_missing_schedule')
            write(anchor, schedule)
        run = root / 'slots' / execution['allocation_id']; run.mkdir(parents=True, exist_ok=True)
        activation_path = run / 'activation.json'
        is_new = not activation_path.exists()
        if is_new:
            require(not any(run.iterdir()), 'jm_A3_missing_activation')
            write(activation_path, seal({'version': 'jev_jm_activation_v1', 'execution': execution,
                                        'initial_checkpoint': initial_checkpoint(execution)}))
            if ledger_hook: ledger_hook('ACTIVATED', {})
        saved = validate_saved_execution(run, expected_execution=execution)
        ledger = RecoveryLedger(run / 'ledger', execution, hook=ledger_hook)
        selector = selector_factory(execution, ledger=ledger, transport=transport)
        task, config = validate_execution(execution)
        if is_new and on_checkpoint: on_checkpoint(copy.deepcopy(saved['checkpoint']))
        checked_events = set()
        def persist(cp):
            validate_saved_checkpoint(cp, execution, _validated=(task, config), _checked_events=checked_events)
            if cp == saved['checkpoint']: return
            saved['sequence'] += 1
            row = seal({'version': 'jev_jm_checkpoint_journal_v1', 'execution_digest': digest(execution),
                        'sequence': saved['sequence'], 'previous_digest': saved['previous_digest'], 'checkpoint': cp})
            write(run / 'stages' / f'{saved["sequence"]:06d}.json', row)
            write(run / 'checkpoint_head.json', {'sequence': saved['sequence'], 'digest': digest(row)})
            saved.update(checkpoint=copy.deepcopy(cp), previous_digest=digest(row))
            if on_checkpoint: on_checkpoint(copy.deepcopy(cp))
        task, config = validate_execution(execution)
        from .episode import run_episode
        episode = run_episode(task, selector, config, job_id=execution['branch_id'], method='jev_no_memory',
                              training_fork=execution, resume=saved['checkpoint'], on_checkpoint=persist)
        write(run / 'episode.json', episode)
        rows = ledger._load()['requests']; selections = [e['selection'] for e in episode['events'] if e.get('selection')]
        write(run / 'counts.json', {'version': 'jev_jm_repeat_counts_v1', 'allocation_id': execution['allocation_id'],
              'repeat_slot': repeat_slot, 'max_sends': execution['max_sends'],
              'forced_actions': sum(s['source'] == 'FORCED_FROM_FROZEN_POOL' for s in selections),
              'singleton_actions': sum(s['source'] == 'singleton' for s in selections),
              'constructed_requests': sum(r['send_started'] for r in rows),
              'constructed_selected_actions': sum(s['source'] == 'test_double' and s['status'] == 'selected' for s in selections),
              'commits': sum(e['event'] == 'PLACE' for e in episode['events']),
              'monitored_actions': sum(e.get('monitor') is not None for e in episode['events']),
              'unknown_sends': sum(r['state'] == 'UNKNOWN_SEND' for r in rows), 'real_model_calls': 0,
              'scope': 'CONSTRUCTED_FAKE_TRANSPORT_MONITOR_STUB', 'model_cost_usd': 'NOT_APPLICABLE_CONSTRUCTED'})
        return episode
