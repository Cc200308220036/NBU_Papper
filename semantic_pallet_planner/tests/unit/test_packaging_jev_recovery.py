"""A3 crash injection only: fake transport, frozen pool, monitor stub."""
import copy

import pytest

from test_packaging_jev_forks import archived, labels, stub_monitor
from test_packaging_jev_continuation import FakeTransport, frozen_inputs, guards
from semantic_pallet_planner.jev_select import packaging_jev_forks as jm
from semantic_pallet_planner.jev_select import packaging_jev_recovery as a3
from semantic_pallet_planner.jev_select.contracts import DecisionContext, JevSelectError, digest, validate_schema
from semantic_pallet_planner.jev_select.ledger import read, write
from semantic_pallet_planner.jev_select.selector import bind_decision


class Crash(BaseException): pass


def schedule(start, slots=(('r0',3),)):
    binding = jm.bind_branch(start, branch_id='B', forced_display_id=labels(start)[0])
    return a3.freeze_schedule([{'binding':binding,'repeat_slot':s,'max_sends':b} for s,b in slots], root=jm.REPO/'a3')


def run_root(s): return jm.REPO/'a3/slots'/s['executions'][0]['allocation_id']


def run(s, fake, **kw):
    return a3.run_repeat(s,branch_id='B',repeat_slot='r0',root=jm.REPO/'a3',transport=fake,**kw)


@pytest.mark.parametrize('point', ['ACTIVATED','CONTEXT_SAVED','RESERVATION_SAVED','INTENT',
                                  'SENDING','RESPONSE_SAVED','SELECTION_SAVED',
                                  'DECISION_READY','SELECTED','MONITORED','COMMITTED','READY','TERMINATED'])
@pytest.mark.parametrize('first', [False, True])
def test_crash_matrix(archived, monkeypatch, point, first):
    start, task, _ = archived
    calls=stub_monitor(monkeypatch,'STABLE'); frozen_inputs(monkeypatch,start)
    s=schedule(start);fake=FakeTransport(); hit=[]
    from semantic_pallet_planner.jev_select import execution as physical
    original=physical.commit_physical;commits=[]
    from semantic_pallet_planner.jev_select.packaging_remote import PackagingRemoteSelector
    select_original=PackagingRemoteSelector.select;selections=[]
    def select(self,*a,**kw): selections.append(kw['decision_id']);return select_original(self,*a,**kw)
    monkeypatch.setattr(PackagingRemoteSelector,'select',select)
    def commit(*a,**kw): commits.append(a[0]['placed_count']);return original(*a,**kw)
    monkeypatch.setattr(physical,'commit_physical',commit)
    def hook(state,row):
        if state==point and not hit:hit.append(state);raise Crash()
    def checkpoint(cp):
        # Exercise both forced-first and suffix phases when available.
        target = 0 if first else 1
        if cp['phase']==point and cp['decision']>=target and not hit:
            hit.append(point);raise Crash()
    # Initial forced selection is atomically in activation; ACTIVATED represents
    # its interruption. SELECTED tests therefore target suffix persisted stages.
    with pytest.raises(Crash):run(s,fake,on_checkpoint=checkpoint,ledger_hook=hook)
    assert hit
    before=(len(fake.calls),len(calls),len(commits))
    a3.validate_saved_execution(run_root(s))
    ep=run(s,fake)
    if point=='SENDING':
        assert not fake.calls and ep['checkpoint']['reason']=='UNKNOWN_IN_FLIGHT'
        assert a3.validate_saved_execution(run_root(s))['states']==['UNKNOWN_SEND']
    else:
        assert ep['checkpoint']['reason']=='ALL_ITEMS_PLACED'
        assert ep['final_state']['placed_count']==len(task['items'])
        assert len(fake.calls)==3 and len(calls)==4 and len(commits)==4
        assert len(selections)==3+int(point in ('CONTEXT_SAVED','RESERVATION_SAVED','INTENT','RESPONSE_SAVED','SELECTION_SAVED'))
    after=(len(fake.calls),len(calls),len(commits))
    data={p:p.read_bytes() for p in (run_root(s)/'stages').glob('*.json')}
    again=run(s,fake)
    assert again['events']==ep['events'] and again['final_state']==ep['final_state']
    assert (len(fake.calls),len(calls),len(commits))==after
    assert {p:p.read_bytes() for p in (run_root(s)/'stages').glob('*.json')}==data
    write(run_root(s)/'recovery_observation.json',{'point':point,'first':first,'before_calls':before,
          'after_calls':after,'selector_calls':len(selections),'terminal':ep['checkpoint']['reason'],'repeat_no_calls':True})


