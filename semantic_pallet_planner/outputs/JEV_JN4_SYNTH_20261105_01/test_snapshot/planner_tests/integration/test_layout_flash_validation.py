"""No real API calls: protocol failures, bound AST dispatch, replay and CLI gates."""
import copy
import json
import socket
import subprocess
import sys

import pytest

from semantic_pallet_planner.config import load_config
from semantic_pallet_planner.domain import PalletState
from semantic_pallet_planner.config import generator_config
from semantic_pallet_planner.planner.generator import ExtremePointGenerator
from semantic_pallet_planner.repository import DatasetRepository
from semantic_pallet_planner.runners import layout_flash_validation as runner
from semantic_pallet_planner.runners.attribute_o3_online import step_state
from semantic_pallet_planner.runners.o3_online_adapter import public_request
from semantic_pallet_planner.selectors.instruction_parser_o1b import resolved_public_policy
from semantic_pallet_planner.vlm.deepseek_client import DeepSeekClientError
from semantic_pallet_planner.vlm.pilot_protocol_v2 import digest
from semantic_pallet_planner.vlm.policy_protocol_o2b import VERSION


def raw(req, ast=None):
    envelope = {'schema_version': VERSION,
        **{k: req[k] for k in ('request_id', 'state_hash', 'policy_digest')},
        'policy_ast': ast or resolved_public_policy(req['instruction_text'], req)}
    return {'provider_payload': {'model': 'test-only', 'id': 'synthetic',
        'choices': [{'message': {'content': json.dumps(envelope)}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 20}}, 'latency_s': .01, 'cache_hit': False}


class Stub:
    """Explicit unit-test dependency; cannot be passed to the public run() API."""
    def __init__(self, values):
        self.values = iter(values)
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        result = next(self.values)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(scope='module')
def scene():
    cfg = load_config(seed=20261015, top_k=16, topk_mode='diverse_v1', fallback_policy='abort')
    repo = DatasetRepository(cfg['dataset'])
    tasks, _ = runner.plan(repo, 'validation', ['SCN_0054'])
    scenario = repo.get_scenario('SCN_0054')
    state = step_state(scenario, tasks[0], [], 0)
    generated = ExtremePointGenerator(generator_config(cfg)).generate(PalletState.from_dict(state))
    req, mapping, _ = public_request(state, generated.candidate_set.data['candidates'], tasks[0]['instruction_text'], seed=cfg['seed'])
    return cfg, repo, tasks, scenario, req, mapping


def test_repair_retains_both_raw_responses_and_replays(tmp_path, scene):
    req = scene[4]
    bad = raw(req)
    bad['provider_payload']['choices'][0]['message']['content'] = 'invalid JSON'
    stub = Stub([bad, raw(req)])
    session = runner.Session(stub, 5)
    result = session.parse(tmp_path/'call', req)
    assert result['parsed'] and len(result['attempts']) == session.used == 2
    assert result == runner.saved_parse(tmp_path/'call', req)
    assert (tmp_path/'call/initial.raw.json').exists()
    assert (tmp_path/'call/repair.raw.json').exists()


@pytest.mark.parametrize('field', ['request_id', 'state_hash', 'policy_digest'])
def test_cross_step_binding_cannot_be_repaired_by_fallback(tmp_path, scene, field):
    req = scene[4]
    wrong = copy.deepcopy(req)
    wrong[field] = 'wrong-step'
    session = runner.Session(Stub([raw(wrong), raw(wrong)]), 5)
    result = session.parse(tmp_path/'call', req)
    assert result['status'] == 'invalid_response' and result['parsed'] is None
    assert session.used == 2
    assert runner.saved_parse(tmp_path/'call', req) == result
    decision = runner.decide(req, scene[5], None, 'safe', 'original', result['status'])
    assert decision['committed_label'] is None and decision['policy_ast'] is None


def test_transport_error_has_no_repair_or_exception_secret(tmp_path, scene):
    req = scene[4]
    session = runner.Session(Stub([DeepSeekClientError('timeout', 'SECRET')]), 10)
    result = session.parse(tmp_path/'call', req)
    assert session.used == 1 and result['status'] == 'provider_error'
    assert runner.saved_parse(tmp_path/'call', req) == result
    assert 'SECRET' not in ''.join(p.read_text() for p in (tmp_path/'call').iterdir())


def test_budget_stops_before_repair_and_before_next_request(tmp_path, scene):
    req = scene[4]
    bad = raw(req)
    bad['provider_payload']['choices'][0]['message']['content'] = '{}'
    stub = Stub([bad])
    session = runner.Session(stub, 1)
    one = session.parse(tmp_path/'one', req)
    two = session.parse(tmp_path/'two', req)
    assert one['status'] == two['status'] == 'api_budget_exhausted'
    assert len(one['attempts']) == 1 and two['attempts'] == [] and stub.calls == 1
    assert runner.saved_parse(tmp_path/'one', req) == one
    assert runner.saved_parse(tmp_path/'two', req) == two


@pytest.mark.parametrize('variant', runner.VARIANTS)
def test_flash_ast_enters_requested_layout_variant_without_parser_substitution(tmp_path, scene, monkeypatch, variant):
    req, mapping = scene[4:]
    ast = resolved_public_policy(req['instruction_text'], req)
    ast = copy.deepcopy(ast)
    ast['hard_constraints'][0]['threshold_kg'] = 999.
    result = runner.Session(Stub([raw(req, ast)]), 1).parse(tmp_path/'call', req)
    seen = []
    actual = runner.select_layout
    def spy(request, policy, selected_variant, **kwargs):
        seen.append((copy.deepcopy(policy), selected_variant))
        return actual(request, policy, selected_variant, **kwargs)
    monkeypatch.setattr(runner, 'select_layout', spy)
    out = runner.decide(req, mapping, result['parsed']['policy_ast'], 'safe', variant)
    assert seen == [(ast, variant)]
    assert out['resolved_policy'] == ast
    assert out['trace']['variant'] == variant


def test_saved_ast_tampering_detected(tmp_path, scene):
    req = scene[4]
    folder = tmp_path/'call'
    runner.Session(Stub([raw(req)]), 1).parse(folder, req)
    p = folder/'attempts.json'
    value = json.loads(p.read_text())
    value['parsed']['policy_ast']['hard_constraints'][0]['threshold_kg'] = 99.
    p.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='AST'):
        runner.saved_parse(folder, req)


