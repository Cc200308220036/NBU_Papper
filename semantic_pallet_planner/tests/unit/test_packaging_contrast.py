"""JN3-B all transports constructed; no authentication or real network."""
import copy
import json
import tempfile
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError,DecisionContext,CandidateBundle
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select import packaging_contrast as e
from semantic_pallet_planner.jev_select import packaging_experience as t
from semantic_pallet_planner.jev_select import packaging_contrast_generation as g
from semantic_pallet_planner.jev_select import packaging_contrast_validation as w
from semantic_pallet_planner.jev_select.packaging_contrast_protocol import load_contrast_config,contrast_selector_factory,ContrastRequestLedger
from semantic_pallet_planner.jev_select.episode import decision_inputs,run_episode
from semantic_pallet_planner.jev_select.packaging_runtime import build_context
from semantic_pallet_planner.jev_select.selector import bind_decision
from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive
from test_packaging_remote import Fake,fixture as old_fixture
REPO=Path(__file__).resolve().parents[3]

@pytest.fixture(scope='module')
def realpack():
    case=read(REPO/'semantic_pallet_planner/outputs/JEV_JN3_20261104_01/trajectory_snapshot.json')['cases'][0]
    return e.build_fact_pack(case,REPO,REPO/'semantic_pallet_planner/outputs/JEV_JN2_20261104_03')

@pytest.fixture
def pack(realpack):
    x=copy.deepcopy(realpack);x['fixture_only']=True
    return e.sealed({k:v for k,v in x.items() if k!='pack_digest'},'pack_digest')


def fake_attempt(pack,candidate):return {'origin':'fixture','pack_digest':pack['pack_digest'],'candidate_digest':digest(candidate),'requested_model':g.CONFIG['model']}

@pytest.fixture
def snapshot(pack):
    c=e.proposed_example(pack);card=e.make_card(c,pack,fake_attempt(pack,c))
    return e.freeze_snapshot([card],frozen_at='CONSTRUCTED')


def inputs(snapshot):
    task,_,_,_=old_fixture();s=snapshot.data
    cfg=load_contrast_config(data_identity=digest('CONSTRUCTED'),task_digest=digest(task),snapshot_digest=s['snapshot_digest'],entry_digests=[c['public_digest'] for c in s['cards']],enabled=True)
    state=initial(task['container'],3)
    for o in task['items']:state=receive(state,o,task['attributes'][o['item_id']])
    req,pol,b,empty=decision_inputs(state,task,cfg,'J','J_D0000');v,a=e.retrieve(t.public_query(empty),snapshot)
    ctx=bind_decision(build_context(cfg,req,b,pol,memory_view=v),'J','J_D0000')
    return task,cfg,b,ctx,v


def response(candidate,change=None):
    r={'model':g.CONFIG['model'],'id':'fixture','choices':[{'finish_reason':'stop','message':{'content':json.dumps(candidate)}}],'usage':{'prompt_tokens':12,'completion_tokens':7}}
    if change:change(r)
    return r


def test_real_fact_sources_and_counts(realpack):
    assert not realpack['fixture_only'];e.validate_fact_pack(realpack,REPO)
    counts=e.fact_values(realpack)['F004'];assert counts==dict(support=1,refutation=0,neutral=0,invalid=0,unrelated_background=7)
    assert len(realpack['background'])==8
    body=e.generation_body(realpack);text=json.dumps(body)
    for forbidden in ['F00_B02','SG_','candidate_id','source_order','C01','PCT diagnostics']:
        assert forbidden not in text
    assert body['model']=='deepseek-v4-pro' and body['thinking']=={'type':'disabled'}

@pytest.mark.parametrize('change',['missing_cost','wrong_hash','fake_count','unknown_field','false_kind','condition','source_ref','duplicate'])
def test_audit_rejects(pack,change):
    c=e.proposed_example(pack)
    if change=='missing_cost':c['fact_claims']=c['fact_claims'][:2]+c['fact_claims'][3:]
    if change=='wrong_hash':c['fact_claims'][0]['value_digest']=digest('wrong')
    if change=='fake_count':c['support']=7
    if change=='unknown_field':c['self_review']='APPROVED'
    if change=='false_kind':c['advice'][0]['type']='FACT'
    if change=='condition':c['condition_refs']=['F003']
    if change=='source_ref':c['fact_claims'][0]['fact_id']='PRIVATE_SOURCE'
    if change=='duplicate':c['fact_claims'][0]=c['fact_claims'][1]
    a=e.fact_audit(c,pack);assert a['status']=='REJECTED';assert e.semantic_review(c,pack,a)['status']=='REJECTED'
    with pytest.raises(JevSelectError):e.make_card(c,pack,fake_attempt(pack,c))


