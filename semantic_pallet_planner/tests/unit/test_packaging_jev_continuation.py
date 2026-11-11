"""A2 mechanism construction only. No model, history replay or LP."""
import copy
import json
import socket

import pytest

from test_packaging_jev_forks import archived, labels, stub_monitor
from semantic_pallet_planner.jev_select import packaging_jev_forks as jm
from semantic_pallet_planner.jev_select import packaging_jev_continuation as a2
from semantic_pallet_planner.jev_select.contracts import CandidateBundle, DecisionContext, digest, JevSelectError, validate_schema
from semantic_pallet_planner.jev_select.ledger import read, write
from semantic_pallet_planner.jev_select.packaging_runtime import build_context, no_policy
from semantic_pallet_planner.jev_select.selector import bind_decision
from semantic_pallet_planner.jev_select.transport import outcome
from semantic_pallet_planner.o4.extensions.e2.protocol import observation


@pytest.fixture(autouse=True)
def guards(monkeypatch):
    def no(*a, **kw): pytest.fail('A2 forbidden dispatch')
    from semantic_pallet_planner.jev_select import transport
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
    from semantic_pallet_planner.jev_select.stability import balance_adapter, exact_adapter
    from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
    from semantic_pallet_planner.jev_select.packaging_evaluation_memory import MemoryDriver
    monkeypatch.setattr(socket.socket, 'connect', no)
    monkeypatch.setattr(transport, 'credential', no)
    monkeypatch.setattr(CandidateProvider, 'build', no)
    monkeypatch.setattr(balance_adapter, 'assess_candidate', no)
    monkeypatch.setattr(exact_adapter, 'assess_candidate', no)
    monkeypatch.setattr(LocalPackagingDouble, 'select', no)
    monkeypatch.setattr(MemoryDriver, 'resolve', no)


class FakeTransport:
    origin = 'test_double'
    scope = 'CONSTRUCTED_FAKE_TRANSPORT'
    def __init__(self, mode='OK', root=None): self.mode, self.calls, self.root = mode, [], root
    def complete(self, body):
        assert body['state']['memories'] == []
        if self.root:
            ledger = read(self.root/'ledger/requests.json')
            assert ledger['requests'][-1]['state'] == 'SENDING'
            did = ledger['requests'][-1]['decision_id']
            assert read(self.root/'ledger/contexts'/f'{did}.json')['request_body'] == body
        self.calls.append(copy.deepcopy(body))
        if self.mode == 'RAISE': raise TimeoutError('CONSTRUCTED_UNKNOWN_SEND')
        if self.mode == 'ERROR': return outcome('PROVIDER_FAILURE', error='CONSTRUCTED_ERROR', http_status=500)
        if self.mode == 'REFUSAL': return outcome('OK', b'{"refusal":"CONSTRUCTED"}', http_status=200)
        labels = list(body['questions']['next_action']['criteria'])
        answer = {'model':body['model'], 'answers':{'next_action':{'type':'choice','choice':labels[0],
                  'probabilities':{k:float(i == 0) for i,k in enumerate(labels)}, 'confidence':1.0}}}
        return outcome('OK', json.dumps(answer).encode(), http_status=200, network_attempted=False)


def frozen_inputs(monkeypatch, start, singleton=False):
    """Explicit candidate fixture provider; no search/generator/solver."""
    from semantic_pallet_planner.jev_select import episode
    base = start['snapshot']['pool']
    candidates = read(__import__('pathlib').Path(__file__).parents[1]/'fixtures/jm_a2_suffix_pool.json')
    def inputs(state, task, config, job_id, decision_id, **kw):
        req = observation(state, task['instruction_text'], [])
        pending = {v['item']['item_id'] for v in state['pending_items']}
        pool = [c for c in candidates['stages'][str(state['placed_count'])] if c['pick_item_id'] in pending]
        if singleton: pool = pool[:1]
        b = copy.deepcopy(base)
        b.update(observation_digest=req['observation_digest'], physical_candidates=pool, physical_digest=digest(pool),
                 selectable_candidates=pool, selectable_digest=digest(pool), policy_digest=digest(no_policy(req).data))
        bundle = CandidateBundle.from_dict(b)
        ctx = bind_decision(build_context(config, req, bundle, no_policy(req)), job_id, decision_id, config=config)
        return req, no_policy(req), bundle, ctx
    monkeypatch.setattr(episode, 'decision_inputs', inputs)