@pytest.mark.parametrize('status',['UNSTABLE','UNASSESSABLE','ERROR'])
@pytest.mark.parametrize('phase',['MONITORED','TERMINATED'])
@pytest.mark.parametrize('suffix',[False,True])
def test_failure_recovery_no_reselection(archived,monkeypatch,status,phase,suffix):
    start,_,_=archived; frozen_inputs(monkeypatch,start)
    from semantic_pallet_planner.jev_select.stability import monitor
    stable_calls=stub_monitor(monkeypatch,'STABLE');stable=monitor.monitor_selected_action
    failed_calls=stub_monitor(monkeypatch,status);failed=monitor.monitor_selected_action
    def assess(*a):
        return stable(*a) if suffix and not stable_calls else failed(*a)
    monkeypatch.setattr(monitor,'monitor_selected_action',assess)
    s=schedule(start);fake=FakeTransport();hit=[]
    def checkpoint(cp):
        target = 2 if suffix and phase == 'TERMINATED' else 1
        if cp['phase']==phase and (not suffix or cp['decision']==target) and not hit:
            hit.append(phase);raise Crash()
    with pytest.raises(Crash):run(s,fake,on_checkpoint=checkpoint)
    ep=run(s,fake)
    assert ep['checkpoint']['reason']==monitor.TERMINATIONS[status]
    assert len(failed_calls)==1 and len(fake.calls)==int(suffix)
    assert ep['final_state']['placed_count']==int(suffix)
    assert read(run_root(s)/'counts.json')['forced_actions']==1
    a3.validate_saved_execution(run_root(s))


@pytest.mark.parametrize('stop',['UNKNOWN_SEND','FAILED'])
def test_existing_intent_other_stop_blocks_send(archived,stop):
    start,_,cfg=archived;s=schedule(start);ex=s['executions'][0];job=ex['branch_id']
    root=jm.REPO/'isolated';fake=FakeTransport()
    ctx=lambda n:bind_decision(DecisionContext.from_dict(start['snapshot']['event']['context']),job,f'{job}_D{n:04d}',config=cfg)
    def interrupt(state,row):
        if state=='INTENT':raise Crash()
    ledger=a3.RecoveryLedger(root,ex,hook=interrupt)
    with pytest.raises(Crash):ledger.request(ctx(1),job,f'{job}_D0001',fake)
    ledger.hook=None
    if stop=='FAILED': fake.mode='ERROR'
    else: fake.mode='RAISE'
    ledger.request(ctx(2),job,f'{job}_D0002',fake)
    assert ledger._load()['requests'][1]['state']==stop
    with pytest.raises(JevSelectError,match='execution_stopped'):
        ledger.request(ctx(1),job,f'{job}_D0001',fake)
    assert len(fake.calls)==1 and ledger._load()['requests'][0]['state']=='INTENT'


def test_repeat_slot_budget_isolation_and_same_slot_reentry(archived,monkeypatch):
    start,_,_=archived;stub_monitor(monkeypatch,'STABLE');frozen_inputs(monkeypatch,start)
    s=schedule(start,(('r0',0),('r1',3)));fake=FakeTransport()
    ep=run(s,fake);assert ep['checkpoint']['reason']=='request_budget_exhausted' and not fake.calls
    ep=run(s,fake);assert not fake.calls
    ep=a3.run_repeat(s,branch_id='B',repeat_slot='r1',root=jm.REPO/'a3',transport=fake)
    assert len(fake.calls)==3 and ep['checkpoint']['reason']=='ALL_ITEMS_PLACED'
    assert len({e['allocation_id'] for e in s['executions']})==2
    assert len({e['branch_id'] for e in s['executions']})==2
    assert len({e['policy_digest'] for e in s['executions']})==1
    with pytest.raises(JevSelectError,match='storage_root_changed'):
        a3.run_repeat(s,branch_id='B',repeat_slot='r0',root=jm.REPO/'another_root',transport=fake)
    assert not (jm.REPO/'another_root').exists()
    with pytest.raises(JevSelectError,match='unregistered_slot'):
        a3.run_repeat(s,branch_id='B',repeat_slot='new',root=jm.REPO/'a3',transport=fake)
    with pytest.raises(JevSelectError,match='duplicate_slot'):schedule(start,(('r0',1),('r0',2)))
    with pytest.raises(JevSelectError,match='schedule_changed'):
        run(schedule(start,(('r0',3),)),fake)


