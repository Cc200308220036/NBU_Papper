import copy
import random
import pytest
from semantic_pallet_planner.protocol import build_request,resolve_response,state_hash
from semantic_pallet_planner.selectors.baselines import make_selector,NAMES
from semantic_pallet_planner.domain import PalletState
from semantic_pallet_planner.validation import validate
from semantic_pallet_planner.logging.artifacts import Experiment
from semantic_pallet_planner.config import load_config


def request(repo):
    case=repo.get_decision_case('DC_00151');s=repo.get_scenario(case['base_scenario_id'])
    return build_request(s['container'],case,repo.get_candidate_set(case['candidate_set_id']),'w.png','c.png')


def test_all_dataset_links(repo):
    assert repo.validate_links()=={'cases':360,'base_scenarios':100}


def test_repository_isolation(repo):
    s=repo.get_scenario('SCN_0051');s['items'].clear()
    assert repo.get_scenario('SCN_0051')['items']
    with pytest.raises(ValueError):repo.get_scenario('../escape')


def test_frozen_snapshot_and_hash(repo):
    q=request(repo);state=PalletState.from_dict(q);v=state.data;v['placed_items'].clear()
    assert state.data==q
    assert state_hash(q['container'],q)==q['state_hash']
    q['available_items'][0]['mass_kg']+=1
    assert state_hash(q['container'],q)!=q['state_hash']


@pytest.mark.parametrize('field,value',[('schema_version','wrong'),('state_hash','0'*64),('request_id','old'),('candidate_id','unknown'),('x_mm',0),('selector','demo'),('confidence',2),('reason',False)])
def test_invalid_response(repo,field,value):
    q=request(repo);a=make_selector('geometry_greedy').select(q,rng=random.Random(0));a[field]=value
    with pytest.raises(ValueError):resolve_response(q,a)


@pytest.mark.parametrize('name',NAMES)
def test_baseline_visibility_and_determinism(repo,name):
    q=request(repo);original=copy.deepcopy(q);kwargs={}
    if name=='candidate_oracle':kwargs['oracle']=repo.get_oracle('DC_00151')
    if name=='handcrafted_rule':kwargs['rules']=repo.get_rules('SCN_0051')
    s=make_selector(name,**kwargs)
    a=s.select(q,rng=random.Random(11));b=s.select(q,rng=random.Random(11),memories=['ignored'])
    assert a==b and q==original
    assert resolve_response(q,a)['candidate_id']==a['candidate_id']
    assert s.privileged_input==(name in ('handcrafted_rule','candidate_oracle'))
    assert not {'oracle_candidate_id','ground_truth_rule','split','candidate_evaluations'}.intersection(q)


def test_config_output_safety(cfg):
    cfg['output_root']=cfg['dataset']
    with pytest.raises(ValueError):Experiment(cfg,'no_write')
    with pytest.raises(ValueError):load_config(top_k=0)
    with pytest.raises(ValueError):validate('step',{'schema_version':'pallet_step_v1'})


def test_acceptance_rejects_truncated_episodes_before_writing(tmp_path):
    from semantic_pallet_planner.cli import main
    with pytest.raises(ValueError,match='complete episodes'):
        main(['acceptance','--max-steps','1','--output-root',str(tmp_path/'out')])
    assert not (tmp_path/'out').exists()
