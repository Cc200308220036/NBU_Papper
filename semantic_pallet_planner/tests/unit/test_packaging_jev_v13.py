"""New v13 protocol construction: frozen fixture pools, fake responses, monitor stub."""
import copy
import socket
from pathlib import Path
import pytest
from test_packaging_jev_continuation import FakeTransport as LegacyFakeTransport
from test_packaging_jev_forks import stub_monitor
from semantic_pallet_planner.jev_select import packaging_jev_v13 as v13
from semantic_pallet_planner.jev_select.contracts import CandidateBundle,digest,JevSelectError
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.packaging_runtime import build_context,no_policy
from semantic_pallet_planner.jev_select.selector import bind_decision
from semantic_pallet_planner.o4.extensions.e2.protocol import observation

class FakeTransport(LegacyFakeTransport):
    def complete(self,body):
        body=copy.deepcopy(body)
        criteria=body['questions']['next_action']['criteria']
        ordered=sorted(criteria,key=lambda k:(criteria[k]['pick_object'],criteria[k]['pose']['x_mm'],criteria[k]['pose']['y_mm']))
        body['questions']['next_action']['criteria']={k:criteria[k] for k in ordered}
        return super().complete(body)

class Crash(BaseException):pass

@pytest.fixture
def setup(tmp_path,monkeypatch):
    def no(*a,**k):pytest.fail('forbidden generator/network/solver/retrieval')
    from semantic_pallet_planner.jev_select import transport,episode
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
    from semantic_pallet_planner.jev_select.stability import balance_adapter,exact_adapter
    from semantic_pallet_planner.jev_select.packaging_evaluation_memory import MemoryDriver
    monkeypatch.setattr(socket.socket,'connect',no);monkeypatch.setattr(transport,'credential',no)
    monkeypatch.setattr(CandidateProvider,'build',no);monkeypatch.setattr(balance_adapter,'assess_candidate',no)
    monkeypatch.setattr(exact_adapter,'assess_candidate',no);monkeypatch.setattr(MemoryDriver,'resolve',no)
    data=read(Path(__file__).parents[1]/'fixtures/jm_a1_frozen_pool.json');task=data['task']
    pool_stages=read(Path(__file__).parents[1]/'fixtures/jm_a2_suffix_pool.json')['stages']
    cfg=v13.load_config(data_identity=digest('CONSTRUCTED_ONLY_V13'),task_digest=digest(task))
    singleton=[]
    def inputs(state,task,config,job_id,did,**kw):
        req=observation(state,task['instruction_text'],[])
        candidates=copy.deepcopy(data['candidates'] if state['placed_count']==0 else pool_stages[str(state['placed_count'])])
        pending={x['item']['item_id'] for x in state['pending_items']}
        candidates=[c for c in candidates if c['pick_item_id'] in pending]
        # Fresh construction identities: legacy tiny fixture uses 24-char tokens,
        # while unchanged B1 requires full SHA256. No historical pool is rewritten.
        for candidate in candidates:
            candidate['candidate_fingerprint']=digest({'constructed_legacy_token':candidate['candidate_fingerprint']})
        if singleton:candidates=candidates[:1]
        b={'version':'jev_candidate_bundle_v13','observation_digest':req['observation_digest'],
            'candidate_backend':'e2_original_v1','generator_config_digest':digest('CONSTRUCTED_ONLY'),
            'physical_candidates':candidates,'physical_digest':digest(candidates),'selectable_candidates':candidates,
            'selectable_digest':digest(candidates),'generation_counts':[],'selectable_pool':'physical_feasible',
            'policy_digest':digest(no_policy(req).data),'experiment_protocol':config['experiment_protocol'],'business_mode':config['business_mode']}
        bundle=CandidateBundle.from_dict(b)
        ctx=bind_decision(build_context(config,req,bundle,no_policy(req)),job_id,did,config=config)
        return req,no_policy(req),bundle,ctx
    monkeypatch.setattr(episode,'decision_inputs',inputs)
    calls=stub_monitor(monkeypatch,'STABLE')
    ex=v13.freeze_execution(task,cfg,job_id='BASE',root=tmp_path/'baseline')
    return ex,calls,singleton


