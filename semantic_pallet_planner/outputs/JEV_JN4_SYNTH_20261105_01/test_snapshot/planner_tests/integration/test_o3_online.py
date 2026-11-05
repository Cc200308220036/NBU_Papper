"""End-to-end O3 behavior, independent of remote provider availability."""
from pathlib import Path
import pytest

from semantic_pallet_planner.config import generator_config, load_config
from semantic_pallet_planner.domain import PalletState
from semantic_pallet_planner.planner.generator import ExtremePointGenerator
from semantic_pallet_planner.repository import DatasetRepository
from semantic_pallet_planner.runners.attribute_o3_online import (
    audit_outputs, replay_all, run, run_episode, step_state, task_plan,
)
from semantic_pallet_planner.runners.o3_online_adapter import public_request, screen
from semantic_pallet_planner.evaluation.policy_v2 import evaluate
from semantic_pallet_planner.selectors.instruction_parser_o1b import resolved_public_policy


def test_online_public_binding_and_screen():
    cfg = load_config(top_k=16)
    repo = DatasetRepository(cfg['dataset'])
    tasks, _ = task_plan(repo, 'train', 1)
    scenario = repo.get_scenario(tasks[0]['scenario_id'])
    state = step_state(scenario, tasks[0], [], 0)
    cs = ExtremePointGenerator(generator_config(cfg)).generate(PalletState.from_dict(state)).candidate_set.data
    req, mapping, scan = public_request(state, cs['candidates'], tasks[0]['instruction_text'])
    assert scan['status'] == 'PASS'
    assert all('candidate_id' not in c for c in req['candidates'])
    assert set(mapping) == {c['display_label'] for c in req['candidates']}
    other, _, _ = public_request(state, cs['candidates'], tasks[1]['instruction_text'])
    assert other['state_hash'] == req['state_hash']
    assert other['policy_digest'] != req['policy_digest']
    evaluations = [evaluate(req,c,resolved_public_policy(req['instruction_text'],req),req['container'])
                   for c in req['candidates']]
    assert screen(req,'C99',evaluations) == (None,False,'invalid_response')


def test_online_episode_replay_detects_tamper(tmp_path):
    root = tmp_path/'O3'
    status, replay = run(root, split='train', limit_orders=1)
    assert status == 'PASS' and replay['status'] == 'PASS'
    manifest = root/'manifest.json'
    assert manifest.is_file()
    repo = DatasetRepository(load_config()['dataset'])
    tasks, _ = task_plan(repo, 'train', 1)
    methods = ['geometry_greedy','fixed_attribute','public_parser','truth_ast_executor']
    audit = audit_outputs(root,tasks,methods,repo)
    assert audit['status'] == 'PASS'
    episode = root/'episodes'/'geometry_greedy'/tasks[0]['episode_id']/'steps.jsonl'
    lines = episode.read_text().splitlines()
    import json
    event = json.loads(lines[0]);event['committed_label'] = 'C99'
    lines[0] = json.dumps(event)
    episode.write_text('\n'.join(lines)+'\n')
    result = replay_all(root,tasks,methods,repo,load_config(seed=20261015,top_k=16,topk_mode='diverse_v1',fallback_policy='abort'))
    assert result['status'] == 'FAIL'


def test_validation_source_is_independent():
    cfg = load_config()
    repo = DatasetRepository(cfg['dataset'])
    train, _ = task_plan(repo,'train',3)
    validation, audit = task_plan(repo,'validation',10)
    assert not ({x['source_order_key'] for x in train} & {x['source_order_key'] for x in validation})
    assert audit['independent_source_orders'] == 10
    assert audit['unseen_test_evidence'] is False


