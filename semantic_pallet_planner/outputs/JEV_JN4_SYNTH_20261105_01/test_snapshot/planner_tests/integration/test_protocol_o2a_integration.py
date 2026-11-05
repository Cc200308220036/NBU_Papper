"""O2a held-out source and one-repair integration checks without paid calls."""
import json
from pathlib import Path

from semantic_pallet_planner.config import WORKSPACE, generator_config, load_config
from semantic_pallet_planner.repository import DatasetRepository
from semantic_pallet_planner.runners.attribute_pilot_v2 import write_json
from semantic_pallet_planner.runners.protocol_o2a import build_dataset, run_one_arm
from semantic_pallet_planner.vlm.client import ModelResult
from semantic_pallet_planner.vlm.protocol_o2a import VERSION


class TwoReplies:
    def __init__(self, request):
        self.calls=0
        self.request=request

    def complete(self, req):
        self.calls+=1
        assert 'hidden_policy' not in req.user_text
        assert 'candidate_id' not in req.user_text
        value={k:self.request[k] for k in ('request_id','state_hash','policy_digest')}
        value.update(schema_version=VERSION,action='select',display_label='C01',reason='测试')
        if self.calls==1:
            value['type']='json_object'
        return ModelResult(json.dumps(value),input_tokens=10,output_tokens=5,latency_s=.1)


def test_new_heldout_sources_and_single_repair(tmp_path):
    repo=DatasetRepository(WORKSPACE/'semantic_pallet_dataset_v1')
    parent=tmp_path/'v2_manifest'
    write_json(parent/'data/source_manifest.json',[])
    cfg=generator_config(load_config(top_k=16,topk_mode='diverse_v1'))
    dataset=build_dataset(tmp_path/'o2a',repo,cfg,parent)
    assert len(dataset)==20
    audit=json.loads((tmp_path/'o2a/data/split_audit.json').read_text())
    assert audit['selected_source_order_count']==10
    assert audit['v2_source_order_overlap']==audit['test_source_order_overlap']==[]
    first,second=dataset[:2]
    a,b=first['public_request'],second['public_request']
    assert a['state_hash']==b['state_hash']
    assert a['candidates']==b['candidates']
    assert a['policy_digest']!=b['policy_digest']
    client=TwoReplies(a)
    row=run_one_arm(tmp_path/'responses',first,'new_prompt',client)
    assert client.calls==2
    assert row['initial_api_valid'] is False
    assert row['final_api_valid'] is True
    assert row['repair_count']==1
    assert row['attempt_count']==2
    folder=tmp_path/'responses/selector_inputs/new_prompt'/a['request_id']
    assert (folder/'initial_response.raw.json').exists()
    assert (folder/'repair_response.raw.json').exists()
    assert (folder/'repair_prompt.json').exists()
    assert json.loads((folder/'leakage_report.json').read_text())['status']=='PASS'
