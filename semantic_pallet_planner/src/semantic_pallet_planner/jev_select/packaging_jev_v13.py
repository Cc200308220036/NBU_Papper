"""Independent exact-v3 no-memory protocol over the public episode engine.

Transport is always injected. This module neither creates a transport nor loads
credentials. REMOTE_INJECTED additionally requires a separately saved send permit;
this engineering delivery issues no permits or formal task matrix.
"""
from __future__ import annotations
import copy
import platform
from importlib.metadata import version
from pathlib import Path

from .contracts import CandidateBundle, DecisionContext, digest, validate_schema
from .ledger import read, write, exclusive
from .packaging_versions import JM_V13, JM_V13_EXECUTION
from .packaging_jev_forks import require, seal, check_seal
from .packaging_remote import RequestLedger, PackagingRemoteSelector


def identity():
    from .experiment import source_manifest
    return {'source':digest(source_manifest()),'python':platform.python_version(),
            'dependencies':{n:version(n) for n in ('jsonschema','numpy','scipy')}}


def load_config(*, data_identity, task_digest, mode='CONSTRUCTED_ONLY'):
    from .packaging_remote import load_remote_config
    from .stability.monitor import exact_freeze
    c=load_remote_config(data_identity=data_identity,task_digest=task_digest,enabled=False)
    c.update(version=JM_V13,jm_mode=mode,stability_monitor=exact_freeze())
    c['runtime_identity']['monitor_identity']=digest(c['stability_monitor'])
    c['runtime_identity']['strategy_identity']=strategy(c)
    validate_schema('config',c)
    return c


def strategy(c):
    return digest({'config':{k:v for k,v in c.items() if k!='runtime_identity'},'identity':identity(),
                   'protocol':JM_V13,'memory':'NONE_NO_RETRIEVAL','continuation':'jev_no_memory'})


def preflight(c):
    validate_schema('config',c)
    from .stability.monitor import exact_freeze
    from .packaging_remote import load_remote_config
    i=c['runtime_identity']
    require(c['version']==JM_V13 and c['selector']=='jev_no_memory' and c['memory_mode']=='none','jm13_method')
    require(c['stability_monitor']==exact_freeze() and i['monitor_identity']==digest(c['stability_monitor']),
            'jm13_monitor_identity')
    require(i['strategy_identity']==strategy(c),'jm13_source_or_dependency_drift')
    base=load_remote_config(data_identity=i['data_identity'],task_digest=i['task_identity'],enabled=False)
    excluded={'version','runtime_identity','stability_monitor','jm_mode'}
    require({k:v for k,v in c.items() if k not in excluded}=={k:v for k,v in base.items() if k not in excluded},'jm13_base_config_changed')
    require(i['physical_identity']==base['runtime_identity']['physical_identity'],'jm13_physical_identity')


def ref(path):
    p=Path(path).resolve()
    return {'path':str(p),'sha256':__import__('hashlib').sha256(p.read_bytes()).hexdigest()}


def load_ref(r):
    require(type(r) is dict and set(r)=={'path','sha256'},'jm13_reference_shape')
    p=Path(r['path']);raw=p.read_bytes()
    require(__import__('hashlib').sha256(raw).hexdigest()==r['sha256'],'jm13_parent_bytes_changed')
    return read(p)


def capture_start(root,decision_id):
    root=Path(root).resolve();saved=validate_saved_execution(root)
    paths=sorted((root/'stages').glob('*.json'))
    require(bool(paths),'jm13_no_saved_decision')
    value={'version':'jev_jm_v13_start_v1','activation_ref':ref(root/'activation.json'),
           'checkpoint_ref':ref(paths[-1]),'decision_id':decision_id}
    validate_start(value)
    return value


def validate_start(start):
    validate_schema('jm_v13_start',start)
    activation=load_ref(start['activation_ref']);check_seal(activation)
    parent=activation['execution'];validate_execution(parent)
    row=load_ref(start['checkpoint_ref']);validate_schema('jm_v13_journal',row);check_seal(row)
    require(row['execution_digest']==digest(parent),'jm13_parent_execution_changed')
    cp=row['checkpoint'];validate_saved_checkpoint(cp,parent,_validated=True)
    events=cp['events']+([cp['pending_event']] if cp['pending_event'] else [])
    found=[e for e in events if e.get('decision_id')==start['decision_id']]
    require(len(found)==1 and found[0].get('selection') is not None and
            found[0]['selection']['status'] in ('selected','singleton'),'jm13_start_not_selected')
    return parent['task'],parent['config'],copy.deepcopy(found[0])


