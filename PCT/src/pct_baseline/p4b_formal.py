"""Formal v2 job admission, selector, durable observers and public episode bridge.

No alternate physical engine. Interrupted calls are UNKNOWN, never counted as
successful calls or silently retried. Historical v1 modules remain read-only.
"""
import copy
import math
import time
from collections import Counter
from pathlib import Path
from .contracts import digest, require, read, sha
from .p4b_storage import Store, seal
from .p4b_runtime import StageJournal
from .p4b_protocol import VERSION
from . import p4b_rng as rng

EXECUTION='pct_p4b_execution_v2'


def current_identity():
    from .execution import source_identity
    from .p3_runtime import environment
    return {'source':source_identity(),'environment':environment()}


def admission(receipt,identity,free_bytes):
    require(isinstance(receipt,dict) and set(receipt)=={'accepted_identity','resources','authorization'},'P4B_ADMISSION_FIELDS')
    accepted=receipt['accepted_identity'];resources=receipt['resources'];auth=receipt['authorization']
    require(isinstance(accepted,dict) and set(accepted)=={'status','identity'} and
            accepted['status']=='ACCEPTED' and accepted['identity']==identity,'P4B_ACCEPTED_IDENTITY_REQUIRED')
    from .p4b_storage import FALLBACK
    require(isinstance(resources,dict) and set(resources)=={'status','identity','required_free_bytes'} and
            resources['status']=='ACCEPTED' and resources['identity']==identity and
            type(resources['required_free_bytes']) is int and resources['required_free_bytes']>=FALLBACK and
            free_bytes>=resources['required_free_bytes'],'P4B_RESOURCE_GATE')
    require(isinstance(auth,dict) and set(auth)=={'status','identity','scope','authorization_id'} and
            auth['status']=='AUTHORIZED' and auth['identity']==identity and auth['scope']=='FORMAL_TRAINING' and
            type(auth['authorization_id']) is str and bool(auth['authorization_id']),'P4B_AUTHORIZATION_REQUIRED')
    return digest(receipt)


def build_config(task,method,formal,policy,receipt,*,slot,model_spec):
    from importlib.resources import files
    import json
    from .execution import strategy_identity
    from semantic_pallet_planner.jev_select.packaging_runtime import physical_manifest
    from semantic_pallet_planner.jev_select.stability.monitor import exact_freeze
    from semantic_pallet_planner.jev_select.contracts import validate_schema
    require(method in ('pct_geo_b1','pct_load_b1'),'P4B_METHOD')
    validate_slot(formal,slot,model_spec,task,method)
    c=json.loads(files('semantic_pallet_planner.jev_select').joinpath('configs/packaging_runtime_v4.json').read_text())
    monitor=exact_freeze()
    c.update(version=VERSION,model=None,buffer_capacity=1,selector=method,stability_monitor=monitor,
             execution_spec_digest=task['execution_spec_digest'],model_identity=policy,
             formal_descriptor=formal['seal'],attempt_slot_digest=digest(slot),policy_snapshot=policy,admission_digest=digest(receipt),formal_mode='training',
             runtime_identity={'data_identity':task['parent_data_identity'],'task_identity':digest(task),
             'physical_identity':digest(physical_manifest()),'strategy_identity':strategy_identity(method),'monitor_identity':digest(monitor)})
    validate_schema('config',c);return c


def validate_slot(formal,slot,model_spec,task,method):
    require(formal['seal']==digest({k:v for k,v in formal.items() if k!='seal'}) and model_spec in formal['models'],'P4B_FORMAL_DESCRIPTOR_DRIFT')
    schedule=next(s['attempts'] for s in formal['schedules'] if s['model_id']==model_spec['model_id'])
    i=slot['attempt_index']
    require(type(i) is int and 0<=i<2000 and len(schedule)==2000 and schedule[i]==slot and
            slot['batch_id']==i//8 and model_spec['method']==method and
            slot['task_digest']==digest(task) and slot['task_id']==task['task_id'],'P4B_FROZEN_SLOT_DRIFT')