def test_cached_response_rejected(tmp_path, scene):
    req = scene[4]
    cached = raw(req)
    cached['cache_hit'] = True
    session = runner.Session(Stub([cached]), 2)
    result = session.parse(tmp_path/'call', req)
    assert result['status'] == 'invalid_response' and result['parsed'] is None and session.used == 1
    assert runner.saved_parse(tmp_path/'call', req) == result


def test_mocked_closed_loop_flash_uses_new_state_each_step(tmp_path, scene):
    cfg, _, tasks, scenario, _, _ = scene
    scenario = copy.deepcopy(scenario)
    scenario['arrival_order'] = scenario['arrival_order'][:2]
    calls = []
    class Echo:
        def complete(self, prompt):
            req = json.loads(prompt.user_text)
            calls.append(req)
            return raw(req)
    session = runner.Session(Echo(), 10)
    summary, events = runner.episode(tmp_path, scenario, tasks[0], 'relaxed_wo_floor', 'observe_business', cfg, 'flash', session)
    assert len(calls) == 2 and calls[0]['state_hash'] != calls[1]['state_hash']
    assert calls[1]['placed_items'] == events[0]['after_placed']
    again, _ = runner.episode(tmp_path, scenario, tasks[0], 'relaxed_wo_floor', 'observe_business', cfg, 'flash', replay_events=events)
    assert again == summary and session.used == 2


@pytest.fixture(scope='module')
def offline(tmp_path_factory):
    root = tmp_path_factory.mktemp('layout-flash')/'offline'
    # Assert a stronger invariant than checking a zero counter after the fact.
    with pytest.MonkeyPatch.context() as patch:
        def forbidden(*args, **kwargs):
            raise AssertionError('offline mode attempted network access')
        patch.setattr(socket, 'create_connection', forbidden)
        patch.setattr(runner.LayoutFlashClient, 'complete', forbidden)
        result = runner.run(root, scenarios=['SCN_0055'], variants=('original',), modes=('safe',))
    assert result['status'] == 'PASS' and result['episodes'] == 2 and result['remote_calls'] == 0
    return root