def freeze_execution(task,config,*,job_id,root,repeat_slot='r0',start=None,forced_label=None,max_sends=None):
    preflight(config)
    require(config['runtime_identity']['task_identity']==digest(task),'jm13_task_identity')
    require(task.get('partition')=='train','jm13_training_partition_required')
    if start is not None:
        t,c,event=validate_start(start)
        require(task==t and config==c,'jm13_parent_task_config_changed')
        require(forced_label in event['context']['display_mapping'],'jm13_forced_outside_frozen_pool')
        bound=max(0,len(task['items'])-event['before']['placed_count']-1)
    else:
        require(forced_label is None,'jm13_baseline_forced_action_forbidden');bound=len(task['items'])
    max_sends=bound if max_sends is None else max_sends
    require(type(max_sends) is int and 0<=max_sends<=bound,'jm13_invalid_budget')
    allocation=digest({'job_id':job_id,'repeat_slot':repeat_slot,'task':digest(task),'start':start,'forced_label':forced_label,'root':str(Path(root).resolve())})
    ex={'version':JM_V13_EXECUTION,'kind':'FORK' if start else 'BASELINE','task':copy.deepcopy(task),
        'config':copy.deepcopy(config),'job_id':job_id+'_'+allocation[:16],'repeat_slot':repeat_slot,
        'storage_root':str(Path(root).resolve()),'start':copy.deepcopy(start),'forced_label':forced_label,
        'max_sends':max_sends,'allocation_id':allocation,'identity':identity()}
    seal(ex);validate_schema('jm_v13_execution',ex)
    return ex


def validate_execution(ex):
    validate_schema('jm_v13_execution',ex);check_seal(ex);preflight(ex['config'])
    require(ex['identity']==identity() and ex['config']['runtime_identity']['task_identity']==digest(ex['task']),
            'jm13_execution_identity_drift')
    require(ex['task'].get('partition')=='train','jm13_training_partition_required')
    # Rebuild all immutable allocation fields, including storage and budget, not history.
    require(ex['kind']==('FORK' if ex['start'] is not None else 'BASELINE'),'jm13_execution_kind')
    if ex['start']:
        t,c,event=validate_start(ex['start'])
        require(t==ex['task'] and c==ex['config'] and ex['forced_label'] in event['context']['display_mapping'],'jm13_execution_parent_changed')
        cap=max(0,len(t['items'])-event['before']['placed_count']-1)
    else:
        require(ex['forced_label'] is None,'jm13_baseline_forced_action_forbidden');cap=len(ex['task']['items'])
    require(ex['max_sends']<=cap,'jm13_budget_changed')
    base_job=ex['job_id'].rsplit('_',1)[0]
    allocation=digest({'job_id':base_job,'repeat_slot':ex['repeat_slot'],'task':digest(ex['task']),
                       'start':ex['start'],'forced_label':ex['forced_label'],'root':ex['storage_root']})
    require(ex['allocation_id']==allocation and ex['job_id']==base_job+'_'+allocation[:16],'jm13_allocation_changed')
    return ex['task'],ex['config']


def initial_checkpoint(ex):
    task,c=validate_execution(ex)
    from semantic_pallet_planner.o4.buffer.buffer_state import initial
    from .selector import bind_decision
    from semantic_pallet_planner.o4.extensions.e2.planning import action_for
    if ex['start']:
        _,_,e=validate_start(ex['start']);state=copy.deepcopy(e['before']);did=ex['job_id']+'_D0000'
        ctx=bind_decision(DecisionContext.from_dict(e['context']),ex['job_id'],did,config=c)
        label=ex['forced_label'];m=ctx.data['display_mapping'][label]
        chosen=next(x for x in e['bundle']['selectable_candidates'] if x['candidate_id']==m['candidate_id'])
        selection={'version':'jev_jm_forced_selection_v1','status':'singleton' if ctx.data['route']=='SINGLETON_BYPASS' else 'selected',
            'selected_display_id':label,'selected_candidate_id':chosen['candidate_id'],'source':'FORCED_FROM_FROZEN_POOL',
            'requested_model':None,'served_model':None,'probabilities':None,'confidence':None,'attempt_ids':[],
            'usage':None,'latency_s':None,'local_binding_digest':digest(ctx.data['local_binding']),
            'raw_response_digest':None,'error':None,'network_attempted':False,'error_stage':None,'error_code':None,
            'fork_binding_digest':digest(ex),'candidate_digest':digest(chosen),'config_digest':digest(c),
            'forced_action_count':1,'model_call_count':0}
        validate_schema('jm_forced_selection_v1',selection)
        e.update(event='STOP',decision_id=did,before=state,after=copy.deepcopy(state),context=ctx.data,selection=selection,
                 proposed_action=action_for(e['observation'],e['bundle']['physical_candidates'],chosen),action=None,
                 monitor=None,monitor_result_reuses=0,reason=None,error=None,reference_after=None,business_after=None,timings={})
        pending=e;phase='SELECTED'
    else:state=initial(task['container'],c['buffer_capacity']);pending=None;phase='READY'
    return seal({'version':'jev_checkpoint_v13','job_id':ex['job_id'],'method':'jev_no_memory',
        'task_digest':digest(task),'config_digest':digest(c),'runtime_identity':copy.deepcopy(c['runtime_identity']),
        'state':state,'cursor':state['arrival_count'],'decision':0,'events':[],'reason':None,'phase':phase,'pending_event':pending})


