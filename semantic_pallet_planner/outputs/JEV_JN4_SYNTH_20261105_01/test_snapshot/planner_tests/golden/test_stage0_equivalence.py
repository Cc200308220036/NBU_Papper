from semantic_pallet_planner.domain import PalletState
from semantic_pallet_planner.config import generator_config
from semantic_pallet_planner.planner.generator import ExtremePointGenerator
from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate


def test_all_360_cached_candidate_fingerprints_scores_audits(repo,cfg):
    cfg['topk_mode']='legacy_v01';g=ExtremePointGenerator(generator_config(cfg))
    checked=0
    for cid in repo.list_cases('all'):
        dc=repo.get_decision_case(cid);s=repo.get_scenario(dc['base_scenario_id']);cs=repo.get_candidate_set(dc['candidate_set_id'])
        out=g.generate(PalletState.from_dict(dict(dc,request_id=cid,container=s['container'])))
        old={c['candidate_id']:c for c in cs['candidates']};new={c['candidate_id']:c for c in out.candidate_set.data['candidates']}
        assert old.keys()==new.keys(),cid
        for key in old:
            for field in ['candidate_fingerprint','pose','geometry_score_components','support','load','resulting_geometry']:
                assert old[key][field]==new[key][field],(cid,key,field)
            assert check_candidate(dc,s,old[key])==[]
            checked+=1
        audit=repo.get_oracle(cid)['geometry_reference']
        for k,v in audit.items():assert out.audit.data[k]==v,(cid,k)
    assert checked==5124


def test_all_five_rule_scores_against_cached_oracle(repo):
    from semantic_pallet_planner.evaluation.semantic import semantic_evaluation
    from semantic_pallet_planner.evaluation.state import apply_candidate
    from semantic_pallet_planner.domain import restore_placed
    seen=set()
    for cid in repo.list_cases('all'):
        dc=repo.get_decision_case(cid);s=repo.get_scenario(dc['base_scenario_id']);cs=repo.get_candidate_set(dc['candidate_set_id']);o=repo.get_oracle(cid)
        rule=o['ground_truth_rule'];seen.add(rule['rule_type'])
        by_id={v['candidate_id']:v for v in o['candidate_evaluations']}
        for candidate in cs['candidates']:
            scores,errors=semantic_evaluation(restore_placed(apply_candidate(dc,candidate)),rule,{'container':s['container']})
            expected=by_id[candidate['candidate_id']]
            assert errors==expected['hard_violations']
            for k,v in scores.items():assert abs(v-expected['semantic_score_components'][k])<=1e-6,(cid,k,v)
    assert seen=={'heavy_low','heavy_center','fragile_protect','category_group','category_separate'}
