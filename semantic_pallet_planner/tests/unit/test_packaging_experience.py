"""JN3 tests never authenticate or send network requests."""
import copy
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select import packaging_experience as m
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError,DecisionContext,CandidateBundle
from semantic_pallet_planner.jev_select.packaging_memory_protocol import load_memory_config,MemoryRequestLedger,memory_selector_factory
from semantic_pallet_planner.jev_select.episode import decision_inputs,run_episode
from semantic_pallet_planner.jev_select.ledger import read
from semantic_pallet_planner.jev_select.packaging_runtime import build_context,no_policy
from semantic_pallet_planner.jev_select.selector import bind_decision
from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive
from test_packaging_remote import fixture as old_fixture,Fake

REPO=Path(__file__).resolve().parents[3]
PARENT=REPO/'semantic_pallet_planner/outputs/JEV_JN2_20261104_03'

@pytest.fixture(scope='module')
def real():return m.build_snapshot(REPO,PARENT,frozen_at='2026-11-04T00:00:00+00:00')

@pytest.fixture
def constructed(real):
    s=real.data
    for c in s['cases']:
        c['fixture_only']=True;c.update(m.sealed({k:v for k,v in c.items() if k!='case_digest'},'case_digest'))
    return m.MemorySnapshotReceipt.from_dict(m.sealed({k:v for k,v in s.items() if k!='snapshot_digest'},'snapshot_digest'))


def inputs(s):
    t,_,_,_=old_fixture();c=load_memory_config(data_identity=digest('CONSTRUCTED'),task_digest=digest(t),snapshot_digest=s.data['snapshot_digest'],entry_digests=[c['public_digest'] for c in s.data['cases']],enabled=True)
    state=initial(t['container'],3)
    for o in t['items']:state=receive(state,o,t['attributes'][o['item_id']])
    req,pol,b,ctx=decision_inputs(state,t,c,'J','J_D0000')
    v,a=m.retrieve(m.public_query(ctx),s)
    ctx=bind_decision(build_context(c,req,b,pol,memory_view=v),'J','J_D0000')
    return t,c,b,ctx,v,a


def test_real_evidence_and_projection(real):
    assert len(real.data['cases'])==2
    for c in real.data['cases']:
        assert not c['fixture_only']
        for e in c['evidence'].values():m.validate_evidence(REPO,e)
        text=str(c['public_fragment'])
        for forbidden in ['F00','F02','SG_','C01','candidate_id','task_id','PCT','future_items','source_order']:
            assert forbidden not in text
        assert c['public_fragment']['historical_result']['delta']['actual_height_mm']>0
        assert 'POST_HOC_USER_REVISED_OBJECTIVE' in c['public_fragment']['limitations']
    c=real.data['cases'][0];e=copy.deepcopy(next(iter(c['evidence'].values())));e['value_digest']=digest('changed')
    with pytest.raises(JevSelectError):m.validate_evidence(REPO,e)


def test_query_closed(real):
    q=real.data['cases'][0]['retrieval_query']
    for bad in ['task_id','source_id','candidate_id','future','PCT','score','reference_action']:
        altered=copy.deepcopy(q);altered[bad]='secret'
        with pytest.raises(JevSelectError):m.retrieve(altered,real)
    for bad in [float('nan'),float('inf'),-1,True]:
        altered=copy.deepcopy(q);altered['features']['mean_mass']=bad
        with pytest.raises(JevSelectError):m.retrieve(altered,real)


def test_retrieval_isolation_determinism_limits(real):
    s=real.data;q=s['cases'][0]['retrieval_query'];g=s['cases'][0]['provenance']['source_group']
    v,a=m.retrieve(q,real,excluded_source_groups=[g]);v2,a2=m.retrieve(q,real,excluded_source_groups=[g])
    assert v.data==v2.data and a==a2
    assert len(v.data['entries'])==1 and a['candidates'][0]['excluded']
    v,_=m.retrieve(q,real,excluded_source_groups=s['source_groups']);assert not v.data['entries']
    v,_=m.retrieve(q,real,excluded_fork_digests=[c['provenance']['fork_digest'] for c in s['cases']]);assert not v.data['entries']
    q=copy.deepcopy(q);q['features']={k:10000 for k in m.RULE['features']}
    v,_=m.retrieve(q,real);assert not v.data['entries']
    with pytest.raises(JevSelectError):m.retrieve(q,real,rule={**m.RULE,'max_entries':2})

@pytest.mark.parametrize('tamper',['snapshot','case','public','unapproved','E','rule'])
def test_snapshot_rejects(real,tamper):
    s=real.data
    if tamper=='snapshot':s['frozen_at']='changed'
    if tamper=='case':s['cases'][0]['fixture_only']=True
    if tamper=='public':s['cases'][0]['public_fragment']['limitations']=[]
    if tamper=='unapproved':s['cases'][0]['review_status']='PENDING'
    if tamper=='E':s['mode']='E'
    if tamper=='rule':s['retrieval_rule']['minimum_score']=0
    with pytest.raises(JevSelectError):m.validate_snapshot(s)
    with pytest.raises(JevSelectError):m.validate_snapshot(real,digest('wrong'))