def validate_saved_checkpoint(cp,ex,*,_validated=False):
    if not _validated:validate_execution(ex)
    task=ex['task'];config=ex['config'];validate_schema('checkpoint_v13',cp);check_seal(cp)
    require(cp['job_id']==ex['job_id'] and cp['task_digest']==digest(task) and cp['config_digest']==digest(config) and
            cp['runtime_identity']==config['runtime_identity'] and cp['method']=='jev_no_memory','jm13_checkpoint_identity')
    from semantic_pallet_planner.o4.buffer.buffer_state import invariant,initial
    from semantic_pallet_planner.o4.extensions.e2.protocol import observation
    from semantic_pallet_planner.o4.extensions.e2.planning import action_for
    from .context import validate_context
    from .stability.monitor import validate_monitor,TERMINATIONS
    state=(validate_start(ex['start'])[2]['before'] if ex['start'] else initial(task['container'],config['buffer_capacity']))
    decisions=forced=0
    for event in cp['events']+([cp['pending_event']] if cp['pending_event'] else []):
        require(event['before']==state,'jm13_state_chain_changed');invariant(event['after'])
        if event.get('context') is not None:
            require(event['decision_id']==f'{ex["job_id"]}_D{decisions:04d}','jm13_decision_changed')
            require(event['observation']==observation(state,task['instruction_text'],task['regions']),'jm13_observation_changed')
            ctx=DecisionContext.from_dict(event['context']);bundle=CandidateBundle.from_dict(event['bundle'])
            validate_context(ctx,event['observation'],bundle,config)
            require(ctx.data['local_binding']['job_id']==ex['job_id'] and ctx.data['local_binding']['decision_id']==event['decision_id'],
                    'jm13_context_job_changed')
            selected=event.get('selection')
            if selected:
                validate_schema('selection_result',selected)
                require(selected['local_binding_digest']==digest(ctx.data['local_binding']),'jm13_selection_changed')
                if selected['status'] in ('selected','singleton'):
                    m=ctx.data['display_mapping'][selected['selected_display_id']]
                    candidate=next(c for c in bundle.data['selectable_candidates'] if c['candidate_id']==m['candidate_id'])
                    require(selected['selected_candidate_id']==m['candidate_id'] and
                            event['proposed_action']==action_for(event['observation'],bundle.data['physical_candidates'],candidate),
                            'jm13_exact_action_changed')
                    if selected['source']=='FORCED_FROM_FROZEN_POOL':
                        forced+=1
                        require(ex['kind']=='FORK' and decisions==0 and selected['fork_binding_digest']==digest(ex) and
                                selected['selected_display_id']==ex['forced_label'],'jm13_forced_changed')
                    if event.get('monitor') is not None:
                        validate_monitor(event['monitor'],state,candidate,event,config,require_stable=event['event']=='PLACE')
                        if event['monitor']['status'] in TERMINATIONS and event is not cp['pending_event']:
                            require(event['reason']==TERMINATIONS[event['monitor']['status']],'jm13_monitor_stop_changed')
            if event['event']=='PLACE':
                require(event.get('monitor') is not None and event['monitor']['status']=='STABLE' and event['action']==event['proposed_action'] and
                        event['after']['placed_count']==state['placed_count']+1,'jm13_commit_changed')
                require(event['after']['placed_items'][:-1]==state['placed_items'] or
                        [x['item_id'] for x in event['after']['placed_items'][:-1]]==[x['item_id'] for x in state['placed_items']],
                        'jm13_placed_prefix_changed')
                require({x['item']['item_id'] for x in event['after']['pending_items']}==
                        {x['item']['item_id'] for x in state['pending_items']}-{candidate['pick_item_id']},
                        'jm13_buffer_commit_changed')
            else:require(event['after']==state and event['action'] is None,'jm13_failure_mutated_state')
            if event is not cp['pending_event']:decisions+=1
        else:require(event['event'] in ('WAIT_RECEIVE','EOS'),'jm13_unknown_event')
        state=event['after']
    require(state==cp['state'] and cp['decision']==decisions and forced==int(ex['kind']=='FORK'),'jm13_progress_changed')
    invariant(state)
    require(cp['cursor']==state['arrival_count'] and state['arrived_ids']==[x['item_id'] for x in task['items'][:cp['cursor']]],'jm13_cursor_changed')
    phase=cp['phase'];pending=cp['pending_event']
    require((pending is None)==(phase in ('READY','TERMINATED')),'jm13_pending_phase')
    if pending:
        require((pending['selection'] is None)==(phase=='DECISION_READY') and
                (pending.get('monitor') is not None)==(phase in ('MONITORED','COMMITTED')) and
                (pending['event']=='PLACE')==(phase=='COMMITTED'),'jm13_pending_facts')
    if phase=='TERMINATED':require(cp['reason'] is not None,'jm13_missing_stop_reason')
    return cp


