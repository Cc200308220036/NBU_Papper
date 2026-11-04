"""Constructed fork mechanism tests. No real task suffix or remote transport."""
import copy
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select import packaging_counterfactual as f
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError
from semantic_pallet_planner.jev_select.episode import run_episode
from semantic_pallet_planner.jev_select.stability.monitor import load_monitor_config,seal_checkpoint
from semantic_pallet_planner.jev_select.tests.unit.test_packaging_runtime import mechanism_task,item


@pytest.fixture
def fixture(monkeypatch):
    task=mechanism_task([item(str(i),size=(20,20,20)) for i in range(6)])
    task.update(partition='train',source_group_id='CONSTRUCTED_ONLY')
    cfg=load_monitor_config(data_identity=digest('CONSTRUCTED_ONLY'),task_digest=digest(task),enabled=True)
    original=run_episode(task,f.continuation_factory(),cfg,job_id='P',method=f.METHOD,event_limit=4)
    event=next(e for e in original['events'] if e.get('decision_id'))
    snapshot=f.seal({'version':f.VERSION,'parent_identity':{'parent':'CONSTRUCTED_ONLY'},'decision_id':event['decision_id'],
        'record':'CONSTRUCTED_ONLY','field_evidence':{'scope':'CONSTRUCTED_ONLY'},'parent_job_id':'P','parent_record_digest':digest(event),'source_group':'CONSTRUCTED_ONLY','task_digest':digest(task),
        'parent_config':cfg,'state':event['before'],'cursor':3,'end_of_stream':False,'buffer':event['before']['pending_items'],
        'pool':event['bundle'],'mapping':event['context']['display_mapping'],'event':event})
    # Replace only archival lookup with an explicitly constructed fixture. Runtime,
    # candidate generator, monitor, commit and checkpoint validator remain real.
    monkeypatch.setattr(f,'restore_training_fork',lambda *a:copy.deepcopy(snapshot))
    def binding(index=0):
        return f.seal({'version':f.VERSION,'job_id':f'B{index:02d}','snapshot':copy.deepcopy(snapshot),
                       'first':f.interventions(snapshot)['branches'][index],'config_digest':digest(cfg),'plan_digest':digest('CONSTRUCTED_PLAN')})
    return task,cfg,snapshot,binding


def execute(fixture,index=0,**kwargs):
    t,c,s,b=fixture;binding=b(index)
    return run_episode(t,f.continuation_factory(),c,job_id=binding['job_id'],method=f.METHOD,training_fork=binding,**kwargs)


def test_exact_first_and_independent_branches(fixture):
    t,c,s,b=fixture;before=copy.deepcopy(s)
    episodes=[execute(fixture,i) for i in range(3)]
    for i,ep in enumerate(episodes):
        first=next(e for e in ep['events'] if e.get('decision_id'))
        assert first['before']==s['state']
        assert first['bundle']['physical_candidates']==s['pool']['physical_candidates']
        assert first['selection']['selected_candidate_id']==b(i)['first']['candidate']['candidate_id']
        assert sum(e.get('decision_id')==f'B{i:02d}_D0000' for e in ep['events'])==1
        assert ep['checkpoint']['reason']=='ALL_ITEMS_PLACED'
        assert ep['final_state']['placed_count']==6
        f.validate_branch_checkpoint(ep['checkpoint'],t,c,f'B{i:02d}',b(i))
    episodes[0]['events'][0]['before']['placed_count']=999
    assert episodes[1]['events'][0]['before']['placed_count']==0 and s==before