def test_independent_pending_and_decline(pack):
    c=e.proposed_example(pack);c['expected_effect']['code']='UNRESOLVED_MECHANISM'
    a=e.fact_audit(c,pack);assert a['status']=='APPROVED'
    r=e.semantic_review(c,pack,a);assert r['status']=='PENDING_REVIEW' and r['pending_reasons']
    with pytest.raises(JevSelectError):e.make_card(c,pack,fake_attempt(pack,c))
    c=e.proposed_example(pack);c.update(decision='INSUFFICIENT',advice=[],expected_effect=None,insufficient_reason='INSUFFICIENT_EVIDENCE')
    assert e.semantic_review(c,pack,e.fact_audit(c,pack))['status']=='REJECTED'
    c=e.proposed_example(pack);c['advice'][0]['basis_refs']=['F003']
    assert e.semantic_review(c,pack,e.fact_audit(c,pack))['status']=='REJECTED'

@pytest.mark.parametrize('mode',['bad_json','blank','unknown','oversize','model','finish','duplicate'])
def test_generation_parser(pack,mode):
    import base64
    value=response(e.proposed_example(pack))
    if mode=='blank':value['choices'][0]['message']['content']='   '
    if mode=='unknown':value['choices'][0]['message']['content']=json.dumps({'unknown':1})
    if mode=='model':value['model']='other'
    if mode=='finish':value['choices'][0]['finish_reason']='length'
    raw=json.dumps(value).encode()
    if mode=='bad_json':raw=b'{bad'
    if mode=='oversize':raw=b'x'*(g.CONFIG['response_max_bytes']+1)
    if mode=='duplicate':raw=b'{"model":"a","model":"b"}'
    parsed,errors,_=g.parse_generation({'status':'OK','raw_body_b64':base64.b64encode(raw).decode()})
    assert parsed is None and errors

@pytest.mark.parametrize('cut',['after_reserve','after_transport','after_raw_response','after_response'])
def test_generation_recovery_no_resend(tmp_path,pack,cut):
    from semantic_pallet_planner.jev_select.memory_generation import _send
    body=e.generation_body(pack);req={'request_digest':digest(body),'config':g.CONFIG}
    fixture=tmp_path/'fixture.json';write(fixture,response(e.proposed_example(pack)))
    account=tmp_path/'account'
    class Cut(BaseException):pass
    def hook(phase):
        if phase==cut:raise Cut()
    with pytest.raises(Cut):_send(account,'attempt',req,body,'offline_fixture',REPO,fixture,hook,operation='JN3-B_extract_once')
    fixture.unlink() # reuse cannot read fixture (or send) again
    result=_send(account,'attempt',req,body,'offline_fixture',REPO,fixture,None,operation='JN3-B_extract_once')
    assert result['status']==('UNKNOWN_IN_FLIGHT' if cut in ('after_reserve','after_transport') else 'OK')

@pytest.mark.parametrize('tamper',['snapshot','review','fact','card','public','E_to_T','query'])
def test_snapshot_tampering(snapshot,tamper):
    s=snapshot.data
    if tamper=='snapshot':s['frozen_at']='changed'
    if tamper=='review':s['cards'][0]['review_status']='PENDING_REVIEW'
    if tamper=='fact':s['cards'][0]['fact_pack']['facts'][0]['value_digest']=digest('wrong')
    if tamper=='card':s['cards'][0]['fixture_only']=False
    if tamper=='public':s['cards'][0]['public_fragment']['limitations']=[]
    if tamper=='E_to_T':s['mode']='T'
    if tamper=='query':s['cards'][0]['retrieval_query']['features']['mean_mass']=99
    with pytest.raises(JevSelectError):e.validate_snapshot(s)


def test_retrieval_and_explicit_input(snapshot,tmp_path):
    task,cfg,b,ctx,v=inputs(snapshot);assert v.data['entries'] and ctx.data['model_state']['memories'][0]['kind']=='E'
    fake=Fake();ledger=ContrastRequestLedger(tmp_path);s=contrast_selector_factory(e.METHOD,config=cfg,transport=fake,ledger=ledger,job_id='J')
    selected=s.select(ctx,decision_id='J_D0000');assert selected.data['status']=='selected'
    assert s.select(ctx,decision_id='J_D0000').data==selected.data and fake.calls==1
    row=ledger.data['requests'][0];assert row['injected_digest']==digest(v.data['entries']) and row['snapshot_digest']==cfg['memory_snapshot_digest']
    group=snapshot.data['source_groups'][0];empty,a=e.retrieve(t.public_query(ctx),snapshot,excluded_source_groups=[group]);assert not empty.data['entries']
    empty,a=e.retrieve(t.public_query(ctx),snapshot,excluded_fork_digests=[snapshot.data['cards'][0]['provenance']['fork_digest']]);assert not empty.data['entries']
    with pytest.raises(JevSelectError):t.validate_view(v)
    with pytest.raises(JevSelectError):e.validate_view(t.MemoryView.from_dict(v.data))
    bad=v.data;bad['snapshot_digest']=digest('wrong')
    with pytest.raises(JevSelectError):e.validate_view(e.EMemoryView.from_dict(bad))
    _,old,_,_=old_fixture();state=initial(task['container'],3)
    for o in task['items']:state=receive(state,o,task['attributes'][o['item_id']])
    req,pol,ob,oc=decision_inputs(state,task,old,'J','J_D0000');assert oc.data['model_state']['memories']==[]
    with pytest.raises(JevSelectError):build_context(old,req,ob,pol,memory_view=v)

