"""O5 behavior/invariant tests. Socket calls are forbidden for every test."""
import base64
import copy
import json
import socket
from pathlib import Path
import pytest
from semantic_pallet_planner.o5.common import O5Error, read, atomic, digest
from semantic_pallet_planner.o5.config import DEFAULT, load, geometry_config
from semantic_pallet_planner.o5.candidates import generate, pool_fingerprint, state_for
from semantic_pallet_planner.o5.public_request import build, envelope, parse_response, validate_request
from semantic_pallet_planner.o5.testing import fixture_task, OfflineTransport
from semantic_pallet_planner.o5.selectors import Ledger, direct_choice, geometry_choice
from semantic_pallet_planner.o5.episode import run_episode, verify_episode
from semantic_pallet_planner.o5.data import source_clusters, profile, eligible
from semantic_pallet_planner.o5.metrics import paired_sources, summarize


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError('O5 S1 attempted network access')
    monkeypatch.setattr(socket.socket, 'connect', reject)
    monkeypatch.setattr(socket, 'create_connection', reject)


@pytest.fixture
def request_fixture(tmp_path):
    task = fixture_task()
    pool, _ = generate(task['container'], [], task['items'][0], 0, DEFAULT)
    req, mapping = build(task['container'], [], task['items'][0], pool, DEFAULT, 'nonce', tmp_path/'request')
    return req, mapping, tmp_path/'request', task


def test_closed_config_and_physical_backend():
    cfg = load()
    assert geometry_config(cfg)['container'] == cfg['container']
    for key in cfg:
        changed = copy.deepcopy(cfg)
        changed[key] = None
        with pytest.raises(O5Error, match='INVALID_CONFIG'):
            load_config(changed)


def load_config(cfg):
    from semantic_pallet_planner.o5.config import validate
    return validate(cfg)


def test_original_e2_exact_pool_without_ast_or_region(monkeypatch):
    from semantic_pallet_planner.o4.extensions.e2.candidates import generate as original
    from semantic_pallet_planner.o4.extensions.e2 import runtime
    monkeypatch.setattr(runtime, 'evaluate_candidates', lambda *a: pytest.fail('AST executed'))
    task = fixture_task()
    state = state_for(task['container'], [], task['items'][0], 0)
    actual, _ = generate(task['container'], [], task['items'][0], 0, DEFAULT)
    expected, _ = original(state, task['items'][0]['item_id'], [], geometry_config(DEFAULT))
    assert actual == expected and 0 < len(actual) <= 16


def test_future_and_business_fields_have_no_effect(request_fixture, tmp_path):
    req, mapping, directory, task = request_fixture
    changed = copy.deepcopy(task)
    changed['items'][0].update(instruction_text='hidden', policy_ast={'secret': True}, source_order_key='secret')
    changed['items'][1]['dimensions_mm']['length'] = 9999
    pool, _ = generate(changed['container'], [], changed['items'][0], 0, DEFAULT)
    again, again_map = build(changed['container'], [], changed['items'][0], pool, DEFAULT, 'nonce', tmp_path/'again')
    assert req == again and mapping == again_map
    assert all(s not in json.dumps(req) for s in ('secret', 'policy_ast', 'instruction_text', 'geometry_score', 'source_cluster', 'arrival_order'))


@pytest.mark.parametrize('where', ['root', 'item', 'candidate', 'image'])
def test_public_whitelist_rejects_injected_fields(request_fixture, where):
    req = copy.deepcopy(request_fixture[0])
    target = {'root': req, 'item': req['current_item'], 'candidate': req['candidates'][0], 'image': req['images'][0]}[where]
    target['future_items'] = ['hidden']
    with pytest.raises(O5Error):
        validate_request(req)


def test_pngs_actually_encoded_and_labels_match(request_fixture):
    req, mapping, directory, _ = request_fixture
    body = envelope(req, directory, DEFAULT)
    content = body['messages'][1]['content']
    assert len(content) == 3 and len(mapping) == len(req['candidates'])
    for image, asset in zip(content[1:], req['images']):
        blob = base64.b64decode(image['image_url']['url'].split(',', 1)[1])
        assert blob == (directory/(asset['asset_id']+'.png')).read_bytes()
    for c in req['candidates']:
        assert c['pose'] == mapping[c['candidate_id']]['pose']
    (directory/'candidates.png').write_bytes(b'changed')
    with pytest.raises(O5Error, match='IMAGE_CHANGED'):
        envelope(req, directory, DEFAULT)