def preflight(config):
    from semantic_pallet_planner.jev_select.contracts import validate_schema
    from semantic_pallet_planner.jev_select.stability.monitor import exact_freeze
    from semantic_pallet_planner.jev_select.packaging_runtime import physical_manifest
    from .execution import strategy_identity
    import torch
    validate_schema('config',config)
    require(config['stability_monitor']==exact_freeze(),'P4B_MONITOR_DRIFT')
    require(config['model_identity']==config['policy_snapshot'],'P4B_MODEL_POLICY_DRIFT')
    require(config['runtime_identity']['physical_identity']==digest(physical_manifest()) and
            config['runtime_identity']['monitor_identity']==digest(config['stability_monitor']) and
            config['runtime_identity']['strategy_identity']==strategy_identity(config['selector']),'P4B_RUNTIME_DRIFT')
    require(torch.get_num_threads()==1 and torch.are_deterministic_algorithms_enabled(),'P4B_DETERMINISM')


def public_compatibility(config):
    from semantic_pallet_planner.jev_select.packaging_runtime import is_packaging
    from semantic_pallet_planner.jev_select.stability.monitor import is_monitored
    require(is_packaging(config) and is_monitored(config),'P4B_PUBLIC_CAPABILITY_MISSING')


class Session:
    """Immutable operation start/result + session start/end; unresolved ops stop."""
    def __init__(self,store,journal):
        self.store=store;self.journal=journal;self.values={v['key']:v['record'] for v in store.records()}
        starts={k for k in self.values if k.startswith('op-start-')}
        require(all(k.replace('op-start-','op-end-',1) in self.values for k in starts),'P4B_OPERATION_OUTCOME_UNKNOWN')
        require(all(self.values[k.replace('op-start-','op-end-',1)]['state']=='RETURNED' for k in starts),'P4B_PREVIOUS_OPERATION_FAILED_NO_RETRY')
        require(not any(k.startswith('session-end-') and v.get('status')=='TECHNICAL_FAILURE' for k,v in self.values.items()),'P4B_JOB_STOPPED')
        self.rng_binding={'store_identity':store.identity,'contract':rng.VERSION}
        self.rng_consumer=rng.Consumer()
        self._resume_rng(journal)
        self.sid=sum(k.startswith('session-start-') for k in self.values)
        self.counts=Counter();self.next_op=len(starts);self.reused=set()
        self.start=journal.session();self.initial=journal.checkpoint
        self.save(f'session-start-{self.sid:06d}',{'version':EXECUTION,'resume':self.start,'rng_contract':rng.VERSION,'start_rng_digest':digest(rng.capture()),
                  'rng_resume_reference':journal.rows[-1]['rng']['seal'] if journal.rows else self.values['rng-entry']['seal'],'started':time.time()})
        self.wall=time.perf_counter()
        for previous in range(self.sid):
            if f'session-end-{previous:06d}' not in self.values:
                self.save(f'session-end-{previous:06d}',{'version':EXECUTION,'status':'INTERRUPTED',
                     'counts':'UNKNOWN_USE_OPERATION_AND_WAL_RECORDS','recovered_by_session':self.sid})

    def save(self,key,row):
        result=self.store.append(row,key=key);self.values[key]=copy.deepcopy(row);return result

    def _resume_rng(self,journal):
        entry=self.values.get('rng-entry')
        if entry is None:
            require(not journal.rows and not any(k.startswith(('session-','op-','selection-','job-result')) for k in self.values),
                    'P4B_RNG_LEGACY_JOB')
            state=rng.capture()
            entry=rng.envelope(state,state,binding=self.rng_binding,owner={'boundary':'job-entry'},result={'store':digest(self.store.identity)})
            self.save('rng-entry',entry)
        rng.validate(entry,binding=self.rng_binding,owner={'boundary':'job-entry'},result={'store':digest(self.store.identity)})
        known={digest(entry['post'])};tail=entry['post']
        for i,row in enumerate(journal.rows):
            require(row['version']==rng.WAL and 'rng' in row,'P4B_RNG_LEGACY_WAL')
            rng.validate(row['rng'],binding=self.rng_binding,
                owner={'sequence':i,'phase':row['checkpoint']['phase'],'previous':row['previous']},
                result={'checkpoint':row['checkpoint'],'events':row['events']})
            known.add(digest(row['rng']['post']));tail=row['rng']['post']
        for key,row in self.values.items():
            if key.startswith('op-end-'):
                require(row.get('version')=='pct_p4b_operation_v3' and 'rng' in row,'P4B_RNG_LEGACY_OPERATION')
                start=self.values[key.replace('op-end-','op-start-',1)]
                owner={'operation':int(key[len('op-end-'):]),'kind':row['kind'],'request':start['owner']}
                self.validate_result(row,owner)
                require(row['rng']['pre']==start['rng_pre'],'P4B_RNG_OPERATION_PRE_DRIFT')
                known.add(digest(row['rng']['post']))
            if key=='job-result':
                self.validate_result(row,{'boundary':'job-result'})
                known.add(digest(row['rng']['post']))
        require(digest(rng.capture()) in known,'P4B_RNG_JOB_ENTRY_DRIFT')
        rng.restore(tail);journal.rng_binding=self.rng_binding

    def validate_result(self,row,owner):
        require('rng' in row,'P4B_RNG_RESULT_MISSING')
        return rng.validate(row['rng'],binding=self.rng_binding,owner=owner,
                            result={k:v for k,v in row.items() if k!='rng'})

    def pack_result(self,row,owner,pre):
        result=copy.deepcopy(row)
        result['rng']=rng.envelope(pre,rng.capture(),binding=self.rng_binding,owner=owner,result=row)
        return result

    def consume_result(self,row,owner):
        self.validate_result(row,owner)
        if row['rng']['seal'] in self.rng_consumer.consumed:
            # Re-reading the same result is idempotent only at exactly its post
            # position. It must not rewind randomness consumed by later work.
            require(digest(rng.capture())==digest(row['rng']['post']),'P4B_RNG_DUPLICATE_CONSUMPTION')
            return False
        self.rng_consumer.advance(row['rng'],binding=self.rng_binding,owner=owner,
                                  result={k:v for k,v in row.items() if k!='rng'})
        self.counts['rng_post_consumptions']+=1
        return True

    def call(self,kind,fn,*,owner=None):
        if owner is not None:
            matches=[(k,v) for k,v in self.values.items() if k.startswith('op-start-') and v.get('owner')==owner]
            require(len(matches)<=1,'P4B_RNG_AMBIGUOUS_OPERATION')
            if matches:
                key,start=matches[0];require(start['kind']==kind,'P4B_RNG_OPERATION_KIND_DRIFT')
                i=int(key[len('op-start-'):]);end=self.values.get(f'op-end-{i:08d}')
                require(end is not None and end['state']=='RETURNED','P4B_OPERATION_OUTCOME_UNKNOWN')
                self.consume_result(end,{'operation':i,'kind':kind,'request':owner})
                self.reuse('operation_result_reuses',str(i));return copy.deepcopy(end['result'])
        i=self.next_op;self.next_op+=1;pre=rng.capture()
        self.save(f'op-start-{i:08d}',{'version':'pct_p4b_operation_v3','session':self.sid,'kind':kind,
                  'state':'INTENT','owner':owner,'rng_pre':pre})
        self.counts[kind+'_calls']+=1
        started=time.perf_counter()
        try:result=fn()
        except BaseException as exc:
            self.save(f'op-end-{i:08d}',{'session':self.sid,'kind':kind,'state':'FAILED','error':type(exc).__name__})
            self.counts[kind+'_failures']+=1;raise
        row={'version':'pct_p4b_operation_v3','session':self.sid,'kind':kind,'state':'RETURNED',
             'result':copy.deepcopy(result),'elapsed_s':time.perf_counter()-started}
        row=self.pack_result(row,{'operation':i,'kind':kind,'request':owner},pre)
        self.save(f'op-end-{i:08d}',row)
        self.counts[kind+'_returns']+=1;return result

    def reuse(self,kind,did):
        if (kind,did) in self.reused:return
        self.save(f'consume-{self.sid:06d}-{len(self.reused):06d}',{'session':self.sid,'kind':kind,'decision_id':did})
        self.reused.add((kind,did));self.counts[kind]+=1

    def observe(self,cp):
        # Only count callback facts after durable publication. Startup planned
        # reuse does not count until a successor checkpoint proves consumption.
        old=self.journal.checkpoint
        self.journal(cp)
        if old==cp:return
        phase=cp['phase'];self.counts['persisted_'+phase]+=1
        initial=self.initial
        if initial and cp!=initial:
            did=(initial.get('pending_event') or {}).get('decision_id')
            if initial['phase'] in ('SELECTED','MONITORED'):
                self.reuse('saved_selection_reuses',did)
            if initial['phase']=='MONITORED':self.reuse('saved_monitor_reuses',did)
            if initial['phase']=='COMMITTED':self.reuse('saved_committed_reuses',did)
        if phase=='MONITORED':self.counts['monitor_returns_confirmed']+=1
        if phase=='COMMITTED':self.resolve_commit(cp)

    def before_commit(self,event):
        did=event['decision_id']
        self.save('commit-intent-'+did,{'version':'pct_p4b_commit_v2','decision_id':did,
              'before':digest(event['before']),'selection':digest(event['selection'])})
        self.counts['commit_dispatch_intents']+=1

    def resolve_commit(self,cp):
        event=cp['pending_event'];key='commit-intent-'+event['decision_id']
        require(key in self.values,'P4B_COMMIT_WITHOUT_INTENT')
        row=self.values[key]
        require(row['before']==digest(event['before']) and row['selection']==digest(event['selection']),'P4B_COMMIT_INTENT_DRIFT')
        done='commit-done-'+event['decision_id']
        if done not in self.values:self.save(done,{'checkpoint':digest(cp)})
        self.counts['commit_returns_confirmed']+=1

    def recover_commits(self):
        for key in list(self.values):
            if key.startswith('commit-intent-') and key.replace('commit-intent-','commit-done-',1) not in self.values:
                cp=self.journal.checkpoint
                require(cp is not None and cp['phase']=='COMMITTED' and
                        cp['pending_event']['decision_id']==key[len('commit-intent-'):],'P4B_COMMIT_OUTCOME_UNKNOWN')
                self.resolve_commit(cp)

    def save_job_result(self,checkpoint,summary):
        require(self.journal.rows and self.journal.checkpoint==checkpoint,'P4B_RESULT_CHECKPOINT_DRIFT')
        pre=self.journal.rows[-1]['rng']['post']
        self.save('job-result',self.pack_result({'version':'pct_p4b_job_result_v3',
                  'checkpoint':digest(checkpoint),'summary':summary},{'boundary':'job-result'},pre))

    def saved_job_result(self,checkpoint,job_id):
        saved=self.values['job-result']
        require(checkpoint and digest(checkpoint)==saved['checkpoint'],'P4B_RESULT_DRIFT')
        self.consume_result(saved,{'boundary':'job-result'})
        self.reuse('saved_episode_result_reuses',job_id)
        return saved

    def finish(self,status,error=None):
        self.save(f'session-end-{self.sid:06d}',{'version':EXECUTION,'status':status,'error':error,
                  'counts':dict(self.counts),'durable_counts':dict(self.journal.counts),
                  'monitor_calls':({'confirmed':self.counts['monitor_returns_confirmed'],
                    'unresolved_dispatch_intents':max(0,self.counts['monitor_dispatch_intents']-self.counts['monitor_returns_confirmed']),
                    'exact_total':'UNKNOWN' if self.counts['monitor_dispatch_intents']!=self.counts['monitor_returns_confirmed'] else self.counts['monitor_returns_confirmed']}),
                  'planned_reuses':self.start['planned_reuses'],'elapsed_s':time.perf_counter()-self.wall,
                  'end_checkpoint':digest(self.journal.checkpoint),'rng_contract':rng.VERSION,
                  'end_rng_digest':digest(rng.capture()),'rng_consumed_references':sorted(self.rng_consumer.consumed)})


