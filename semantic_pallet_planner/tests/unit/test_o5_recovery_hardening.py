"""Fault boundaries that must be checked before resuming another decision."""
import socket
import pytest

from semantic_pallet_planner.o5 import episode
from semantic_pallet_planner.o5.common import O5Error, atomic, read
from semantic_pallet_planner.o5.config import DEFAULT
from semantic_pallet_planner.o5.testing import OfflineTransport, fixture_task


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError('offline test attempted a network connection')
    monkeypatch.setattr(socket.socket, 'connect', reject)
    monkeypatch.setattr(socket, 'create_connection', reject)


def test_recovery_hardening_request_mapping_write_gap(tmp_path, monkeypatch):
    original = episode.atomic
    failed = False
    def crash(path, value):
        nonlocal failed
        if path.name == 'mapping.private.json' and not failed:
            failed = True
            raise KeyboardInterrupt('crash between durable request/mapping writes')
        return original(path, value)
    monkeypatch.setattr(episode, 'atomic', crash)
    task = fixture_task()
    first = OfflineTransport()
    with pytest.raises(KeyboardInterrupt):
        episode.run_episode(task, 'D0', DEFAULT, tmp_path, 'job', 'nonce', transport=first)
    assert not first.calls
    monkeypatch.setattr(episode, 'atomic', original)
    resumed = OfflineTransport()
    result = episode.run_episode(task, 'D0', DEFAULT, tmp_path, 'job', 'nonce', transport=resumed, resume=True)
    assert result['summary']['completed'] and len(resumed.calls) == 14


def test_recovery_hardening_missing_ledger_cannot_reset_budget(tmp_path):
    task = fixture_task()
    episode.run_episode(task, 'D0', DEFAULT, tmp_path, 'job', 'nonce', transport=OfflineTransport(), stop_after=1)
    (tmp_path/'ledger.json').unlink()
    resumed = OfflineTransport()
    with pytest.raises(O5Error, match='MISSING_LEDGER'):
        episode.run_episode(task, 'D0', DEFAULT, tmp_path, 'job', 'nonce', transport=resumed, resume=True)
    assert not resumed.calls and not (tmp_path/'ledger.json').exists()


def test_recovery_hardening_saved_ledger_checked_before_next_call(tmp_path):
    task = fixture_task()
    episode.run_episode(task, 'D0', DEFAULT, tmp_path, 'job', 'nonce', transport=OfflineTransport(), stop_after=1)
    ledger = read(tmp_path/'ledger.json')
    response = ledger['attempts'][0]['response']
    response.update(action='STOP', candidate_id=None)
    atomic(tmp_path/'ledger.json', ledger)
    resumed = OfflineTransport()
    with pytest.raises(O5Error, match='DECISION_LEDGER_RECOMPUTATION_MISMATCH'):
        episode.run_episode(task, 'D0', DEFAULT, tmp_path, 'job', 'nonce', transport=resumed, resume=True)
    assert not resumed.calls


def test_recovery_hardening_pending_g0_checks_original_image(tmp_path):
    task = fixture_task()
    episode.run_episode(task, 'G0', DEFAULT, tmp_path, 'job', 'nonce', stop_after=1)
    # Existing first-step artifacts are independently verified before continuation.
    (tmp_path/'decisions/000/workspace.png').write_bytes(b'changed')
    with pytest.raises(O5Error, match='IMAGE_CHANGED'):
        episode.run_episode(task, 'G0', DEFAULT, tmp_path, 'job', 'nonce', resume=True)


def test_recovery_hardening_mapping_can_be_rebuilt_from_intact_pending_request(tmp_path, monkeypatch):
    original = episode.direct_choice
    def crash(*args, **kwargs):
        raise KeyboardInterrupt('request persisted but decision not started')
    monkeypatch.setattr(episode, 'direct_choice', crash)
    task = fixture_task()
    with pytest.raises(KeyboardInterrupt):
        episode.run_episode(task, 'D0', DEFAULT, tmp_path, 'job', 'nonce', transport=OfflineTransport())
    (tmp_path/'decisions/000/mapping.private.json').unlink()
    monkeypatch.setattr(episode, 'direct_choice', original)
    transport = OfflineTransport()
    result = episode.run_episode(task, 'D0', DEFAULT, tmp_path, 'job', 'nonce', transport=transport, resume=True)
    assert result['summary']['completed'] and len(transport.calls) == 14


def test_recovery_hardening_uncommitted_g0_checks_original_image(tmp_path, monkeypatch):
    original = episode.geometry_choice
    def crash(*args, **kwargs):
        raise KeyboardInterrupt('pending G0 has no committed journal yet')
    monkeypatch.setattr(episode, 'geometry_choice', crash)
    task = fixture_task()
    with pytest.raises(KeyboardInterrupt):
        episode.run_episode(task, 'G0', DEFAULT, tmp_path, 'job', 'nonce')
    (tmp_path/'decisions/000/workspace.png').write_bytes(b'changed')
    monkeypatch.setattr(episode, 'geometry_choice', original)
    with pytest.raises(O5Error, match='IMAGE_CHANGED'):
        episode.run_episode(task, 'G0', DEFAULT, tmp_path, 'job', 'nonce', resume=True)