@pytest.mark.parametrize('phase',['DECISION_READY','SELECTED','MONITORED','COMMITTED'])
def test_saved_validation_has_zero_dispatch_and_no_writes(archived,monkeypatch,phase):
    start,_,_=archived;stub_monitor(monkeypatch,'STABLE');frozen_inputs(monkeypatch,start)
    s=schedule(start);fake=FakeTransport()
    def interrupt(cp):
        if cp['phase']==phase:raise Crash()
    with pytest.raises(Crash):run(s,fake,on_checkpoint=interrupt)
    def no(*a,**kw):pytest.fail('saved validation dispatched')
    from semantic_pallet_planner.jev_select import episode,execution as physical
    from semantic_pallet_planner.jev_select.packaging_remote import PackagingRemoteSelector
    from semantic_pallet_planner.jev_select.stability import monitor
    monkeypatch.setattr(episode,'decision_inputs',no);monkeypatch.setattr(physical,'commit_physical',no)
    monkeypatch.setattr(monitor,'monitor_selected_action',no);monkeypatch.setattr(PackagingRemoteSelector,'select',no)
    monkeypatch.setattr(fake,'complete',no)
    root=run_root(s);before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert a3.validate_saved_execution(root)['checkpoint']['phase']==phase
    assert before=={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('target',['source','dependencies','policy','task','body','mapping','monitor','context_missing','reservation_missing','checkpoint_missing','checkpoint_corrupt'])
def test_changed_identity_or_missing_saved_fact_rejected(archived,monkeypatch,target):
    start,_,_=archived;stub_monitor(monkeypatch,'STABLE');frozen_inputs(monkeypatch,start)
    s=schedule(start);fake=FakeTransport();run(s,fake);root=run_root(s)
    if target in ('source','dependencies','policy','task','monitor'):
        bad=copy.deepcopy(s)
        e=bad['executions'][0]
        if target=='source':e['policy']['source_identity']=digest('drift')
        elif target=='dependencies':e['policy']['dependencies']['numpy']='drift'
        elif target=='policy':e['policy']['prompt_version']='drift'
        elif target=='task':e['task_digest']=digest('drift')
        else:e['binding']['start']['snapshot']['parent_config']['runtime_identity']['monitor_identity']=digest('drift')
        e['policy_digest']=digest(e['policy']);jm.seal(e);jm.seal(bad)
        with pytest.raises((JevSelectError,KeyError)):run(bad,fake)
    else:
        if target in ('checkpoint_missing','checkpoint_corrupt'):
            p=next((root/'stages').glob('*.json'))
        else:
            d='reservations' if target=='reservation_missing' else 'contexts'
            p=next((root/'ledger'/d).glob('*.json'))
        if target.endswith('_missing'):p.unlink()
        else:
            v=read(p)
            if target=='body':v['request_body']['state']['memories']=['bad']
            elif target=='mapping':v['display_mapping']['C01']['candidate_id']='bad'
            else:v['checkpoint']['cursor']+=1
            write(p,v)
        with pytest.raises((JevSelectError,FileNotFoundError)):run(s,fake)
    assert len(fake.calls)==3


def test_old_schemas_reject_a3_and_new_schemas_closed(archived):
    start,_,_=archived;ex=schedule(start)['executions'][0]
    with pytest.raises(JevSelectError):validate_schema('jm_continuation_v1',ex)
    with pytest.raises(JevSelectError):validate_schema('jm_recovery_v1',dict(ex,extra=1))
    with pytest.raises(JevSelectError):validate_schema('checkpoint_v6',a3.initial_checkpoint(ex))


@pytest.mark.parametrize('phase',['SELECTED','MONITORED'])
def test_singleton_recovery_never_sends(archived,monkeypatch,phase):
    start,_,_=archived;calls=stub_monitor(monkeypatch,'STABLE');frozen_inputs(monkeypatch,start,singleton=True)
    s=schedule(start);fake=FakeTransport();hit=[]
    def interrupt(cp):
        if cp['phase']==phase and cp['decision']==1 and not hit:hit.append(1);raise Crash()
    with pytest.raises(Crash):run(s,fake,on_checkpoint=interrupt)
    ep=run(s,fake)
    assert not fake.calls and len(calls)==4 and ep['final_state']['placed_count']==4
    counts=read(run_root(s)/'counts.json')
    assert counts['singleton_actions']==3 and counts['constructed_requests']==0


@pytest.mark.parametrize('field',['source_identity','dependencies'])
def test_actual_current_identity_drift_refuses_before_dispatch(archived,monkeypatch,field):
    start,_,_=archived;s=schedule(start);fake=FakeTransport()
    from semantic_pallet_planner.jev_select import packaging_jev_continuation as a2
    original=a2.policy
    def changed(config):
        value=original(config)
        if field=='dependencies':value[field]['numpy']='CHANGED_RUNTIME_DEPENDENCY'
        else:value[field]=digest('CHANGED_CURRENT_SOURCE')
        return value
    monkeypatch.setattr(a2,'policy',changed)
    with pytest.raises(JevSelectError,match='execution_changed'):run(s,fake)
    assert not fake.calls and not (jm.REPO/'a3').exists()


def test_cross_call_lock_and_intervention_registration(archived):
    start,_,_=archived
    rows=[]
    for i in range(3):
        b=jm.bind_branch(start,branch_id=f'B{i}',forced_display_id=labels(start)[i])
        rows.append({'binding':b,'repeat_slot':'r0','max_sends':3})
    s=a3.freeze_schedule(rows, root=jm.REPO/'locked')
    assert {e['binding']['intervention'] for e in s['executions']}=={
        'ORIGINAL_ACTION_REFERENCE','SAME_BOX_DIFFERENT_POSE','CROSS_BOX_SELECTION'}
    assert len({e['policy_digest'] for e in s['executions']})==1 and s['total_max_sends']==9
    from semantic_pallet_planner.jev_select.ledger import exclusive
    root=jm.REPO/'locked';root.mkdir()
    fake=FakeTransport()
    with exclusive(root):
        with pytest.raises(JevSelectError,match='experiment_locked'):
            a3.run_repeat(s,branch_id='B0',repeat_slot='r0',root=root,transport=fake)
    assert not fake.calls and not (root/'schedule.json').exists()