def run(ex,**kw):return v13.run_execution(ex,root=ex['storage_root'],transport=kw.pop('transport',FakeTransport()),**kw)


def test_baseline_public_export(setup,tmp_path,monkeypatch):
    ex,calls,_=setup;fake=FakeTransport();ep=run(ex,transport=fake)
    assert ep['checkpoint']['reason']=='ALL_ITEMS_PLACED';assert len(fake.calls)==4 and len(calls)==4
    assert ex['config']['stability_monitor']['algorithm']=='pct_exact_pose_network_v3'
    assert ep['summary']['origin']=='CONSTRUCTED_FAKE_TRANSPORT_MONITOR_STUB'
    from semantic_pallet_planner.jev_select.transport import JevTransport
    import json
    assert json.loads(JevTransport(ex['config']).encode(fake.calls[0]))==fake.calls[0]
    before=len(calls);assert run(ex,transport=fake)['final_state']==ep['final_state'];assert len(calls)==before and len(fake.calls)==4
    from semantic_pallet_planner.jev_select import execution,episode
    monkeypatch.setattr(execution,'commit_physical',lambda *a,**k:pytest.fail('saved validator committed'))
    monkeypatch.setattr(episode,'decision_inputs',lambda *a,**k:pytest.fail('saved validator generated'))
    for _ in range(2):v13.validate_saved_execution(ex['storage_root'])
    index=v13.export_public(ex['storage_root'],tmp_path/'public')
    from semantic_pallet_planner.jev_select import packaging_jev_sampling as b1
    records=[read(tmp_path/'public'/r['public_ref']['path']) for r in index['decisions'] if r['status']=='PUBLIC_SAVED']
    assert len(records)==4
    for p in records:
        assert b1.parse_probabilities(p)['lexemes'];assert not any(k in p for k in ('terminal','future','monitor','task'))
    write(tmp_path/'proof.json',{'scope':'CONSTRUCTED_ONLY','requests':len(fake.calls),'monitor_stubs':len(calls),'solver':0,'public_records':len(records)})


@pytest.mark.parametrize('phase',['ACTIVATED','CONTEXT_SAVED','RESERVATION_SAVED','INTENT','SENDING','RESPONSE_SAVED','SELECTION_SAVED','DECISION_READY','SELECTED','MONITORED','COMMITTED','READY','TERMINATED'])
def test_baseline_recovery(setup,phase):
    ex,calls,_=setup;fake=FakeTransport();hit=[]
    def hook(p,row):
        if p==phase and not hit:hit.append(p);raise Crash()
    def checkpoint(cp):
        if cp['phase']==phase and not hit:hit.append(phase);raise Crash()
    with pytest.raises(Crash):run(ex,transport=fake,ledger_hook=hook,on_checkpoint=checkpoint)
    assert hit
    v13.validate_saved_execution(ex['storage_root'])
    result=run(ex,transport=fake)
    if phase=='SENDING':assert result['checkpoint']['reason']=='UNKNOWN_IN_FLIGHT' and not fake.calls
    else:assert result['checkpoint']['reason']=='ALL_ITEMS_PLACED' and len(fake.calls)==4 and len(calls)==4
    after=len(fake.calls),len(calls);run(ex,transport=fake);assert after==(len(fake.calls),len(calls))


