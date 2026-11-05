"""State/action comparison evidence must not masquerade as real support."""
from copy import deepcopy
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select.contracts import JevSelectError, digest
from semantic_pallet_planner.jev_select.ledger import read
from semantic_pallet_planner.jev_select.diagnostics import violation_measure, outcome_dominates, decision_case


def metric(count, kg=0., mm=0.):
    instances = []
    for i in range(count):
        instances.append({'rule_id':'load', 'kind':'max_top_load', 'severity':{'unit':'kg','value':kg/count}})
    if mm:
        instances.append({'rule_id':'gap', 'kind':'relative_position', 'severity':{'unit':'mm','value':mm}})
    return violation_measure({'instances':instances})


def test_severity_units_and_rules_are_never_added_together():
    out = metric(2, kg=7.21, mm=500.)
    assert out['instance_count']==3
    assert out['by_rule']['load:max_top_load']['severity_by_unit']=={'kg':7.21}
    assert out['by_rule']['gap:relative_position']['severity_by_unit']=={'mm':500.}
    assert 'total_severity' not in out


@pytest.mark.parametrize('placed,count,kg,mm,better', [
    (3,0,0.,0.,False),  # less packed is not an improved order outcome
    (6,1,8.,0.,False),  # fewer instances but higher same-rule severity
    (6,1,3.,0.,True),
])
def test_dominance_rejects_partial_and_severity_tradeoffs(placed,count,kg,mm,better):
    base={'placed_items':6,'final_violations':metric(2,kg=7.21)}
    candidate={'placed_items':placed,'final_violations':metric(count,kg=kg,mm=mm)}
    assert outcome_dominates(candidate,base) is better


def test_lower_final_count_cannot_hide_worse_trajectory():
    base={'placed_items':6,'final_violations':metric(2,kg=7.21),
          'trajectory_violation_instance_steps':4,'ever_unique_violation_instances':2}
    candidate={'placed_items':6,'final_violations':metric(1,kg=3.),
               'trajectory_violation_instance_steps':8,'ever_unique_violation_instances':2}
    assert not outcome_dominates(candidate,base)


@pytest.fixture
def historical():
    root=next(p for p in Path(__file__).resolve().parents if (p/'semantic_pallet_planner/outputs').is_dir())
    run=root/'semantic_pallet_planner/outputs/EXP_JEV_J4_V2_MODERATE_REST3_20261101_01'
    if not run.exists(): pytest.skip('saved real training record unavailable')
    episode=read(run/'episodes/J0000.json')
    task=read(run/'plan/private/input_snapshot.json')['tasks'][0]
    return root,episode,task


def test_real_case_uses_cumulative_load_and_active_override(historical):
    _,episode,task=historical
    event=[e for e in episode['events'] if e['event']=='PLACE'][4]
    case=decision_case(event,task)
    base=next(s for s in case['affected_supports'] if s['support_box']['mass_kg']==9.8)
    assert base['before_top_load_kg']==6.38
    assert base['after_top_load_kg']==14.39
    assert base['effective_business_limit_kg']==10.5
    assert base['excess_above_effective_limit_kg']==pytest.approx(3.89)
    reinforced=next(s for s in case['affected_supports'] if s['support_box']['packaging']['reinforced'])
    assert reinforced['effective_business_limit_kg']==23.5
    assert reinforced['excess_above_effective_limit_kg']==0


def test_actual_outcome_tamper_is_detected(historical):
    _,episode,task=historical
    event=deepcopy([e for e in episode['events'] if e['event']=='PLACE'][-1])
    event['business_after']['instances']=[]
    with pytest.raises(JevSelectError,match='case_actual_outcome_mismatch'):
        decision_case(event,task)


def test_local_branch_cannot_be_exported_as_real_training(historical):
    root,_,_=historical
    branch=root/'semantic_pallet_planner/outputs/CASE_JEV_J4_STATE_ACTION_20261101_02/simulated_branches/1.json'
    if not branch.exists(): pytest.skip('saved comparison branch unavailable')
    ep=read(branch)
    from semantic_pallet_planner.jev_select.memory_export import export_completed_episode
    manifest={'source_groups':[ep['summary']['source_order_key']], 'source_code_digest':'1'*64,
              'episodes':{ep['job_id']:{'episode_digest':digest(ep),'source_code_digest':'1'*64}}}
    with pytest.raises(JevSelectError,match='teacher_method_not_allowed'):
        export_completed_episode(ep,manifest,version='jev_episode_export_v2')
