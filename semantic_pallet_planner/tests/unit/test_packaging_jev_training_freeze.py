"""Offline freeze, immutable QA, fixed storage and refusal tests; no execution."""
import copy
import json
from pathlib import Path

import pytest

from test_packaging_jev_training_plan import prepared, ROOT, reseal
from semantic_pallet_planner.jev_select import packaging_jev_training_freeze as freeze
from semantic_pallet_planner.jev_select import packaging_jev_training_plan as plan
from semantic_pallet_planner.jev_select import packaging_jev_v13 as v13
from semantic_pallet_planner.jev_select.packaging_jev_sampling import SamplingError


def saved_plan_ref(prepared):
    return plan.ref((Path(prepared['assignments'][0]['execution_ref']['path']).parent/'training_plan.json').as_posix(), root=ROOT)


def receipt_seal(value):
    value['receipt_digest'] = plan.digest({k:v for k,v in value.items() if k != 'receipt_digest'})
    return value


def test_full_qa_freeze_and_drift_rejections(prepared):
    reference = saved_plan_ref(prepared)
    value = freeze.freeze_plan(reference, root=ROOT)
    assert value['formal_frozen'] and value['execution_authorized'] is False
    assert len(value['qa_refs']) == 10
    assert freeze.validate_frozen_plan(value, root=ROOT)['formal_freeze'] == 'FROZEN_OFFLINE'
    assert plan.load(reference, root=ROOT)['formal_frozen'] is False
    assert [value['budget'][k] for k in ('baseline_send_upper', 'initial_suffix_send_upper',
           'repeat_suffix_send_upper', 'suffix_send_upper', 'global_send_upper')] == [103,564,210,774,877]
    assert not Path(value['runtime_root']).exists()
    for case, code in [('root','FREEZE_OPERATION_ROOT_DRIFT'), ('runtime_path','FREEZE_IDENTITY_OR_BINDING_DRIFT'),
                       ('qa_hash','FREEZE_REFERENCE_BYTES_DRIFT'), ('qa_inventory','FREEZE_IDENTITY_OR_BINDING_DRIFT'),
                       ('budget','FREEZE_IDENTITY_OR_BINDING_DRIFT'), ('authorization','FREEZE_SCHEMA')]:
        changed = copy.deepcopy(value)
        if case == 'root': changed['operation_root'] += '_different'
        elif case == 'runtime_path': changed['runtime_root'] += '_different'
        elif case == 'qa_hash': changed['qa_refs'][0]['sha256'] = '0'*64
        elif case == 'qa_inventory': changed['qa_refs'][0] = copy.deepcopy(changed['qa_refs'][1])
        elif case == 'budget': changed['budget']['global_send_upper'] += 1
        elif case == 'authorization': changed['execution_authorized'] = True
        with pytest.raises(SamplingError, match=code):
            freeze.validate_frozen_plan(receipt_seal(changed), root=ROOT)


def test_missing_qa_defer_without_dispatch(prepared, monkeypatch):
    missing = freeze.PREP_QA_ROOT+'next_stage_admission.json'
    original = Path.is_file
    def visible(path):
        return False if path == ROOT/missing else original(path)
    monkeypatch.setattr(Path, 'is_file', visible)
    check = freeze.freeze_readiness(root=ROOT)
    assert check['status'] == 'DEFER_MISSING_QA' and check['missing'] == [missing]
    assert check['execution_authorized'] is False
    with pytest.raises(SamplingError, match='FREEZE_QA_MISSING_DEFER'):
        freeze.freeze_plan(saved_plan_ref(prepared), root=ROOT)


def test_receipt_is_never_sending_permission(prepared):
    value = freeze.freeze_plan(saved_plan_ref(prepared), root=ROOT)
    for stage in ('BASELINE', 'SUFFIX'):
        for permit in (None, {'authorized':True}):
            with pytest.raises(SamplingError, match='FREEZE_NOT_A_SEND_PERMIT'):
                freeze.require_send_authorization(value, root=ROOT, stage=stage, permit=permit)


def test_runtime_identity_drift(prepared, monkeypatch):
    value = freeze.freeze_plan(saved_plan_ref(prepared), root=ROOT)
    identity = v13.identity()
    monkeypatch.setattr(v13, 'identity', lambda:{**identity, 'dependencies':{**identity['dependencies'],'numpy':'CHANGED'}})
    with pytest.raises(SamplingError, match='PLAN_RUNTIME_DRIFT'):
        freeze.validate_frozen_plan(value, root=ROOT)


def test_resigned_different_execution_path_refused(prepared):
    """Even internally valid v13 allocations cannot relocate the frozen job root."""
    row = prepared['assignments'][0]
    old = plan.load(row['execution_ref'], root=ROOT)
    modified = v13.freeze_execution(old['task'], old['config'],
        job_id=old['job_id'].rsplit('_',1)[0], root=Path(old['storage_root']).parent/'relocated')
    execution_path = ROOT/row['execution_ref']['path']
    execution_path.write_text(json.dumps(modified))
    row['execution_ref'] = plan.ref(row['execution_ref']['path'], root=ROOT)
    row['job_id'] = modified['job_id']
    prepared['budget'] = plan.budgets(prepared['assignments'])
    schedule = plan.load(prepared['schedule_ref'], root=ROOT)
    schedule['executions'][0] = modified
    replacement = v13.freeze_schedule(schedule['executions'], root=schedule['storage_root'], global_max_sends=103)
    schedule_path = ROOT/prepared['schedule_ref']['path']
    schedule_path.write_text(json.dumps(replacement))
    prepared['schedule_ref'] = plan.ref(prepared['schedule_ref']['path'], root=ROOT)
    reference = saved_plan_ref(prepared)
    (ROOT/reference['path']).write_text(json.dumps(reseal(prepared)))
    reference = plan.ref(reference['path'], root=ROOT)
    with pytest.raises(SamplingError, match='FREEZE_JOB_PATH_DRIFT'):
        freeze.freeze_plan(reference, root=ROOT)


def test_historical_preparation_cannot_be_frozen_in_place(prepared):
    reference = plan.ref(freeze.HISTORICAL_PLAN, root=ROOT)
    with pytest.raises(SamplingError, match='FREEZE_NEW_PLAN_REQUIRED'):
        freeze.freeze_plan(reference, root=ROOT)