def test_fork_reference_same_cross_and_repeat(setup,tmp_path,monkeypatch):
    ex,calls,_=setup;run(ex)
    cp=v13.validate_saved_execution(ex['storage_root'])['checkpoint'];event=next(e for e in cp['events'] if e.get('context'))
    start=v13.capture_start(ex['storage_root'],event['decision_id'])
    mapping=event['context']['display_mapping'];original=event['selection']['selected_display_id'];item=mapping[original]['pick_item_id']
    same=next(k for k,m in mapping.items() if k!=original and m['pick_item_id']==item)
    cross=next(k for k,m in mapping.items() if m['pick_item_id']!=item)
    # Frozen suffix fixture need not support every intervened layout: first-step
    # checks use failure monitor to stop exactly at the saved intervention.
    from unittest.mock import patch
    from semantic_pallet_planner.jev_select.stability import monitor
    original_monitor=monitor.monitor_selected_action
    for i,label in enumerate([original,same,cross]):
        branch=v13.freeze_execution(ex['task'],ex['config'],job_id='B'+str(i),root=tmp_path/f'b{i}',start=start,forced_label=label)
        initial=v13.initial_checkpoint(branch);v13.validate_saved_checkpoint(initial,branch)
        assert initial['pending_event']['selection']['source']=='FORCED_FROM_FROZEN_POOL'
        assert initial['pending_event']['context']['model_state']['memories']==[]
        stub_monitor(monkeypatch,'UNSTABLE')
        stopped=run(branch)
        assert stopped['final_state']==event['before'] and stopped['checkpoint']['reason']=='PREDICTED_STATIC_INSTABILITY'
        monkeypatch.setattr(monitor,'monitor_selected_action',original_monitor)
    branch=v13.freeze_execution(ex['task'],ex['config'],job_id='REF',root=tmp_path/'ref',start=start,forced_label=original)
    fake=FakeTransport();result=run(branch,transport=fake)
    assert len(fake.calls)==3 and result['checkpoint']['reason']=='ALL_ITEMS_PLACED'
    repeat=v13.freeze_execution(ex['task'],ex['config'],job_id='REF',root=tmp_path/'r1',repeat_slot='r1',start=start,forced_label=original)
    assert repeat['allocation_id']!=branch['allocation_id'];assert len(FakeTransport().calls)==0
    result=run(repeat);assert result['final_state']['placed_count']==4


@pytest.mark.parametrize('status',['UNSTABLE','UNASSESSABLE','ERROR'])
@pytest.mark.parametrize('phase',['MONITORED','TERMINATED'])
def test_failure_not_committed_or_reselected(setup,monkeypatch,status,phase):
    ex,_,_=setup;calls=stub_monitor(monkeypatch,status);fake=FakeTransport();hit=[]
    def checkpoint(cp):
        if cp['phase']==phase and not hit:hit.append(phase);raise Crash()
    with pytest.raises(Crash):run(ex,transport=fake,on_checkpoint=checkpoint)
    result=run(ex,transport=fake)
    from semantic_pallet_planner.jev_select.stability.monitor import TERMINATIONS
    assert result['checkpoint']['reason']==TERMINATIONS[status]
    assert result['final_state']['placed_count']==0 and len(result['final_state']['pending_items'])==3
    assert len(fake.calls)==1 and len(calls)==1
    event=result['events'][-1];assert event['before']==event['after'] and event['action'] is None
    v13.validate_saved_execution(ex['storage_root'])


@pytest.mark.parametrize('mode,expected',[('RAISE','UNKNOWN_IN_FLIGHT'),('ERROR','PROVIDER_FAILURE'),('REFUSAL','INVALID_RESPONSE')])
def test_request_error_stop(setup,mode,expected):
    ex,calls,_=setup;fake=FakeTransport(mode)
    result=run(ex,transport=fake);assert result['checkpoint']['reason']==expected
    assert len(fake.calls)==1 and not calls
    run(ex,transport=fake);assert len(fake.calls)==1


def test_singleton_and_zero_budget(setup,tmp_path):
    ex,calls,singleton=setup;singleton.append(True);fake=FakeTransport()
    ep=run(ex,transport=fake);assert ep['final_state']['placed_count']==4 and not fake.calls
    assert read(Path(ex['storage_root'])/'counts.json')['singleton_actions']==4
    singleton.clear()
    zero=v13.freeze_execution(ex['task'],ex['config'],job_id='ZERO',root=tmp_path/'zero',max_sends=0)
    result=run(zero,transport=fake);assert result['final_state']['placed_count']==0 and not fake.calls


@pytest.mark.parametrize('field',['task','config','identity','algorithm','root','budget'])
def test_identity_and_root_tamper(setup,field,tmp_path):
    ex,_,_=setup;bad=copy.deepcopy(ex)
    if field=='task':bad['task']['items'][0]['mass_kg']+=1
    elif field=='config':bad['config']['display_order_seed']+=1
    elif field=='identity':bad['identity']['dependencies']['numpy']='CHANGED'
    elif field=='algorithm':bad['config']['stability_monitor']['algorithm']='pct_contact_network_v2'
    elif field=='budget':bad['max_sends']=9999
    else:
        with pytest.raises(JevSelectError,match='storage_root'):v13.run_execution(ex,root=tmp_path/'wrong',transport=FakeTransport())
        return
    v13.seal(bad)
    with pytest.raises(JevSelectError):v13.validate_execution(bad)