def test_explicit_context_body_ledger_and_old_protection(constructed,tmp_path):
    t,c,b,ctx,v,a=inputs(constructed)
    assert ctx.data['request_body']['state']['memories']==v.data['entries'] and v.data['entries']
    f=Fake();l=MemoryRequestLedger(tmp_path);sel=memory_selector_factory(m.METHOD,config=c,transport=f,ledger=l,job_id='J')
    r=sel.select(ctx,decision_id='J_D0000');assert r.data['status']=='selected'
    assert sel.select(ctx,decision_id='J_D0000').data==r.data and f.calls==1
    row=l.data['requests'][0];assert row['snapshot_digest']==c['memory_snapshot_digest'] and row['injected_digest']==digest(v.data['entries'])
    _,old,_,_=old_fixture()
    from semantic_pallet_planner.jev_select.context import ContextBuilder
    state=initial(t['container'],3)
    for o in t['items']:state=receive(state,o,t['attributes'][o['item_id']])
    req,pol,b0,oldctx=decision_inputs(state,t,old,'J','J_D0000')
    assert oldctx.data['model_state']['memories']==[]
    with pytest.raises(JevSelectError):ContextBuilder(old).build(req,b0,pol,memory_view=v)
    changed=v.data;changed['snapshot_digest']=digest('changed')
    with pytest.raises(JevSelectError):m.validate_view(m.MemoryView.from_dict(changed))
    with pytest.raises(JevSelectError):m.validate_view(v.data)

@pytest.mark.parametrize('cut',['INTENT','SENDING','RESPONSE_SAVED','SELECTION_SAVED'])
def test_ledger_restore(constructed,tmp_path,cut):
    _,c,_,ctx,_,_=inputs(constructed);f=Fake()
    class Cut(BaseException):pass
    def hook(phase,row):
        if phase==cut:raise Cut()
    l=MemoryRequestLedger(tmp_path,hook=hook);s=memory_selector_factory(m.METHOD,config=c,transport=f,ledger=l,job_id='J')
    with pytest.raises(Cut):s.select(ctx,decision_id='J_D0000')
    s=memory_selector_factory(m.METHOD,config=c,transport=f,ledger=MemoryRequestLedger(tmp_path),job_id='J')
    r=s.select(ctx,decision_id='J_D0000')
    assert r.data['status']==('unknown_in_flight' if cut=='SENDING' else 'selected')
    s.select(ctx,decision_id='J_D0000');assert f.calls==(0 if cut=='SENDING' else 1)

@pytest.mark.parametrize('phase',['SELECTED','MONITORED','COMMITTED'])
def test_episode_restore(constructed,tmp_path,phase,monkeypatch):
    t,c,_,ctx,v,_=inputs(constructed);f=Fake();l=MemoryRequestLedger(tmp_path)
    s=memory_selector_factory(m.METHOD,config=c,transport=f,ledger=l,job_id='J');saved=[]
    class Cut(BaseException):pass
    def checkpoint(cp):
        if cp['phase']==phase:saved.append(cp);raise Cut()
    with pytest.raises(Cut):run_episode(t,s,c,job_id='J',method=m.METHOD,memory_view=v,on_checkpoint=checkpoint)
    cp=saved[0]
    def forbidden(*a,**k):raise AssertionError('repeated saved dispatch')
    monkeypatch.setattr(s,'select',forbidden)
    import semantic_pallet_planner.jev_select.stability.monitor as mon
    import semantic_pallet_planner.jev_select.execution as ex
    if phase in ('MONITORED','COMMITTED'):monkeypatch.setattr(mon,'monitor_selected_action',forbidden)
    if phase=='COMMITTED':monkeypatch.setattr(ex,'commit_physical',forbidden)
    ep=run_episode(t,s,c,job_id='J',method=m.METHOD,memory_view=v,resume=cp,event_limit=len(cp['events'])+1)
    assert ep['events'][-1]['event']=='PLACE' and f.calls==1
    bad=copy.deepcopy(c);bad['memory_snapshot_digest']=digest('changed')
    with pytest.raises(JevSelectError):run_episode(t,s,bad,job_id='J',method=m.METHOD,memory_view=v,resume=cp)

@pytest.mark.parametrize('change',['private','drop_cost','drop_limits','E','budget','query'])
def test_view_closed_and_bound(constructed,change):
    _,c,_,ctx,v,_=inputs(constructed);d=v.data
    if change=='private':d['entries'][0]['source_order']='secret'
    if change=='drop_cost':del d['entries'][0]['historical_result']['delta']['actual_height_mm']
    if change=='drop_limits':d['entries'][0]['limitations']=[]
    if change=='E':d['mode']='E'
    if change=='budget':d['entries']*=6
    if change=='query':d['query_digest']=digest('wrong')
    rendered=m.canonical(d['entries']);d.update(injected_chars=len(rendered),injected_utf8_bytes=len(rendered.encode()))
    d=m.sealed({k:v for k,v in d.items() if k!='view_digest'},'view_digest')
    if change=='query':
        x=ctx.data;x['memory_view']=d;x['local_binding']['memory_view_digest']=d['view_digest']
        with pytest.raises(JevSelectError):
            from semantic_pallet_planner.jev_select.context import validate_context
            validate_context(DecisionContext.from_dict(x),config=c)
    else:
        with pytest.raises(JevSelectError):m.validate_view(m.MemoryView.from_dict(d))


