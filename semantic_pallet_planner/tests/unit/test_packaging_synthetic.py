"""Synthetic adapter tests use constructed orders only; no formal task dispatch."""
import copy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import pytest
from semantic_pallet_planner.jev_select import packaging_synthetic_data as data
from semantic_pallet_planner.jev_select import packaging_synthetic_protocol as protocol
from semantic_pallet_planner.jev_select import packaging_synthetic_orders as plans
from semantic_pallet_planner.jev_select import packaging_evaluation_orders as runner
from semantic_pallet_planner.jev_select import packaging_evaluation_memory as memory
from semantic_pallet_planner.jev_select.contracts import digest,validate_schema,JevSelectError,DecisionContext
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.tests.unit.test_packaging_runtime import mechanism_task,item
from semantic_pallet_planner.jev_select.episode import run_episode
from test_packaging_remote import Fake

@pytest.fixture(autouse=True)
def no_network_or_credentials(monkeypatch):
    import socket
    from semantic_pallet_planner.jev_select import transport
    def forbidden(*a,**k):raise AssertionError('network/credentials forbidden')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(transport,'credential',forbidden)


def relation(groups=(),forks=()):
    return {'memory_scope_version':data.MEMORY_SCOPE,'material_source_components':['MATERIAL_SHARED'],
      'order_related_source_groups':list(groups),'excluded_fork_digests':list(forks),'new_combination_status':'PASS'}


def setup(tmp_path,relations=None,n=3):
    t=mechanism_task([item(str(i),size=(20,20,20)) for i in range(n)])
    t.update(task_id='CONSTRUCTED_SYNTH',source_group_id='CONSTRUCTED_GROUP',partition='train')
    d={'version':data.VERSION,'fixture_only':True,'data_identity':digest('CONSTRUCTED_SYNTHETIC'),
       'tasks':[t],'dataset_root':None,'relations':{t['task_id']:relations or relation()}}
    return plans.prepare(d,tmp_path/'plan',purpose='SYNTHETIC_ENGINEERING')


def driver(cfg,p):
    mode=cfg['memory_mode'];rm='E' if mode=='E_unrelated_control' else mode
    return memory.MemoryDriver(cfg,snapshot=None if mode=='none' else p['snapshots'][rm],control=p['snapshots']['control'] if mode=='E_unrelated_control' else None)


def test_decimal_identity_order_and_validation():
    a={'id':'0007','length/mm':Decimal('300.0'),'width/mm':Decimal('0200'),'height/mm':Decimal('1e2'),'weight/kg':Decimal('6.3800')}
    assert data.identity(a)==['0007','300','200','100','6.38']
    b=dict(a);b['length/mm']=300
    assert digest(data.identity(a))==digest(data.identity(b))
    b['length/mm']=200;b['width/mm']=300
    assert digest(data.identity(a))!=digest(data.identity(b))
    for val in (True,Decimal('NaN'),Decimal('Infinity'),Decimal('-1'),0):
        with pytest.raises(JevSelectError):data.decimal_string(val)
    with pytest.raises(JevSelectError):data.runtime_number('0.123456789012345678901')
    with pytest.raises(JevSelectError):data.identity(dict(a,id=True))


def test_pool_conflicts_refs_and_hash_collision(monkeypatch):
    row={'id':'01','length/mm':20,'width/mm':10,'height/mm':5,'weight/kg':Decimal('.25'),'sequence':1}
    other=dict(row);other['height/mm']=6
    raw={'A':{'item_sequence':{'1':row,'2':row,'3':other}}}
    p=data.prototype_pool(raw,{'A':'C'})
    assert len(p['prototypes'])==2 and sum(len(r['references']) for r in p['prototypes'])==3
    assert p['article_physical_conflicts']['01']
    monkeypatch.setattr(data,'digest',lambda *a:'0'*64)
    with pytest.raises(JevSelectError):data.prototype_pool(raw,{'A':'C'})


def test_static_pressure_is_eligible_and_not_hidden_by_unknown(tmp_path):
    p=setup(tmp_path);t=copy.deepcopy(p['data']['tasks'][0]);t['items'][0]['mass_kg']=2000
    t['items'][1]['dimensions_mm']['length']=20000
    c=data.static_classification(t)
    assert c['data_validity']=='PASS' and c['single_item_fit']=='FAIL' and c['completion_necessary_conditions']=='FAIL'
    assert c['partial_loading_eligible'] and 'TOTAL_MASS_EXCEEDS_PAYLOAD' in c['reasons']


def test_multiset_90pct_and_no_sku_only_match():
    from collections import Counter
    a=Counter({'a':9,'b':1});b=Counter({'a':9,'c':1})
    assert data.related(a,b)
    assert not data.related(a,Counter({'a':8,'c':2}))
    assert not data.related(a,Counter({'a':20}))


