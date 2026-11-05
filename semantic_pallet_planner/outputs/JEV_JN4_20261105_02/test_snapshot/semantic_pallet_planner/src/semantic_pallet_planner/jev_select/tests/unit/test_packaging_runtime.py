"""Runtime engineering checks. All selectors are local, constructed or bounded."""
import copy
from pathlib import Path
import pytest

from semantic_pallet_planner.jev_select.packaging_runtime import (
    load_runtime_dataset,load_runtime_config,LocalPackagingDouble,METHODS,INSTRUCTION,
    DATA_VERSION,no_policy,layout_facts,geometry_facts,pose_from_corner,length_unit,
    evaluate_state,summary,runtime_readiness,
)
from semantic_pallet_planner.jev_select.contracts import (
    digest,DecisionContext,CandidateBundle,JevSelectError,MemorySnapshot,validate_schema,
)
from semantic_pallet_planner.jev_select.episode import run_episode,decision_inputs,semantic_record
from semantic_pallet_planner.jev_select.context import ContextBuilder,validate_context
from semantic_pallet_planner.jev_select.candidates import PublicBusinessGuard,CandidateProvider
from semantic_pallet_planner.jev_select.config import generator_config
from semantic_pallet_planner.jev_select.selector import result,JevSelector
from semantic_pallet_planner.jev_select.execution import commit_physical
from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive,place
from semantic_pallet_planner.o4.extensions.e2.protocol import observation
from semantic_pallet_planner.planner.constraints import evaluate_pose
from semantic_pallet_planner.domain import internal_item,restore_placed
from semantic_pallet_planner.jev_select.dataset_j4 import offline_dataset_guard

REPO=Path(__file__).resolve().parents[6]


@pytest.fixture(scope='module')
def data():
    return load_runtime_dataset(REPO/'semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02')


def item(name,mass=1,capacity=100,stackable=True,size=(100,100,100)):
    return {'item_id':name,'mass_kg':mass,'dimensions_mm':dict(zip(('length','width','height'),size)),
        'stackable':stackable,'top_load_limit_kg_synthetic':capacity,'fragile':False,
        'weight_class':'medium','product_category':'general'}


def attrs(obj):
    return {'object_id':obj['item_id'],'physical_top_load_limit_kg':obj['top_load_limit_kg_synthetic'],
        'cargo_category':'general','packaging':{'reinforced':False},
        'labels':{'no_top_load':not obj['stackable'],'max_top_load_kg':obj['top_load_limit_kg_synthetic']}}


def mechanism_task(items):
    return {'version':DATA_VERSION,'task_id':'CONSTRUCTED_NOT_SOURCE_ORDER','mode':'controlled_packaging',
        'layer':'CONSTRUCTED_MECHANISM','feasibility_status':'UNKNOWN','regions':[],
        'reference_policy':{'version':DATA_VERSION,'rules':[]},'instruction_text':INSTRUCTION,
        'container':{'container_id':'fixture','coordinate_frame':'container_bottom_center',
            'length_mm':1000,'width_mm':1000,'max_height_mm':1000,'max_payload_kg':1000},
        'items':items,'attributes':{o['item_id']:attrs(o) for o in items}}


def configured(task,method=METHODS[0],identity=None):
    return load_runtime_config(data_identity=identity or digest('CONSTRUCTED_NOT_SOURCE_DATA'),
        method=method,task_digest=digest(task))


def manual_candidate(state,name,x=-50,y=-50,z=0,yaw=0,mass_override=None):
    obj=copy.deepcopy(next(p['item'] for p in state['pending_items'] if p['item']['item_id']==name))
    if mass_override is not None:obj['mass_kg']=mass_override
    obj=internal_item(obj);size=obj['dimensions'][:2]
    if yaw==90:size=size[::-1]
    cfg=generator_config();cfg['container']=state['container']
    return evaluate_pose(obj,restore_placed(state['placed_items']),x,y,z,*size,yaw,cfg)


def place_manually(state,obj,*,x=-50,y=-50,z=0):
    state=receive(state,obj,attrs(obj));candidate,error=manual_candidate(state,obj['item_id'],x=x,y=y,z=z)
    assert error is None
    return place(state,candidate['visible'])