def execution(start, index=0, branch='B', budget=3):
    binding = jm.bind_branch(start, branch_id=branch, forced_display_id=labels(start)[index])
    return a2.freeze_execution(binding, max_sends=budget)


@pytest.mark.parametrize('status', ['STABLE','UNSTABLE','UNASSESSABLE','ERROR'])
@pytest.mark.parametrize('singleton', [False,True])
def test_public_continuation_order_counts_and_monitor_stop(archived, monkeypatch, status, singleton):
    start, task, config = archived
    # First monitor STABLE, suffix takes the requested synthetic status.
    calls = stub_monitor(monkeypatch, 'STABLE')
    from semantic_pallet_planner.jev_select.stability import monitor
    stable = monitor.monitor_selected_action
    failed_calls = stub_monitor(monkeypatch, status)
    suffix = monitor.monitor_selected_action
    saved = []
    def assess(state, candidate, event, config):
        assert saved[-1]['phase'] == 'SELECTED' and saved[-1]['pending_event']['monitor'] is None
        return stable(state,candidate,event,config) if not calls else suffix(state,candidate,event,config)
    monkeypatch.setattr(monitor, 'monitor_selected_action', assess)
    frozen_inputs(monkeypatch, start, singleton)
    root = jm.REPO/'a2'; fake = FakeTransport(root=root)
    ex = execution(start)
    write(jm.REPO/'execution.json', ex)
    ep = a2.run_continuation(ex, root=root, transport=fake, on_checkpoint=lambda cp:saved.append(cp))
    counts = read(root/'counts.json')
    assert len(calls) == 1 and counts['forced_actions'] == 1
    assert counts['real_model_calls'] == 0
    assert counts['constructed_requests'] == len(fake.calls)
    assert all(b['state']['memories'] == [] for b in fake.calls)
    if status == 'STABLE':
        assert ep['checkpoint']['reason'] == 'ALL_ITEMS_PLACED'
        assert ep['final_state']['placed_count'] == len(task['items'])
        assert counts['commits'] == 4 and len(failed_calls) == 3
    else:
        assert ep['final_state']['placed_count'] == 1 and len(failed_calls) == 1
        e = ep['events'][-1]
        assert e['after'] == e['before'] and e['action'] is None
        assert ep['checkpoint']['reason'] == monitor.TERMINATIONS[status]
        assert counts['commits'] == 1
    if singleton:
        assert not fake.calls and counts['singleton_actions'] == len(failed_calls)
    else:
        assert fake.calls and counts['singleton_actions'] == 0
    with pytest.raises(JevSelectError, match='resume_not_implemented'):
        a2.run_continuation(ex, root=root, transport=fake)


@pytest.mark.parametrize('mode,reason,state', [('RAISE','UNKNOWN_IN_FLIGHT','UNKNOWN_SEND'),
 ('ERROR','PROVIDER_FAILURE','FAILED'), ('REFUSAL','INVALID_RESPONSE','RESPONSE_SAVED')])
def test_request_failures_stop_no_second_send(archived, monkeypatch, mode, reason, state):
    start,_,_ = archived; stub_monitor(monkeypatch,'STABLE'); frozen_inputs(monkeypatch,start)
    root = jm.REPO/'a2'; fake = FakeTransport(mode,root)
    ex = execution(start);ep = a2.run_continuation(ex,root=root,transport=fake)
    assert ep['checkpoint']['reason'] == reason and ep['final_state']['placed_count'] == 1
    ledger = a2.ContinuationLedger(root/'ledger',ex)
    row = ledger._load()['requests'][0];assert row['state'] == state
    ctx = DecisionContext.from_dict(read(root/'ledger/contexts'/f'{row["decision_id"]}.json'))
    ledger.request(ctx,row['job_id'],row['decision_id'],fake)
    assert len(fake.calls) == 1
    data = ctx.data;data['local_binding']['decision_id'] = 'B_D0002'
    with pytest.raises(JevSelectError,match='execution_stopped'):
        ledger.request(DecisionContext.from_dict(data),'B','B_D0002',fake)
    assert len(fake.calls) == 1