class V13Ledger(RequestLedger):
    context_version='jev_decision_context_v13';ledger_version='jev_jm_v13_requests_v1'
    def __init__(self,root,ex,*,hook=None,permit=None):
        self.execution=copy.deepcopy(ex);self.task,self.config=validate_execution(ex);self.permit=permit
        root=Path(root).resolve()
        require(root==Path(ex['storage_root'])/'ledger','jm13_ledger_storage_changed')
        root.mkdir(parents=True,exist_ok=True)
        with exclusive(root):
            anchor=root/'execution.json'
            if anchor.exists():require(read(anchor)==ex,'jm13_ledger_anchor_changed')
            else:
                require(not any(p.name!='.writer.lock' for p in root.iterdir()),'jm13_missing_ledger_anchor');write(anchor,ex)
                self.root=root;self.path=root/'requests.json'
                self._save({'version':self.ledger_version,'max_sends':ex['max_sends'],'requests':[]})
        super().__init__(root,max_sends=ex['max_sends'],hook=hook)

    def check_context(self,context,job,did):
        from .context import validate_context
        validate_context(context,config=self.config)
        require(job==self.execution['job_id'] and did.startswith(job+'_D') and '/' not in did and '\\' not in did,'jm13_request_job')
        require(context.data['model_state']['memories']==[] and context.data['request_body']['state']['memories']==[], 'jm13_request_memory')
        return self.identity(context,job,did)

    def reservation(self,context,job,did):
        return {'version':'jev_jm_v13_reservation_v1','allocation_id':self.execution['allocation_id'],
                'repeat_slot':self.execution['repeat_slot'],'execution_digest':digest(self.execution),**self.check_context(context,job,did)}

    def _load(self):
        require(read(self.root/'execution.json')==self.execution,'jm13_ledger_anchor_changed')
        data=super()._load()
        origin='test_double' if self.config['jm_mode']=='CONSTRUCTED_ONLY' else 'jev'
        for row in data['requests']:
            ctx=DecisionContext.from_dict(read(self.root/'contexts'/(row['decision_id']+'.json')))
            ids=self.check_context(ctx,row['job_id'],row['decision_id'])
            require(row['origin']==origin and row['model']==self.config['model'] and all(row[k]==v for k,v in ids.items()),'jm13_saved_request_changed')
            require(read(self.root/'reservations'/(row['decision_id']+'.json'))==self.reservation(ctx,row['job_id'],row['decision_id']),'jm13_reservation_changed')
            if row['selection'] is not None:
                from .selector import parse_response
                require(parse_response(ctx,row,self.config).data==row['selection'],'jm13_saved_response_selection_changed')
        return data

    def admit_request(self,job,did):
        require(not any(r['state'] in ('SENDING','UNKNOWN_SEND','FAILED') or
            (r['selection'] is not None and r['selection']['status']!='selected') for r in self.data['requests']), 'jm13_request_stopped')

    def admit_send(self,row):
        validate_execution(self.execution);self.admit_request(row['job_id'],row['decision_id'])
        require(row['state']=='INTENT' and row['send_started'] is False,'jm13_unsafe_send')
        if self.config['jm_mode']=='REMOTE_INJECTED':
            require(self.permit is not None,'jm13_remote_send_not_authorized')
            permit=load_ref(self.permit)
            require(permit=={'version':'jev_jm_v13_send_permit_v1','execution_digest':digest(self.execution),
                'allocation_id':self.execution['allocation_id'],'max_sends':self.max_sends,'authorized':True},'jm13_send_permit_changed')

    def request(self,context,job_id,decision_id,transport):
        self.check_context(context,job_id,decision_id)
        validate_transport_binding(self.execution,transport)
        with exclusive(self.root):
            self._load()
            for folder,value,stage in [('contexts',context.data,'CONTEXT_SAVED'),('reservations',self.reservation(context,job_id,decision_id),'RESERVATION_SAVED')]:
                path=self.root/folder/(decision_id+'.json')
                if path.exists():require(read(path)==value,'jm13_prepared_record_changed')
                else:
                    write(path,value)
                    if self.hook:self.hook(stage,{})
        return super().request(context,job_id,decision_id,transport)


