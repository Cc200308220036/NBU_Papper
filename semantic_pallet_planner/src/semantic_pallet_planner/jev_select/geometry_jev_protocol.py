"""GP6-F0 independent v18 plan, admission, and run contracts.

Does not relax GP5/v17 local gates or schemas, never loads credentials,
and never authorizes real API calls without external signed admission.
"""
from __future__ import annotations

import copy
from pathlib import Path

from .contracts import JevSelectError, digest, validate_schema
from .geometry_native_protocol import policy_digest
from .geometry_runtime_contracts import environment, same_native
from .packaging_geometry_protocol import TASK_IDS, require, read_reference
from .packaging_versions import (
    GEOMETRY_BACKENDS,
    GEOMETRY_JEV_VERSION,
)

GP6_DEVELOPMENT = 'GP6_DEVELOPMENT_SYNTHETIC_ONLY'
GP6_ORDER = 'GP6_EXPOSED_TRAIN_JEV_F0_ONLY'
GP6_SCOPES = (GP6_DEVELOPMENT, GP6_ORDER)
GP6_METHOD = 'jev_no_memory'
GP6_MODEL = 'jev-1.14.0'
GP6_ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
GP6_API_KEY_ENV = 'TYPESAFE_API_KEY'
GP6_PROMPT_VERSION = 'packaging_load_en_v1'
GP6_FEATURE_VERSION = 'packaging_physical_facts_v1'
GP6_MAX_PER_JOB_SENDS = 19
GP6_MAX_SHARED_SENDS = 76


def jev_identity_fields() -> dict[str, str]:
    return {
        'runtime_version': GEOMETRY_JEV_VERSION,
        'publication_policy_digest': policy_digest(),
    }


def prepare_jev_plan(
    adapted,
    *,
    data_identity: str,
    scope: str = GP6_DEVELOPMENT,
    per_job_max_sends: int = GP6_MAX_PER_JOB_SENDS,
    shared_max_sends: int = GP6_MAX_SHARED_SENDS,
    request_ledger_path: str | None = None,
    call_ledger_path: str | None = None,
) -> dict:
    """Pure GP6 plan preparation. Formal plans are always DRAFT here."""
    from .candidate_backends import _identity

    require(scope in GP6_SCOPES and 1 <= len(adapted) <= 2, 'geometry_jev_plan_scope')
    require(
        type(per_job_max_sends) is int and 1 <= per_job_max_sends <= GP6_MAX_PER_JOB_SENDS,
        'geometry_jev_per_job_budget',
    )
    require(
        type(shared_max_sends) is int and 1 <= shared_max_sends <= GP6_MAX_SHARED_SENDS,
        'geometry_jev_shared_budget',
    )
    tasks = [copy.deepcopy(t['identity']) for t in adapted]
    jobs = [
        {'job_id': f'G{i:02d}', 'task_id': t['task_id'], 'backend': b, 'method': GP6_METHOD}
        for i, (t, b) in enumerate((t, b) for t in tasks for b in GEOMETRY_BACKENDS)
    ]
    plan = {
        **jev_identity_fields(),
        'version': 'geometry_jev_plan_v1',
        'status': 'DEVELOPMENT_READY' if scope == GP6_DEVELOPMENT else 'DRAFT',
        'scope': scope,
        'data_identity': data_identity,
        'source_identity': _identity()['source_identity'],
        'environment_digest': digest(environment()),
        'tasks': tasks,
        'jobs': jobs,
        'feature_profile': 'F0_existing_facts',
        'model': GP6_MODEL,
        'prompt_version': GP6_PROMPT_VERSION,
        'feature_version': GP6_FEATURE_VERSION,
        'event_limit': None,
        'extra_seeds': False,
        'per_job_max_sends': per_job_max_sends,
        'shared_max_sends': shared_max_sends,
        'model_calls_max': 0 if scope == GP6_DEVELOPMENT else shared_max_sends,
        'assessment_limit': 0 if scope == GP6_DEVELOPMENT else 76,
        'solver_limit': 0 if scope == GP6_DEVELOPMENT else 4096,
        'call_ledger_path': call_ledger_path,
        'request_ledger_path': request_ledger_path,
    }
    validate_jev_plan(plan)
    return plan


def validate_jev_plan(plan: dict) -> dict:
    from .candidate_backends import _identity

    validate_schema('geometry_jev_plan_v1', plan)
    require(all(plan.get(k) == v for k, v in jev_identity_fields().items()), 'geometry_jev_plan_identity')
    require(
        plan['source_identity'] == _identity()['source_identity']
        and plan['environment_digest'] == digest(environment()),
        'geometry_jev_plan_source_or_env_drift',
    )
    require(
        1 <= len(plan['tasks']) <= 2 and len({t['task_id'] for t in plan['tasks']}) == len(plan['tasks']),
        'geometry_jev_plan_tasks',
    )
    expected = [
        {'job_id': f'G{i:02d}', 'task_id': t['task_id'], 'backend': b, 'method': GP6_METHOD}
        for i, (t, b) in enumerate((t, b) for t in plan['tasks'] for b in GEOMETRY_BACKENDS)
    ]
    require(same_native(plan['jobs'], expected) and len(expected) <= 4, 'geometry_jev_matrix')
    synthetic = plan['scope'] == GP6_DEVELOPMENT
    require(
        all(t['origin'] == ('SYNTHETIC_FIXED' if synthetic else 'EXPOSED_TRAIN') for t in plan['tasks']),
        'geometry_jev_task_origin_scope',
    )
    if not synthetic:
        require(tuple(t['task_id'] for t in plan['tasks']) == TASK_IDS, 'geometry_jev_fixed_tasks')
        require(
            plan['status'] in ('DRAFT', 'FROZEN')
            and 0 < plan['model_calls_max'] <= plan['shared_max_sends'] <= GP6_MAX_SHARED_SENDS
            and 0 < plan['assessment_limit'] <= 76
            and 0 < plan['solver_limit'] <= 4096,
            'geometry_jev_formal_budget',
        )
        if plan['status'] == 'FROZEN':
            require(
                type(plan['call_ledger_path']) is str
                and bool(plan['call_ledger_path'])
                and type(plan['request_ledger_path']) is str
                and bool(plan['request_ledger_path']),
                'geometry_jev_frozen_ledgers_required',
            )
    else:
        require(
            plan['status'] == 'DEVELOPMENT_READY'
            and plan['model_calls_max'] == 0
            and plan['assessment_limit'] == 0
            and plan['solver_limit'] == 0,
            'geometry_jev_development_budget',
        )
    return plan