def test_actual_frozen_fields_to_shared_pool_and_public_facts(data):
    task=data['tasks'][0];cfg=configured(task,identity=data['data_identity'])
    state=initial(task['container'],3)
    for obj in task['items'][:3]:state=receive(state,obj,task['attributes'][obj['item_id']])
    with offline_dataset_guard() as counters:
        req,policy,bundle,context=decision_inputs(state,task,cfg,'P','P_D0000')
    assert counters=={'network_attempts':0,'credential_reads':0}
    assert bundle.data['physical_candidates']==bundle.data['selectable_candidates']
    assert len(bundle.data['physical_candidates'])<=48
    assert all(row['returned']<=16 and 'rejections' in row for row in bundle.data['generation_counts'])
    body=context.data['request_body'];public=body['state'];text=str(body)
    for forbidden in ('source_order','sku_id','original_physical','article_id','witness',
        'cargo_category','business_requirements','reinforced','labels','regions','relative_position','compatibility'):
        assert forbidden not in text
    assert len(public['available_objects'])==3 and not public['placed_objects'] and public['memories']==[]
    for original,exposed in zip(task['items'][:3],public['available_objects']):
        assert exposed['mass_kg']==original['mass_kg']
        assert exposed['dimensions_mm']==original['dimensions_mm']
        assert exposed['max_top_load_kg']==original['top_load_limit_kg_synthetic']
        assert exposed['stackable']==original['stackable']
    for key in ('data_identity','physical_identity','strategy_identity','task_identity'):
        assert context.data['local_binding']['runtime_identity'][key]==cfg['runtime_identity'][key]
    future=copy.deepcopy(task);future['items'][5]['mass_kg']=999
    othercfg=configured(future,identity=data['data_identity'])
    other=decision_inputs(state,future,othercfg,'P','P_D0000')[3]
    assert other.data['request_body']==body
    assert other.data['local_binding']['runtime_identity']!=context.data['local_binding']['runtime_identity']


def test_all_local_selectors_share_physical_pool(data):
    task=data['tasks'][0];state=initial(task['container'],3)
    for obj in task['items'][:3]:state=receive(state,obj,task['attributes'][obj['item_id']])
    contexts=[];pools=[]
    for method in METHODS:
        cfg=configured(task,method);req,pol,bundle,ctx=decision_inputs(state,task,cfg,'P','P_D0000')
        pools.append(bundle.data['physical_digest']);contexts.append(ctx.data['request_body'])
        selected=LocalPackagingDouble(method).select(ctx,decision_id='P_D0000')
        after=commit_physical(state,[],req,bundle,ctx,selected,cfg)
        assert not evaluate_state(after)['violations']
        assert selected.data['source']=='test_double' and not selected.data['attempt_ids']
    assert len(set(pools))==1 and contexts[0]==contexts[1]


def test_capacity_ancestor_context_and_commit_gate_reject_resigned_overload():
    task=mechanism_task([]);state=initial(task['container'],3)
    state=place_manually(state,item('a',capacity=20))
    state=place_manually(state,item('b',mass=12),z=100)
    assert [o['supported_load_kg'] for o in state['placed_items']]==[12,0]
    top=item('c',mass=9);state=receive(state,top,attrs(top));task['items']=[top];cfg=configured(task)
    assert manual_candidate(state,'c',z=200)[1]=='overload'
    # A dishonest upstream bundle claims an equality-8kg pose is valid for actual 9kg.
    valid,error=manual_candidate(state,'c',z=200,mass_override=8);assert error is None
    req=observation(state,INSTRUCTION,[]);policy=no_policy(req)
    original=CandidateProvider().build(state,req,generator_config(),config=cfg).data
    c=valid['visible'];original.update(physical_candidates=[c],physical_digest=digest([c]),
        selectable_candidates=[],selectable_digest=digest([]),selectable_pool='unfiltered')
    bundle=PublicBusinessGuard().filter(req,policy,CandidateBundle.from_dict(original),cfg)
    ctx=ContextBuilder(cfg).build(req,bundle,policy)
    assert ctx.data['route']=='SINGLETON_BYPASS'
    changes=ctx.data['criteria']['C01']['load_changes']
    assert sorted(ch['increment_top_load_kg'] for ch in changes)==[9,9]
    assert any(ch['after_top_load_kg']==21 and ch['remaining_top_load_kg']==-1 for ch in changes)
    selected=result(ctx,status='singleton',source='singleton',label='C01')
    before=copy.deepcopy(state)
    with pytest.raises(JevSelectError,match='physical_rejection.*overload'):
        commit_physical(state,[],req,bundle,ctx,selected,cfg)
    assert before==state
    # Real equality path goes through unchanged independent oracle and state update.
    equal=copy.deepcopy(state);equal['pending_items'][0]['item']['mass_kg']=8
    equal=place(equal,c)
    assert [o['supported_load_kg'] for o in equal['placed_items']]==[20,8,0]
    assert not evaluate_state(equal)['violations']