@pytest.mark.parametrize('mutation,code', [
    (lambda r: r.update(request_id='stale'), 'STALE_BINDING'),
    (lambda r: r.update(state_hash='0'*64), 'STALE_BINDING'),
    (lambda r: r.update(candidate_id='C99'), 'UNKNOWN_CANDIDATE'),
    (lambda r: r.update(action='STOP'), 'INVALID_STOP'),
    (lambda r: r.update(coordinates=[0, 0, 0]), 'SCHEMA_ERROR')])
def test_response_rejects_stale_unknown_or_coordinates(request_fixture, mutation, code):
    req, mapping, _, _ = request_fixture
    response = geometry_choice(req, mapping)
    mutation(response)
    with pytest.raises(O5Error, match=code):
        parse_response(response, req)


def test_duplicate_json_keys_rejected(request_fixture):
    req = request_fixture[0]
    with pytest.raises(O5Error, match='INVALID_JSON'):
        parse_response('{"action":"STOP","action":"PLACE"}', req)


def test_one_repair_no_fallback_and_no_new_context(request_fixture, tmp_path):
    req, mapping, directory, _ = request_fixture
    transport = OfflineTransport(script=['not json', 'valid'])
    ledger = Ledger(tmp_path/'ledger.json', 'job', 2)
    response, attempts, reason = direct_choice(req, directory, DEFAULT, transport, ledger)
    assert response and reason is None and len(attempts) == len(transport.calls) == 2
    first, repair = [json.loads(b['messages'][1]['content'][0]['text']) for b in transport.calls]
    assert first['public_input'] == repair['public_input'] == req
    assert first['repair_error'] is None and repair['repair_error'] == 'INVALID_JSON'
    assert transport.calls[0]['messages'][1]['content'][1:] == transport.calls[1]['messages'][1]['content'][1:]


@pytest.mark.parametrize('script,expected', [(['bad', 'bad'], 'INVALID_JSON'),
                                           ([RuntimeError('secret')], 'SERVICE_ERROR')])
def test_failure_keeps_complete_denominator(tmp_path, script, expected):
    task = fixture_task()
    transport = OfflineTransport(script=script)
    result = run_episode(task, 'D0', DEFAULT, tmp_path, 'job', 'nonce', transport=transport)
    summary = result['summary']
    assert summary['planned_items'] == 14 and summary['placed_items'] == 0
    assert summary['placed_volume_ratio'] == 0 and summary['termination_reason'] == expected
    assert len(transport.calls) <= 2
    assert 'secret' not in (tmp_path/'ledger.json').read_text()
    assert verify_episode(task, 'D0', DEFAULT, tmp_path, 'job', 'nonce')['status'] == 'PASS'


def test_stop_empty_pool_and_zero_budget(tmp_path):
    task = fixture_task()
    stopped = run_episode(task, 'D0', DEFAULT, tmp_path/'stop', 'job', 'stop', transport=OfflineTransport('stop'))
    assert stopped['summary']['termination_reason'] == 'MODEL_STOP'
    empty = fixture_task(length=1400, width=1300)
    transport = OfflineTransport()
    result = run_episode(empty, 'D0', DEFAULT, tmp_path/'empty', 'job', 'empty', transport=transport)
    assert result['summary']['termination_reason'] == 'NO_PHYSICAL_CANDIDATE' and not transport.calls
    result = run_episode(task, 'D0', DEFAULT, tmp_path/'budget', 'job', 'budget', transport=transport, attempt_limit=0)
    assert result['summary']['termination_reason'] == 'BUDGET_EXHAUSTED' and not transport.calls


def test_sent_unknown_attempt_never_retried(request_fixture, tmp_path):
    req, _, directory, _ = request_fixture
    class Crash(OfflineTransport):
        def complete(self, body):
            raise KeyboardInterrupt()
    ledger = Ledger(tmp_path/'ledger.json', 'job', 2)
    with pytest.raises(KeyboardInterrupt):
        ledger.attempt(req, directory, DEFAULT, Crash())
    transport = OfflineTransport()
    restored = Ledger(tmp_path/'ledger.json', 'job', 2)
    response, _, failure = direct_choice(req, directory, DEFAULT, transport, restored)
    assert failure == 'UNKNOWN_IN_FLIGHT' and response is None and not transport.calls
    assert read(tmp_path/'ledger.json')['attempts'][0]['status'] == 'unknown'