def selector_factory(ex,*,ledger,transport):
    validate_execution(ex)
    require(type(ledger) is V13Ledger and ledger.execution==ex,'jm13_selector_ledger_changed')
    return PackagingRemoteSelector(ex['config'],ledger,ex['job_id'],transport)


def validate_route(ex,task,config,job_id,selector):
    validate_execution(ex)
    require(task==ex['task'] and config==ex['config'] and job_id==ex['job_id'] and
            type(selector) is PackagingRemoteSelector and type(selector.ledger) is V13Ledger and
            selector.ledger.execution==ex and selector.config==config and selector.job_id==job_id,'jm13_episode_route_changed')


def validate_saved_execution(root,*,expected_execution=None):
    root=Path(root);activation=read(root/'activation.json');check_seal(activation)
    require(set(activation)=={'version','execution','initial_checkpoint','send_permit_ref','record_digest'} and
            activation['version']=='jev_jm_v13_activation_v1','jm13_activation_shape')
    ex=activation['execution'];validate_execution(ex)
    validate_send_permit(ex,activation['send_permit_ref'])
    require(expected_execution is None or ex==expected_execution,'jm13_activation_changed')
    cp=activation['initial_checkpoint'];require(cp==initial_checkpoint(ex),'jm13_initial_changed')
    previous=digest(activation);paths=sorted((root/'stages').glob('*.json'))
    for i,path in enumerate(paths,1):
        row=read(path);validate_schema('jm_v13_journal',row);check_seal(row)
        require(path.name==f'{i:06d}.json' and row['sequence']==i and row['previous_digest']==previous and row['execution_digest']==digest(ex),'jm13_journal_chain_changed')
        nxt=row['checkpoint'];validate_saved_checkpoint(nxt,ex,_validated=True)
        require(nxt['events'][:len(cp['events'])]==cp['events'],'jm13_events_overwritten')
        allowed={'READY':{'READY','DECISION_READY','TERMINATED'},'DECISION_READY':{'DECISION_READY','SELECTED','TERMINATED'},
                 'SELECTED':{'MONITORED','TERMINATED'},'MONITORED':{'COMMITTED','TERMINATED'},'COMMITTED':{'READY','TERMINATED'},'TERMINATED':{'TERMINATED'}}
        require(nxt['phase'] in allowed[cp['phase']],'jm13_phase_transition')
        cp=nxt;previous=digest(row)
    if paths or (root/'checkpoint_head.json').exists():
        require(read(root/'checkpoint_head.json')=={'sequence':len(paths),'digest':previous},'jm13_journal_head_changed')
    ledger_root=root/'ledger';rows=[];contexts={}
    if ledger_root.exists():
        obj=V13Ledger.__new__(V13Ledger);obj.root=ledger_root;obj.path=ledger_root/'requests.json';obj.execution=ex
        obj.task=ex['task'];obj.config=ex['config'];obj.max_sends=ex['max_sends'];obj.permit=None
        rows=obj._load()['requests']
        contexts={p.stem:read(p) for p in (ledger_root/'contexts').glob('*.json')}
        reservations={p.stem:read(p) for p in (ledger_root/'reservations').glob('*.json')}
        events={e['decision_id']:e for e in cp['events']+([cp['pending_event']] if cp['pending_event'] else [])
                if e.get('context') and e['context']['route']=='CHOICE_REQUIRED' and
                   (not e.get('selection') or e['selection']['source']!='FORCED_FROM_FROZEN_POOL')}
        require(set(contexts)<=set(events) and set(reservations)<=set(contexts),'jm13_unexplained_ledger_progress')
        for did,ctx in contexts.items():
            require(events[did]['context']==ctx,'jm13_context_progress_changed')
            ready=cp['phase']=='DECISION_READY' and events[did] is cp['pending_event']
            require(did in reservations or ready,'jm13_missing_reservation')
            if did in reservations:require(reservations[did]==obj.reservation(DecisionContext.from_dict(ctx),ex['job_id'],did),'jm13_reservation_changed')
        for row in rows:
            require(row['decision_id'] in events,'jm13_unexplained_request_progress')
            event=events[row['decision_id']];ready=cp['phase']=='DECISION_READY' and event is cp['pending_event']
            require(ready or row['selection']==event['selection'],'jm13_request_ahead_of_checkpoint')
        for did,event in events.items():
            if event.get('selection'):
                matches=[r for r in rows if r['decision_id']==did]
                require(contexts.get(did)==event['context'] and len(matches)==1 and matches[0]['selection']==event['selection'],'jm13_missing_selected_request')
    else:require(not paths,'jm13_missing_ledger')
    if not paths:require(not (root/'episode.json').exists() and not (root/'counts.json').exists(),'jm13_unexplained_finished_progress')
    if (root/'episode.json').exists():
        ep=read(root/'episode.json');require(ep['checkpoint']==cp and ep['events']==cp['events'] and ep['final_state']==cp['state'],'jm13_episode_changed')
    if (root/'counts.json').exists():
        require(read(root/'counts.json')==counts(ex,cp,rows),'jm13_counts_changed')
    return {'version':'jev_jm_v13_saved_check_v1','execution':ex,'checkpoint':cp,'sequence':len(paths),
            'previous_digest':previous,'requests':len(rows),'states':[r['state'] for r in rows]}