class Selector:
    def __init__(self,config,core,session):
        self.config=copy.deepcopy(config);self.core=core;self.session=session;self.bound=None
        from . import geo_encoding,load_encoding
        self.encoding=geo_encoding if config['selector']=='pct_geo_b1' else load_encoding
        self.encode=self.encoding.encode_geometry if config['selector']=='pct_geo_b1' else self.encoding.encode_load
        from .p4b_state import tensor_digest
        require(tensor_digest(core)==config['policy_snapshot'],'P4B_POLICY_DRIFT')

    def bind(self,event,*,compute_singleton=True):
        from semantic_pallet_planner.jev_select.contracts import DecisionContext
        from semantic_pallet_planner.jev_select.context import validate_context
        ctx=DecisionContext.from_dict(event['context']);validate_context(ctx,config=self.config)
        e=self.encode(ctx);candidates=event['bundle']['selectable_candidates']
        require(digest(candidates)==ctx.data['local_binding']['physical_digest']==ctx.data['local_binding']['selectable_digest'],'P4B_POOL_DRIFT')
        self.bound=(ctx,e,self.encoding.verify_candidates(e,candidates))
        if compute_singleton and e.data['candidate_count']==1:self.record(ctx,event['decision_id'])

    def validate_saved(self,event):
        if event.get('selection') is None:return
        from semantic_pallet_planner.jev_select.contracts import DecisionContext
        from semantic_pallet_planner.jev_select.selector import SelectionResult
        from .p4b_protocol import validate_selection
        ctx=DecisionContext.from_dict(event['context']);e=self.encode(ctx)
        by_id=self.encoding.verify_candidates(e,event['bundle']['selectable_candidates'])
        key='selection-'+event['decision_id'];require(key in self.session.values,'P4B_SAVED_RECORD_MISSING')
        row=self.session.values[key]
        require(row['version']=='pct_p4b_selection_v3' and row['policy']==self.config['policy_snapshot'] and
                row['context_digest']==digest(ctx.data) and row['encoding']==e.data and
                row['selection']==event['selection'],'P4B_SAVED_RECORD_DRIFT')
        self.session.validate_result(row,{'decision':event['decision_id'],'context':digest(ctx.data),'policy':self.config['policy_snapshot']})
        output=row['output'];i=output['leaf_index'];mapped=e.resolve(i)
        require(row['exact_candidate']==by_id[mapped['candidate_id']] and
                event['selection']['selected_candidate_id']==mapped['candidate_id'],'P4B_SAVED_ACTION_DRIFT')
        p=output['probabilities'];n=e.data['candidate_count']
        require(len(p)==16 and all(math.isfinite(v) and 0<=v<=1 for v in p) and abs(sum(p)-1)<1e-5 and
                all(v==0 for v in p[n:]) and p[i]>0 and math.isfinite(output['value']),'P4B_SAVED_OUTPUT_DRIFT')
        validate_selection(ctx,SelectionResult.from_dict(event['selection']),self.config)

    def select(self,context,*,decision_id):return self.record(context,decision_id)

    def record(self,ctx,did):
        import torch
        from .p4b_state import tensor_digest
        from semantic_pallet_planner.jev_select.selector import result,SelectionResult
        from .p4b_protocol import validate_selection
        require(self.bound and self.bound[0].data==ctx.data,'P4B_UNBOUND')
        _,e,by_id=self.bound;singleton=e.data['candidate_count']==1
        require(tensor_digest(self.core)==self.config['policy_snapshot'],'P4B_POLICY_DRIFT')
        key='selection-'+did;session=self.session
        if key in session.values:
            r=session.values[key]
            require(r['version']=='pct_p4b_selection_v3' and r['context_digest']==digest(ctx.data) and
                    r['policy']==self.config['policy_snapshot'] and r['encoding']==e.data,'P4B_SELECTION_RECORD_DRIFT')
            selected=SelectionResult.from_dict(r['selection']);validate_selection(ctx,selected,self.config)
            require(r['exact_candidate']==by_id[selected.data['selected_candidate_id']],'P4B_SELECTION_ACTION_DRIFT')
            session.consume_result(r,{'decision':did,'context':digest(ctx.data),'policy':self.config['policy_snapshot']})
            session.reuse('selection_record_reuses',did);return selected
        decision_owner={'decision':did,'context':digest(ctx.data),'policy':self.config['policy_snapshot']}
        rng_key='decision-rng-'+did
        if rng_key in session.values:
            decision_rng=session.values[rng_key]
            rng.validate(decision_rng,binding=session.rng_binding,owner=decision_owner,result={'boundary':'decision-pre'})
            # Session restored the saved WAL; a completed operation, when
            # present, owns post-state advancement and is reused below.
            require(rng.capture()==decision_rng['pre'],'P4B_RNG_DECISION_PRE_DRIFT')
        else:
            before=rng.capture()
            decision_rng=rng.envelope(before,before,binding=session.rng_binding,owner=decision_owner,result={'boundary':'decision-pre'})
            session.save(rng_key,decision_rng)
        def forward():
            with torch.no_grad():
                _,index,entropy,hidden,dist=self.core.actor(e.tensor(),deterministic=singleton,normFactor=1,evaluate=True)
                value=self.core.critic(hidden)
            return {'probabilities':dist.probs[0].tolist(),'value':float(value.item()),
                    'leaf_index':0 if singleton else int(index.item()),'entropy':float(entropy.item())}
        output=session.call('singleton_critic' if singleton else 'policy_choice',forward,owner=decision_owner)
        p=output['probabilities'];i=output['leaf_index'];n=e.data['candidate_count']
        require(len(p)==16 and all(math.isfinite(x) and 0<=x<=1 for x in p) and
                abs(sum(p)-1)<1e-5 and all(x==0 for x in p[n:]) and math.isfinite(output['value']),'P4B_NONFINITE_OUTPUT')
        row=e.resolve(i);require(p[i]>0,'P4B_INVALID_CHOICE')
        value=result(ctx,status='singleton' if singleton else 'selected',source='singleton' if singleton else 'local_baseline',label=row['display_label']).data
        if not singleton:value.update(source='pct_local',probabilities={r['display_label']:p[r['leaf_index']] for r in e.data['mapping']},
                    confidence=p[i],inference_receipt={'feature_digest':e.data['feature_digest'],'weights_sha256':self.config['policy_snapshot'],
                    'leaf_index':i,'inference_s':0.0})
        # Actual measured forward duration is in op-end; no fabricated latency.
        if not singleton:value['inference_receipt']['inference_s']=next(v['elapsed_s'] for k,v in session.values.items() if k.startswith('op-end-') and
            session.values[k.replace('op-end-','op-start-',1)]['owner']==decision_owner)
        selected=SelectionResult.from_dict(value);validate_selection(ctx,selected,self.config)
        selection_row={'version':'pct_p4b_selection_v3','policy':self.config['policy_snapshot'],
                     'context_digest':digest(ctx.data),'encoding':e.data,'output':output,
                     'selection':value,'exact_candidate':by_id[row['candidate_id']]}
        session.save(key,session.pack_result(selection_row,decision_owner,decision_rng['pre']))
        session.counts['selection_results_persisted']+=1;return selected