def test_persisted_response_recovers_without_new_request(request_fixture, tmp_path):
    req, _, directory, _ = request_fixture
    first = OfflineTransport()
    ledger = Ledger(tmp_path/'ledger.json', 'job', 2)
    a = direct_choice(req, directory, DEFAULT, first, ledger)
    second = OfflineTransport()
    b = direct_choice(req, directory, DEFAULT, second, Ledger(tmp_path/'ledger.json', 'job', 2))
    assert a == b and len(first.calls) == 1 and not second.calls


@pytest.mark.parametrize('method', ['G0', 'D0'])
def test_full_order_checkpoint_resume_and_independent_verify(tmp_path, method):
    task = fixture_task()
    a = run_episode(task, method, DEFAULT, tmp_path/'a', 'job', 'nonce', transport=OfflineTransport())
    partial = run_episode(task, method, DEFAULT, tmp_path/'b', 'job', 'nonce', transport=OfflineTransport(), stop_after=3)
    assert partial['execution_status'] == 'CHECKPOINTED'
    b = run_episode(task, method, DEFAULT, tmp_path/'b', 'job', 'nonce', transport=OfflineTransport(), resume=True)
    assert a == b and a['summary']['planned_items'] == 14
    assert verify_episode(task, method, DEFAULT, tmp_path/'b', 'job', 'nonce')['status'] == 'PASS'
    # A duplicate continuation does not submit or request again.
    transport = OfflineTransport()
    c = run_episode(task, method, DEFAULT, tmp_path/'b', 'job', 'nonce', transport=transport, resume=True)
    assert c == b and not transport.calls
    journal = tmp_path/'b/decisions/000/journal.json'
    changed = read(journal)
    changed['after'][0]['pose']['x_mm'] += 1
    atomic(journal, changed)
    with pytest.raises(O5Error, match='CHECKPOINT_JOURNAL_CHANGED'):
        run_episode(task, method, DEFAULT, tmp_path/'b', 'job', 'nonce', transport=OfflineTransport(), resume=True)


def raw_order(values, alias):
    return {'properties': {'order_nr': alias, 'id': alias}, 'item_sequence': {
        str(i): {'sequence': i+1, 'length/mm': x, 'width/mm': 100, 'height/mm': 50, 'weight/kg': 1}
        for i, x in enumerate(values)}}


def test_source_alias_window_rotation_and_multiset_clusters():
    raw = {'a': raw_order(list(range(140, 154)), 'one'),
           'b': raw_order(list(range(140, 154))[::-1], 'two'),
           'c': raw_order([999]+list(range(140, 153)), 'three'),
           'd': raw_order([140, 141]+list(range(300, 312)), 'four'),
           'e': raw_order(list(range(400, 414)), 'one')}
    clusters, edges = source_clusters(raw)
    assert clusters['a'] == clusters['b'] == clusters['c'] == clusters['e']
    assert clusters['d'] != clusters['a']  # Common individual SKUs do not join orders.
    rotated = copy.deepcopy(raw['a'])
    for x in rotated['item_sequence'].values():
        x['length/mm'], x['width/mm'] = x['width/mm'], x['length/mm']
    assert profile(list(raw['a']['item_sequence'].values())) == profile(list(rotated['item_sequence'].values()))
    assert eligible(list(raw['a']['item_sequence'].values()))
    raw['f'] = raw_order(list(range(500, 514)), 'new-alias')
    raw['f']['properties']['id'] = 'a'  # Aliases are joined across field namespaces too.
    cross, _ = source_clusters(raw)
    assert cross['f'] == cross['a']