def test_double_support_area_fraction_and_public_delta_not_full_weight_each():
    task=mechanism_task([]);state=initial(task['container'],3)
    state=place_manually(state,item('left',capacity=6,size=(60,100,100)),x=-50)
    state=place_manually(state,item('right',capacity=4,size=(40,100,100)),x=10)
    top=item('top',mass=10);state=receive(state,top,attrs(top))
    raw,error=manual_candidate(state,'top',z=100);assert error is None
    after=place(state,raw['visible']);assert not evaluate_state(after)['violations']
    loads,edges,_=layout_facts(after['placed_items'])
    assert loads=={'left':6,'right':4,'top':0}
    assert [e['fraction'] for e in edges['top']]==[.6,.4]
    assert sum(e['fraction'] for e in edges['top'])==1
    task['items']=[top];cfg=configured(task)
    req=observation(state,INSTRUCTION,[]);policy=no_policy(req)
    bundle=CandidateProvider().build(state,req,generator_config(),config=cfg)
    # The unchanged Top-16 sampler can omit this admissible bridge. This explicit
    # constructed interface check supplies its oracle-checked action; it does not
    # claim candidate reachability or modify the production generator.
    from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate
    from semantic_pallet_planner.o4.buffer.buffer_state import physical
    assert not check_candidate(physical(state,'top'),{'container':state['container']},raw['visible'])
    b=bundle.data;c=raw['visible']
    b.update(physical_candidates=[c],physical_digest=digest([c]),
        selectable_candidates=[],selectable_digest=digest([]),selectable_pool='unfiltered')
    bundle=PublicBusinessGuard().filter(req,policy,CandidateBundle.from_dict(b),cfg)
    ctx=ContextBuilder(cfg).build(req,bundle,policy).data
    upper=[c for c in ctx['criteria'].values() if c['pose']['z_base_mm']==100]
    assert upper and sorted(d['increment_top_load_kg'] for d in upper[0]['load_changes'])==[4,6]


@pytest.mark.parametrize('capacity',[0,100])
def test_nonstackable_is_hard_even_when_source_capacity_positive(capacity):
    task=mechanism_task([]);state=initial(task['container'],3)
    state=place_manually(state,item('base',capacity=capacity,stackable=False))
    top=item('top');state=receive(state,top,attrs(top))
    assert manual_candidate(state,'top',z=100)[1]=='non_stackable_support'
    task['items']=[top];cfg=configured(task)
    req,pol,bundle,ctx=decision_inputs(state,task,cfg,'P','P_D0000')
    obj=ctx.data['model_state']['placed_objects'][0]
    assert obj['max_top_load_kg']==capacity and obj['effective_top_permission_kg']==0
    assert obj['capacity_utilization'] is None and obj['utilization_status']=='NOT_APPLICABLE'
    assert not any(c['pose']['z_base_mm']==100 for c in bundle.data['physical_candidates'])