def admit_execution(task,selector,config,*,execution,job_id,method,resume,on_checkpoint,
                    expected_events,training_fork,memory_snapshot,memory_view,memory_driver):
    require(isinstance(on_checkpoint,JobSink) and on_checkpoint.store.lock.stream is not None,'P4B_LOCKED_SINK')
    h=on_checkpoint.header
    validate_slot(on_checkpoint.formal,on_checkpoint.slot,on_checkpoint.model_spec,task,method)
    require(config['formal_descriptor']==on_checkpoint.formal['seal'] and
            config['attempt_slot_digest']==digest(on_checkpoint.slot),'P4B_FROZEN_DESCRIPTOR_BINDING')
    require(h['identity']==current_identity(),'P4B_SOURCE_ENV_DRIFT')
    admission(on_checkpoint.receipt,h['identity'],on_checkpoint.store.free())
    preflight(config);public_compatibility(config)
    require(all(v is None for v in (expected_events,training_fork,memory_snapshot,memory_view,memory_driver)),'P4B_NO_REMOTE_FORK_MEMORY')
    require(execution=={'version':EXECUTION,'header_digest':digest(h)} and h['task']==task and
            h['config']==config and h['job_id']==job_id and method==config['selector'],'P4B_EXECUTION_BINDING')
    require(config['runtime_identity']['task_identity']==digest(task) and
            config['runtime_identity']['data_identity']==task['parent_data_identity'] and
            config['execution_spec_digest']==task['execution_spec_digest'],'P4B_TASK_BINDING')
    require(isinstance(selector,Selector) and selector.config==config and resume==on_checkpoint.session.journal.checkpoint,'P4B_RESUME_BINDING')