def test_source_clustered_repeats_and_complete_pair_denominator():
    def row(s, method, vr):
        return {'source_cluster_id': s, 'method': method, 'summary': {'placed_volume_ratio': vr}}
    results = [row('a', 'G0', .5), row('a', 'D0', .7), row('a', 'D0', .9),
               row('b', 'G0', .6), row('b', 'D0', .6)]
    actual = paired_sources(results)
    assert actual['independent_sources'] == 2 and actual['mean_difference'] == pytest.approx(.15)
    with pytest.raises(O5Error, match='INCOMPLETE_PAIRED_DENOMINATOR'):
        paired_sources(results+[row('missing', 'G0', 1.)])


def test_independent_multisupport_propagation_and_limit_boundary():
    from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate
    from semantic_pallet_planner.evaluation.state import apply_candidate
    task = fixture_task(length=100, width=100, height=100, mass=2.)
    placed = []
    def c(item, x, y, z, l=100, w=100, ids=()):
        volume = sum(__import__('math').prod(p['oriented_size_mm']) for p in placed)+l*w*100
        return {'pick_item_id': item['item_id'], 'pose': {'x_mm': x, 'y_mm': y, 'z_base_mm': z, 'yaw_deg': 0},
                'oriented_size_mm': [l, w, 100], 'support': {'support_item_ids': list(ids), 'support_ratio': 1.},
                'resulting_geometry': {'max_height_mm': z+100, 'volume_utilization': round(volume/(1200*1000*850), 6)}}
    for i, x in enumerate((-50, 50)):
        item = task['items'][i]
        case = {'placed_items': placed, 'available_items': [item]}
        candidate = c(item, x, 0, 0)
        assert check_candidate(case, {'container': task['container']}, candidate) == []
        placed = apply_candidate(case, candidate)
    bridge = copy.deepcopy(task['items'][2])
    bridge['dimensions_mm']['length'] = 200
    bridge['mass_kg'] = 20
    candidate = c(bridge, 0, 0, 100, l=200, ids=('box_01', 'box_02'))
    case = {'placed_items': placed, 'available_items': [bridge]}
    assert check_candidate(case, {'container': task['container']}, candidate) == []
    placed = apply_candidate(case, candidate)
    assert [p['supported_load_kg'] for p in placed] == [10., 10., 0.]
    top = copy.deepcopy(task['items'][3]); top['mass_kg'] = 100
    candidate = c(top, 0, 0, 200, ids=('box_03',))
    case = {'placed_items': placed, 'available_items': [top]}
    assert check_candidate(case, {'container': task['container']}, candidate) == []
    placed = apply_candidate(case, candidate)
    assert [p['supported_load_kg'] for p in placed] == [60., 60., 100., 0.]
    extra = task['items'][4]
    candidate = c(extra, 0, 0, 300, ids=('box_04',))
    assert 'overload' in check_candidate({'placed_items': placed, 'available_items': [extra]}, {'container': task['container']}, candidate)


def test_proposal_rejection_is_not_actual_violation(tmp_path, monkeypatch):
    import semantic_pallet_planner.o5.episode as module
    original = module.check_candidate
    monkeypatch.setattr(module, 'check_candidate', lambda *args: ['overload'])
    result = run_episode(fixture_task(), 'D0', DEFAULT, tmp_path, 'job', 'nonce', transport=OfflineTransport())
    assert result['summary']['termination_reason'] == 'PHYSICAL_REJECTION'
    assert result['summary']['proposal_physical_rejections'] == 1
    assert result['summary']['actual_physical_violations'] == 0
    assert result['summary']['placed_items'] == 0


def test_ledger_and_checkpoint_identity_and_lock_guards(tmp_path):
    from semantic_pallet_planner.o5.common import exclusive, new_directory
    with exclusive(tmp_path/'lock'):
        with pytest.raises(O5Error, match='RUN_BUSY'):
            with exclusive(tmp_path/'lock'):
                pass
    directory = new_directory(tmp_path/'new')
    with pytest.raises(FileExistsError):
        new_directory(directory)
    from semantic_pallet_planner.o5.common import ROOT
    with pytest.raises(O5Error, match='PROTECTED_OUTPUT'):
        new_directory(ROOT/'semantic_pallet_planner/outputs/OLD_EXPERIMENT/subfolder')
    Ledger(tmp_path/'ledger.json', 'job', 2)
    with pytest.raises(O5Error, match='LEDGER_IDENTITY_CHANGED'):
        Ledger(tmp_path/'ledger.json', 'another', 2)
    run_episode(fixture_task(), 'D0', DEFAULT, tmp_path/'cp', 'job', 'nonce', transport=OfflineTransport(), stop_after=1)
    with pytest.raises(O5Error, match='CHECKPOINT_IDENTITY_CHANGED'):
        run_episode(fixture_task(), 'D0', DEFAULT, tmp_path/'cp', 'job', 'changed', transport=OfflineTransport(), resume=True)