@pytest.mark.parametrize('yaw',[0,90])
def test_geometry_orientation_corner_centroid_and_units(yaw):
    task=mechanism_task([]);obj=item('rot',mass=7,size=(120,80,60))
    state=receive(initial(task['container'],3),obj,attrs(obj))
    raw,error=manual_candidate(state,'rot',x=100,y=-120,yaw=yaw);assert error is None
    c=raw['visible'];size=c['oriented_size_mm'];pose=c['pose']
    assert size==([120,80,60] if yaw==0 else [80,120,60])
    geo=geometry_facts(pose,size)
    assert geo['corner_mm']==[100,-120,0]
    assert geo['centroid_mm']==[pose['x_mm'],pose['y_mm'],30]
    assert pose_from_corner(geo['corner_mm'],size,yaw)==pose
    assert length_unit(length_unit(geo['centroid_mm'],'mm','m'),'m','mm')==pytest.approx(geo['centroid_mm'])
    assert not evaluate_state(place(state,c))['violations']


def test_zero_area_height_gap_and_same_volume_mass_preserved():
    from semantic_pallet_planner.jev_select.dataset_packaging import constructed_checks
    assert all(v=='PASS' for v in constructed_checks().values())
    state=initial(mechanism_task([])['container'],3)
    state=place_manually(state,item('base'))
    top=item('top',mass=10);state=receive(state,top,attrs(top))
    heavy=manual_candidate(state,'top',z=100)[0]
    light=manual_candidate(state,'top',z=100,mass_override=2)[0]
    assert heavy['visible']['oriented_size_mm']==light['visible']['oriented_size_mm']
    assert heavy['load_increments']=={'base':10} and light['load_increments']=={'base':2}
    assert manual_candidate(state,'top',x=50,z=100)[1]=='insufficient_support'
    assert manual_candidate(state,'top',z=100+2e-6)[1]=='insufficient_support'


class StackDouble(LocalPackagingDouble):
    """Constructed-only earliest visible item, prefer highest feasible pose."""
    def select(self,context,*,decision_id):
        v=context.data;pending=v['model_state']['buffer']['pending'];pick=min(pending,key=lambda p:p['arrival_index'])['object_id']
        labels=[l for l,c in v['criteria'].items() if c['pick_object']==pick]
        label=min(labels,key=lambda l:(-v['criteria'][l]['pose']['z_base_mm'],
            v['criteria'][l]['pose']['x_mm'],v['criteria'][l]['pose']['y_mm']))
        return result(context,status='selected',source='test_double',label=label)


@pytest.mark.parametrize('phase',['READY','COMMITTED'])
def test_recovery_reconstructs_load_once_and_rejects_each_identity(phase):
    task=mechanism_task([item('a',capacity=20),item('b',mass=12),item('c',mass=8)])
    cfg=configured(task);selector=StackDouble();saved=[]
    class Interrupted(RuntimeError):pass
    def hook(name,cp):
        if phase=='COMMITTED' and name=='after_commit_checkpoint' and cp['state']['placed_count']==2:
            saved.append(copy.deepcopy(cp));raise Interrupted()
    if phase=='COMMITTED':
        with pytest.raises(Interrupted):run_episode(task,selector,cfg,job_id='P',method=cfg['selector'],hook=hook)
        cp=saved[0];assert cp['state']['placed_items'][0]['supported_load_kg']==12
    else:
        cp=run_episode(task,selector,cfg,job_id='P',method=cfg['selector'],event_limit=5)['checkpoint']
    with offline_dataset_guard() as counters:
        resumed=run_episode(task,selector,cfg,job_id='P',method=cfg['selector'],resume=cp)
    assert all(v==0 for v in counters.values())
    uninterrupted=run_episode(task,selector,cfg,job_id='P',method=cfg['selector'])
    assert resumed['final_state']==uninterrupted['final_state']
    assert [o['supported_load_kg'] for o in resumed['final_state']['placed_items']]==[20,8,0]
    assert resumed['summary']['completed'] and resumed['summary']['physical_valid']
    for key in cfg['runtime_identity']:
        changed=copy.deepcopy(cfg);changed['runtime_identity'][key]=digest(['different',key])
        with pytest.raises(JevSelectError):run_episode(task,selector,changed,job_id='P',method=cfg['selector'],resume=cp)
    bad=copy.deepcopy(cp);bad['state']['placed_items'][0]['supported_load_kg']+=1
    with pytest.raises(JevSelectError):run_episode(task,selector,cfg,job_id='P',method=cfg['selector'],resume=bad)
    bad=copy.deepcopy(cp);bad['version']='jev_checkpoint_v2'
    with pytest.raises(JevSelectError):run_episode(task,selector,cfg,job_id='P',method=cfg['selector'],resume=bad)