def development_binding(plan: dict) -> dict:
    validate_jev_plan(plan)
    require(plan['scope'] == GP6_DEVELOPMENT, 'geometry_jev_development_only')
    binding = {
        **jev_identity_fields(),
        'version': 'geometry_jev_development_binding_v1',
        'scope': GP6_DEVELOPMENT,
        'transport_evidence': 'TEST_DOUBLE',
        'monitor_evidence': 'TEST_DOUBLE',
        'plan_digest': digest(plan),
    }
    validate_schema('geometry_jev_development_binding_v1', binding)
    return binding


def validate_jev_kernel_receipt(receipt: dict, plan: dict, monitor_snapshot: dict) -> None:
    """Consume the independent GP5 evidence -> GP6 target binding contract."""
    from .geometry_jev_kernel_bridge import validate_kernel_bridge

    require(isinstance(receipt, dict), 'geometry_jev_kernel_receipt_required')
    if receipt.get('runtime_version') == 'jev_packaging_geometry_order_v17':
        require(False, 'geometry_jev_kernel_receipt_runtime_version_mismatch')
    validate_kernel_bridge(receipt, plan, monitor_snapshot)


def validate_jev_admission(plan: dict, monitor_snapshot: dict, admission: dict, kernel_receipt=None) -> bool:
    """Validate GP6 admission. Returns True iff real Jev transport is authorized."""
    validate_jev_plan(plan)
    if plan['scope'] == GP6_DEVELOPMENT:
        validate_schema('geometry_jev_development_binding_v1', admission)
        require(
            admission == development_binding(plan) and kernel_receipt is None,
            'geometry_jev_development_binding_drift',
        )
        return False

    require(plan['status'] == 'FROZEN', 'geometry_jev_draft_not_executable')
    require(admission is not None, 'gp6_real_transport_unauthorized')
    validate_schema('geometry_jev_admission_v1', admission)
    expected = {
        **jev_identity_fields(),
        'plan_digest': digest(plan),
        'source_identity': plan['source_identity'],
        'environment_digest': plan['environment_digest'],
        'monitor_digest': digest(monitor_snapshot),
        'scope': GP6_ORDER,
        'status': 'APPROVED',
    }
    require(all(admission.get(k) == v for k, v in expected.items()), 'geometry_jev_admission_binding')
    authorization = read_reference(admission['authorization'])
    review = read_reference(admission['review'])
    api_check = read_reference(admission['api_spec_check'])
    for doc in (authorization, review):
        require(
            doc.get('scope') == GP6_ORDER
            and doc.get('plan_digest') == digest(plan)
            and doc.get('status') == 'APPROVED',
            'geometry_jev_external_approval',
        )
    require(
        api_check.get('model') == plan['model']
        and api_check.get('endpoint') == GP6_ENDPOINT
        and api_check.get('status') == 'VERIFIED',
        'geometry_jev_api_spec_check',
    )
    validate_jev_kernel_receipt(kernel_receipt, plan, monitor_snapshot)
    return True


def draft_jev_run(plan: dict) -> dict:
    validate_jev_plan(plan)
    value = {
        **jev_identity_fields(),
        'version': 'geometry_jev_run_v1',
        'plan_digest': digest(plan),
        'rows': [{'job_id': j['job_id'], 'status': 'NOT_RUN', 'metrics': None} for j in plan['jobs']],
    }
    validate_schema('geometry_jev_run_v1', value)
    return value


def update_jev_run(run: dict, plan: dict, job_id: str, status: str, metrics=None) -> dict:
    require(
        run['plan_digest'] == digest(plan)
        and [r['job_id'] for r in run['rows']] == [j['job_id'] for j in plan['jobs']],
        'geometry_jev_run_denominator',
    )
    value = copy.deepcopy(run)
    row = next((r for r in value['rows'] if r['job_id'] == job_id), None)
    require(row is not None, 'geometry_jev_run_job')
    job = next(j for j in plan['jobs'] if j['job_id'] == job_id)
    if metrics is not None:
        require(
            metrics['task_id'] == job['task_id']
            and metrics['method'] == job['method']
            and metrics['candidate_backend'] == job['backend']
            and metrics['scope'] == plan['scope'],
            'geometry_jev_run_metrics_binding',
        )
        require((status == 'COMPLETE') == metrics['completed'], 'geometry_jev_run_completion_status')
    else:
        require(status in ('NOT_RUN', 'RUNNING', 'TECHNICAL_FAILURE', 'CANCELLED'), 'geometry_jev_run_metrics_required')
    row.update(status=status, metrics=metrics)
    validate_schema('geometry_jev_run_v1', value)
    return value