@pytest.mark.parametrize('phase',['SELECTED','MONITORED','COMMITTED','READY','TERMINATED'])
def test_resume_never_repeats_selected_monitor_commit(fixture,monkeypatch,phase):
    t,c,s,b=fixture;saved=[];counts={'commit':0,'monitor':0}
    import semantic_pallet_planner.jev_select.execution as ex
    import semantic_pallet_planner.jev_select.stability.monitor as mon
    real_commit=ex.commit_physical;real_monitor=mon.monitor_selected_action
    def commit(*a,**kw):counts['commit']+=1;return real_commit(*a,**kw)
    def monitor(*a,**kw):counts['monitor']+=1;return real_monitor(*a,**kw)
    monkeypatch.setattr(ex,'commit_physical',commit);monkeypatch.setattr(mon,'monitor_selected_action',monitor)
    class Cut(BaseException):pass
    def checkpoint(cp):
        if cp['phase']==phase and (phase!='READY' or cp['decision']>=1):
            saved.append(copy.deepcopy(cp));raise Cut()
    if phase=='SELECTED':saved.append(f.bootstrap(b(),t,c,'B00'))
    else:
        with pytest.raises(Cut):execute(fixture,on_checkpoint=checkpoint)
    ep=execute(fixture,resume=saved[0]);assert ep['final_state']['placed_count']==6
    assert counts=={'commit':6,'monitor':6}
    def forbidden(*a,**kw):raise AssertionError('saved validation dispatched execution')
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
    import semantic_pallet_planner.jev_select.stability.balance_adapter as ba
    monkeypatch.setattr(ex,'commit_physical',forbidden);monkeypatch.setattr(mon,'monitor_selected_action',forbidden)
    monkeypatch.setattr(ba,'assess_candidate',forbidden);monkeypatch.setattr(CandidateProvider,'build',forbidden)
    monkeypatch.setattr(f.LocalPackagingDouble,'select',forbidden)
    f.validate_branch_checkpoint(ep['checkpoint'],t,c,'B00',b())
    assert execute(fixture,resume=ep['checkpoint'])['checkpoint']==ep['checkpoint']


def test_first_does_not_generate_pool_then_suffix_regenerates(fixture,monkeypatch):
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
    real=CandidateProvider.build;calls=[]
    def build(self,state,*a,**kw):
        assert state['placed_count']>=1
        calls.append(state['placed_count']);return real(self,state,*a,**kw)
    monkeypatch.setattr(CandidateProvider,'build',build)
    execute(fixture);assert calls and min(calls)==1


@pytest.mark.parametrize('status',['UNSTABLE','UNASSESSABLE','ERROR'])
@pytest.mark.parametrize('when',['first','suffix'])
def test_monitor_stop_no_reselection_or_failed_load(fixture,monkeypatch,status,when):
    from dataclasses import replace
    from semantic_pallet_planner.jev_select.stability import balance_adapter as ba
    real=ba.assess_candidate;calls=[]
    def assess(*a,**kw):
        calls.append(1);out=real(*a,**kw)
        if when=='first' or len(calls)>1:return replace(out,status=status,reason_code='CONSTRUCTED_FAULT')
        return out
    monkeypatch.setattr(ba,'assess_candidate',assess)
    ep=execute(fixture)
    expected=0 if when=='first' else 1
    assert ep['final_state']['placed_count']==expected and len(calls)==expected+1
    assert ep['checkpoint']['reason']=={'UNSTABLE':'PREDICTED_STATIC_INSTABILITY','UNASSESSABLE':'STABILITY_UNASSESSABLE','ERROR':'STABILITY_MONITOR_ERROR'}[status]
    last=ep['events'][-1];assert last['before']==last['after'] and last['action'] is None
    assert last['selection'] is not None


@pytest.mark.parametrize('mutate',['state','first','task','config','nontrain'])
def test_binding_tamper_rejected(fixture,mutate):
    t,c,s,b=fixture;binding=b();t=copy.deepcopy(t);c=copy.deepcopy(c)
    if mutate=='state':binding['snapshot']['state']['arrival_count']+=1
    elif mutate=='first':binding['first']['candidate']['pose']['x_mm']+=1
    elif mutate=='task':t['items'][0]['mass_kg']+=1
    elif mutate=='config':c['display_order_seed']+=1
    else:t['partition']='test'
    f.seal(binding)
    with pytest.raises(JevSelectError):f.bootstrap(binding,t,c,'B00')