def test_policy_reference_alternative_and_saved_validation(archived,monkeypatch):
    start,task,cfg=archived
    exs=[execution(start,i,f'B{i}') for i in range(3)]
    assert len({e['policy_digest'] for e in exs}) == 1
    assert len({e['binding_digest'] for e in exs}) == 3
    def no(*a,**kw):pytest.fail('saved validation dispatched')
    from semantic_pallet_planner.jev_select import execution as physical,episode
    monkeypatch.setattr(physical,'commit_physical',no);monkeypatch.setattr(episode,'decision_inputs',no)
    for e in exs:a2.validate_execution(e)
    with pytest.raises(JevSelectError):validate_schema('jm_fork_binding_v1',exs[0])
    with pytest.raises(JevSelectError):validate_schema('jm_continuation_v1',dict(exs[0],extra=0))


@pytest.mark.parametrize('field',['config','policy','branch','binding','body','mapping','budget'])
def test_identity_tamper_even_resealed(archived,monkeypatch,field):
    start,task,cfg=archived;ex=execution(start)
    if field in ('config','policy','branch','binding','budget'):
        bad=copy.deepcopy(ex)
        if field=='config':bad['config_digest']=digest('changed')
        elif field=='policy':bad['policy']['model']='changed';bad['policy_digest']=digest(bad['policy'])
        elif field=='branch':bad['branch_id']='other'
        elif field=='budget':bad['max_sends']=100
        else:bad['binding']['exact_action']['pick_item_id']='other';jm.seal(bad['binding']);bad['binding_digest']=digest(bad['binding'])
        jm.seal(bad)
        with pytest.raises(JevSelectError):a2.validate_execution(bad)
    else:
        stub_monitor(monkeypatch,'STABLE');frozen_inputs(monkeypatch,start)
        root=jm.REPO/'a2';fake=FakeTransport(root=root)
        a2.run_continuation(ex,root=root,transport=fake)
        ledger=a2.ContinuationLedger(root/'ledger',ex);row=ledger._load()['requests'][0]
        p=root/'ledger/contexts'/f'{row["decision_id"]}.json';ctx=read(p)
        if field=='body':ctx['request_body']['state']['memories']=['forbidden']
        else:ctx['display_mapping']['C01']['candidate_id']='other'
        for key,part in [('request_body_digest','request_body'),('mapping_digest','display_mapping')]:
            ctx['local_binding'][key]=digest(ctx[part])
        write(p,ctx)
        # Re-sign the mutable ledger too: the separate pre-send reservation
        # remains the original identity anchor and must still reject the edit.
        data=read(ledger.path);row=data['requests'][0]
        for key,part in [('context_digest',None),('body_digest','request_body'),('mapping_digest','display_mapping'),('binding_digest','local_binding')]:
            row[key]=digest(ctx if part is None else ctx[part])
        data['record_digest']=digest({k:v for k,v in data.items() if k!='record_digest'})
        write(ledger.path,data)
        with pytest.raises(JevSelectError):ledger._load()


def test_saved_readonly_no_dispatch_and_anchor_budget(archived,monkeypatch):
    start,_,_=archived;stub_monitor(monkeypatch,'STABLE');frozen_inputs(monkeypatch,start)
    ex=execution(start);root=jm.REPO/'a2';fake=FakeTransport(root=root)
    a2.run_continuation(ex,root=root,transport=fake)
    def no(*a,**kw):pytest.fail('saved validation dispatched')
    from semantic_pallet_planner.jev_select import episode,execution as physical
    from semantic_pallet_planner.jev_select.stability import monitor
    monkeypatch.setattr(episode,'decision_inputs',no);monkeypatch.setattr(physical,'commit_physical',no)
    monkeypatch.setattr(monitor,'monitor_selected_action',no);monkeypatch.setattr(fake,'complete',no)
    before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert a2.validate_saved_execution(root)['requests']==3
    assert all(p.read_bytes()==b for p,b in before.items())
    bad=a2.freeze_execution(ex['binding'],max_sends=2)
    with pytest.raises(JevSelectError,match='anchor_changed'):a2.ContinuationLedger(root/'ledger',bad)