def run_execution(ex,*,root,transport,permit=None,on_checkpoint=None,ledger_hook=None):
    validate_execution(ex);root=Path(root).resolve()
    require(str(root)==ex['storage_root'],'jm13_storage_root_changed')
    validate_send_permit(ex,permit)
    validate_transport_binding(ex,transport)
    root.mkdir(parents=True,exist_ok=True)
    with exclusive(root):
        anchor=root/'activation.json';fresh=not anchor.exists()
        if fresh:
            require(not any(p.name!='.writer.lock' for p in root.iterdir()),'jm13_missing_activation')
            write(anchor,seal({'version':'jev_jm_v13_activation_v1','execution':ex,'initial_checkpoint':initial_checkpoint(ex),'send_permit_ref':permit}))
            if ledger_hook:ledger_hook('ACTIVATED',{})
        saved=validate_saved_execution(root,expected_execution=ex)
        require(read(root/'activation.json')['send_permit_ref']==permit,'jm13_send_permit_identity_changed')
        ledger=V13Ledger(root/'ledger',ex,hook=ledger_hook,permit=permit)
        selector=selector_factory(ex,ledger=ledger,transport=transport)
        if fresh and on_checkpoint:on_checkpoint(copy.deepcopy(saved['checkpoint']))
        def persist(cp):
            validate_saved_checkpoint(cp,ex,_validated=True)
            if cp==saved['checkpoint']:return
            saved['sequence']+=1
            row=seal({'version':'jev_jm_v13_journal_v1','sequence':saved['sequence'],'previous_digest':saved['previous_digest'],
                      'execution_digest':digest(ex),'checkpoint':cp})
            write(root/'stages'/f'{saved["sequence"]:06d}.json',row)
            write(root/'checkpoint_head.json',{'sequence':saved['sequence'],'digest':digest(row)})
            saved.update(checkpoint=copy.deepcopy(cp),previous_digest=digest(row))
            if on_checkpoint:on_checkpoint(copy.deepcopy(cp))
        from .episode import run_episode
        episode=run_episode(ex['task'],selector,ex['config'],job_id=ex['job_id'],method='jev_no_memory',
            training_fork=ex,resume=saved['checkpoint'],on_checkpoint=persist)
        write(root/'episode.json',episode)
        rows=ledger._load()['requests']
        write(root/'counts.json',counts(ex,episode['checkpoint'],rows))
        return episode