def test_missing_journal_with_request_progress_refused(setup):
    ex,calls,_=setup;fake=FakeTransport()
    def hook(phase,row):
        if phase=='RESPONSE_SAVED':raise Crash()
    with pytest.raises(Crash):run(ex,transport=fake,ledger_hook=hook)
    root=Path(ex['storage_root'])
    for path in (root/'stages').glob('*.json'):path.unlink()
    (root/'checkpoint_head.json').unlink()
    before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with pytest.raises(JevSelectError,match='unexplained_ledger_progress'):v13.validate_saved_execution(root)
    with pytest.raises(JevSelectError):run(ex,transport=fake)
    assert before=={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert len(fake.calls)==1 and not calls


def test_native_mode_registered_but_no_permit_cannot_run(setup,tmp_path):
    ex,calls,_=setup
    cfg=v13.load_config(data_identity=ex['config']['runtime_identity']['data_identity'],task_digest=digest(ex['task']),mode='REMOTE_INJECTED')
    remote=v13.freeze_execution(ex['task'],cfg,job_id='REMOTE',root=tmp_path/'remote')
    with pytest.raises(JevSelectError,match='not_authorized'):run(remote)
    assert not Path(remote['storage_root']).exists() and not calls


def test_schedule_aggregation_no_slot_budget_borrow(setup,tmp_path):
    ex,_,_=setup;root=tmp_path/'scheduled'
    a=v13.freeze_execution(ex['task'],ex['config'],job_id='ONE',root=root/'one',max_sends=0)
    b=v13.freeze_execution(ex['task'],ex['config'],job_id='TWO',root=root/'two',max_sends=4)
    s=v13.freeze_schedule([a,b],root=root,global_max_sends=4)
    assert sum(e['max_sends'] for e in s['executions'])==s['global_max_sends']
    fake=FakeTransport();result=v13.run_scheduled(s,allocation_id=a['allocation_id'],transport=fake)
    assert not fake.calls and result['final_state']['placed_count']==0
    with pytest.raises(JevSelectError,match='budget_sum'):v13.freeze_schedule([a,b],root=root,global_max_sends=5)
    with pytest.raises(JevSelectError,match='duplicate_schedule_slot'):v13.freeze_schedule([a,a],root=root,global_max_sends=0)
    with pytest.raises(JevSelectError,match='unregistered'):v13.run_scheduled(s,allocation_id='x',transport=fake)


def test_unbound_episode_route_rejected(setup):
    ex,_,_=setup
    from semantic_pallet_planner.jev_select.episode import run_episode
    with pytest.raises(JevSelectError,match='explicit_execution_route_required'):
        run_episode(ex['task'],None,ex['config'],job_id='BAD',method='jev_no_memory')


def test_fork_first_phase_recovery(setup,tmp_path):
    ex,calls,_=setup;run(ex)
    cp=v13.validate_saved_execution(ex['storage_root'])['checkpoint']
    event=next(e for e in cp['events'] if e.get('context'))
    start=v13.capture_start(ex['storage_root'],event['decision_id']);label=event['selection']['selected_display_id']
    records=[]
    for phase in ['SELECTED','MONITORED','COMMITTED']:
        branch=v13.freeze_execution(ex['task'],ex['config'],job_id='F_'+phase,root=tmp_path/phase,start=start,forced_label=label)
        fake=FakeTransport();hit=[];before=len(calls)
        def callback(cp):
            if cp['phase']==phase and cp['decision']==0 and not hit:hit.append(phase);raise Crash()
        with pytest.raises(Crash):run(branch,transport=fake,on_checkpoint=callback)
        result=run(branch,transport=fake)
        assert len(calls)-before==4 and len(fake.calls)==3 and result['final_state']['placed_count']==4
        after=len(calls);run(branch,transport=fake);assert len(calls)==after and len(fake.calls)==3
        records.append({'phase':phase,'monitor_stub_calls':4,'fake_requests':3,'forced_actions':read(Path(branch['storage_root'])/'counts.json')['forced_actions']})
    write(tmp_path/'fork_recovery_proof.json',{'scope':'CONSTRUCTED_ONLY','cases':records})


def test_parent_saved_tampering_and_counts_refused(setup,tmp_path):
    ex,_,_=setup;run(ex);root=Path(ex['storage_root'])
    cp=v13.validate_saved_execution(root)['checkpoint'];event=next(e for e in cp['events'] if e.get('context'))
    start=v13.capture_start(root,event['decision_id']);original={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    row=v13.load_ref(start['checkpoint_ref']);observations=[]
    for field in ['state','cursor','buffer','pool','action']:
        bad=copy.deepcopy(row);target=next(e for e in bad['checkpoint']['events'] if e.get('context'))
        if field=='state':bad['checkpoint']['state']['placed_count']=99
        elif field=='cursor':bad['checkpoint']['cursor']+=1
        elif field=='buffer':target['before']['pending_items'].reverse()
        elif field=='pool':target['bundle']['selectable_candidates'].reverse()
        else:target['proposed_action']['candidate_id']='ALTERED_CANDIDATE'
        v13.seal(bad['checkpoint']);v13.seal(bad)
        path=tmp_path/(field+'.json');write(path,bad);changed=copy.deepcopy(start);changed['checkpoint_ref']=v13.ref(path)
        with pytest.raises((JevSelectError,ValueError,KeyError)) as err:v13.validate_start(changed)
        observations.append({'field':field,'refused':True,'reason':str(err.value)[:140]})
    assert original=={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    ledger_path=root/'ledger/requests.json';ledger_bytes=ledger_path.read_bytes();ledger=read(ledger_path)
    ledger['requests'][0]['selection']['confidence']=0.25
    ledger['requests'][0]['selection_digest']=digest(ledger['requests'][0]['selection'])
    v13.seal(ledger);write(ledger_path,ledger)
    with pytest.raises(JevSelectError,match='saved_response_selection_changed'):v13.validate_saved_execution(root)
    ledger_path.write_bytes(ledger_bytes)
    count_path=root/'counts.json';count=read(count_path);count['commits']+=1;write(count_path,count)
    with pytest.raises(JevSelectError,match='counts_changed'):v13.validate_saved_execution(root)
    write(tmp_path/'tamper_proof.json',{'scope':'CONSTRUCTED_ONLY','cases':observations,'original_parent_unchanged_before_counts_test':True,'counts_refused':True,'raw_selection_mismatch_refused':True})


def test_scheduled_unknown_send_stops_other_slot(setup,tmp_path):
    ex,_,_=setup;root=tmp_path/'batch'
    a=v13.freeze_execution(ex['task'],ex['config'],job_id='FIRST',root=root/'a')
    b=v13.freeze_execution(ex['task'],ex['config'],job_id='SECOND',root=root/'b')
    schedule=v13.freeze_schedule([a,b],root=root,global_max_sends=8)
    result=v13.run_scheduled(schedule,allocation_id=a['allocation_id'],transport=FakeTransport('RAISE'))
    assert result['checkpoint']['reason']=='UNKNOWN_IN_FLIGHT'
    fake=FakeTransport()
    with pytest.raises(JevSelectError,match='batch_technical_stop'):
        v13.run_scheduled(schedule,allocation_id=b['allocation_id'],transport=fake)
    assert not fake.calls and not Path(b['storage_root']).exists()


def test_native_transport_configuration_binding(setup,tmp_path):
    ex,_,_=setup
    cfg=v13.load_config(data_identity=ex['config']['runtime_identity']['data_identity'],task_digest=digest(ex['task']),mode='REMOTE_INJECTED')
    remote=v13.freeze_execution(ex['task'],cfg,job_id='WIRE',root=tmp_path/'wire')
    from semantic_pallet_planner.jev_select.transport import JevTransport
    v13.validate_transport_binding(remote,JevTransport(cfg))
    changed=JevTransport(cfg);changed.config['endpoint']='https://invalid.example/changed'
    with pytest.raises(JevSelectError,match='transport_config_changed'):
        v13.validate_transport_binding(remote,changed)
