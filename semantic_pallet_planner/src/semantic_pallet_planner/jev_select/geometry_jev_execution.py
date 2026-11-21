"""GP6-F0 v18 execution, durable request ledger, selector, recovery, and metrics.

Reuses shared CandidateProvider, F0 projection, parse_response, RequestLedger,
run_episode, post-selection monitor, and commit_physical without duplicating
the order engine or relaxing GP5/v17 local guards.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
import time

from .contracts import JevSelectError, digest, validate_schema
from .geometry_execution import GeometryStore, _validate_saved_transitions
from .geometry_jev_protocol import (
    GP6_API_KEY_ENV,
    GP6_DEVELOPMENT,
    GP6_ENDPOINT,
    GP6_METHOD,
    GP6_MODEL,
    GP6_ORDER,
    draft_jev_run,
    jev_identity_fields,
    update_jev_run,
    validate_jev_admission,
)
from .geometry_native_protocol import config_fields
from .geometry_order_execution import _order_timing_totals, validate_monitor_snapshot
from .geometry_runtime_contracts import environment, same_native
from .ledger import exclusive, read, write
from .packaging_geometry_protocol import adapt_task, require
from .packaging_remote import RequestLedger
from .packaging_versions import GEOMETRY_JEV_CONTEXT, GEOMETRY_JEV_VERSION
from .selector import SelectionResult, parse_response, result
from .transport import outcome, validate_transport


class GeometryJevRequestLedger(RequestLedger):
    """Durable single-send request ledger for v18 with per-job and shared limits.

    - Inherits RequestLedger's INTENT -> SENDING -> RESPONSE_SAVED/UNKNOWN_SEND/FAILED -> SELECTION_SAVED state machine.
    - Never releases budget on failure or UNKNOWN_SEND; never implicitly retries.
    - Refuses real 'jev' transport unless explicitly authorized by validated formal admission.
    """

    ledger_version = 'geometry_jev_requests_v1'
    context_version = GEOMETRY_JEV_CONTEXT

    def __init__(
        self,
        root,
        *,
        plan_digest: str,
        per_job_max_sends: int,
        shared_max_sends: int,
        allow_real_transport: bool = False,
        hook=None,
    ):
        self.plan_digest = plan_digest
        self.per_job_max_sends = per_job_max_sends
        self.allow_real_transport = bool(allow_real_transport)
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'requests.json'
        self.max_sends = shared_max_sends
        self.hook = hook
        with exclusive(self.root):
            if not self.path.exists():
                self._save({
                    'version': self.ledger_version,
                    'plan_digest': self.plan_digest,
                    'per_job_max_sends': self.per_job_max_sends,
                    'max_sends': self.max_sends,
                    'requests': [],
                })
            self._load()

    def _load(self):
        d = read(self.path)
        if (
            d.get('version') != self.ledger_version
            or d.get('plan_digest') != self.plan_digest
            or d.get('per_job_max_sends') != self.per_job_max_sends
            or d.get('max_sends') != self.max_sends
            or d.get('record_digest') != digest({k: v for k, v in d.items() if k != 'record_digest'})
        ):
            raise JevSelectError('request_ledger_changed')
        keys = set()
        per_job_counts: dict[str, int] = {}
        for i, r in enumerate(d['requests'], 1):
            key = (r['job_id'], r['decision_id'])
            if (
                key in keys
                or r['attempt_id'] != f'A{i:06d}'
                or r['state'] not in ('INTENT', 'SENDING', 'RESPONSE_SAVED', 'SELECTION_SAVED', 'UNKNOWN_SEND', 'FAILED')
            ):
                raise JevSelectError('invalid_request_ledger')
            keys.add(key)
            if r['send_started']:
                per_job_counts[r['job_id']] = per_job_counts.get(r['job_id'], 0) + 1
            if r['transport'] is not None:
                validate_transport(r['transport'])
                if r['transport_digest'] != digest(r['transport']):
                    raise JevSelectError('request_response_changed')
            if r['selection'] is not None:
                validate_schema('selection_result', r['selection'])
                if r['selection_digest'] != digest(r['selection']):
                    raise JevSelectError('request_selection_changed')
        if sum(r['send_started'] for r in d['requests']) > self.max_sends:
            raise JevSelectError('request_budget_exceeded')
        if any(c > self.per_job_max_sends for c in per_job_counts.values()):
            raise JevSelectError('per_job_request_budget_exceeded')
        self.data = d
        return d

    def admit_request(self, job_id, decision_id):
        job_sends = sum(r['send_started'] for r in self.data['requests'] if r['job_id'] == job_id)
        if job_sends >= self.per_job_max_sends:
            raise JevSelectError('request_budget_exhausted', f'per_job_limit:{job_id}')

    def admit_send(self, row):
        job_sends = sum(r['send_started'] for r in self.data['requests'] if r['job_id'] == row['job_id'])
        if job_sends >= self.per_job_max_sends:
            raise JevSelectError('request_budget_exhausted', f'per_job_limit:{row["job_id"]}')
        if row['origin'] == 'jev' and not self.allow_real_transport:
            raise JevSelectError('gp6_real_transport_unauthorized')

    def request(self, context, job_id, decision_id, transport):
        if transport is not None and getattr(transport, 'origin', None) == 'jev' and not self.allow_real_transport:
            raise JevSelectError('gp6_real_transport_unauthorized')
        return super().request(context, job_id, decision_id, transport)

    def find_attempt(self, job_id: str, decision_id: str):
        with exclusive(self.root):
            rows = self._load()['requests']
            matches = [r for r in rows if (r['job_id'], r['decision_id']) == (job_id, decision_id)]
            return copy.deepcopy(matches[0]) if matches else None

    def statistics(self, job_id: str | None = None):
        rows = self._load()['requests']
        if job_id is not None:
            rows = [r for r in rows if r['job_id'] == job_id]
        sent = [r for r in rows if r['send_started']]
        real_sent = [r for r in sent if r['origin'] == 'jev']
        double_sent = [r for r in sent if r['origin'] == 'test_double']
        usages = [r['selection']['usage'] for r in sent if r['selection'] is not None]
        if not sent:
            usage_status = 'NA_NO_SERVICE_CALL'
            usage_out = []
        elif any(u is None for u in usages) or len(usages) < len(sent):
            usage_status = 'UNKNOWN'
            usage_out = 'UNKNOWN'
        else:
            usage_status = 'AVAILABLE'
            usage_out = usages
        return {
            'send_reservations': len(sent),
            'model_calls': sum(
                r['transport'] is not None and r['transport']['network_attempted'] is True
                for r in real_sent
            ),
            'test_double_sends': len(double_sent),
            'successful_selections': sum(
                r['state'] == 'SELECTION_SAVED'
                and r['selection'] is not None
                and r['selection']['status'] == 'selected'
                for r in sent
            ),
            'failed_requests': sum(
                r['state'] == 'FAILED'
                or (r['selection'] is not None and r['selection']['status'] in ('invalid_response', 'provider_failure'))
                for r in sent
            ),
            'unknown_sends': sum(r['state'] == 'UNKNOWN_SEND' for r in sent),
            'usage_status': usage_status,
            'usage': usage_out,
            'service_cost_usd': 'UNKNOWN' if real_sent else 'NA_NO_SERVICE_CALL',
            'request_latency_s': [r['transport']['latency_s'] for r in sent if r['transport'] is not None],
        }


class GeometryJevSelector:
    """GP6-F0 v18 selector over GeometryJevRequestLedger and shared parse_response.

    Never falls back to a local selector on failure, invalid response, or UNKNOWN_SEND.
    """

    def __init__(self, config: dict, ledger: GeometryJevRequestLedger, job_id: str, transport):
        self.config = config
        self.ledger = ledger
        self.job_id = job_id
        self.transport = transport

    def select(self, context, *, decision_id: str) -> SelectionResult:
        from .context import validate_context

        validate_context(context, config=self.config)
        v = context.data
        b = v['local_binding']
        if b.get('job_id') != self.job_id or b.get('decision_id') != decision_id:
            raise JevSelectError('selector_identity_mismatch')
        if v['route'] == 'SINGLETON_BYPASS':
            return result(context, status='singleton', source='singleton', label='C01')
        if v['model_state']['memories'] != []:
            raise JevSelectError('gp6_f0_memories_not_empty')
        if self.config['transport_evidence'] == 'TEST_DOUBLE' and getattr(self.transport, 'origin', None) == 'jev':
            raise JevSelectError('gp6_real_transport_unauthorized')
        if self.config['transport_evidence'] == 'REAL_JEV' and not self.ledger.allow_real_transport:
            raise JevSelectError('gp6_real_transport_unauthorized')
        try:
            attempt = self.ledger.request(context, self.job_id, decision_id, self.transport)
        except JevSelectError as exc:
            if exc.code == 'request_budget_exhausted':
                src = 'jev' if getattr(self.transport, 'origin', None) == 'jev' else 'test_double'
                return result(context, status='budget_exhausted', source=src, error='ATTEMPT_BUDGET_EXHAUSTED')
            raise
        if attempt['selection'] is not None:
            return SelectionResult.from_dict(attempt['selection'])
        selected = parse_response(context, attempt, self.config)
        self.ledger.save_selection(attempt, selected)
        return selected


def load_jev_config(plan: dict, job_id: str, *, monitor_snapshot: dict, admission: dict, kernel_receipt=None) -> dict:
    real_authorized = validate_jev_admission(plan, monitor_snapshot, admission, kernel_receipt)
    job = next((j for j in plan['jobs'] if j['job_id'] == job_id), None)
    require(job is not None, 'geometry_jev_job')
    task = next(t for t in plan['tasks'] if t['task_id'] == job['task_id'])
    from .candidate_backends import load_geometry_config

    cfg = load_geometry_config(
        backend=job['backend'],
        data_identity=plan['data_identity'],
        task_identity=task['runtime_digest'],
        monitor_identity=digest(monitor_snapshot),
        method='local_geometry_test_double',
    )
    cfg.update(
        **config_fields(),
        version=GEOMETRY_JEV_VERSION,
        model=GP6_MODEL,
        selector=GP6_METHOD,
        construction_only=False,
        execution_version='geometry_jev_execution_v1',
        experiment_protocol='geometry_jev_run_v1',
        order_task_identity=copy.deepcopy(task),
        plan_digest=digest(plan),
        execution_scope=plan['scope'],
        admission_digest=digest(admission),
        kernel_receipt_digest=digest(kernel_receipt) if kernel_receipt else None,
        monitor_evidence='TEST_DOUBLE' if plan['scope'] == GP6_DEVELOPMENT else 'REAL_KERNEL',
        transport_evidence='REAL_JEV' if real_authorized else 'TEST_DOUBLE',
        stability_monitor=copy.deepcopy(monitor_snapshot),
        endpoint=GP6_ENDPOINT,
        api_key_env=GP6_API_KEY_ENV,
        timeout_s=30.0,
        max_retries=0,
        response_max_bytes=1000000,
        probability_tolerance=1e-5,
        probability_sum_validation='strict_or_2dp_rounding_interval_v1',
        per_job_max_sends=plan['per_job_max_sends'],
        shared_max_sends=plan['shared_max_sends'],
    )
    cfg['runtime_identity']['strategy_identity'] = digest({k: v for k, v in cfg.items() if k != 'runtime_identity'})
    preflight_jev(cfg)
    return cfg


def preflight_jev(config: dict) -> None:
    from .candidate_backends import load_geometry_config

    validate_schema('config_v18', config)
    ids = config['runtime_identity']
    task = config['order_task_identity']
    snapshot = config['stability_monitor']
    if config['monitor_evidence'] == 'REAL_KERNEL':
        validate_monitor_snapshot(snapshot)
    else:
        require(snapshot.get('enabled') is True and snapshot.get('algorithm') == 'pct_exact_pose_network_v3', 'geometry_jev_monitor_required')
    require(ids['task_identity'] == task['runtime_digest'] and ids['monitor_identity'] == digest(snapshot), 'geometry_jev_task_identity')
    require((task['origin'] == 'SYNTHETIC_FIXED') == (config['execution_scope'] == GP6_DEVELOPMENT), 'geometry_jev_origin_scope')
    require((config['monitor_evidence'] == 'TEST_DOUBLE') == (config['execution_scope'] == GP6_DEVELOPMENT), 'geometry_jev_evidence_scope')
    require((config['transport_evidence'] == 'TEST_DOUBLE') == (config['execution_scope'] == GP6_DEVELOPMENT), 'geometry_jev_transport_scope')
    require((config['kernel_receipt_digest'] is not None) == (config['execution_scope'] == GP6_ORDER), 'geometry_jev_kernel_receipt_scope')
    expected = load_geometry_config(
        backend=config['candidate_backend'],
        data_identity=ids['data_identity'],
        task_identity=ids['task_identity'],
        monitor_identity=ids['monitor_identity'],
        method='local_geometry_test_double',
    )
    expected.update({
        k: copy.deepcopy(config[k])
        for k in (
            'version', 'model', 'selector', 'construction_only', 'execution_version', 'experiment_protocol',
            'order_task_identity', 'plan_digest', 'execution_scope', 'admission_digest', 'kernel_receipt_digest',
            'monitor_evidence', 'transport_evidence', 'stability_monitor', 'endpoint', 'api_key_env',
            'timeout_s', 'max_retries', 'response_max_bytes', 'probability_tolerance', 'probability_sum_validation',
            'per_job_max_sends', 'shared_max_sends',
        )
    })
    expected.update(config_fields())
    expected['runtime_identity']['strategy_identity'] = digest({k: v for k, v in expected.items() if k != 'runtime_identity'})
    require(same_native(expected, config), 'geometry_jev_config_drift')


def jev_execution_for_config(config: dict, job_id: str) -> dict:
    preflight_jev(config)
    v = {
        **jev_identity_fields(),
        'version': 'geometry_jev_execution_v1',
        'scope': config['execution_scope'],
        'task_digest': config['order_task_identity']['runtime_digest'],
        'config_digest': digest(config),
        'source_identity': config['runtime_identity']['source_identity'],
        'environment_digest': digest(environment()),
        'plan_digest': config['plan_digest'],
        'job_id': job_id,
        'admission_digest': config['admission_digest'],
        'kernel_receipt_digest': config['kernel_receipt_digest'],
        'per_job_max_sends': config['per_job_max_sends'],
        'shared_max_sends': config['shared_max_sends'],
        'transport_evidence': config['transport_evidence'],
    }
    validate_schema('geometry_jev_execution_v1', v)
    return v


def validate_jev_execution(value: dict, config: dict) -> None:
    validate_schema('geometry_jev_execution_v1', value)
    require(same_native(value, jev_execution_for_config(config, value['job_id'])), 'geometry_jev_execution_drift')


class JevOrderStore(GeometryStore):
    decision_version = 'geometry_jev_durable_decision_v1'

    def __init__(
        self,
        root,
        *,
        plan: dict,
        job_id: str,
        adapted: dict,
        monitor_snapshot: dict,
        admission: dict,
        request_ledger: GeometryJevRequestLedger,
        kernel_receipt=None,
    ):
        super().__init__(root)
        self._plan = copy.deepcopy(plan)
        self._job_id = job_id
        self._raw = bytes(adapted['raw'])
        self._identity = copy.deepcopy(adapted['identity'])
        self._monitor = copy.deepcopy(monitor_snapshot)
        self._admission = copy.deepcopy(admission)
        self._kernel = copy.deepcopy(kernel_receipt)
        self.request_ledger = request_ledger

    def authorize_config(self, config: dict) -> dict:
        expected = load_jev_config(
            self._plan,
            self._job_id,
            monitor_snapshot=self._monitor,
            admission=self._admission,
            kernel_receipt=self._kernel,
        )
        require(same_native(config, expected), 'geometry_jev_store_config')
        return jev_execution_for_config(config, self._job_id)

    def load_event(self, event, config):
        self.authorize_config(config)
        return super().load_event(event, config)

    def validate_request(self, task: dict, config: dict) -> dict:
        self.authorize_config(config)
        adapted = adapt_task(self._raw, origin=self._identity['origin'], expected_sha256=self._identity['raw_sha256'])
        require(
            same_native(adapted['identity'], config['order_task_identity'])
            and same_native(task, adapted['runtime']),
            'geometry_jev_runtime_task_drift',
        )
        return jev_execution_for_config(config, self._job_id)


def validate_jev_request_ledger_binding(
    plan: dict,
    config: dict,
    ledger: GeometryJevRequestLedger,
    transport,
    *,
    real_authorized: bool,
) -> None:
    """Bind actual request ledger identity, limits, path, and transport mode to frozen plan."""
    require(isinstance(ledger, GeometryJevRequestLedger), 'geometry_jev_ledger_required')
    expected_plan_digest = digest(plan)
    require(
        ledger.plan_digest == expected_plan_digest == config['plan_digest'],
        'geometry_jev_ledger_plan_drift',
    )
    require(
        ledger.per_job_max_sends == plan['per_job_max_sends'] == config['per_job_max_sends'],
        'geometry_jev_ledger_per_job_limit_drift',
    )
    require(
        ledger.max_sends == plan['shared_max_sends'] == config['shared_max_sends'],
        'geometry_jev_ledger_shared_limit_drift',
    )
    require(
        bool(ledger.allow_real_transport) == bool(real_authorized) == (config['transport_evidence'] == 'REAL_JEV'),
        'geometry_jev_ledger_transport_mode_drift',
    )
    if plan['scope'] == GP6_ORDER:
        require(type(plan.get('request_ledger_path')) is str and bool(plan['request_ledger_path']), 'geometry_jev_ledger_path_required')
        require(
            Path(ledger.path).resolve() == Path(plan['request_ledger_path']).resolve(),
            'geometry_jev_ledger_path_drift',
        )
    elif plan.get('request_ledger_path') is not None:
        require(
            Path(ledger.path).resolve() == Path(plan['request_ledger_path']).resolve(),
            'geometry_jev_ledger_path_drift',
        )
    origin = getattr(transport, 'origin', None)
    if config['transport_evidence'] == 'REAL_JEV':
        require(origin == 'jev', 'geometry_jev_transport_origin_mismatch')
    else:
        require(origin == 'test_double', 'gp6_real_transport_unauthorized' if origin == 'jev' else 'geometry_jev_transport_origin_mismatch')
    # Force durable readback check under lock before any dispatch/send/assessment/commit.
    with exclusive(ledger.root):
        ledger._load()


def validate_jev_request(task, selector, config, method, store, on_checkpoint, *, job_id=None) -> dict:
    preflight_jev(config)
    require(type(store) is JevOrderStore and callable(on_checkpoint), 'geometry_jev_explicit_authority_required')
    require(
        type(selector) is GeometryJevSelector
        and method == config['selector'] == GP6_METHOD
        and selector.job_id == (job_id or selector.job_id)
        and selector.ledger is store.request_ledger,
        'geometry_jev_selector_required',
    )
    binding = store.validate_request(task, config)
    require(job_id is None or job_id == binding['job_id'], 'geometry_jev_job_drift')
    validate_jev_request_ledger_binding(
        store._plan,
        config,
        store.request_ledger,
        selector.transport,
        real_authorized=(config['transport_evidence'] == 'REAL_JEV'),
    )
    if config['monitor_evidence'] == 'REAL_KERNEL':
        from .geometry_order_meter import current_counts

        current_counts(config['plan_digest'])
    return binding


def validate_jev_saved_checkpoint(cp, task, config, job_id, method, store):
    require(type(store) is JevOrderStore, 'geometry_jev_recovery_store')
    expected = store.validate_request(task, config)
    require(expected['job_id'] == job_id, 'geometry_jev_recovery_job')
    _validate_saved_transitions(
        cp,
        task,
        config,
        job_id,
        method,
        store,
        schema='checkpoint_v18',
        expected_execution=expected,
    )
    # Cross-check saved selections against durable request ledger
    ledger = store.request_ledger
    all_events = list(cp['events']) + ([cp['pending_event']] if cp['pending_event'] is not None else [])
    for ev in all_events:
        if not ev.get('decision_id'):
            continue
        sel = ev.get('selection')
        att = ledger.find_attempt(job_id, ev['decision_id'])
        if sel is None:
            if att is not None and att['state'] in ('SENDING', 'UNKNOWN_SEND'):
                raise JevSelectError('geometry_jev_recovery_unknown_send_blocked')
            continue
        if sel['source'] == 'singleton':
            require(att is None, 'geometry_jev_singleton_unexpected_send')
            continue
        if sel['status'] == 'budget_exhausted':
            continue
        require(att is not None, 'geometry_jev_missing_ledger_attempt')
        require(att['context_digest'] == digest(ev['context']), 'geometry_jev_ledger_context_drift')
        if att['selection'] is not None:
            require(same_native(att['selection'], sel), 'geometry_jev_ledger_selection_drift')
    return cp


def jev_order_metrics(task, config, method, state, events, reason, *, ledger=None, job_id=None) -> dict:
    placed = state['placed_items']
    items = task['items']
    container = state['container']
    planned_volume = sum(math.prod(o['dimensions_mm'].values()) for o in items)
    volume = sum(math.prod(o['oriented_size_mm']) for o in placed)
    planned_mass = sum(o['mass_kg'] for o in items)
    mass = sum(o['mass_kg'] for o in placed)
    height = max((o['pose']['z_base_mm'] + o['oriented_size_mm'][2] for o in placed), default=0)
    envelope = None
    if placed:
        axes = []
        for axis, k in enumerate(('x_mm', 'y_mm')):
            axes.append(
                max(o['pose'][k] + o['oriented_size_mm'][axis] / 2 for o in placed)
                - min(o['pose'][k] - o['oriented_size_mm'][axis] / 2 for o in placed)
            )
        envelope = volume / (math.prod(axes) * height)
    complete = len(placed) == len(items)
    require(not complete or reason == 'ALL_ITEMS_PLACED', 'geometry_jev_completion_reason')
    if reason == 'ALL_ITEMS_PLACED':
        require(complete and state['end_of_stream'] and not state['pending_items'], 'geometry_jev_incomplete_eos')
    category = {
        'ALL_ITEMS_PLACED': 'COMPLETE',
        'STOP_NO_PHYSICAL_CANDIDATE': 'NO_CANDIDATE',
        'PREDICTED_STATIC_INSTABILITY': 'PREDICTED_STATIC_INSTABILITY',
        'STABILITY_UNASSESSABLE': 'UNASSESSABLE',
        'UNKNOWN_IN_FLIGHT': 'UNKNOWN_SEND',
        'UNKNOWN_SEND': 'UNKNOWN_SEND',
        'PROVIDER_FAILURE': 'PROVIDER_FAILURE',
        'INVALID_RESPONSE': 'INVALID_RESPONSE',
        'BUDGET_EXHAUSTED': 'BUDGET_EXHAUSTED',
        'CANCELLED': 'CANCELLED',
    }.get(reason, 'TECHNICAL_FAILURE')
    ratios = {
        'placed_item_ratio': len(placed) / len(items),
        'placed_volume_ratio': volume / planned_volume,
        'placed_mass_ratio': mass / planned_mass,
    }
    bad = next((e for e in events if (e.get('monitor') or {}).get('status') == 'UNSTABLE'), None)
    rows = [e['monitor'] for e in events if e.get('monitor')]
    marked = sum((r.get('result') or {}).get('diagnostics', {}).get('TEST_DOUBLE') is True for r in rows)
    if config['monitor_evidence'] == 'REAL_KERNEL':
        from .geometry_order_meter import current_counts

        counts = current_counts(config['plan_digest'])
    else:
        counts = {'assessment_entries': 0, 'solver_calls': 0, 'test_double_assessments': marked}
    timings = _order_timing_totals(events, rows)

    singleton_bypasses = sum(
        1 for e in events if (e.get('selection') or {}).get('source') == 'singleton'
    )
    if ledger is not None:
        lstats = ledger.statistics(job_id=job_id)
        cost = {
            'send_reservations': lstats['send_reservations'],
            'model_calls': lstats['model_calls'],
            'test_double_sends': lstats['test_double_sends'],
            'successful_selections': lstats['successful_selections'],
            'failed_requests': lstats['failed_requests'],
            'unknown_sends': lstats['unknown_sends'],
            'singleton_bypasses': singleton_bypasses,
            'usage_status': lstats['usage_status'],
            'usage': lstats['usage'],
            'service_cost_usd': lstats['service_cost_usd'],
            'local_compute_cost': 'UNKNOWN',
        }
    else:
        sels = [e['selection'] for e in events if e.get('selection')]
        non_single = [s for s in sels if s['source'] != 'singleton']
        real_sels = [s for s in non_single if s['source'] == 'jev']
        cost = {
            'send_reservations': len(non_single),
            'model_calls': sum(s.get('network_attempted') is True for s in real_sels),
            'test_double_sends': sum(s['source'] == 'test_double' for s in non_single),
            'successful_selections': sum(s['status'] == 'selected' for s in non_single),
            'failed_requests': sum(s['status'] in ('invalid_response', 'provider_failure') for s in non_single),
            'unknown_sends': sum(s['status'] in ('unknown_in_flight', 'unknown_send') for s in non_single),
            'singleton_bypasses': singleton_bypasses,
            'usage_status': 'UNKNOWN' if non_single else 'NA_NO_SERVICE_CALL',
            'usage': 'UNKNOWN' if non_single else [],
            'service_cost_usd': 'UNKNOWN' if real_sels else 'NA_NO_SERVICE_CALL',
            'local_compute_cost': 'UNKNOWN',
        }

    value = {
        **jev_identity_fields(),
        'version': 'geometry_jev_metrics_v1',
        'task_id': task['task_id'],
        'candidate_backend': config['candidate_backend'],
        'method': method,
        'scope': config['execution_scope'],
        'monitor_evidence': config['monitor_evidence'],
        'transport_evidence': config['transport_evidence'],
        'runtime_identity': copy.deepcopy(config['runtime_identity']),
        'planned_items': len(items),
        'arrived_items': state['arrival_count'],
        'placed_items': len(placed),
        'planned_volume_mm3': planned_volume,
        'placed_volume_mm3': volume,
        'planned_mass_kg': planned_mass,
        'placed_mass_kg': mass,
        **ratios,
        'fixed_container_utilization': volume / (container['length_mm'] * container['width_mm'] * container['max_height_mm']),
        'max_height_mm': height,
        'envelope_utilization': envelope,
        'envelope_status': 'APPLICABLE' if placed else 'NA_EMPTY',
        'completed': complete,
        'termination_reason': reason,
        'termination_class': category,
        'predicted_instability_progress': None if bad is None else {
            'decision_id': bad['decision_id'],
            'failed_item_id': next(
                c['pick_item_id']
                for c in bad['bundle']['physical_candidates']
                if c['candidate_id'] == bad['selection']['selected_candidate_id']
            ),
            **ratios,
        },
        'counts': counts,
        'timings': timings,
        'cost': cost,
        'global_infeasibility_proven': False,
    }
    validate_schema('geometry_jev_metrics_v1', value)
    return value


def run_jev_job(
    plan: dict,
    job_id: str,
    adapted: dict,
    *,
    monitor_snapshot: dict,
    admission: dict,
    root,
    transport,
    ledger: GeometryJevRequestLedger,
    kernel_receipt=None,
    resume=None,
    on_checkpoint=None,
    hook=None,
) -> dict:
    """Orchestrate one GP6-F0 v18 job over the shared public run_episode loop."""
    config = load_jev_config(
        plan,
        job_id,
        monitor_snapshot=monitor_snapshot,
        admission=admission,
        kernel_receipt=kernel_receipt,
    )
    validate_jev_request_ledger_binding(
        plan,
        config,
        ledger,
        transport,
        real_authorized=(config['transport_evidence'] == 'REAL_JEV'),
    )

    root = Path(root)
    store = JevOrderStore(
        root / 'jobs' / job_id,
        plan=plan,
        job_id=job_id,
        adapted=adapted,
        monitor_snapshot=monitor_snapshot,
        admission=admission,
        request_ledger=ledger,
        kernel_receipt=kernel_receipt,
    )
    store.validate_request(adapted['runtime'], config)
    task = adapted['runtime']
    selector = GeometryJevSelector(config, ledger, job_id, transport)
    callback = on_checkpoint if on_checkpoint is not None else (lambda cp: None)
    from .episode import run_episode

    def execute_and_measure(started_ts: float):
        validate_jev_request(task, selector, config, GP6_METHOD, store, callback, job_id=job_id)
        ep = run_episode(
            task,
            selector,
            config,
            job_id=job_id,
            method=GP6_METHOD,
            resume=resume,
            on_checkpoint=callback,
            geometry_store=store,
            hook=hook,
        )
        reason = ep['checkpoint']['reason']
        metric = None
        if reason is not None:
            metric = jev_order_metrics(
                task,
                config,
                GP6_METHOD,
                ep['final_state'],
                ep['events'],
                reason,
                ledger=ledger,
                job_id=job_id,
            )
            metric['timings'].append({'segment': 'invocation_wall_s', 'seconds': time.perf_counter() - started_ts})
            validate_schema('geometry_jev_metrics_v1', metric)
            ep['summary'] = metric
        return ep, metric

    root.mkdir(parents=True, exist_ok=True)
    with exclusive(root):
        plan_path = root / 'plan.json'
        if plan_path.exists():
            require(same_native(read(plan_path), plan), 'geometry_jev_saved_plan_drift')
        else:
            write(plan_path, plan)
        run = read(root / 'run.json') if (root / 'run.json').exists() else draft_jev_run(plan)
        prior = next(r for r in run['rows'] if r['job_id'] == job_id)
        require(prior['status'] == 'NOT_RUN' or resume is not None, 'geometry_jev_duplicate_job_requires_checkpoint')
        raw_ref = store.put(adapted['raw'])
        raw_path = store.root / 'blobs' / raw_ref['sha256']
        write(store.root / 'task_identity.json', adapted['identity'])
        write(store.root / 'config.json', config)
        run = update_jev_run(run, plan, job_id, 'RUNNING')
        write(root / 'run.json', run)
        started = time.perf_counter()
        try:
            if plan['scope'] == GP6_DEVELOPMENT:
                ep, metric = execute_and_measure(started)
            else:
                from .geometry_order_meter import metered_jev_run

                with metered_jev_run(
                    plan,
                    job_id=job_id,
                    monitor_snapshot=monitor_snapshot,
                    admission=admission,
                    kernel_receipt=kernel_receipt,
                ):
                    ep, metric = execute_and_measure(started)
        except BaseException as exc:
            status = 'CANCELLED' if isinstance(exc, KeyboardInterrupt) else 'TECHNICAL_FAILURE'
            write(root / 'run.json', update_jev_run(run, plan, job_id, status))
            write(store.root / 'driver_failure.json', {'type': type(exc).__name__, 'detail': str(exc)[:240], 'no_implicit_retry': True})
            raise
        if metric is not None:
            status = (
                'COMPLETE'
                if metric['completed']
                else ('TECHNICAL_FAILURE' if metric['termination_class'] == 'TECHNICAL_FAILURE' else 'STOPPED')
            )
            write(store.root / 'metrics.json', metric)
        else:
            status = 'TECHNICAL_FAILURE'
        write(root / 'run.json', update_jev_run(run, plan, job_id, status, metric))
        write(
            store.root / 'record.json',
            {
                'checkpoint': ep['checkpoint'],
                'config': config,
                'raw_task': {'path': str(raw_path), 'sha256': raw_ref['sha256']},
                'durable_root': str(store.root),
            },
        )
        write(store.root / 'episode.json', ep)
        return ep