def test_new_context_rejects_old_memory_and_remote_selector(data):
    task=data['tasks'][0];cfg=configured(task);state=initial(task['container'],3)
    for obj in task['items'][:3]:state=receive(state,obj,task['attributes'][obj['item_id']])
    req,pol,bundle,ctx=decision_inputs(state,task,cfg,'P','P_D0000')
    with pytest.raises(JevSelectError,match='memory_protocol_incompatible'):
        ContextBuilder(cfg).build(req,bundle,pol,memories=MemorySnapshot.empty())
    with pytest.raises(JevSelectError,match='remote_and_old_memory_protocol_disabled'):
        JevSelector(cfg,None,'P').select(ctx,decision_id='P_D0000')
    bad=ctx.data;bad['model_state']['memories']=[{'text':'old semantics'}]
    with pytest.raises(JevSelectError):validate_context(DecisionContext.from_dict(bad),config=cfg)
    bad=ctx.data;bad['model_state']['future_items']=[]
    with pytest.raises(JevSelectError):validate_context(DecisionContext.from_dict(bad),config=cfg)
    bad=ctx.data;bad['criteria']['C01']['load_changes']=[{'fake':'answer'}]
    with pytest.raises(JevSelectError):validate_context(DecisionContext.from_dict(bad),config=cfg)


def test_empty_state_metrics_na_and_empty_pool_not_global_infeasible():
    task=mechanism_task([item('large',size=(1200,1200,1200))]);cfg=configured(task)
    ep=run_episode(task,LocalPackagingDouble(),cfg,job_id='P',method=cfg['selector'])
    row=ep['summary'];assert row['termination_reason']=='STOP_NO_PHYSICAL_CANDIDATE'
    assert row['combined_centroid_mm'] is None and row['maximum_capacity_utilization'] is None
    assert not row['completed'] and row['physical_valid']
    assert row['feasibility_status']=='UNKNOWN' and not row['global_infeasibility_proven']
    assert row['cost']['model_calls']==0 and row['policy_effect']=='NOT_MEASURED'
    assert runtime_readiness()['third_party_api'].startswith('UNVERIFIED')


@pytest.mark.parametrize('case,reason',[('collision','overlap'),('bounds','out_of_bounds'),
    ('height','out_of_bounds'),('unsupported','insufficient_support'),('payload','over_payload')])
def test_v4_commit_common_geometry_payload_gate_even_with_resigned_pool(case,reason):
    task=mechanism_task([]);state=initial(task['container'],3)
    state=place_manually(state,item('base'))
    top=item('top');state=receive(state,top,attrs(top))
    raw,error=manual_candidate(state,'top',x=100);assert error is None
    candidate=raw['visible']
    if case=='collision':candidate['pose'].update(x_mm=0,y_mm=0,z_base_mm=0)
    elif case=='bounds':candidate['pose']['x_mm']=1000
    elif case=='height':candidate['pose']['z_base_mm']=1000
    elif case=='unsupported':candidate['pose']['z_base_mm']=50
    else:state['container']['max_payload_kg']=1
    task['items']=[top];cfg=configured(task)
    req=observation(state,INSTRUCTION,[]);pol=no_policy(req)
    b=CandidateProvider().build(state,req,generator_config(),config=cfg).data
    b.update(physical_candidates=[candidate],physical_digest=digest([candidate]),
        selectable_candidates=[],selectable_digest=digest([]),selectable_pool='unfiltered')
    bundle=PublicBusinessGuard().filter(req,pol,CandidateBundle.from_dict(b),cfg)
    ctx=ContextBuilder(cfg).build(req,bundle,pol)
    selected=result(ctx,status='singleton',source='singleton',label='C01')
    before=copy.deepcopy(state)
    with pytest.raises(JevSelectError,match='physical_rejection.*'+reason):
        commit_physical(state,[],req,bundle,ctx,selected,cfg)
    assert state==before