class JobSink:
    def __init__(self,store,header,receipt,*,formal,slot,model_spec):
        self.store=store;self.header=header;self.receipt=receipt
        self.formal=formal;self.slot=slot;self.model_spec=model_spec
        journal=StageJournal(store);self.session=Session(store,journal);self.session.recover_commits()
    def __call__(self,cp):self.session.observe(cp)


def run_job(root,task,config,core,receipt,*,formal,slot,model_spec):
    validate_slot(formal,slot,model_spec,task,config['selector'])
    require(config['attempt_slot_digest']==digest(slot) and config['formal_descriptor']==formal['seal'],'P4B_FROZEN_DESCRIPTOR_BINDING')
    identity=current_identity();require(config['admission_digest']==digest(receipt),'P4B_ADMISSION_DRIFT')
    # Guard before touching a model or dispatching candidate/monitor work.
    import shutil
    root=Path(root);existing=root if root.exists() else root.parent
    admission(receipt,identity,shutil.disk_usage(existing).free)
    preflight(config);public_compatibility(config)
    header={'version':EXECUTION,'rng_contract':rng.VERSION,'identity':identity,'task':task,'config':config,'job_id':root.name}
    with Store(root,{'header':digest(header)},reserve=receipt['resources']['required_free_bytes']) as store:
        records={r['key']:r['record'] for r in store.records()}
        if 'header' in records:require(records['header']==header,'P4B_HEADER_DRIFT')
        else:store.append(header,key='header')
        sink=JobSink(store,header,receipt,formal=formal,slot=slot,model_spec=model_spec);session=sink.session;selector=Selector(config,core,session)
        cp=session.journal.checkpoint
        if cp:
            for event in cp['events']+([cp['pending_event']] if cp['pending_event'] else []):selector.validate_saved(event)
        def hook(phase,value):
            if phase=='decision_ready':
                saved=cp is not None and cp['phase'] in ('SELECTED','MONITORED') and cp['pending_event']['decision_id']==value['decision_id']
                if not saved:selector.bind(value)
            if phase=='after_selected_checkpoint' or (phase=='decision_ready' and cp is not None and cp['phase']=='SELECTED'):
                session.counts['monitor_dispatch_intents']+=1
            if phase=='before_commit':session.before_commit(value)
        try:
            if 'job-result' in session.values:
                saved=session.saved_job_result(cp,header['job_id']);session.finish('SAVED_RESULT_REUSED')
                return {'checkpoint':cp,'events':cp['events'],'final_state':cp['state'],'summary':saved['summary']},session.values
            from semantic_pallet_planner.jev_select.episode import run_episode
            ep=run_episode(task,selector,config,job_id=root.name,method=config['selector'],resume=cp,on_checkpoint=sink,
                           hook=hook,extension_execution={'version':EXECUTION,'header_digest':digest(header)})
            session.save_job_result(ep['checkpoint'],ep['summary'])
            session.finish('FINISHED');return ep,session.values
        except BaseException as exc:
            session.finish('TECHNICAL_FAILURE',{'type':type(exc).__name__,'detail':str(exc)[:300]});raise