@pytest.mark.parametrize('target', ['ast', 'action', 'summary', 'aggregate', 'csv'])
def test_offline_replay_detects_tampering_even_with_updated_digest(offline, target):
    root = offline
    manifest = json.loads((root/'manifest.json').read_text())
    task = json.loads((root/'data/tasks.private.json').read_text())[0]
    folder, events = runner.events_at(root, manifest['modes'][0], manifest['variants'][0], 'public_parser', task)
    step, ep, agg = folder/'steps.jsonl', folder/'episode.json', root/'metrics/summary.json'
    table = root/'metrics/per_episode.csv'
    backups = {p: p.read_text() for p in (step, ep, agg, table)}
    try:
        record = json.loads(ep.read_text())
        if target == 'ast':
            events[0]['policy_ast']['hard_constraints'][0]['threshold_kg'] = 999.
        elif target == 'action':
            events[0]['committed_label'] = 'C99'
        elif target == 'summary':
            record['summary']['clean_completed'] = not record['summary']['clean_completed']
        elif target == 'aggregate':
            value = json.loads(agg.read_text())
            value[next(iter(value))]['completed'] = 999
            agg.write_text(json.dumps(value))
        else:
            table.write_text('forged,table\n1,2\n')
        record['events_digest'] = digest(events)
        step.write_text(''.join(json.dumps(e)+'\n' for e in events))
        ep.write_text(json.dumps(record))
        result = runner.replay(root)
        assert result['status'] == 'FAIL' and result['failures']
    finally:
        for p, content in backups.items():
            p.write_text(content)


def test_reject_overwrite_invalid_scenarios_and_missing_key(tmp_path, offline, scene, monkeypatch):
    with pytest.raises(FileExistsError):
        runner.run(offline)
    with pytest.raises(ValueError, match='unique members'):
        runner.plan(scene[1], 'validation', ['SCN_0001'])
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    with pytest.raises(ValueError, match='DEEPSEEK_API_KEY'):
        runner.run(tmp_path/'remote', remote=True)
    assert not (tmp_path/'remote').exists()


def test_cli_help_and_conflicting_flags(tmp_path):
    base = [sys.executable, '-m', 'semantic_pallet_planner.runners.layout_flash_validation']
    help_result = subprocess.run(base+['--help'], capture_output=True, text=True)
    assert help_result.returncode == 0 and '--execution-modes' in help_result.stdout
    result = subprocess.run(base+['--output', str(tmp_path/'bad'), '--offline-only', '--remote'], capture_output=True, text=True)
    assert result.returncode == 2 and not (tmp_path/'bad').exists()


def test_remote_budget_exhaustion_is_partial_not_pass(tmp_path, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'unit-test-only')
    calls = []
    def echo(self, prompt):
        req = json.loads(prompt.user_text)
        calls.append(req)
        return raw(req)
    monkeypatch.setattr(runner.LayoutFlashClient, 'complete', echo)
    root = tmp_path/'synthetic-remote-budget'
    result = runner.run(root, scenarios=['SCN_0055'], variants=('original',),
                        modes=('safe',), remote=True, max_api_attempts=1)
    assert result['status'] == 'PARTIAL' and result['remote_calls'] == len(calls) == 1
    assert result['episodes'] == 4 and result['api_incomplete']
    assert json.loads((root/'replay_report.json').read_text())['status'] == 'PASS'
    assert json.loads((root/'api_usage.json').read_text())['actual_attempts'] == 1


def test_transport_records_actual_payload_and_no_credentials(scene, monkeypatch):
    import io
    from semantic_pallet_planner.vlm import layout_flash_client as transport
    req = scene[4]
    payload = raw(req)['provider_payload']
    seen = []
    def fake_urlopen(request, timeout):
        seen.append((json.loads(request.data), timeout, request.get_header('Authorization')))
        return io.BytesIO(json.dumps(payload).encode())
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'unit-test-secret')
    monkeypatch.setattr(transport.urllib.request, 'urlopen', fake_urlopen)
    prompt, recorded = runner.prompt_record(req)
    result = transport.LayoutFlashClient().complete(prompt)
    assert result['provider_payload'] == payload and result['cache_hit'] is False
    assert seen == [(recorded['http_body'], 60., 'Bearer unit-test-secret')]
    assert 'unit-test-secret' not in json.dumps(result)
    assert 'unit-test-secret' not in json.dumps(recorded)


def test_semantic_ast_comparison_normalizes_constraint_order(scene):
    req = scene[4]
    policy = resolved_public_policy(req['instruction_text'], req)
    reordered = copy.deepcopy(policy)
    reordered['hard_constraints'].reverse()
    reordered['soft_priorities'].reverse()
    assert runner.normalized_policy(policy) == runner.normalized_policy(reordered)
    reordered['hard_constraints'] = copy.deepcopy(policy['hard_constraints'])
    reordered['hard_constraints'][0]['threshold_kg'] = 99.
    assert runner.normalized_policy(policy) != runner.normalized_policy(reordered)
