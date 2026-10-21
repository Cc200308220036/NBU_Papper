import json
from pathlib import Path
import socket

import pytest

from semantic_pallet_planner.runners import layout_flash_validation_v2 as v2
from semantic_pallet_planner.vlm.policy_protocol_o2b import VERSION


@pytest.fixture(scope='module')
def baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp('stable-v2')/'reference'
    with pytest.MonkeyPatch.context() as patch:
        def forbidden(*args, **kwargs):
            raise AssertionError('stage 1-4 must not access network')
        patch.setattr(socket, 'create_connection', forbidden)
        patch.setattr(v2.LayoutFlashClient, 'complete', forbidden)
        result = v2.run(root, scenarios=['SCN_0055'], variants=('original',), modes=('safe',))
    assert result['status'] == 'PASS' and result['remote_calls'] == 0
    assert result['baseline_role'] == 'reference_build'
    return root


def test_v2_reference_replayed_without_mutating_original(baseline):
    result = v2.replay(baseline)
    assert result['status'] == 'PASS' and result['episodes'] == 2
    assert result['reference_kind'] == 'frozen_original_control_only'


def test_v2_peer_matches_all_selected_reference_episodes(tmp_path, baseline):
    root = tmp_path/'peer'
    result = v2.run(root, scenarios=['SCN_0055'], variants=('original',), modes=('safe',), baseline=baseline)
    assert result['status'] == 'PASS' and result['cross_runtime_status'] == 'REFERENCE_MATCHED'
    assert json.loads((root/'replay_report.json').read_text())['reference_steps_compared'] == 34


def test_remote_requires_certified_v2_reference_before_any_call(tmp_path, baseline, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-only')
    def forbidden(*args, **kwargs):
        raise AssertionError('must reject before API call')
    monkeypatch.setattr(v2.LayoutFlashClient, 'complete', forbidden)
    with pytest.raises(ValueError, match='requires'):
        v2.run(tmp_path/'no-ref', remote=True)
    with pytest.raises(FileNotFoundError):
        v2.run(tmp_path/'no-cert', remote=True, baseline=baseline,
               scenarios=['SCN_0055'], variants=('original',), modes=('safe',))
    assert not (tmp_path/'no-ref').exists() and not (tmp_path/'no-cert').exists()


def test_stable_flash_ast_dispatch_all_variants(tmp_path, baseline):
    task = json.loads((baseline/'data/tasks.private.json').read_text())[0]
    _, events = v2.events_at(baseline, 'safe', 'original', 'public_parser', task)
    req = events[0]['request']
    policy = v2.resolved_public_policy(req['instruction_text'], req)
    policy['hard_constraints'][0]['threshold_kg'] = 999.
    envelope = {'schema_version': VERSION, **{k: req[k] for k in ('request_id', 'state_hash', 'policy_digest')},
                'policy_ast': policy}
    class Simulated:
        def complete(self, prompt):
            return {'provider_payload': {'choices': [{'message': {'content': json.dumps(envelope)}}]},
                    'cache_hit': False, 'latency_s': 0.}
    parsed = v2.Session(Simulated(), 1).parse(tmp_path/'synthetic-only', req)
    mapping = {c['display_label']: c for c in req['candidates']}
    for variant in v2.VARIANTS:
        chosen = v2.decide(req, mapping, parsed['parsed']['policy_ast'], 'safe', variant)
        assert chosen['policy_ast'] == policy
        assert chosen['trace']['ranking_version'] == v2.RANKING_VERSION