def test_whole_entry_budget_and_tie(real,monkeypatch):
    # Constructed stress versions are never written as real snapshots.
    s=real.data;q=s['cases'][0]['retrieval_query']
    for c in s['cases']:
        c['retrieval_query']=q;c['fixture_only']=True
        c.update(m.sealed({k:v for k,v in c.items() if k!='case_digest'},'case_digest'))
    s=m.sealed({k:v for k,v in s.items() if k!='snapshot_digest'},'snapshot_digest')
    original=m.validate_snapshot
    def stress_validate(value,expected=None):
        # Synthetic equal-vector index to test ranking, independent of evidence builder.
        return value.data if isinstance(value,m.Snapshot) else value
    monkeypatch.setattr(m,'validate_snapshot',stress_validate)
    v,a=m.retrieve(q,s)
    assert a['candidates'][0]['public_digest']==min(c['public_digest'] for c in s['cases'])
    rule={**m.RULE,'max_utf8_bytes':100,'max_chars':100}
    s['retrieval_rule']=rule;s=m.sealed({k:v for k,v in s.items() if k!='snapshot_digest'},'snapshot_digest')
    monkeypatch.setattr(m,'RULE',rule)
    v,a=m.retrieve(q,s);assert v.data['entries']==[] and a['length_handling']

@pytest.mark.parametrize('mode',['invalid','unknown','exception'])
def test_failures_no_retry(constructed,tmp_path,mode):
    _,c,_,ctx,_,_=inputs(constructed)
    from semantic_pallet_planner.jev_select.transport import outcome
    def change(r):
        if mode=='exception':raise TimeoutError()
        if mode=='unknown':return outcome('UNKNOWN_IN_FLIGHT',error='TIMEOUT',network_attempted=True)
        r['answers']['next_action']['choice']='C99'
        import json
        return outcome('OK',json.dumps(r).encode(),http_status=200,network_attempted=True)
    f=Fake(change);l=MemoryRequestLedger(tmp_path);s=memory_selector_factory(m.METHOD,config=c,transport=f,ledger=l,job_id='J')
    r=s.select(ctx,decision_id='J_D0000')
    assert r.data['status']==('invalid_response' if mode=='invalid' else 'unknown_in_flight')
    s.select(ctx,decision_id='J_D0000');assert f.calls==1


def test_singleton_no_request(constructed,tmp_path):
    t,c,b,ctx,v,_=inputs(constructed)
    state=initial(t['container'],3)
    for o in t['items']:state=receive(state,o,t['attributes'][o['item_id']])
    req,pol,_,_=decision_inputs(state,t,c,'J','J_D0000')
    d=b.data;d['physical_candidates']=d['physical_candidates'][:1];d['selectable_candidates']=d['physical_candidates'];d['physical_digest']=d['selectable_digest']=digest(d['physical_candidates'])
    from semantic_pallet_planner.jev_select.candidates import PublicBusinessGuard
    b=PublicBusinessGuard().filter(req,pol,CandidateBundle.from_dict(d),c)
    ctx=bind_decision(build_context(c,req,b,pol),'J','J_D0000')
    f=Fake();l=MemoryRequestLedger(tmp_path);s=memory_selector_factory(m.METHOD,config=c,transport=f,ledger=l,job_id='J')
    assert s.select(ctx,decision_id='J_D0000').data['status']=='singleton' and f.calls==0 and not l.data['requests']


def test_workflow_constructed_transport_closed_loop(monkeypatch):
    import tempfile
    from semantic_pallet_planner.jev_select import packaging_trajectory_validation as w
    # Constructed transport scope must not spend or reset the archived real stage budget.
    monkeypatch.setattr(w,'prior_requests',lambda output:[])
    with tempfile.TemporaryDirectory(prefix='CONSTRUCTED_JN3_',dir=REPO/'semantic_pallet_planner/outputs') as d:
        p=w.prepare(d);assert p['ready_to_send']
        fake=Fake();r=w.run(d,transport=fake)
        assert fake.calls==1 and r['event']=='PLACE'
        assert w.validate_saved(d)['status']=='PASS'
        w.run(d,transport=fake);assert fake.calls==1


def test_exact_threshold(real):
    s=real.data;c=s['cases'][0];q=copy.deepcopy(c['retrieval_query'])
    for k in q['features']:q['features'][k]+=1
    view,a=m.retrieve(q,real,excluded_source_groups=[s['cases'][1]['provenance']['source_group']])
    row=next(r for r in a['candidates'] if r['case_digest']==c['case_digest'])
    assert row['score']==0.5 and row['qualified'] and view.data['entries']
    for k in q['features']:q['features'][k]+=1e-6
    view,a=m.retrieve(q,real,excluded_source_groups=[s['cases'][1]['provenance']['source_group']]);assert not view.data['entries']
