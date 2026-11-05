"""Byte budgeting and v4 transport retain original one-episode gates; fixtures only."""
from copy import deepcopy
import pytest
from semantic_pallet_planner.jev_select.contracts import JevSelectError
from semantic_pallet_planner.jev_select.memory_generation import (
    make_request, validate_request, prepare_generation, validate_prepared, run_generation_batch)
from semantic_pallet_planner.jev_select.memory_retrieval import card_text
from semantic_pallet_planner.jev_select.memory_store import MemoryStore
from semantic_pallet_planner.jev_select.ledger import write
from semantic_pallet_planner.jev_select.tests.unit.test_j4_b2_v2 import export2, prop2
from semantic_pallet_planner.jev_select.tests.unit.test_j4_b2a import response


def test_budget_is_for_rendered_bytes_and_old_prompt_stays_bound():
    old = make_request(export2(), protocol='v3')
    new = make_request(export2(), protocol='v4')
    assert old['input'] == new['input']
    assert old['request_digest'] != new['request_digest']
    assert old['prompt']['version'] == 'observational_claims_v3'
    budget = new['prompt']['render_budget']
    p = prop2(new)
    for key, n in budget['field_target_utf8_bytes'].items():
        p[key] = 'a' * n
    text = card_text(dict(p, version='jev_memory_card_v3', render_version='memory_prose_v2'))
    assert len(text.encode()) == budget['target_total_utf8_bytes'] == 1374
    assert budget['hard_item_limit_utf8_bytes'] == 1600
    validate_request(old)
    validate_request(new)
    changed = deepcopy(new)
    changed['prompt']['render_budget']['hard_item_limit_utf8_bytes'] = 1700
    with pytest.raises(JevSelectError):
        validate_request(changed)


@pytest.mark.parametrize('byte_length,expected', [(1600, 'PASS'), (1601, 'STOP_TECHNICAL_REJECTION')])
def test_v4_real_admission_boundary_and_stopped_resume(tmp_path, monkeypatch, byte_length, expected):
    MemoryStore(tmp_path/'source').ingest(export2())
    prepare_generation(tmp_path/'source', tmp_path/'prepared', mode='offline_fixture', protocol='v4')
    requests = validate_prepared(tmp_path/'prepared')[2]
    identity = next(iter(requests))
    p = prop2(requests[identity])
    # Use multibyte prose to catch character counts substituted for UTF-8 bytes.
    p['observed_evidence'] = '观测'
    c = dict(p, version='jev_memory_card_v3', render_version='memory_prose_v2')
    p['advice'] += 'x' * (byte_length - len(card_text(c).encode()))
    write(tmp_path/'fixture.json', response({'version':'jev_generation_output_v2', 'cards':[p]}))
    args = (tmp_path/'prepared', [identity], tmp_path/'store', tmp_path/'batch')
    kwargs = dict(mode='offline_fixture', fixtures={identity:tmp_path/'fixture.json'})
    result = run_generation_batch(*args, **kwargs)
    assert result['status'] == expected
    monkeypatch.setattr('semantic_pallet_planner.jev_select.memory_generation._fixture_complete',
                        lambda *a: pytest.fail('resume must not resend'))
    assert run_generation_batch(*args, **kwargs, resume=True) == result
