"""JM1-A1 only: frozen constructed pool, monitor stub, real public commit.

No generator, model, credential, solver or historical trajectory execution.
"""
import copy
import hashlib
import json
import socket
from dataclasses import asdict
from pathlib import Path

import pytest

from semantic_pallet_planner.jev_select import packaging_jev_forks as jm
from semantic_pallet_planner.jev_select.contracts import CandidateBundle, digest, JevSelectError, validate_schema
from semantic_pallet_planner.jev_select.ledger import write, read
from semantic_pallet_planner.jev_select.packaging_remote import load_remote_config
from semantic_pallet_planner.jev_select.packaging_runtime import build_context, no_policy
from semantic_pallet_planner.jev_select.selector import bind_decision, result
from semantic_pallet_planner.o4.extensions.e2.protocol import observation
from semantic_pallet_planner.o4.extensions.e2.planning import action_for

FIXTURE = Path(__file__).parents[1]/'fixtures/jm_a1_frozen_pool.json'


@pytest.fixture(autouse=True)
def forbidden_dispatch(monkeypatch):
    def no(*a, **kw):
        pytest.fail('JM A1 attempted generator/model/credentials/solver')
    from semantic_pallet_planner.jev_select import transport
    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
    from semantic_pallet_planner.jev_select.stability import balance_adapter, exact_adapter
    from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
    from semantic_pallet_planner.jev_select.packaging_remote import PackagingRemoteSelector
    monkeypatch.setattr(socket.socket,'connect',no)
    monkeypatch.setattr(transport,'credential',no)
    monkeypatch.setattr(CandidateProvider,'build',no)
    monkeypatch.setattr(balance_adapter,'assess_candidate',no)
    monkeypatch.setattr(exact_adapter,'assess_candidate',no)
    monkeypatch.setattr(LocalPackagingDouble,'select',no)
    monkeypatch.setattr(PackagingRemoteSelector,'select',no)


@pytest.fixture
def archived(tmp_path, monkeypatch, request):
    monkeypatch.setattr(jm,'REPO',tmp_path)
    variant = getattr(request,'param','v6')
    data = read(FIXTURE)
    if variant=='nonempty':data=data['nonempty_prefix']
    task = data['task']; state = data['state']; candidates = data['candidates']
    if variant=='singleton':candidates=candidates[:1]
    config = load_remote_config(data_identity=digest('CONSTRUCTED_ONLY'),task_digest=digest(task),enabled=True)
    if variant=='v12':
        from semantic_pallet_planner.jev_select.packaging_exact_protocol import load_exact_config
        from semantic_pallet_planner.jev_select.packaging_synthetic_data import MEMORY_SCOPE
        config=load_exact_config(data_identity=digest('CONSTRUCTED_ONLY'),task_digest=digest(task),method='jev_no_memory',
            relation={'memory_scope_version':MEMORY_SCOPE,'order_related_source_groups':[],'excluded_fork_digests':[]},purpose='SYNTHETIC_ENGINEERING')
    suffix=config['version'].rsplit('_',1)[1]
    req = observation(state,task['instruction_text'],[]); policy = no_policy(req)
    pool = {'version':'jev_candidate_bundle_'+suffix,'observation_digest':req['observation_digest'],
        'candidate_backend':'e2_original_v1','generator_config_digest':digest('FROZEN_CONSTRUCTED_POOL'),
        'physical_candidates':candidates,'physical_digest':digest(candidates),
        'generation_counts':[], 'selectable_pool':'physical_feasible',
        'selectable_candidates':copy.deepcopy(candidates),'selectable_digest':digest(candidates),
        'policy_digest':digest(policy.data),'experiment_protocol':config['experiment_protocol'],'business_mode':config['business_mode']}
    extras={}
    if variant=='v12':
        from semantic_pallet_planner.jev_select.packaging_runtime import public_facts
        from semantic_pallet_planner.jev_select.packaging_evaluation_memory import MemoryDriver
        _,public,criteria,_,_=public_facts(config,req,CandidateBundle.from_dict(pool),policy)
        view,receipt=MemoryDriver(config).resolve(public,criteria)
        extras={'memory_view':view,'retrieval_receipt':receipt}
    ctx = bind_decision(build_context(config,req,CandidateBundle.from_dict(pool),policy,**extras),'P','P_D0000',config=config)
    label = next(k for k,v in ctx.data['display_mapping'].items() if v['candidate_id']==candidates[0]['candidate_id'])
    selected = result(ctx,status='singleton' if variant=='singleton' else 'selected',source='singleton' if variant=='singleton' else 'jev',label=label).data
    event = {'event':'PLACE','decision_id':'P_D0000','before':state,'after':state,'route':ctx.data['route'],
        'observation':req,'bundle':pool,'context':ctx.data,'selection':selected,
        'proposed_action':action_for(req,candidates,candidates[0]),'action':None,'monitor':None,
        'monitor_result_reuses':0,'reason':None,'error':None,'business_after':None,'reference_after':None,'timings':{}}
    snapshot = jm.seal({'version':'jev_training_fork_v1','parent_identity':{'scope':'CONSTRUCTED_ONLY'},
        'decision_id':'P_D0000','parent_job_id':'P','record':'CONSTRUCTED_ONLY','parent_record_digest':digest(event),
        'source_group':'CONSTRUCTED_ONLY','task_digest':digest(task),'parent_config':config,'state':state,'cursor':state['arrival_count'],
        'end_of_stream':False,'buffer':state['pending_items'],'pool':pool,'mapping':ctx.data['display_mapping'],
        'event':event,'field_evidence':{'scope':'CONSTRUCTED_ONLY'}})
    write(tmp_path/'parent/snapshot.json',snapshot); write(tmp_path/'parent/task.json',task)
    write(tmp_path/'parent/receipt.json',{'files_sha256':{n:hashlib.sha256((tmp_path/'parent'/n).read_bytes()).hexdigest() for n in ['snapshot.json','task.json']}})
    start = jm.freeze_start(receipt_path='parent/receipt.json',snapshot_path='parent/snapshot.json',snapshot_pointer='',task_path='parent/task.json',evidence_scope='CONSTRUCTED_ONLY')
    return start, task, config