def test_sampling_missing_ties_dedup_and_gaps(fixture):
    t,c,s,b=fixture
    choices=f.interventions(s);assert len(choices['branches'])==3
    assert [r['intervention'] for r in choices['branches']][1:]==['SAME_BOX_DIFFERENT_POSE','CROSS_BOX_SELECTION']
    assert not choices['native_probability_complete']
    s=copy.deepcopy(s);s['event']['selection']['probabilities']={k:.5 for k in s['mapping']}
    assert f.interventions(s)['native_probability_complete']
    assert f.interventions(s)==f.interventions(copy.deepcopy(s))
    s['pool']['selectable_candidates'].reverse();assert f.interventions(s)==f.interventions(copy.deepcopy(s))
    # Duplicate geometry is not an intervention, regardless of candidate ID.
    chosen=choices['branches'][0]['candidate'];duplicate=copy.deepcopy(chosen);duplicate['candidate_id']='DUP'
    s['pool']['selectable_candidates']=[chosen,duplicate]
    s['mapping']['DUP']={'candidate_id':'DUP','pick_item_id':chosen['pick_item_id'],'candidate_digest':digest(duplicate)}
    out=f.interventions(s);assert len(out['branches'])==1 and len(out['coverage_gaps'])==2


def test_checkpoint_resigned_tamper_rejected(fixture):
    t,c,s,b=fixture;cp=execute(fixture)['checkpoint'];bad=copy.deepcopy(cp)
    bad['events'][0]['selection']['selected_candidate_id']='BAD';seal_checkpoint(bad)
    with pytest.raises(JevSelectError):f.validate_branch_checkpoint(bad,t,c,'B00',b())


def test_real_parent_restore_readonly_and_bad_decision(monkeypatch):
    parent=Path('semantic_pallet_planner/outputs/JEV_JN1_20261103_03')
    before=f.file_manifest(parent)
    def forbidden(*a,**kw):raise AssertionError('restore dispatched')
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
    import semantic_pallet_planner.jev_select.execution as ex
    import semantic_pallet_planner.jev_select.stability.balance_adapter as ba
    monkeypatch.setattr(CandidateProvider,'build',forbidden);monkeypatch.setattr(ex,'commit_physical',forbidden)
    monkeypatch.setattr(ba,'assess_candidate',forbidden);monkeypatch.setattr(f.LocalPackagingDouble,'select',forbidden)
    s=f.restore_training_fork(parent,'J0000_D0001')
    assert s['cursor']==s['state']['arrival_count'] and s['state']['placed_count']==1
    with pytest.raises(JevSelectError):f.restore_training_fork(parent,'J0001_D0000')
    assert before==f.file_manifest(parent)


def prepared(fixture,tmp_path,monkeypatch):
    from semantic_pallet_planner.jev_select.ledger import write
    t,c,s,b=fixture
    parent=tmp_path/'parent';output=tmp_path/'output'
    write(parent/'plan/plan.json',{'jobs':[{'job_id':'P','method_id':'jev_no_memory'}]})
    write(parent/'jn2_decision_index.json',{'all_decisions':[{'job_id':'P','decision_id':'P_D0000','eligible_training_decision':True}]})
    write(tmp_path/'private.json',t)
    s['field_evidence']['task']=str(tmp_path/'private.json')
    s['parent_identity'].update(manifest_sha256=digest('CONSTRUCTED_ONLY'),data_identity=c['runtime_identity']['data_identity'])
    f.seal(s)
    monkeypatch.setattr(f,'audit_parent',lambda *a:copy.deepcopy(s['parent_identity']))
    def fresh(path):
        path=Path(path);assert not path.exists();path.mkdir(parents=True);return path
    monkeypatch.setattr(f.common,'new_output',fresh)
    f.prepare(parent,output)
    return output