def test_sending_interruption_conservatively_becomes_unknown(archived):
    start,_,_=archived;ex=execution(start)
    root=jm.REPO/'isolated_ledger'
    ctx=bind_decision(DecisionContext.from_dict(start['snapshot']['event']['context']),'B','B_D0001',config=start['snapshot']['parent_config'])
    def interrupt(state,row):
        if state=='SENDING':raise RuntimeError('CONSTRUCTED_PROCESS_INTERRUPTION')
    ledger=a2.ContinuationLedger(root,ex,hook=interrupt);fake=FakeTransport()
    with pytest.raises(RuntimeError):ledger.request(ctx,'B','B_D0001',fake)
    assert ledger._load()['requests'][0]['state']=='SENDING' and fake.calls==[]
    ledger.hook=None
    row=ledger.request(ctx,'B','B_D0001',fake)
    assert row['state']=='UNKNOWN_SEND' and fake.calls==[]
    ledger.request(ctx,'B','B_D0001',fake)
    assert fake.calls==[]


@pytest.mark.parametrize('status',['UNSTABLE','UNASSESSABLE','ERROR'])
def test_forced_first_failure_never_enters_continuation(archived,monkeypatch,status):
    start,_,_=archived;calls=stub_monitor(monkeypatch,status)
    ex=execution(start);fake=FakeTransport()
    ep=a2.run_continuation(ex,root=jm.REPO/'a2',transport=fake)
    assert len(calls)==1 and ep['final_state']==start['snapshot']['state'] and fake.calls==[]
    assert read(jm.REPO/'a2/counts.json')['commits']==0


def test_budget_zero_and_nonfake_transport_rejected(archived,monkeypatch):
    start,_,_=archived;stub_monitor(monkeypatch,'STABLE');frozen_inputs(monkeypatch,start)
    ex=execution(start,budget=0);root=jm.REPO/'a2';fake=FakeTransport(root=root)
    ep=a2.run_continuation(ex,root=root,transport=fake)
    assert ep['checkpoint']['reason']=='request_budget_exhausted' and not fake.calls
    assert ep['final_state']['placed_count']==1
    ledger=a2.ContinuationLedger(root/'ledger',ex)
    fake.origin='jev'
    with pytest.raises(JevSelectError,match='fake_transport_required'):
        a2.selector_factory(ex,ledger=ledger,transport=fake)


def test_private_future_not_in_final_body_actual_selector_used(archived,monkeypatch):
    start,_,_=archived;stub_monitor(monkeypatch,'STABLE');frozen_inputs(monkeypatch,start)
    from semantic_pallet_planner.jev_select.packaging_remote import PackagingRemoteSelector
    original=PackagingRemoteSelector.select;calls=[]
    def select(self,*a,**kw):
        calls.append(type(self));return original(self,*a,**kw)
    monkeypatch.setattr(PackagingRemoteSelector,'select',select)
    ex=execution(start);fake=FakeTransport();root=jm.REPO/'a2'
    ep=a2.run_continuation(ex,root=root,transport=fake)
    assert calls==[PackagingRemoteSelector]*3
    first=fake.calls[0]['state']
    assert 'D' not in [o['object_id'] for o in first['available_objects']]
    for body in fake.calls:
        assert body['state']['memories']==[]
        text=json.dumps(body)
        assert all(k not in text for k in ('reference_policy','task_digest','fork_binding_digest','forced_display_id','future_items','witness','monitor_result'))
    assert ep['checkpoint']['reason']=='ALL_ITEMS_PLACED'


@pytest.mark.parametrize('index',[0,1,2])
def test_reference_and_alternatives_share_actual_suffix_route(archived,monkeypatch,index):
    start,_,_=archived;stub_monitor(monkeypatch,'STABLE');frozen_inputs(monkeypatch,start)
    ex=execution(start,index);root=jm.REPO/'a2';fake=FakeTransport(root=root)
    ep=a2.run_continuation(ex,root=root,transport=fake)
    assert ep['checkpoint']['reason']=='ALL_ITEMS_PLACED' and len(fake.calls)==3
    assert ex['policy']==a2.policy(start['snapshot']['parent_config'])
    assert ep['events'][0]['proposed_action']==ex['binding']['exact_action']
    assert read(root/'counts.json')['forced_actions']==1