def stub_monitor(monkeypatch,status):
    """Return explicitly synthetic credentials, retain production validation."""
    from semantic_pallet_planner.jev_select.stability import monitor as mon
    from semantic_pallet_planner.jev_select.stability.contracts import StabilityResult
    from semantic_pallet_planner.jev_select.stability.geometry import state_from_runtime, box_from_runtime
    calls=[]
    def monitor(state,candidate,event,config):
        calls.append(copy.deepcopy(event))
        frozen=config['stability_monitor']
        res=StabilityResult(status=status,reason_code='CONSTRUCTED_MONITOR_STUB_NOT_SOLVER',
            state_digest=digest(asdict(state_from_runtime(state))),candidate_digest=digest(asdict(box_from_runtime(mon.selected_box(state,candidate)))),
            candidate_id=candidate['pick_item_id'],config_digest=digest(frozen['kernel_config']),algorithm_identity=frozen['algorithm_identity'],
            baseline_status='NOT_ASSESSED',first_bad_prefix=None,failed_item_id=None,height_delta_mm=None,evaluated_pose=None,
            kernel_calls=0,diagnostics={'scope':'CONSTRUCTED_ONLY'},version='pct_stability_result_v3' if frozen['algorithm']=='pct_exact_pose_network_v3' else 'pct_stability_result_v2').to_dict()
        row={'version':'selected_action_monitor_v1','binding':mon.binding(state,candidate,event,config),
             'status':status,'result':res,'attempted':True,'committed':False,'result_digest':digest(res)}
        row['credential_digest']=digest(row)
        mon.validate_monitor(row,state,candidate,event,config)
        return row
    monkeypatch.setattr(mon,'monitor_selected_action',monitor)
    return calls


def labels(start):
    return list(start['snapshot']['mapping'])


@pytest.mark.parametrize('field',['state','cursor','pool','action','task','identity','mapping','config','candidate'])
def test_resigned_content_tamper_rejected(archived,field):
    start,task,cfg=archived
    binding=jm.bind_branch(start,branch_id='B',forced_display_id=labels(start)[0])
    if field=='state':binding['start']['snapshot']['state']['placed_count']+=1
    elif field=='cursor':binding['start']['snapshot']['cursor']+=1
    elif field=='pool':binding['start']['snapshot']['pool']['physical_candidates'].reverse()
    elif field=='action':binding['exact_action']['pick_item_id']='INVALID'
    elif field=='task':task=copy.deepcopy(task);task['items'][0]['mass_kg']+=1
    elif field=='identity':binding['branch_id']='OTHER'
    elif field=='candidate':binding['forced_candidate']['pose']['x_mm']+=1
    elif field=='mapping':binding['start']['snapshot']['mapping'][labels(start)[0]]['candidate_id']='INVALID'
    else:cfg=copy.deepcopy(cfg);cfg['display_order_seed']+=1
    jm.seal(binding['start']['snapshot']); jm.seal(binding['start']); binding['start_digest']=digest(binding['start']); jm.seal(binding)
    with pytest.raises(JevSelectError):jm.bootstrap(binding,task,cfg,'B')