def export_public(root,output):
    """New-run saved records -> closed B1 inputs, with audit linkage separate.

    Reads only saved bytes. Never reconstructs historical candidates or state.
    All decisions remain in the index, including no/invalid selection and singleton.
    """
    from . import packaging_jev_sampling as sampling
    root=Path(root).resolve();out=Path(output).resolve();saved=validate_saved_execution(root)
    require(not out.exists(),'jm13_public_output_exists');out.mkdir(parents=True)
    cp=saved['checkpoint'];ex=saved['execution']
    ledger=read(root/'ledger/requests.json')['requests'] if (root/'ledger/requests.json').exists() else []
    events=cp['events']+([cp['pending_event']] if cp['pending_event'] else [])
    index=[];audit=[]
    for event_index,e in enumerate(events):
        if not e.get('context'):continue
        selected=e.get('selection');entry={'decision_id':e['decision_id'],'candidate_count':len(e['bundle']['selectable_candidates'])}
        if not selected or selected['status'] not in ('selected','singleton') or selected['source']=='FORCED_FROM_FROZEN_POOL':
            entry['status']='FORCED_NOT_NATIVE' if selected and selected['source']=='FORCED_FROM_FROZEN_POOL' else 'NO_SAVED_VALID_SELECTION'
            index.append(entry);continue
        state=e['before'];ctx=e['context'];pool=e['bundle']['selectable_candidates']
        def item(obj):
            return {'item_id':obj['item_id'],'size_mm':[obj['dimensions_mm'][k] for k in ('length','width','height')],
                'mass_kg':obj['mass_kg'],'max_top_load_kg':obj['top_load_limit_kg_synthetic'],'stackable':obj['stackable']}
        public_state={'container':{k:state['container'][k] for k in ('length_mm','width_mm','max_height_mm','max_payload_kg')},
            'buffer':[item(x['item']) for x in state['pending_items']],
            'placed_objects':[item(x)|{'pose':x['pose'],'oriented_size_mm':x['oriented_size_mm'],
                'area_current_top_load_kg':x['supported_load_kg'],
                'area_remaining_top_load_kg':x['top_load_limit_kg_synthetic']-x['supported_load_kg']} for x in state['placed_items']]}
        directory=out/f'D{len(index):04d}';write(directory/'pool.json',pool);write(directory/'prefix.json',public_state)
        def public_ref(path):
            return {'path':path.relative_to(out).as_posix(),'sha256':ref(path)['sha256'],'pointer':''}
        mapping=[{'label':k,'candidate_id':v['candidate_id'],'candidate_digest':v['candidate_digest']} for k,v in ctx['display_mapping'].items()]
        chosen=next(c for c in pool if c['candidate_id']==selected['selected_candidate_id'])
        rows=[r for r in ledger if r['decision_id']==e['decision_id']]
        probability=None
        if selected['source']!='singleton':
            require(len(rows)==1 and rows[0]['selection']==selected,'jm13_public_request_binding')
            transport=rows[0]['transport']
            from .transport import validate_transport
            validate_transport(transport)
            require(transport['raw_sha256']==selected['raw_response_digest'],'jm13_public_raw_binding')
            probability={'protocol':'jev_systemone_choice_native_v1','origin':'CONSTRUCTED_ONLY' if ex['config']['jm_mode']=='CONSTRUCTED_ONLY' else 'SAVED_REAL_RESPONSE_NOT_EXECUTION_ADMISSION',
                'raw_base64':transport['raw_body_b64'],'raw_sha256':transport['raw_sha256']}
        record={'version':sampling.JM_SAMPLING_VERSION,
            'evidence_scope':'CONSTRUCTED_ONLY' if ex['config']['jm_mode']=='CONSTRUCTED_ONLY' else 'SAVED_PUBLIC_ONLY_NOT_EXECUTION_ADMISSION',
            'task_id':ex['task']['task_id'],'source_group':ex['task']['source_group_id'],'decision_id':e['decision_id'],
            'decision_ordinal':int(e['decision_id'].rsplit('_D',1)[1]),'prefix_ref':public_ref(directory/'prefix.json'),
            'pool_ref':public_ref(directory/'pool.json'),'public_state':public_state,
            'pool':[{k:copy.deepcopy(c[k]) for k in ('candidate_id','pick_item_id','pose','oriented_size_mm')}|
                    {'candidate_digest':digest(c),'frozen_candidate':copy.deepcopy(c)} for c in pool],
            'display_mapping':mapping,'original':{'label':selected['selected_display_id'],'candidate_id':chosen['candidate_id'],
                'exact_action_digest':sampling.exact_digest(chosen)},'probability_evidence':probability}
        sampling.validate_public(record);sampling.validate_saved_evidence(record,root=out)
        write(directory/'public.json',record)
        entry.update(status='PUBLIC_SAVED',public_ref=public_ref(directory/'public.json'));index.append(entry)
        audit.append({'public_digest':digest(record),'execution_digest':digest(ex),'private_activation_ref':ref(root/'activation.json'),
            'private_last_checkpoint_ref':ref(sorted((root/'stages').glob('*.json'))[-1]),'event_index':event_index,
            'candidate_pool_digest':digest(pool),'mapping_digest':digest(ctx['display_mapping']),
            'request_ledger_ref':ref(root/'ledger/requests.json') if rows else None})
    write(out/'index.json',{'version':'jev_jm_v13_public_export_v1','scope':'SAVED_FACTS_ONLY_NOT_COLLECTION_ADMISSION',
        'decisions':index,'all_saved_context_decisions':len(index),'real_epsilon':'NOT_MATERIALIZED','dispatches':0})
    write(out/'private_audit.json',{'version':'jev_jm_v13_projection_audit_v1','audit_only_never_sampler_input':True,'bindings':audit})
    return read(out/'index.json')