def test_offline_plan_execution_partial_resume_and_verify(tmp_path):
    from semantic_pallet_planner.o5.experiment import prepare, execute, verify, validate_plan
    plan, run = tmp_path/'plan', tmp_path/'run'
    assert prepare(None, plan, fixture=True)['jobs'] == 4
    partial = execute(plan, run, max_jobs=1, stop_after=2)
    assert partial['status'] == 'PARTIAL' and partial['completed_jobs'] == 0
    complete = execute(plan, run, resume=True)
    assert complete['status'] == 'PASS' and complete['completed_jobs'] == 4
    audited = verify(run)
    assert audited['checked_jobs'] == 4 and audited['new_api_attempts'] == 0
    state = read(run/'run.json')
    state['jobs'].pop()
    atomic(run/'run.json', state)
    with pytest.raises(O5Error, match='JOB_REGISTRY_CHANGED'):
        verify(run)
    tampered = read(plan/'plan.json')
    tampered['stub_policy'] = 'stop'
    atomic(plan/'plan.json', tampered)
    with pytest.raises(O5Error, match='PLAN_OR_SOURCE_DRIFT'):
        validate_plan(plan)


def test_nonfinite_item_and_premature_checkpoint_rejected(tmp_path):
    task = fixture_task()
    task['items'][0]['dimensions_mm']['length'] = float('nan')
    with pytest.raises(O5Error, match='INVALID_PHYSICAL_ITEM'):
        run_episode(task, 'G0', DEFAULT, tmp_path/'nan', 'job', 'nonce')
    task = fixture_task()
    run_episode(task, 'G0', DEFAULT, tmp_path/'cp', 'job', 'nonce', stop_after=1)
    cp = read(tmp_path/'cp/checkpoint.json'); cp['reason'] = 'ALL_ITEMS_PLACED'
    atomic(tmp_path/'cp/checkpoint.json', cp)
    with pytest.raises(O5Error, match='PREMATURE_SUCCESS'):
        run_episode(task, 'G0', DEFAULT, tmp_path/'cp', 'job', 'nonce', resume=True)


def test_same_state_same_mapping_across_method_nonce(request_fixture, tmp_path):
    req, mapping, _, task = request_fixture
    pool, _ = generate(task['container'], [], task['items'][0], 0, DEFAULT)
    other, other_mapping = build(task['container'], [], task['items'][0], pool, DEFAULT, 'another-method-and-repeat', tmp_path/'other')
    assert mapping == other_mapping
    assert {k: v for k, v in req.items() if k != 'request_id'} == {k: v for k, v in other.items() if k != 'request_id'}
    assert req['request_id'] != other['request_id']


def test_episode_unknown_inflight_keeps_checkpoint_without_result(tmp_path):
    class Crash(OfflineTransport):
        def complete(self, body):
            raise KeyboardInterrupt('simulated process loss after send')
    task = fixture_task()
    with pytest.raises(KeyboardInterrupt):
        run_episode(task, 'D0', DEFAULT, tmp_path, 'job', 'nonce', transport=Crash())
    assert read(tmp_path/'checkpoint.json')['cursor'] == 0
    assert not (tmp_path/'result.json').exists()
    transport = OfflineTransport()
    with pytest.raises(O5Error, match='UNKNOWN_IN_FLIGHT'):
        run_episode(task, 'D0', DEFAULT, tmp_path, 'job', 'nonce', transport=transport, resume=True)
    assert not transport.calls and not (tmp_path/'result.json').exists()


def test_runtime_offline_guard_restores_network_api():
    from semantic_pallet_planner.o5.common import offline_guard
    original = socket.create_connection
    with offline_guard():
        with pytest.raises(O5Error, match='NETWORK_FORBIDDEN_IN_S1'):
            socket.create_connection(('example.invalid', 443))
    assert socket.create_connection is original