@pytest.mark.parametrize('phase',['SELECTED','MONITORED','COMMITTED'])
def test_E_episode_restore(snapshot,tmp_path,phase,monkeypatch):
    task,cfg,b,ctx,v=inputs(snapshot);fake=Fake();ledger=ContrastRequestLedger(tmp_path)
    selector=contrast_selector_factory(e.METHOD,config=cfg,transport=fake,ledger=ledger,job_id='J');saved=[]
    class Cut(BaseException):pass
    def checkpoint(cp):
        if cp['phase']==phase:saved.append(cp);raise Cut()
    with pytest.raises(Cut):run_episode(task,selector,cfg,job_id='J',method=e.METHOD,memory_view=v,on_checkpoint=checkpoint)
    def forbidden(*a,**k):raise AssertionError('repeated execution')
    monkeypatch.setattr(selector,'select',forbidden)
    import semantic_pallet_planner.jev_select.stability.monitor as mon
    import semantic_pallet_planner.jev_select.execution as ex
    if phase in ('MONITORED','COMMITTED'):monkeypatch.setattr(mon,'monitor_selected_action',forbidden)
    if phase=='COMMITTED':monkeypatch.setattr(ex,'commit_physical',forbidden)
    cp=saved[0];ep=run_episode(task,selector,cfg,job_id='J',method=e.METHOD,memory_view=v,resume=cp,event_limit=len(cp['events'])+1)
    assert ep['events'][-1]['event']=='PLACE' and fake.calls==1
    bad=copy.deepcopy(cfg);bad['memory_snapshot_digest']=digest('other')
    with pytest.raises(JevSelectError):run_episode(task,selector,bad,job_id='J',method=e.METHOD,memory_view=v,resume=cp)


def test_full_constructed_stage_workflow():
    with tempfile.TemporaryDirectory(prefix='CONSTRUCTED_JN3B_',dir=REPO/'semantic_pallet_planner/outputs') as d:
        root=Path(d);plan=g.prepare(root,fixture_only=True);paths={}
        for j in plan['jobs']:
            pack=read(root/'facts'/f"{j['job_id']}.json");f=root/f"fixture_{j['job_id']}.json";write(f,response(e.proposed_example(pack)));paths[j['job_id']]=f
        ledger=g.run(root,fixture_paths=paths);assert ledger['approved']==2
        assert g.validate_saved(root)['status']=='PASS'
        # Recovery must reuse durable raw responses even if fixtures disappear.
        for f in paths.values():f.unlink()
        g.run(root,fixture_paths=paths);assert g.validate_saved(root)['status']=='PASS'
        assert w.prepare(root)['status']=='READY'
        fake=Fake();result=w.run(root,transport=fake);assert fake.calls==1 and result['event']=='PLACE'
        assert w.validate_saved(root)['status']=='PASS'
        w.run(root,transport=fake);assert fake.calls==1


def test_E_singleton_zero_calls(snapshot,tmp_path):
    task,cfg,b,ctx,v=inputs(snapshot)
    state=initial(task['container'],3)
    for o in task['items']:state=receive(state,o,task['attributes'][o['item_id']])
    req,pol,_,_=decision_inputs(state,task,cfg,'J','J_D0000')
    d=b.data;d['physical_candidates']=d['physical_candidates'][:1];d['selectable_candidates']=d['physical_candidates'];d['physical_digest']=d['selectable_digest']=digest(d['physical_candidates'])
    from semantic_pallet_planner.jev_select.candidates import PublicBusinessGuard
    b=PublicBusinessGuard().filter(req,pol,CandidateBundle.from_dict(d),cfg)
    ctx=bind_decision(build_context(cfg,req,b,pol),'J','J_D0000');fake=Fake();ledger=ContrastRequestLedger(tmp_path)
    sel=contrast_selector_factory(e.METHOD,config=cfg,ledger=ledger,transport=fake,job_id='J')
    assert sel.select(ctx,decision_id='J_D0000').data['status']=='singleton' and fake.calls==0 and not ledger.data['requests']