def counts(ex,cp,rows):
    selections=[e['selection'] for e in cp['events'] if e.get('selection')]
    return {'version':'jev_jm_v13_counts_v1','mode':ex['config']['jm_mode'],'allocation_id':ex['allocation_id'],
        'max_sends':ex['max_sends'],'requests':sum(r['send_started'] for r in rows),
        'unknown_sends':sum(r['state']=='UNKNOWN_SEND' for r in rows),
        'forced_actions':sum(s['source']=='FORCED_FROM_FROZEN_POOL' for s in selections),
        'singleton_actions':sum(s['source']=='singleton' for s in selections),
        'commits':sum(e['event']=='PLACE' for e in cp['events']),
        'real_service_validation':'NOT_RUN' if ex['config']['jm_mode']=='CONSTRUCTED_ONLY' else 'EXTERNAL_PERMIT_SCOPE'}


def freeze_schedule(executions,*,root,global_max_sends):
    schedule=seal({'version':'jev_jm_v13_schedule_v1','storage_root':str(Path(root).resolve()),
        'executions':copy.deepcopy(executions),'global_max_sends':global_max_sends})
    validate_schedule(schedule)
    return schedule


def validate_schedule(schedule):
    validate_schema('jm_v13_schedule',schedule);check_seal(schedule)
    root=Path(schedule['storage_root']).resolve();keys=set();locations=set();allocations=set()
    for ex in schedule['executions']:
        validate_execution(ex)
        key=(ex['job_id'].rsplit('_',1)[0],ex['repeat_slot']);location=Path(ex['storage_root']).resolve()
        require(key not in keys and location not in locations and ex['allocation_id'] not in allocations,'jm13_duplicate_schedule_slot')
        require(location!=root and location.is_relative_to(root),'jm13_schedule_storage_scope')
        keys.add(key);locations.add(location);allocations.add(ex['allocation_id'])
    require(schedule['global_max_sends']==sum(ex['max_sends'] for ex in schedule['executions']),'jm13_schedule_budget_sum')


def run_scheduled(schedule,*,allocation_id,transport,permit=None,on_checkpoint=None,ledger_hook=None):
    """Run exactly one registered slot; no loop, new task selection or budget reuse."""
    validate_schedule(schedule);root=Path(schedule['storage_root']);root.mkdir(parents=True,exist_ok=True)
    matches=[ex for ex in schedule['executions'] if ex['allocation_id']==allocation_id]
    require(len(matches)==1,'jm13_unregistered_schedule_slot')
    with exclusive(root):
        anchor=root/'schedule.json'
        if anchor.exists():require(read(anchor)==schedule,'jm13_schedule_anchor_changed')
        else:
            require(not any(p.name!='.writer.lock' for p in root.iterdir()),'jm13_missing_schedule_anchor')
            write(anchor,schedule)
        for ex in schedule['executions']:
            ledger=Path(ex['storage_root'])/'ledger/requests.json'
            if ledger.exists():
                saved=validate_saved_execution(ex['storage_root'],expected_execution=ex)
                stopped=any(s in ('UNKNOWN_SEND','SENDING','FAILED') for s in saved['states']) or saved['checkpoint']['reason'] not in (None,'ALL_ITEMS_PLACED','STOP_NO_PHYSICAL_CANDIDATE','PREDICTED_STATIC_INSTABILITY','STABILITY_UNASSESSABLE')
                require(not stopped or ex['allocation_id']==allocation_id,'jm13_batch_technical_stop')
        return run_execution(matches[0],root=matches[0]['storage_root'],transport=transport,permit=permit,
            on_checkpoint=on_checkpoint,ledger_hook=ledger_hook)


def validate_send_permit(ex,permit):
    if ex['config']['jm_mode']=='CONSTRUCTED_ONLY':
        require(permit is None,'jm13_constructed_permit_forbidden')
        return
    require(permit is not None,'jm13_remote_send_not_authorized')
    value=load_ref(permit)
    require(value=={'version':'jev_jm_v13_send_permit_v1','execution_digest':digest(ex),
                   'allocation_id':ex['allocation_id'],'max_sends':ex['max_sends'],'authorized':True},
            'jm13_send_permit_changed')


def validate_transport_binding(ex,transport):
    expected='test_double' if ex['config']['jm_mode']=='CONSTRUCTED_ONLY' else 'jev'
    require(transport is not None and transport.origin==expected and callable(getattr(transport,'complete',None)),
            'jm13_transport_mode_changed')
    if expected=='test_double':
        require(getattr(transport,'scope',None)=='CONSTRUCTED_FAKE_TRANSPORT','jm13_constructed_transport_scope')
    else:
        require(getattr(transport,'config',None)==ex['config'],'jm13_injected_transport_config_changed')
