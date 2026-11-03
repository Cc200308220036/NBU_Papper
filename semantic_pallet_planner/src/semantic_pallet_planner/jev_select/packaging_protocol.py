"""JN0 orchestration protocol; execution remains the sealed monitored v5 protocol.

JN1 must register a new version before admitting a remote selector or memory.
"""
from .contracts import JevSelectError
from .packaging_runtime import LocalPackagingDouble

PLAN_VERSION = 'jev_packaging_full_order_plan_v1'
RUN_VERSION = 'jev_packaging_full_order_run_v1'
EXECUTION_VERSION = 'jev_packaging_monitored_v5'
METHOD_REGISTRY = {
    'local_geometry_test_double': {'name': '几何基线', 'origin': 'LOCAL_TEST_DOUBLE_NOT_JEV'},
    'local_first_test_double': {'name': '固定顺序基线', 'origin': 'LOCAL_TEST_DOUBLE_NOT_JEV'},
}
CATEGORIES = ('COMPLETE', 'PREDICTED_STATIC_INSTABILITY', 'UNASSESSABLE', 'ERROR',
              'EMPTY_POOL', 'COMMIT_FAILURE', 'SELECTION_FAILURE', 'TECHNICAL_LIMIT',
              'CANCELED', 'NOT_RUN')
METRICS_CONTRACT = {
    'version': 'jev_packaging_full_order_metrics_v1',
    'denominator': 'all frozen jobs; loading fractions use all planned items including future arrivals',
    'stable_complete': 'complete and monitor enabled and every committed action STABLE',
    'fixed_utilization': 'committed volume / (L W Hmax)',
    'envelope_utilization': 'committed volume / (L W actual height); empty NA',
    'coverage': 'STABLE+UNSTABLE / selected actions; UNASSESSABLE and ERROR not assessable',
    'latency': 'saved per-event wall segments; linear p50/p95 and sample count; order active wall includes IO/preflight/resume validation',
    'capacity': 'original area ledger only; no PCT reaction writeback',
    'branch_and_memory': 'NOT_RUN',
}


def selector_factory(method, *, execution_version=EXECUTION_VERSION, config=None, transport=None, ledger=None, job_id=None):
    if execution_version == "jev_packaging_remote_v6":
        from .packaging_remote import remote_selector_factory
        return remote_selector_factory(method, config=config, transport=transport, ledger=ledger, job_id=job_id)
    if execution_version != EXECUTION_VERSION or method not in METHOD_REGISTRY:
        raise JevSelectError('full_order_unregistered_method_or_protocol')
    return LocalPackagingDouble(method)


def termination_category(reason, events):
    mapped = {'ALL_ITEMS_PLACED': 'COMPLETE', 'PREDICTED_STATIC_INSTABILITY': 'PREDICTED_STATIC_INSTABILITY',
              'STABILITY_UNASSESSABLE': 'UNASSESSABLE', 'STABILITY_MONITOR_ERROR': 'ERROR',
              'STOP_NO_PHYSICAL_CANDIDATE': 'EMPTY_POOL'}
    if reason in mapped:
        return mapped[reason]
    if any(e['event'] == 'COMMIT_FAILURE' for e in events):
        return 'COMMIT_FAILURE'
    return 'ERROR' if reason == 'EVALUATION_ERROR' else 'SELECTION_FAILURE'