def test_v11_six_methods_same_common_engine_and_saved_validation(tmp_path,monkeypatch):
    p=setup(tmp_path);f=Fake()
    s=runner.run_validation(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:f)
    assert s['categories']['COMPLETE']==6 and s['actual_model_api_calls']==0
    assert f.calls==12
    for j in p['jobs']:
        cp=read(tmp_path/'run/jobs'/j['job_id']/'checkpoint.json')
        assert cp['version']=='jev_checkpoint_v11'
        assert all(e['context']['version']=='jev_decision_context_v11' for e in cp['events'] if e.get('context'))
    def forbidden(*a,**k):raise AssertionError('saved validation dispatched')
    monkeypatch.setattr(memory.MemoryDriver,'resolve',forbidden)
    monkeypatch.setattr(runner.common,'_run_job',forbidden)
    runner.validate_run(tmp_path/'run')
    assert runner.run_validation(tmp_path/'plan',tmp_path/'run',resume=True,transport_factory=lambda *a:f)==s
    assert f.calls==12


@pytest.mark.parametrize('phase',['DECISION_READY','SELECTED','MONITORED','COMMITTED'])
def test_v11_resume_binding_no_retrieval_or_recommit(tmp_path,monkeypatch,phase):
    p=setup(tmp_path);j=p['jobs'][4];cfg=j['config'];f=Fake()
    ledger=protocol.SyntheticLedger(tmp_path/'ledger',p['request_budget'],{x['job_id']:x['config'] for x in p['jobs']})
    sel=protocol.selector_factory(j['method_id'],config=cfg,transport=f,ledger=ledger,job_id=j['job_id']);d=driver(cfg,p);saved=[]
    class Cut(BaseException):pass
    def hook(cp):
        if cp['phase']==phase:saved.append(cp);raise Cut()
    with pytest.raises(Cut):run_episode(p['data']['tasks'][0],sel,cfg,job_id=j['job_id'],method=j['method_id'],memory_driver=d,on_checkpoint=hook)
    def forbidden(*a,**k):raise AssertionError('repeated durable action')
    monkeypatch.setattr(d,'resolve',forbidden)
    if phase!='DECISION_READY':monkeypatch.setattr(sel,'select',forbidden)
    from semantic_pallet_planner.jev_select.stability import monitor
    from semantic_pallet_planner.jev_select import execution
    if phase in ('MONITORED','COMMITTED'):monkeypatch.setattr(monitor,'monitor_selected_action',forbidden)
    if phase=='COMMITTED':monkeypatch.setattr(execution,'commit_physical',forbidden)
    cp=saved[0];r=run_episode(p['data']['tasks'][0],sel,cfg,job_id=j['job_id'],method=j['method_id'],memory_driver=d,resume=cp,event_limit=len(cp['events'])+1)
    assert r['events'][-1]['event']=='PLACE' and f.calls==1


def test_multigroup_and_fork_exclusions_reach_actual_retrieval(tmp_path):
    snaps=runner.snapshots();groups=snaps['T']['source_groups']+snaps['E']['source_groups']
    forks=[c['provenance']['fork_digest'] for c in snaps['T']['cases']]
    p=setup(tmp_path,relation(sorted(set(groups)),sorted(set(forks))))
    t=p['data']['tasks'][0]
    from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive
    from semantic_pallet_planner.jev_select.episode import decision_inputs
    state=initial(t['container'],3)
    for o in t['items']:state=receive(state,o,t['attributes'][o['item_id']])
    for j in p['jobs'][3:]:
        cfg=j['config'];ctx=decision_inputs(state,t,cfg,j['job_id'],'D',memory_driver=driver(cfg,p))[3]
        assert not ctx.data['model_state']['memories'] and cfg['excluded_fork_digests']==sorted(set(forks))
        assert cfg['excluded_source_groups']==sorted(set(groups))
    with pytest.raises(JevSelectError):validate_schema('config_v10',p['jobs'][0]['config'])


@pytest.mark.parametrize('kind',['OK','PROVIDER_FAILURE','UNKNOWN_IN_FLIGHT','CRASH'])
def test_constructed_real_origin_ledger_accounting_no_network(tmp_path,kind):
    p=setup(tmp_path);j=p['jobs'][2];cfg=j['config'];t=p['data']['tasks'][0];saved=[];f=Fake()
    ledger=protocol.SyntheticLedger(tmp_path/'ledger',p['request_budget'],{x['job_id']:x['config'] for x in p['jobs']})
    sel=protocol.selector_factory(j['method_id'],config=cfg,transport=f,ledger=ledger,job_id=j['job_id'])
    class Cut(BaseException):pass
    def cp(c):
        if c['phase']=='DECISION_READY':saved.append(c);raise Cut()
    with pytest.raises(Cut):run_episode(t,sel,cfg,job_id=j['job_id'],method=j['method_id'],memory_driver=driver(cfg,p),on_checkpoint=cp)
    class SimulatedRealOrigin:
        origin='jev'  # Constructed origin record ONLY; no network implementation.
        calls=0
        def complete(self,body):
            self.calls+=1
            from semantic_pallet_planner.jev_select.transport import outcome
            if kind=='CRASH':raise RuntimeError('simulated uncertain send')
            if kind=='OK':return f.complete(body)
            return outcome(kind,error='CONSTRUCTED',network_attempted=None if kind=='UNKNOWN_IN_FLIGHT' else True)
    transport=SimulatedRealOrigin();ctx=DecisionContext.from_dict(saved[0]['pending_event']['context']);did=saved[0]['pending_event']['decision_id']
    row=ledger.request(ctx,j['job_id'],did,transport)
    if kind=='OK':
        # Fake returns network_attempted=True but remains explicitly constructed origin evidence.
        pass
    ledger.request(ctx,j['job_id'],did,transport)
    assert transport.calls==1
    stats=protocol.request_accounting(ledger._load()['requests'])
    assert stats['send_reservations']==1
    if kind in ('UNKNOWN_IN_FLIGHT','CRASH'):
        assert stats['actual_model_api_calls']=='UNKNOWN' and stats['unknown_real_send_count']==1
    else:assert stats['actual_model_api_calls']==1
    assert stats['model_cost_usd']=='UNKNOWN'
    bad=copy.deepcopy(p['request_budget']);bad['global']+=1
    with pytest.raises(JevSelectError):protocol.SyntheticLedger(tmp_path/'ledger',bad,{x['job_id']:x['config'] for x in p['jobs']})


