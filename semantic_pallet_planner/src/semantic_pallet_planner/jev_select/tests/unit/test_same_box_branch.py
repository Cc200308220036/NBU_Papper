from copy import deepcopy
from pathlib import Path

import pytest

from semantic_pallet_planner.jev_select.candidate_branch import same_box_ranking, segregation_feedback
from semantic_pallet_planner.jev_select.contracts import JevSelectError
from semantic_pallet_planner.jev_select.ledger import read


def event():
    root=next(p for p in Path(__file__).resolve().parents if (p/'semantic_pallet_planner/outputs').is_dir())
    p=root/'semantic_pallet_planner/outputs/EXP_JEV_J4_V2_MODERATE_REST3_20261101_01/episodes/J0000.json'
    if not p.exists():pytest.skip('saved historical source unavailable')
    return [e for e in read(p)['events'] if e['event']=='PLACE']


def test_ranking_restricts_same_box_and_preserves_native_probability_and_tie():
    ranks=same_box_ranking(event()[0])
    assert [r['display_id'] for r in ranks[:3]]==['C15','C36','C39']
    assert [r['probability'] for r in ranks[:3]]==[.18,.05,.05]
    assert {r['candidate']['pick_item_id'] for r in ranks}=={'item_02'}
    assert ranks[1]['tied_probability'] and ranks[2]['tied_probability']


def test_missing_probabilities_cannot_be_replaced_with_geometry_rank():
    e=deepcopy(event()[0]);e['selection']['probabilities']=None
    with pytest.raises(JevSelectError,match='native_probabilities_missing_or_unbound'):
        same_box_ranking(e)


def test_same_pallet_violation_survives_large_gap_and_does_not_mutate_old_feedback():
    e=deepcopy(event()[2]);old=deepcopy(e)
    original=segregation_feedback(e)
    food=next(b for b in e['after']['placed_items'] if b['item_id']=='item_03')
    food['pose']['x_mm']+=100
    shifted=segregation_feedback(e)
    assert shifted==original
    assert any(i['kind']=='forbidden_co_pallet' for i in shifted['instances'])
    assert not any(i['kind']=='forbidden_contact' for i in shifted['instances'])
    assert e['business_after']==old['business_after']


def test_no_food_cleaner_mix_means_no_co_pallet_instance():
    assert not any(i['kind']=='forbidden_co_pallet' for i in segregation_feedback(event()[0])['instances'])


def test_cli_negative_scientific_result_is_still_a_successful_execution(monkeypatch,capsys):
    from semantic_pallet_planner.jev_select import candidate_branch
    from semantic_pallet_planner.jev_select.cli import main
    monkeypatch.setattr(candidate_branch,'compare_same_box',lambda *a,**k: {'decision':'NO_DOMINATING_ALTERNATIVE_FOUND'})
    assert main(['compare-same-box-candidates','--experiment','unused','--output','unused'])==0
    assert 'NO_DOMINATING_ALTERNATIVE_FOUND' in capsys.readouterr().out