@pytest.mark.parametrize('forced_index',[0,1,2])
@pytest.mark.parametrize('status',['STABLE','UNSTABLE','UNASSESSABLE','ERROR'])
def test_public_first_step_accounts_and_no_fallback(archived,monkeypatch,status,forced_index):
    start,task,cfg=archived
    before=copy.deepcopy(start); files={p:p.read_bytes() for p in jm.REPO.rglob('*.json')}
    monitor_calls=stub_monitor(monkeypatch,status)
    from semantic_pallet_planner.jev_select import execution
    real=execution.commit_physical;commits=[]
    def commit(*args,**kw):
        commits.append(1);return real(*args,**kw)
    monkeypatch.setattr(execution,'commit_physical',commit)
    binding=jm.bind_branch(start,branch_id='B',forced_display_id=labels(start)[forced_index]); saved=[]
    def persist(cp):
        saved.append(copy.deepcopy(cp))
        write(jm.REPO/'branch/stages'/f"{len(saved):02d}_{cp['phase']}.json",cp)
    write(jm.REPO/'branch/binding.json',binding)
    ep=jm.run_forced_first(binding,on_checkpoint=persist)
    write(jm.REPO/'branch/episode.json',ep)
    write(jm.REPO/'branch/counts.json',{'scope':'CONSTRUCTED_MONITOR_STUB','forced_actions':1,'monitor_calls':len(monitor_calls),'commits':len(commits),'model_calls':0,'transport_calls':0,'solver_calls':0,'credential_reads':0,'intervention':binding['intervention'],'monitor_status':status})
    assert len(monitor_calls)==1 and len(commits)==int(status=='STABLE')
    assert saved[0]['phase']=='SELECTED' and saved[1]['phase']=='MONITORED'
    assert saved[0]['pending_event']['monitor'] is None
    assert len(ep['events'])==1 and ep['checkpoint']['cursor']==3 and ep['checkpoint']['decision']==1
    selection=ep['events'][0]['selection']
    assert selection['source']==jm.SOURCE and selection['forced_action_count']==1 and selection['model_call_count']==0
    assert selection['attempt_ids']==[] and selection['network_attempted'] is False
    state=ep['final_state'];base=start['snapshot']['state']
    if status=='STABLE':
        assert ep['checkpoint']['reason']==jm.STOP and ep['summary']['termination_reason']==jm.STOP
        assert state['placed_count']==1 and len(state['pending_items'])==2
        c=binding['forced_candidate'];obj=state['placed_items'][0]
        assert obj['mass_kg']==next(x['mass_kg'] for x in task['items'] if x['item_id']==c['pick_item_id'])
        from math import prod
        assert prod(obj['oriented_size_mm'])==prod(c['oriented_size_mm'])
        assert sum(x['mass_kg'] for x in state['placed_items'])==obj['mass_kg']
        assert len([cp for cp in saved if cp['phase']=='COMMITTED'])==1
    else:
        from semantic_pallet_planner.jev_select.stability.monitor import TERMINATIONS
        assert ep['checkpoint']['reason']==TERMINATIONS[status] and state==base
        assert ep['events'][0]['action'] is None and state['placed_items']==[]
    assert start==before and all(p.read_bytes()==b for p,b in files.items())


def test_three_roles_exact_bindings_and_deep_copies(archived):
    start,task,cfg=archived;first=[];types=[]
    for i,label in enumerate(labels(start)):
        b=jm.bind_branch(start,branch_id=f'B{i}',forced_display_id=label);types.append(b['intervention'])
        cp=jm.bootstrap(b,task,cfg,b['branch_id']);first.append(cp)
        e=cp['pending_event'];assert e['bundle']==start['snapshot']['pool']
        assert e['context']['display_mapping']==start['snapshot']['mapping']
        assert e['proposed_action']==b['exact_action']
        assert e['selection']['selected_candidate_id']==b['forced_candidate']['candidate_id']
    assert set(types)=={'ORIGINAL_ACTION_REFERENCE','SAME_BOX_DIFFERENT_POSE','CROSS_BOX_SELECTION'}
    first[0]['state']['pending_items'].clear();first[0]['pending_event']['bundle']['physical_candidates'].clear()
    assert len(first[1]['state']['pending_items'])==len(start['snapshot']['buffer'])==3
    assert len(first[1]['pending_event']['bundle']['physical_candidates'])==3


