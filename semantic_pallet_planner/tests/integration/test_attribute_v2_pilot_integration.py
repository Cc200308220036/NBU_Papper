import copy
import json
import pytest
from semantic_pallet_planner.config import generator_config, load_config
from semantic_pallet_planner.repository import DatasetRepository
from semantic_pallet_planner.runners.attribute_pilot_v2 import (
    build_pilot, run_methods, validate_and_replay, read_json, write_json,
)
from semantic_pallet_planner.runners.pilot_micro_v2 import microcases, verify_micro
from semantic_pallet_planner.vlm.client import ModelResult
from semantic_pallet_planner.vlm.pilot_protocol_v2 import scan_public


@pytest.fixture(scope='module')
def pilot(tmp_path_factory):
    root = tmp_path_factory.mktemp('attribute_v2')
    cfg = load_config()
    repo = DatasetRepository(cfg['dataset'])
    data = build_pilot(root, repo, generator_config(cfg))
    write_json(root/'checks/microcases_report.json', [verify_micro(m) for m in microcases()])
    return root, data


def test_all_validation_states_retained_same_mapping_paired(pilot):
    root, data = pilot
    assert len(data)==60
    assert len({d['public_request']['state_hash'] for d in data})==30
    for a, b in zip(data[::2], data[1::2]):
        assert a['mapping']==b['mapping']
        assert a['public_request']['candidates']==b['public_request']['candidates']
        assert a['public_request']['policy_digest']!=b['public_request']['policy_digest']
        assert scan_public(a['public_request'], a['mapping'].values())['status']=='PASS'
    audit = read_json(root/'data/split_audit.json')
    assert audit['cross_split_source_order_overlaps']==[]
    assert audit['unique_source_orders']==10  # explicitly do not pretend 30 independent orders


def test_offline_matrix_schema_and_independent_replay(pilot, monkeypatch):
    root, data = pilot
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    rows = run_methods(root, data)
    report = validate_and_replay(root, data, rows)
    assert report['status']=='PASS', report['failures']
    assert sum(r['method']!='flash_direct_text' for r in rows)==300
    assert sum(r['status']=='blocked_missing_api_key' for r in rows)==60
    by_key = {(r['request_id'],r['method']):r for r in rows}
    for d in data:
        rid = d['public_request']['request_id']
        assert by_key[rid,'public_parser']['display_label']==by_key[rid,'candidate_oracle']['display_label']
        if not d['optimum']['feasible_indices']:
            assert by_key[rid,'public_parser']['status']=='abstain'
            assert by_key[rid,'public_parser']['business_hard_satisfied'] is False
            assert by_key[rid,'public_parser']['avoidable_new_violation'] is None


class BindingClient:
    """Protocol test double only; no model performance is asserted."""
    def __init__(self, stale=False):
        self.stale = stale
        self.calls = []

    def complete(self, request):
        assert request.image_paths==()
        public = json.loads(request.user_text)
        self.calls.append(public)
        assert scan_public(public)['status']=='PASS'
        response = {k: public[k] for k in ('request_id','state_hash','policy_digest')}
        response.update(schema_version='pallet_choice_v2_pilot', action='select',
                        display_label=public['candidates'][0]['display_label'], reason='protocol test double')
        if self.stale:
            response['policy_digest']='old'
        return ModelResult(raw_text=json.dumps(response), input_tokens=1, output_tokens=1)


def test_remote_protocol_public_only_and_stale_policy_failures(pilot, tmp_path):
    _, data = pilot
    for stale in (False, True):
        client = BindingClient(stale)
        folder = tmp_path/str(stale)
        rows = run_methods(folder, data[:2], remote=True, client=client)
        flash = [r for r in rows if r['method']=='flash_direct_text']
        assert len(client.calls)==2
        assert all(r['api_valid'] is (not stale) for r in flash)
        if stale:
            assert all(r['status']=='invalid_response' and r['fallback'] is False and r['display_label'] is None for r in flash)


def test_replay_detects_policy_binding_tamper(pilot):
    root, data = pilot
    rows = read_json(root/'metrics/per_decision.json')
    rows[0]['policy_digest']='stale'
    result = validate_and_replay(root, data, rows)
    assert result['status']=='FAIL'
    assert any(x['kind']=='row_binding' for x in result['failures'])