def test_formal_synthetic_never_dispatched(tmp_path,monkeypatch):
    p=setup(tmp_path);p['purpose']=protocol.PURPOSE
    monkeypatch.setattr(runner,'validate_plan',lambda *a:p)
    with pytest.raises(JevSelectError,match='FORMAL_TEST_EXECUTION_FORBIDDEN'):
        runner.run_validation(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:pytest.fail('dispatch'))
    assert not (tmp_path/'run').exists()


def test_singleton_v11_does_not_send(tmp_path,monkeypatch):
    p=setup(tmp_path,n=1);f=Fake()
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
    from semantic_pallet_planner.jev_select.contracts import CandidateBundle
    original=CandidateProvider.build
    def one(self,*a,**kw):
        b=original(self,*a,**kw).data
        b['physical_candidates']=b['physical_candidates'][:1];b['selectable_candidates']=b['selectable_candidates'][:1]
        b['physical_digest']=digest(b['physical_candidates']);b['selectable_digest']=digest(b['selectable_candidates'])
        return CandidateBundle.from_dict(b)
    monkeypatch.setattr(CandidateProvider,'build',one)
    s=runner.run_validation(tmp_path/'plan',tmp_path/'run',transport_factory=lambda *a:f)
    assert f.calls==0 and s['request_statistics']['send_reservations']==0
    assert read(tmp_path/'run/first_gate.json')['status']=='DEFER_NO_EXPOSURE'


def test_relation_order_mapping_and_transitive_fork_inheritance():
    def task(tid,na):
        return {'task_id':tid,'items':[{'dimensions_mm':{'length':20 if i<na else 30,'width':10,'height':10},'mass_kg':1} for i in range(10)]}
    tasks=[task('CONSTRUCTED_A',10),task('CONSTRUCTED_B',9),task('CONSTRUCTED_C',8)]
    raw={'OLD':{'item_sequence':{str(i):{'length/mm':20 if i<7 else 30,'width/mm':10,'height/mm':10,'weight/kg':1,'sequence':i} for i in range(10)}}}
    audit={'components':[{'component':'OLD_COMPONENT','raw_keys':['OLD']}]}
    r=data.relations(tasks,[],{'prototypes':[]},raw,audit,[],{'OLD_COMPONENT':['SG_1','SG_2']},{'SG_2':{'a'*64}})
    for tid in r:
        assert r[tid]['order_related_source_groups']==['SG_1','SG_2']
        assert r[tid]['excluded_fork_digests']==['a'*64]
        assert r[tid]['new_combination_status']=='PAUSE_OVERLAPPING_ORDER'


def test_sending_crash_is_budgeted_unknown_on_resume(tmp_path):
    p=setup(tmp_path);j=p['jobs'][2];cfg=j['config'];t=p['data']['tasks'][0];saved=[]
    class Cut(BaseException):pass
    def cp(c):
        if c['phase']=='DECISION_READY':saved.append(c);raise Cut()
    l=protocol.SyntheticLedger(tmp_path/'ledger',p['request_budget'],{x['job_id']:x['config'] for x in p['jobs']})
    f=Fake();sel=protocol.selector_factory(j['method_id'],config=cfg,transport=f,ledger=l,job_id=j['job_id'])
    with pytest.raises(Cut):run_episode(t,sel,cfg,job_id=j['job_id'],method=j['method_id'],memory_driver=driver(cfg,p),on_checkpoint=cp)
    def cut(phase,row):
        if phase=='SENDING':raise Cut()
    l.hook=cut;ctx=DecisionContext.from_dict(saved[0]['pending_event']['context']);did=saved[0]['pending_event']['decision_id']
    with pytest.raises(Cut):l.request(ctx,j['job_id'],did,f)
    restored=protocol.SyntheticLedger(tmp_path/'ledger',p['request_budget'],{x['job_id']:x['config'] for x in p['jobs']})
    r=restored.request(ctx,j['job_id'],did,f)
    assert r['state']=='UNKNOWN_SEND' and f.calls==0 and restored.statistics()['send_reservations']==1