def test_illegal_action_no_selector_and_resume_rejected(archived):
    start,task,cfg=archived
    with pytest.raises(JevSelectError):jm.bind_branch(start,branch_id='B',forced_display_id='C99')
    b=jm.bind_branch(start,branch_id='B',forced_display_id=labels(start)[0]);cp=jm.bootstrap(b,task,cfg,'B')
    from semantic_pallet_planner.jev_select.episode import run_episode
    with pytest.raises(JevSelectError,match='jm_resume_not_implemented_A3'):
        run_episode(task,jm.UnimplementedContinuation(),cfg,job_id='B',method=cfg['selector'],training_fork=b,resume=cp,on_checkpoint=lambda cp:None)
    with pytest.raises(JevSelectError,match='NOT_IMPLEMENTED'):jm.UnimplementedContinuation().select(None)
    with pytest.raises(JevSelectError,match='persistence'):jm.run_forced_first(b,on_checkpoint=None)


def test_saved_validation_never_dispatches_and_detects_bytes(archived,monkeypatch):
    start,task,cfg=archived
    from semantic_pallet_planner.jev_select import execution
    from semantic_pallet_planner.jev_select.stability import monitor
    def forbidden(*a,**kw):pytest.fail('validation dispatched')
    monkeypatch.setattr(execution,'commit_physical',forbidden);monkeypatch.setattr(monitor,'monitor_selected_action',forbidden)
    b=jm.bind_branch(start,branch_id='B',forced_display_id=labels(start)[0]);jm.validate_binding(b,task,cfg,'B')
    write(jm.REPO/'parent/snapshot.json',dict(start['snapshot'],cursor=2))
    with pytest.raises(JevSelectError,match='saved_bytes_changed'):jm.validate_binding(b,task,cfg,'B')


def test_registration_and_legacy_closed_selection(archived):
    from semantic_pallet_planner.jev_select.packaging_versions import JM_FORK_PROTOCOLS
    start,task,cfg=archived;b=jm.bind_branch(start,branch_id='B',forced_display_id=labels(start)[0])
    assert b['version'] in JM_FORK_PROTOCOLS
    selected=jm.bootstrap(b,task,cfg,'B')['pending_event']['selection'];validate_schema('selection_result',selected)
    with pytest.raises(JevSelectError):validate_schema('selection_result_v6',selected)
    with pytest.raises(JevSelectError):validate_schema('jm_fork_binding_v1',dict(b,extra=True))
    from semantic_pallet_planner.jev_select import packaging_counterfactual as old
    with pytest.raises(JevSelectError):old.bootstrap(b,task,cfg,'B')


@pytest.mark.parametrize('archived',['singleton','nonempty','v12'],indirect=True)
def test_extra_saved_envelopes_first_step_only(archived,monkeypatch):
    start,task,cfg=archived
    calls=stub_monitor(monkeypatch,'STABLE')
    label=next(k for k,v in start['snapshot']['mapping'].items() if v['candidate_id']==start['snapshot']['pool']['physical_candidates'][0]['candidate_id'])
    binding=jm.bind_branch(start,branch_id='X',forced_display_id=label)
    saved=[];ep=jm.run_forced_first(binding,on_checkpoint=lambda cp:saved.append(cp))
    assert len(calls)==1 and ep['checkpoint']['reason']==jm.STOP
    assert ep['final_state']['placed_count']==start['snapshot']['state']['placed_count']+1
    assert ep['checkpoint']['cursor']==start['snapshot']['cursor']
    assert ep['events'][0]['before']==start['snapshot']['state']
    assert ep['events'][0]['bundle']==start['snapshot']['pool']
    assert len(ep['final_state']['pending_items'])==len(start['snapshot']['buffer'])-1
    assert ep['events'][0]['selection']['attempt_ids']==[]


def test_legacy_public_episode_keeps_ordinary_selection(archived,monkeypatch):
    start,task,cfg=archived;s=start['snapshot']
    stub_monitor(monkeypatch,'STABLE')
    from semantic_pallet_planner.jev_select import episode
    from semantic_pallet_planner.jev_select.contracts import DecisionContext
    calls=[]
    class OrdinarySelector:
        def select(self,context,**kwargs):
            calls.append(1)
            return result(context,status='selected',source='test_double',label=labels(start)[0])
    def inputs(state,task,config,job_id,decision_id,**kw):
        assert state==s['state']
        context=bind_decision(DecisionContext.from_dict(s['event']['context']),job_id,decision_id,config=config)
        return s['event']['observation'],no_policy(s['event']['observation']),CandidateBundle.from_dict(s['pool']),context
    monkeypatch.setattr(episode,'decision_inputs',inputs)
    ep=episode.run_episode(task,OrdinarySelector(),cfg,job_id='L',method=cfg['selector'],event_limit=4)
    assert calls==[1] and ep['checkpoint']['phase']=='READY'
    assert ep['checkpoint']['reason'] is None and ep['final_state']['placed_count']==1
    assert ep['events'][-1]['selection']['version']=='jev_selection_result_v6'
    assert ep['events'][-1]['selection']['source']=='test_double'