@pytest.mark.parametrize('kind',['ERROR','TECHNICAL_LIMIT','UNASSESSABLE','CANCELED'])
def test_registered_batch_full_denominator_stop_and_resume(fixture,tmp_path,monkeypatch,kind):
    from semantic_pallet_planner.jev_select.ledger import read
    output=prepared(fixture,tmp_path,monkeypatch)
    if kind in ('ERROR','CANCELED'):
        def hook(*a):
            if kind=='CANCELED':raise KeyboardInterrupt()
            raise RuntimeError('CONSTRUCTED_TECHNICAL_ERROR')
        out=f.run(output,hook=hook)
    else:
        from dataclasses import replace
        from semantic_pallet_planner.jev_select.stability import balance_adapter as ba
        real=ba.assess_candidate
        if kind=='UNASSESSABLE':
            monkeypatch.setattr(ba,'assess_candidate',lambda *a,**kw:replace(real(*a,**kw),status='UNASSESSABLE',reason_code='CONSTRUCTED_RANGE'))
        else:
            # Reach watchdog through elapsed time; immutable registration unchanged.
            real_clock=f.time.perf_counter;clock=[0.]
            def step():clock[0]+=601;return clock[0]
            monkeypatch.setattr(f.time,'perf_counter',step)
        out=f.run(output)
    assert out['planned_suffixes']==3 and out['model_calls']==0
    assert [r['category'] for r in out['branches']]==([kind]*3 if kind=='UNASSESSABLE' else [kind,'NOT_RUN','NOT_RUN'])
    before=f.file_manifest(output)
    def forbidden(*a,**kw):raise AssertionError('completed batch dispatched')
    import semantic_pallet_planner.jev_select.episode as ep
    monkeypatch.setattr(ep,'run_episode',forbidden)
    f.validate_output(output)
    assert f.run(output,resume=True)==out and f.file_manifest(output)==before


def test_nonempty_prefix_cursor_and_increment(fixture,monkeypatch):
    t,c,s,b=fixture
    ep=run_episode(t,f.continuation_factory(),c,job_id='P',method=f.METHOD)
    event=[e for e in ep['events'] if e.get('decision_id')][1]
    snapshot=copy.deepcopy(s)
    snapshot.update(decision_id=event['decision_id'],state=event['before'],cursor=event['before']['arrival_count'],
                    buffer=event['before']['pending_items'],pool=event['bundle'],mapping=event['context']['display_mapping'],event=event)
    f.seal(snapshot)
    monkeypatch.setattr(f,'restore_training_fork',lambda *a:copy.deepcopy(snapshot))
    binding=f.seal({'version':f.VERSION,'job_id':'NONEMPTY','snapshot':snapshot,'first':f.interventions(snapshot)['branches'][0],
                    'config_digest':digest(c),'plan_digest':digest('CONSTRUCTED_PLAN')})
    out=run_episode(t,f.continuation_factory(),c,job_id='NONEMPTY',method=f.METHOD,training_fork=binding)
    assert snapshot['state']['placed_count']==1 and snapshot['cursor']==4
    assert out['final_state']['placed_count']==6 and len([e for e in out['events'] if e['event']=='PLACE'])==5
    status={'state':'FINISHED','category':'COMPLETE','active_wall_s':1.,'error':None}
    metrics=f.branch_metrics(t,c,out['checkpoint'],status,snapshot)
    assert metrics['branch_metrics']['suffix_increment']['items']==5
    assert metrics['loading']['planned_items']==6 and metrics['stable_complete']


def test_batch_interruption_resumes_saved_monitor_once(fixture,tmp_path,monkeypatch):
    output=prepared(fixture,tmp_path,monkeypatch)
    import semantic_pallet_planner.jev_select.stability.monitor as mon
    real=mon.monitor_selected_action;first_calls=[]
    def monitor(*args,**kw):
        if args[2]['decision_id']=='B00_D0000':first_calls.append(1)
        return real(*args,**kw)
    monkeypatch.setattr(mon,'monitor_selected_action',monitor)
    class PowerLoss(BaseException):pass
    def hook(phase,value):
        if phase=='after_monitored_checkpoint':raise PowerLoss()
    with pytest.raises(PowerLoss):f.run(output,hook=hook)
    out=f.run(output,resume=True)
    assert out['started_suffixes']==3 and first_calls==[1]
    assert all(r['category']=='COMPLETE' for r in out['branches'])


def test_parent_bytes_tamper_rejected(tmp_path):
    from semantic_pallet_planner.jev_select.ledger import write
    payload=tmp_path/'saved.json';write(payload,{'original':True})
    write(tmp_path/'delivery_manifest.json',{'files_sha256':{'saved.json':f.sha(payload)}})
    write(payload,{'original':False})
    with pytest.raises(JevSelectError,match='parent_files_changed'):f.audit_parent(tmp_path)