@pytest.mark.parametrize('execution_mode', ['safe', 'observe_business'])
def test_flash_ast_adapter_with_fake_bound_provider(tmp_path, execution_mode):
    import json
    from semantic_pallet_planner.selectors.instruction_parser_o1b import parse_o1b_instruction
    from semantic_pallet_planner.vlm.client import ModelResult

    class BoundPolicyClient:
        def complete(self, model_request):
            request = json.loads(model_request.user_text)
            reply = {k: request[k] for k in ('request_id','state_hash','policy_digest')}
            reply.update(schema_version='pallet_policy_response_o2b_1',
                         policy_ast=parse_o1b_instruction(request['instruction_text']))
            return ModelResult(raw_text=json.dumps(reply),input_tokens=100,output_tokens=50)

    cfg = load_config(seed=20261015,top_k=16,topk_mode='diverse_v1',fallback_policy='abort')
    repo = DatasetRepository(cfg['dataset'])
    task = task_plan(repo,'train',1)[0][0]
    root = tmp_path/'O3_fake_remote'
    gen = ExtremePointGenerator(generator_config(cfg))
    summary, events = run_episode(root,task,'flash_policy_parser',repo,gen,cfg,BoundPolicyClient(),
                                  execution_mode=execution_mode)
    assert summary['steps'] == len(events)
    assert summary['remote_attempts'] > 0
    assert all(e['status'] != 'invalid_response' for e in events)
    assert replay_all(root,[task],['flash_policy_parser'],repo,cfg,
                      execution_mode=execution_mode)['status'] == 'PASS'
    if execution_mode == 'observe_business':
        assert any(e['diagnostic_continuation'] for e in events)
        assert all(e['proposed_label'] == e['committed_label']
                   for e in events if e['proposed_label'])
    assert audit_outputs(root,[task],['flash_policy_parser'],repo)['status'] == 'PASS'


def test_observe_business_commits_blocked_proposals_and_replays(tmp_path, monkeypatch):
    import json
    root = tmp_path/'O3_observe'
    status, replay = run(root, split='train', limit_orders=1,
                         execution_mode='observe_business')
    assert status == 'PASS' and replay['status'] == 'PASS'
    rows = [json.loads(line) for path in root.glob('episodes/*/*/steps.jsonl')
            for line in path.read_text().splitlines()]
    assert any(row['would_screen_block'] for row in rows)
    assert all(not row['screen_intervened'] for row in rows)
    assert all(row['committed_label'] == row['proposed_label']
               for row in rows if row['proposed_label'] is not None)
    assert (root/'metrics/business_violation_comparison.json').is_file()
    assert (root/'acceptance_report.json').is_file()
    repo = DatasetRepository(load_config()['dataset'])
    tasks, _ = task_plan(repo, 'train', 1)
    methods = ['geometry_greedy','fixed_attribute','public_parser','truth_ast_executor']
    assert replay_all(root,tasks,methods,repo,
                      load_config(seed=20261015,top_k=16,topk_mode='diverse_v1',
                                  fallback_policy='abort'))['status'] == 'PASS'
    # Cross-Python math roundoff must not break exact binding to the recorded
    # input, while regenerated public facts still have to agree numerically.
    from semantic_pallet_planner.runners import o3_online_adapter
    original_relations = o3_online_adapter.public_relations
    def rounded_relations(*args):
        result = original_relations(*args)
        value = result['after']['heavy_center_distance_mm']
        if value is not None:
            result['after']['heavy_center_distance_mm'] = value + 1e-13
        return result
    with monkeypatch.context() as patch:
        patch.setattr(o3_online_adapter, 'public_relations', rounded_relations)
        assert replay_all(root,tasks,methods,repo,
                          load_config(seed=20261015,top_k=16,topk_mode='diverse_v1',
                                      fallback_policy='abort'))['status'] == 'PASS'
    with pytest.raises(ValueError, match='configuration mismatch'):
        run(root, split='train', limit_orders=1, resume=True, execution_mode='safe')
    episode_path = next(root.glob('episodes/geometry_greedy/*/episode.json'))
    episode = json.loads(episode_path.read_text())
    episode['summary']['final_business_violation_count'] += 1
    episode_path.write_text(json.dumps(episode))
    assert replay_all(root,tasks,methods,repo,
                      load_config(seed=20261015,top_k=16,topk_mode='diverse_v1',
                                  fallback_policy='abort'))['status'] == 'FAIL'
