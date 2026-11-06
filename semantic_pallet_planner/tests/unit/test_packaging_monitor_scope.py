"""Scope routing after successful placements; constructed tasks, no real sends."""
import copy
import socket
from dataclasses import replace

import pytest

from semantic_pallet_planner.jev_select import packaging_experiment as common
from semantic_pallet_planner.jev_select import packaging_evaluation_orders as evaluation
from semantic_pallet_planner.jev_select import packaging_memory_pilot as pilot
from semantic_pallet_planner.jev_select import packaging_synthetic_orders as synthetic
from semantic_pallet_planner.jev_select import transport
from semantic_pallet_planner.jev_select.contracts import JevSelectError
from semantic_pallet_planner.jev_select.ledger import read
from test_packaging_evaluation_v10 import setup as evaluation_setup
from test_packaging_memory_pilot import setup as pilot_setup
from test_packaging_synthetic_execution import prepare, factory
from test_packaging_remote import Fake


@pytest.fixture(autouse=True)
def block_external_access(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('scope regression attempted network or credential access')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(transport, 'credential', forbidden)


def checkpoint():
    def event(status, reason_code, **kwargs):
        return {'monitor': {'status': status, 'result': {'status': status, 'reason_code': reason_code}}, **kwargs}
    return {'phase': 'TERMINATED', 'reason': 'STABILITY_UNASSESSABLE', 'pending_event': None,
            'events': [event('STABLE', 'CONTACT_NETWORK_BALANCED', event='PLACE'),
                       event('UNASSESSABLE', 'POSE_HEIGHT_MISMATCH', event='STOP', reason='STABILITY_UNASSESSABLE')]}


def test_scope_extraction_excludes_success_without_mutating_saved_facts():
    cp = checkpoint(); before = copy.deepcopy(cp)
    assert common.unassessable_reasons_from_checkpoint(cp) == {'POSE_HEIGHT_MISMATCH'}
    assert cp == before


@pytest.mark.parametrize('corruption', ['missing_monitor', 'missing_result', 'missing_reason',
    'empty_reason', 'contradictory_status', 'wrong_stop', 'wrong_phase', 'pending', 'no_failure'])
def test_scope_extraction_fails_closed(corruption):
    cp = checkpoint(); last = cp['events'][-1]
    if corruption == 'missing_monitor': last['monitor'] = None
    elif corruption == 'missing_result': last['monitor']['result'] = None
    elif corruption == 'missing_reason': del last['monitor']['result']['reason_code']
    elif corruption == 'empty_reason': last['monitor']['result']['reason_code'] = ' '
    elif corruption == 'contradictory_status': last['monitor']['result']['status'] = 'STABLE'
    elif corruption == 'wrong_stop': last['reason'] = 'PREDICTED_STATIC_INSTABILITY'
    elif corruption == 'wrong_phase': cp['phase'] = 'MONITORED'
    elif corruption == 'pending': cp['pending_event'] = copy.deepcopy(last)
    elif corruption == 'no_failure': last['monitor'] = copy.deepcopy(cp['events'][0]['monitor'])
    with pytest.raises(JevSelectError, match='invalid_unassessable_checkpoint'):
        common.unassessable_reasons_from_checkpoint(cp)


@pytest.mark.parametrize('engine', ['v9', 'v10', 'v11'])
@pytest.mark.parametrize('reason', ['POSE_HEIGHT_MISMATCH', 'CONSTRUCTED_UNREGISTERED_RANGE'])
def test_mixed_success_and_range_routes_batch_and_preserves_failed_action(tmp_path, monkeypatch, engine, reason):
    if engine == 'v9':
        plan, fake, make = pilot_setup(tmp_path, monkeypatch, n=3, tasks=2)
        run = lambda **kw: pilot.run(tmp_path/'plan', tmp_path/'run', transport_factory=make, **kw)
        first_block = 3
    elif engine == 'v10':
        plan, fake = evaluation_setup(tmp_path, n=3, tasks=2)
        run = lambda **kw: evaluation.run_validation(tmp_path/'plan', tmp_path/'run', transport_factory=lambda *a: fake, **kw)
        first_block = 6
    else:
        plan = prepare(tmp_path, tasks=2, n=3); fake = Fake()
        run = lambda **kw: synthetic.run_constructed(tmp_path/'plan', tmp_path/'run', transport_factory=factory(fake), **kw)
        first_block = 6
    from semantic_pallet_planner.jev_select.stability import balance_adapter
    original = balance_adapter.assess_candidate
    def range_after_successes(state, candidate, config=None):
        result = original(state, candidate, config)
        return replace(result, status='UNASSESSABLE', reason_code=reason) if len(state.placed) == 2 else result
    monkeypatch.setattr(balance_adapter, 'assess_candidate', range_after_successes)
    result = run(); root = tmp_path/'run'
    allowed = reason == 'POSE_HEIGHT_MISMATCH'
    assert result['status'] == ('PASS_IN_EXECUTED_SCOPE' if allowed else 'ERROR')
    closed = first_block if allowed else 1
    assert result['categories']['UNASSESSABLE'] == closed
    assert result['categories']['NOT_RUN'] == len(plan['jobs']) - closed
    for job in plan['jobs'][:closed]:
        cp = read(root/'jobs'/job['job_id']/'checkpoint.json')
        metrics = read(root/'jobs'/job['job_id']/'metrics.json')
        assert metrics['monitor_reasons'] == {'CONTACT_NETWORK_BALANCED': 2, reason: 1}
        assert cp['state']['placed_count'] == 2
        failed = cp['events'][-1]
        assert failed['event'] == 'STOP' and failed['before'] == failed['after']
        assert failed['action'] is None and cp['state']['pending_items']
    if allowed:
        assert not (root/'technical_failure.json').exists()
    else:
        assert (root/'technical_failure.json').exists()
        calls = fake.calls
        run(resume=True, continue_pending=True)
        assert fake.calls == calls
        assert read(root/'jobs'/plan['jobs'][1]['job_id']/'status.json')['state'] == 'NOT_RUN'
