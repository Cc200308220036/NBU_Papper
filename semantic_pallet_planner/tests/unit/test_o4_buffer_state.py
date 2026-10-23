import copy
import pytest
from semantic_pallet_planner.config import generator_config,load_config
from semantic_pallet_planner.o4.common import O4Error,digest
from semantic_pallet_planner.o4.buffer.validation import gold_specs,run_gold,diagnostics
from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive,public_state,place
from semantic_pallet_planner.o4.buffer.buffer_protocol import validate_state,action,validate_action
from semantic_pallet_planner.o4.fixtures import item,CONTAINER,policy,render_policy

@pytest.fixture(scope='module')
def cfg():return generator_config(load_config())

@pytest.mark.parametrize('name,expected',gold_specs())
def test_declared_state_machine_gold(name,expected,cfg):
    if expected=='ok':run_gold(name,cfg)
    else:
        with pytest.raises(O4Error) as exc:run_gold(name,cfg)
        assert exc.value.code==expected


def test_full_state_binding_and_future_counterexamples(cfg):
    rows=diagnostics(cfg)
    assert all(r['passed'] for r in rows),[(r['name'],r['passed']) for r in rows]


def test_closed_buffer_schema_and_atomic_failed_commit():
    box=item('a');attrs=box.pop('_attributes');s=receive(initial(CONTAINER),box,attrs)
    pub=public_state(s,render_policy(policy([])))
    pub['private_reference']={'answer':True}
    pub['buffer_state_hash']=digest({k:v for k,v in pub.items() if k!='buffer_state_hash'})
    with pytest.raises(O4Error):validate_state(pub)
    before=copy.deepcopy(s)
    from semantic_pallet_planner.o4.buffer.buffer_candidates import pools
    groups,_=pools(s,render_policy(policy([])),policy([]),generator_config(load_config()))
    bad=copy.deepcopy(groups[0]['eligible'][0]['raw']);bad['pose']['x_mm']=10000
    with pytest.raises(O4Error) as exc:place(s,bad)
    assert exc.value.code=='physical_rejection' and s==before


def test_commit_rejects_public_and_raw_pose_divergence(cfg):
    from semantic_pallet_planner.o4.buffer.buffer_candidates import pools,public_candidates
    from semantic_pallet_planner.o4.buffer.buffer_evaluation import submit
    box=item('a');attrs=box.pop('_attributes');text=render_policy(policy([]))
    s=receive(initial(CONTAINER),box,attrs);pub=public_state(s,text)
    groups,_=pools(s,text,policy([]),cfg);candidate=copy.deepcopy(groups[0]['eligible'][0])
    public=public_candidates(groups,pub['buffer_state_hash'])
    value=action(pub,'PLACE',pick='a',label=candidate['candidate_id'],candidates=public)
    candidate['raw']['pose']['x_mm']+=1
    before=copy.deepcopy(s)
    with pytest.raises(O4Error) as exc:submit(s,text,policy([]),candidate,value,public)
    assert exc.value.code=='invalid_binding' and s==before
