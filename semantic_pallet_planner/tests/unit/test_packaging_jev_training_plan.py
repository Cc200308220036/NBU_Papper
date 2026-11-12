"""Actual-task offline preparation; traps prevent any experiment execution."""
import copy
from pathlib import Path
import socket
import tempfile

import pytest

from semantic_pallet_planner.jev_select import packaging_jev_training_plan as plan
from semantic_pallet_planner.jev_select import packaging_jev_v13 as v13
from semantic_pallet_planner.jev_select import packaging_jev_sampling as sampling
from semantic_pallet_planner.jev_select import packaging_jev_training_template as template

ROOT = Path(__file__).resolve().parents[3]
CATALOG = 'semantic_pallet_planner/outputs/JEV_JM1_B2_20261111_01/task_source_candidates.json'


def reseal(value):
    value['plan_digest'] = plan.digest({k:v for k,v in value.items() if k != 'plan_digest'})
    return value


@pytest.fixture
def prepared(monkeypatch):
    from semantic_pallet_planner.jev_select import episode, transport
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
    from semantic_pallet_planner.jev_select.stability import exact_adapter, balance_adapter
    import scipy.optimize
    def forbidden(*a, **kw):
        pytest.fail('OFFLINE_BOUNDARY_VIOLATION')
    for owner, name in [(socket.socket, 'connect'), (transport, 'credential'),
                        (CandidateProvider, 'build'), (episode, 'run_episode'),
                        (v13, 'run_execution'), (v13, 'run_scheduled'),
                        (sampling, 'sample'), (exact_adapter, 'assess_candidate'),
                        (balance_adapter, 'assess_candidate'), (scipy.optimize, 'linprog')]:
        monkeypatch.setattr(owner, name, forbidden)
    with tempfile.TemporaryDirectory(dir=ROOT/'semantic_pallet_planner/outputs', prefix='JM_B2_TEST_') as temp:
        output = Path(temp).relative_to(ROOT)/'plan'
        value = plan.prepare_plan(root=ROOT, output=output, catalog_path=CATALOG, inputs=plan.REQUIRED_INPUTS)
        yield value


def test_actual_saved_plan(prepared):
    checked = plan.validate_plan(prepared, root=ROOT)
    assert checked['saved_facts'] == 'PASS'
    assert checked['execution_authorized'] is False
    assert checked['baseline_send_upper'] == 103
    assert checked['suffix_send_upper'] == 774
    assert prepared['budget']['total_suffix_cap'] == 48
    assert [r['wave'] for r in prepared['assignments']] == [1,1,1,2,2,2]
    assert all(r['partition'] == 'train' for r in prepared['assignments'])
    assert not any((Path(r['execution_ref']['path']).parent/'future_runs').exists() for r in prepared['assignments'])
    assert prepared['sampling']['epsilon'] == plan.DEFER


@pytest.mark.parametrize('case,code', [
    ('duplicate_task', 'PLAN_DUPLICATE_TASK'),
    ('duplicate_slot', 'PLAN_DUPLICATE_SLOT'),
    ('budget', 'PLAN_BUDGET'),
    ('missing_input', 'PLAN_REQUIRED_INPUTS'),
    ('arrival', 'PLAN_ARRIVAL_DRIFT'),
    ('epsilon', 'PLAN_SCHEMA'),
    ('authorized', 'PLAN_SCHEMA'),
    ('wave', 'PLAN_SLOT_ORDER'),
    ('model', 'PLAN_MODEL_CHANGED'),
    ('missing_qa_erased', 'PLAN_QA_INVENTORY'),
])
def test_refuse_mutations(prepared, case, code):
    value = copy.deepcopy(prepared)
    if case == 'duplicate_task': value['assignments'][1]['task_id'] = value['assignments'][0]['task_id']
    elif case == 'duplicate_slot': value['assignments'][1]['slot_id'] = value['assignments'][0]['slot_id']
    elif case == 'budget': value['budget']['global_send_upper'] += 1
    elif case == 'missing_input': value['input_refs'].pop()
    elif case == 'arrival': value['assignments'][0]['arrival_digest'] = '0'*64
    elif case == 'epsilon': value['sampling']['epsilon'] = 0
    elif case == 'authorized': value['execution_authorized'] = True
    elif case == 'wave': value['assignments'][0]['wave'] = 2
    elif case == 'model': value['model_declaration']['requested_model'] = 'changed'
    elif case == 'missing_qa_erased': value['missing_qa'] = []
    with pytest.raises(sampling.SamplingError, match=code):
        plan.validate_plan(reseal(value), root=ROOT)


def test_identity_drift(prepared, monkeypatch):
    identity = v13.identity()
    monkeypatch.setattr(v13, 'identity', lambda:{**identity, 'source':'0'*64})
    with pytest.raises(sampling.SamplingError, match='PLAN_RUNTIME_DRIFT'):
        plan.validate_plan(prepared, root=ROOT)


def test_saved_bytes_drift_and_missing(prepared):
    path = ROOT/prepared['assignments'][0]['execution_ref']['path']
    raw = path.read_bytes()
    path.write_bytes(raw+b' ')
    with pytest.raises(sampling.SamplingError, match='B2_SAVED_BYTES_CHANGED'):
        plan.validate_plan(prepared, root=ROOT)
    path.unlink()
    with pytest.raises(sampling.SamplingError, match='B2_MISSING_SAVED_FILE'):
        plan.validate_plan(prepared, root=ROOT)


def test_old_template_refused(prepared):
    old = template.make_template(policy_ref=prepared['input_refs'][0], source_candidates_ref=prepared['catalog_ref'])
    with pytest.raises(sampling.SamplingError, match='PLAN_SCHEMA'):
        plan.validate_plan(old, root=ROOT)


@pytest.mark.parametrize('stage', ['BASELINE', 'SUFFIX'])
def test_send_gates_refuse_even_fake_permit(prepared, stage):
    for permit in (None, {'authorized':True}):
        with pytest.raises(sampling.SamplingError, match='PLAN_SEND_NOT_AUTHORIZED'):
            plan.require_send_authorization(prepared, root=ROOT, stage=stage, permit=permit)


def test_missing_preparation_materials(tmp_path):
    with pytest.raises((sampling.SamplingError, FileNotFoundError)):
        plan.prepare_plan(root=tmp_path, output='plan', catalog_path='absent.json', inputs=plan.REQUIRED_INPUTS)
    assert not (tmp_path/'plan').exists()


def test_smaller_scope_budget(prepared):
    audit = plan.load(prepared['audit_ref'], root=ROOT)['rows']
    rows = plan.select_tasks(audit, 2)
    budget = plan.budgets([{**r, 'job_id':'capacity_'+r['task_id']} for r in rows])
    assert budget['point_cap'] == 4 and budget['total_suffix_cap'] == 24
    with pytest.raises(sampling.SamplingError, match='PLAN_TASK_CAP'):
        plan.select_tasks(audit, 7)
