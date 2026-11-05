import copy
import random
import pytest
from semantic_pallet_planner.environment import PalletEnvironment
from semantic_pallet_planner.selectors.baselines import make_selector
from semantic_pallet_planner.protocol import state_hash


def test_online_arrival_snapshot_and_state(cfg,repo,generator):
    env=PalletEnvironment(repo,generator);env.reset('SCN_0051')
    scenario=repo.get_scenario('SCN_0051');h=[]
    while not env.done:
        obs=env.observe();index=env.step_index
        assert [x['item_id'] for x in obs['available_items']]==[scenario['arrival_order'][index]]
        env.generate_candidates()
        if env.done:break
        req=env.selection_request();h.append(req['state_hash'])
        mutated=env.selection_request();mutated['candidates'].clear()
        assert env.selection_request()['candidates']
        a=make_selector('geometry_greedy').select(req,rng=random.Random(0))
        r=env.step(a).data
        assert r['committed'] and r['geometry_errors']==[] and len(r['after']['placed_items'])==index+1
        assert r['state_hash_after']!=req['state_hash']
    assert env.termination_reason=='all_items_placed' and env.step_index==10 and len(set(h))==10
    assert any(x['supported_load_kg']>0 for x in env.placed)
    with pytest.raises(ValueError):env.step(a)


@pytest.mark.parametrize('policy,committed,reason',[('geometry_greedy',True,None),('abort',False,'invalid_selector_response')])
def test_invalid_response_fallback(repo,generator,policy,committed,reason):
    env=PalletEnvironment(repo,generator,policy);env.reset('SCN_0051')
    r=env.step(dict(candidate_id='BAD')).data
    assert r['committed']==committed and r['termination_reason']==reason
    assert r['fallback']==committed


def test_no_candidate_max_steps_and_buffer_boundary(repo,generator):
    env=PalletEnvironment(repo,generator);env.reset('SCN_0051',max_steps=1)
    req=env.selection_request();r=env.step(make_selector('geometry_greedy').select(req,rng=random.Random(0))).data
    assert r['termination_reason']=='max_steps_reached'
    env.reset('SCN_0051');env.items[0]['mass_kg']=1e9
    result=env.generate_candidates()
    assert not result.candidate_set.data['candidates'] and env.termination_reason=='no_feasible_candidate'
    assert result.audit.data['raw_candidate_count']>0
    buffer_sid=repo.split('validation_buffer3')['scenario_ids'][0]
    with pytest.raises(ValueError):env.reset(buffer_sid)