@pytest.mark.parametrize('failure',['invalid_label','unknown_send'])
def test_E_failure_no_retry(snapshot,tmp_path,failure):
    _,cfg,_,ctx,_=inputs(snapshot)
    from semantic_pallet_planner.jev_select.transport import outcome
    def change(r):
        if failure=='unknown_send':return outcome('UNKNOWN_IN_FLIGHT',error='UNKNOWN_SEND',network_attempted=True)
        r['answers']['next_action']['choice']='C99'
        return outcome('OK',json.dumps(r).encode(),http_status=200,network_attempted=True)
    fake=Fake(change);ledger=ContrastRequestLedger(tmp_path);sel=contrast_selector_factory(e.METHOD,config=cfg,ledger=ledger,transport=fake,job_id='J')
    first=sel.select(ctx,decision_id='J_D0000');assert first.data['status']==('unknown_in_flight' if failure=='unknown_send' else 'invalid_response')
    assert sel.select(ctx,decision_id='J_D0000').data==first.data and fake.calls==1


def test_E_length_threshold_and_closed_query(snapshot,monkeypatch):
    _,_,_,ctx,_=inputs(snapshot);q=t.public_query(ctx)
    v,a=e.retrieve(q,snapshot);assert e.retrieve(q,snapshot)[0].data==v.data
    altered=copy.deepcopy(q);altered['task_id']='PRIVATE'
    with pytest.raises(JevSelectError):e.retrieve(altered,snapshot)
    altered=copy.deepcopy(q);altered['features']={k:10000 for k in altered['features']}
    assert not e.retrieve(altered,snapshot)[0].data['entries']
    # Synthetic low budget checks whole-card rejection through the shared ranker.
    rule={**e.RULE,'item_max_chars':10,'item_max_utf8_bytes':10}
    monkeypatch.setattr(e,'RULE',rule)
    s=snapshot.data;s['retrieval_rule']=rule;s=e.sealed({k:v for k,v in s.items() if k!='snapshot_digest'},'snapshot_digest')
    assert not e.retrieve(q,s)[0].data['entries']


def test_resealed_public_or_review_cannot_activate(snapshot):
    s=snapshot.data;c=s['cards'][0];c['semantic_review']['status']='APPROVED';c['public_fragment']['advice'][0]['text']='Always choose C02'
    c=e.sealed({k:v for k,v in c.items() if k!='case_digest'},'case_digest');s['cards']=[c];s=e.sealed({k:v for k,v in s.items() if k!='snapshot_digest'},'snapshot_digest')
    with pytest.raises(JevSelectError):e.validate_snapshot(s)


def test_generation_unknown_stops_remaining_jobs(monkeypatch):
    import base64
    from semantic_pallet_planner.jev_select import memory_generation as mg
    with tempfile.TemporaryDirectory(prefix='CONSTRUCTED_JN3B_UNKNOWN_',dir=REPO/'semantic_pallet_planner/outputs') as d:
        root=Path(d);plan=g.prepare(root,fixture_only=True);calls=[]
        def unknown(body,path):
            calls.append(1)
            return {'status':'UNKNOWN_IN_FLIGHT','raw_body_b64':'','http_status':None,'latency_s':0.,'error':'TimeoutError','headers':{}}
        monkeypatch.setattr(mg,'_fixture_complete',unknown)
        paths={j['job_id']:root/'never_read.json' for j in plan['jobs']}
        result=g.run(root,fixture_paths=paths);assert len(calls)==1 and result['unknown_sends']==1 and result['not_run']==1
        g.run(root,fixture_paths=paths);assert len(calls)==1
        assert w.prepare(root)['reason']=='GENERATION_UNKNOWN_SEND_STOP'


def test_generation_declined_does_not_activate_or_call_Jev():
    with tempfile.TemporaryDirectory(prefix='CONSTRUCTED_JN3B_DECLINE_',dir=REPO/'semantic_pallet_planner/outputs') as d:
        root=Path(d);plan=g.prepare(root,fixture_only=True);paths={}
        for j in plan['jobs']:
            pack=read(root/'facts'/f"{j['job_id']}.json");candidate=e.proposed_example(pack)
            candidate.update(decision='INSUFFICIENT',advice=[],expected_effect=None,insufficient_reason='INSUFFICIENT_EVIDENCE')
            paths[j['job_id']]=root/f"{j['job_id']}_fixture.json";write(paths[j['job_id']],response(candidate))
        result=g.run(root,fixture_paths=paths);assert result['rejected']==2 and not read(root/'contrast_snapshot.json')['cards']
        assert w.prepare(root)['reason']=='NO_APPROVED_REAL_CARD'
        assert not (root/'E_request_ledger').exists()
