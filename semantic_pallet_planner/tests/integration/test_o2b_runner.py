import json

from semantic_pallet_planner.evaluation.policy_v2 import evaluate
from semantic_pallet_planner.runners.attribute_o2b import PARENT, dataset, remote, replay
from semantic_pallet_planner.selectors.instruction_parser_o1b import parse_o1b_instruction
from semantic_pallet_planner.vlm.client import ModelResult


class StubClient:
    def __init__(self, raw):
        self.raw = raw
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        assert 'hidden_policy' not in request.user_text
        assert 'candidate_id' not in request.user_text
        return ModelResult(raw_text=self.raw, input_tokens=100, output_tokens=50,
                           latency_s=.1, provider_request_id='stub')


def test_direct_unsafe_proposal_is_recorded_and_screened(tmp_path):
    items=dataset(PARENT)
    selected=None
    for task,req,group in items:
        if not task['coverage']['topk_feasible_count']:
            continue
        for candidate in req['candidates']:
            evaluation=evaluate(req,candidate,task['resolved_policy'],req['container'])
            if evaluation['after_violation_instances']:
                selected=(task,req,group,candidate['display_label'])
                break
        if selected:break
    assert selected is not None
    task,req,group,label=selected
    raw=json.dumps({'schema_version':'pallet_choice_v3_protocol_2',
                    'request_id':req['request_id'],'state_hash':req['state_hash'],
                    'policy_digest':req['policy_digest'],'action':'select',
                    'display_label':label,'reason':'stub'})
    client=StubClient(raw)
    row=remote(tmp_path,task,req,group,'flash_direct_text',client)
    assert client.calls==1
    assert row['proposed_label']==label and row['committed_label'] is None
    assert row['screen_intervened'] and row['raw_avoidable_hard_wrong']
    assert replay(tmp_path,items,[row],complete=False)['status']=='PASS'
    tampered=dict(row,committed_label=label)
    assert replay(tmp_path,items,[tampered],complete=False)['status']=='FAIL'


def test_ast_parser_runs_shared_executor_with_bound_response(tmp_path):
    items=dataset(PARENT)
    task,req,group=items[0]
    ast=parse_o1b_instruction(req['instruction_text'])
    raw=json.dumps({'schema_version':'pallet_policy_response_o2b_1',
                    'request_id':req['request_id'],'state_hash':req['state_hash'],
                    'policy_digest':req['policy_digest'],'policy_ast':ast})
    row=remote(tmp_path,task,req,group,'flash_policy_parser',StubClient(raw))
    assert row['ast_accuracy']['whole_policy']
    assert row['final_api_valid'] and row['physical_violations']==0
    assert replay(tmp_path,items,[row],complete=False)['status']=='PASS'
