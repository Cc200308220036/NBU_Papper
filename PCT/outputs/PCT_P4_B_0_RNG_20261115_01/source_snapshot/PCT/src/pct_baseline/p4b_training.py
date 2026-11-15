"""Formal frozen-schedule controller, A2C collection and transactional updates.

Only explicit launch admission can dispatch production work. Testable batch
orchestration takes synthetic callbacks; it is not a physical order engine.
"""
import copy
import math
from pathlib import Path
from .contracts import digest, require
from .p4b_storage import Store, seal, checked
from .p4b_state import tensor_digest, save_initial, save_update, load
from .p4b_formal import admission, current_identity, build_config, run_job
from . import p4b_rng as rng

VERSION='pct_p4b_training_v2'
NATURAL={'ALL_ITEMS_PLACED':'COMPLETED','STOP_NO_PHYSICAL_CANDIDATE':'NATURAL_EMPTY_POOL',
         'PREDICTED_STATIC_INSTABILITY':'PREDICTED_STATIC_INSTABILITY'}


def formal_descriptor(plan,catalog,identity):
    from .p4a import validate_plan
    validate_plan('training',plan,catalog,plan['input_identity'],plan['build_spec'])
    return seal({'version':VERSION,'parent_plan':plan['plan_digest'],'identity':identity,
                 **{k:copy.deepcopy(plan[k]) for k in ('models','schedules','rules','denominators')}})


def initialize(method,seed):
    import random
    import numpy as np
    import torch
    from types import SimpleNamespace
    require(seed in (11,23,37) and method in ('pct_geo_b1','pct_load_b1'),'P4B_MODEL_SCOPE')
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
    if method=='pct_geo_b1':
        from .geo_model import ARCHITECTURE,PaddingSafeDRLGAT
        core=PaddingSafeDRLGAT(SimpleNamespace(**ARCHITECTURE))
    else:
        from .load_model import ARCHITECTURE,LoadDRLGAT
        core=LoadDRLGAT(SimpleNamespace(**ARCHITECTURE))
    core=core.cpu().float().eval()
    return core,torch.optim.Adam(core.parameters(),lr=1e-4)


def trajectory(ep,records):
    from .p3_training import committed_reward
    require(ep['checkpoint']['reason'] in NATURAL,'P4B_COLLECTION_TECHNICAL_FAILURE')
    transitions=[];c=ep['final_state']['container'];cv=c['length_mm']*c['width_mm']*c['max_height_mm']
    for ev in ep['events']:
        if ev.get('selection') is None:continue
        r=records['selection-'+ev['decision_id']]
        require(r['selection']==ev['selection'],'P4B_COLLECT_SELECTION_DRIFT')
        before=sum(math.prod(p['oriented_size_mm']) for p in ev['before']['placed_items'])
        after=sum(math.prod(p['oriented_size_mm']) for p in ev['after']['placed_items'])
        reward=committed_reward(before,after,cv)
        require((ev['event']=='PLACE')==(reward>0),'P4B_REWARD_COMMIT')
        transitions.append({'decision_id':ev['decision_id'],'context_digest':r['context_digest'],
                'selection':r['selection'],'monitor':ev['monitor'],'before':digest(ev['before']),'after':digest(ev['after']),
                'encoding':r['encoding'],'reward':reward,'choice':ev['route']=='CHOICE_REQUIRED',
                'leaf_index':r['output']['leaf_index'],'value':r['output']['value'],
                'probability':r['output']['probabilities'][r['output']['leaf_index']],
                'terminal':False,'truncated':False})
    if transitions:transitions[-1]['terminal']=True
    return transitions


def update_parameters(core,optimizer,trajectories):
    """Real gradient/step path: implemented, deliberately NOT_RUN in this unit."""
    import torch
    from .p3_training import segmented_targets,a2c_loss
    from .p4b_state import finite
    values=[];logps=[];targets=[];choices=[];entropies=[]
    for ts in trajectories:
        if not ts:continue
        require(ts[-1]['terminal'] and not ts[-1]['truncated'],'P4B_COMPLETE_ORDER_ONLY')
        target,_=segmented_targets(torch.tensor([t['reward'] for t in ts]),torch.tensor([t['value'] for t in ts]),terminal=True)
        targets.append(target)
        for t in ts:
            x=torch.tensor([t['encoding']['packed']],dtype=torch.float32)
            _,_,entropy,hidden,dist=core.actor(x,deterministic=True,normFactor=1,evaluate=True)
            value=core.critic(hidden).reshape(())
            probability=dist.probs[0,t['leaf_index']]
            require(bool(torch.isfinite(dist.probs).all()) and bool(probability>0) and
                    abs(float(value.detach())-t['value'])<1e-5 and
                    abs(float(probability.detach())-t['probability'])<1e-5,'P4B_BATCH_POLICY_DRIFT')
            values.append(value);logps.append(probability.log());choices.append(t['choice']);entropies.append(float(entropy.detach().item()))
    require(bool(values),'P4B_NO_UPDATE_EMPTY_BATCH')
    loss,actor,critic=a2c_loss(torch.stack(values),torch.stack(logps),torch.cat(targets),torch.tensor(choices))
    optimizer.zero_grad(set_to_none=True);loss.backward()
    require(all(p.grad is None or bool(torch.isfinite(p.grad).all()) for p in core.parameters()),'P4B_NONFINITE_GRADIENT')
    norm=torch.nn.utils.clip_grad_norm_(core.parameters(),.5,error_if_nonfinite=True)
    optimizer.step()
    require(finite(core.state_dict()) and finite(optimizer.state_dict()),'P4B_NONFINITE_POST_UPDATE')
    return {'transitions':len(values),'choices':sum(choices),'singleton':len(values)-sum(choices),
            'loss':float(loss.detach()),'actor':float(actor.detach()),'critic':float(critic.detach()),
            'entropy_mean':sum(entropies)/len(entropies),'gradient_norm':float(norm)}


class BatchController:
    """Common production/test orchestration; callbacks never generate physics here."""
    def __init__(self,store,schedule,policy):
        self.store=store;self.schedule=schedule;self.policy=policy
        self.records={r['key']:r['record'] for r in store.records()}
        self.stopped=any(k.startswith('stop-') for k in self.records)
        self.rng_batches_consumed=set()
        self.rng_counts={'actual_attempts':0,'saved_attempt_reuses':0,'rng_post_consumptions':0}

    def stop(self,batch,reason):
        self.stopped=True
        key=f'stop-{batch:04d}'
        if key not in self.records:
            value={'reason':reason,'batch':batch};self.store.append(value,key=key);self.records[key]=value

    def denominator(self):
        return [dict(slot,status=self.records.get(f'attempt-{slot["attempt_index"]:04d}',{}).get('status','NOT_RUN'))
                for slot in self.schedule]

    def update_denominator(self):
        rows={r['key']:r['record'] for r in self.store.records()}
        result=[]
        for i in range(1,251):
            status='NOT_RUN'
            if f'update-result-{i:04d}' in rows:status='COMPLETED'
            elif (self.store.root/f'updates/u{i:06d}').exists():status='INCOMPLETE_RESULT_SAVED_UPDATE'
            elif f'optimizer-intent-{i:04d}' in rows:status='INCOMPLETE_UNKNOWN_OUTCOME'
            elif f'stop-{i-1:04d}' in rows:
                status='NO_UPDATE' if 'NO_UPDATE_EMPTY_BATCH' in rows[f'stop-{i-1:04d}']['reason'] else 'TECHNICAL_FAILURE'
            result.append({'update_slot':i,'status':status})
        return result

    def batch(self,batch_id,collect,update,policy_digest):
        require(not self.stopped,'P4B_BATCH_STOPPED')
        slots=self.schedule[batch_id*8:batch_id*8+8]
        require(len(slots)==8 and all(s['batch_id']==batch_id for s in slots),'P4B_BATCH_SCHEDULE')
        require(not (self.store.root/f'updates/u{batch_id+1:06d}').exists() and
                f'optimizer-intent-{batch_id+1:04d}' not in self.records,'P4B_UPDATE_ALREADY_STARTED_NO_REAPPLY')
        require(batch_id not in self.rng_batches_consumed,'P4B_RNG_DUPLICATE_BATCH_CONSUMPTION')
        self.rng_batches_consumed.add(batch_id)
        policy=self.policy;require(policy_digest()==policy,'P4B_BATCH_POLICY_DRIFT')
        binding={'scheduled_policy_id':slots[0].get('policy_snapshot_id'),'tensor_digest':policy,'batch_id':batch_id,
                 'rng_contract':rng.VERSION}
        rng_binding={'store_identity':self.store.identity,'batch_binding':binding}
        key=f'batch-binding-{batch_id:04d}'
        existing=[f'attempt-{s["attempt_index"]:04d}' in self.records for s in slots]
        require(not any(existing[i] and not all(existing[:i]) for i in range(8)),'P4B_RNG_ATTEMPT_GAP')
        for slot in slots:
            saved=self.records.get(f'attempt-{slot["attempt_index"]:04d}')
            if saved is not None:
                require(saved.get('version')=='pct_p4b_attempt_result_v3' and 'rng' in saved,'P4B_RNG_LEGACY_ATTEMPT')
        if key in self.records:
            stored=self.records[key]
            require(stored.get('binding')==binding and 'rng_start' in stored,'P4B_RNG_LEGACY_OR_BINDING_DRIFT')
            rng.validate(stored['rng_start'],binding=rng_binding,owner={'boundary':'batch-start'},result=binding)
            require(rng.capture()==stored['rng_start']['pre'],'P4B_RNG_BATCH_START_DRIFT')
        else:
            require(not any(existing),'P4B_RNG_BATCH_START_MISSING')
            before=rng.capture();stored={'binding':binding,'rng_start':rng.envelope(before,before,
                    binding=rng_binding,owner={'boundary':'batch-start'},result=binding)}
            self.store.append(stored,key=key);self.records[key]=stored
        consumer=rng.Consumer()
        trajectories=[];refs=[]
        try:
            for slot in slots:
                key=f'attempt-{slot["attempt_index"]:04d}'
                owner={'attempt':slot['attempt_index'],'next_attempt':slot['attempt_index']+1,'slot_digest':digest(slot)}
                pre_key=f'attempt-pre-{slot["attempt_index"]:04d}'
                if key in self.records:
                    value=self.records[key]
                    require(value['slot_digest']==digest(slot) and value['policy']==policy,'P4B_ATTEMPT_DRIFT')
                    require(pre_key in self.records,'P4B_RNG_ATTEMPT_PRE_MISSING')
                    rng.validate(self.records[pre_key],binding=rng_binding,owner=owner,result={'boundary':'attempt-pre'})
                    require(value['rng']['pre']==self.records[pre_key]['pre'],'P4B_RNG_ATTEMPT_PRE_DRIFT')
                    consumer.advance(value['rng'],binding=rng_binding,owner=owner,result={k:v for k,v in value.items() if k!='rng'})
                    self.rng_counts['saved_attempt_reuses']+=1;self.rng_counts['rng_post_consumptions']+=1
                else:
                    pre=rng.capture()
                    if pre_key in self.records:
                        rng.validate(self.records[pre_key],binding=rng_binding,owner=owner,result={'boundary':'attempt-pre'})
                        require(pre==self.records[pre_key]['pre'],'P4B_RNG_ATTEMPT_ENTRY_DRIFT')
                    else:
                        saved_pre=rng.envelope(pre,pre,binding=rng_binding,owner=owner,result={'boundary':'attempt-pre'})
                        self.store.append(saved_pre,key=pre_key);self.records[pre_key]=saved_pre
                    self.rng_counts['actual_attempts']+=1
                    try:
                        value=collect(copy.deepcopy(slot),policy)
                        require(policy_digest()==policy,'P4B_BATCH_POLICY_DRIFT')
                    except BaseException as exc:
                        value={'status':'TECHNICAL_FAILURE','transitions':[],
                               'error':{'type':type(exc).__name__,'detail':str(exc)[:300]}}
                        value.update(version='pct_p4b_attempt_result_v3',slot_digest=digest(slot),policy=policy)
                        value['rng']=rng.envelope(pre,rng.capture(),binding=rng_binding,owner=owner,result=value)
                        self.store.append(value,key=key);self.records[key]=value;raise
                    require('rng' not in value,'P4B_RNG_RESERVED_FIELD')
                    value=dict(value,version='pct_p4b_attempt_result_v3',slot_digest=digest(slot),policy=policy)
                    value['rng']=rng.envelope(pre,rng.capture(),binding=rng_binding,owner=owner,result=value)
                    require(value['status'] in ('COMPLETED','NATURAL_EMPTY_POOL','PREDICTED_STATIC_INSTABILITY','UNASSESSABLE','TECHNICAL_FAILURE'),'P4B_ATTEMPT_STATUS')
                    self.store.append(value,key=key);self.records[key]=value
                require(value['status'] in NATURAL.values(),'P4B_ATTEMPT_TECHNICAL_STOP')
                trajectories.append(value['transitions'])
                refs.append({'key':key,'seal':checked(self.store.root/'index'/(key+'.json'))['seal']})
            require(any(trajectories),'P4B_NO_UPDATE_EMPTY_BATCH')
            require(policy_digest()==policy,'P4B_BATCH_POLICY_DRIFT')
            return update(batch_id,trajectories,refs)
        except BaseException as exc:
            self.stop(batch_id,str(exc)[:300]);raise


def check_update_intents(store):
    """Never re-apply an optimizer whose publication outcome is not established."""
    records={r['key']:r['record'] for r in store.records()}
    for key,row in records.items():
        if not key.startswith('optimizer-intent-'):continue
        update=row['update_id'];root=store.root/f'updates/u{update:06d}'
        require(root.exists(),'P4B_OPTIMIZER_OUTCOME_UNKNOWN')
        published=store.update_record(root,update)
        require(published['batch_refs']==row['batch_refs'],'P4B_UPDATE_BATCH_DRIFT')
    return records


def train_model(root,formal,model_spec,tasks,receipt):
    """Public full-schedule entry. No path from offline tests auto-admits this."""
    import shutil
    root=Path(root);identity=current_identity()
    require(formal['identity']==identity and formal['seal']==digest({k:v for k,v in formal.items() if k!='seal'}),'P4B_FORMAL_IDENTITY')
    admission(receipt,identity,shutil.disk_usage(root if root.exists() else root.parent).free)
    schedule=next(s['attempts'] for s in formal['schedules'] if s['model_id']==model_spec['model_id'])
    require(model_spec in formal['models'] and len(schedule)==2000,'P4B_FORMAL_MODEL')
    # Public capability check occurs before model creation or any order activity.
    from .p4b_formal import public_compatibility
    public_compatibility({'version':'pct_p4b_config_v2'})
    core,optimizer=initialize(model_spec['method'],model_spec['seed'])
    with Store(root,{'formal_descriptor':formal['seal'],'model_id':model_spec['model_id'],'identity':identity,'rng_contract':rng.VERSION},
               reserve=receipt['resources']['required_free_bytes']) as store:
        records=check_update_intents(store)
        if not (root/'initial').exists():save_initial(store,core,optimizer,tensor_digest(core))
        updates=len(list((root/'updates').glob('u[0-9]*')))
        snapshot=checked(root/('initial/manifest.json' if updates==0 else f'updates/u{updates:06d}/manifest.json'))
        load(store,core,optimizer,update_id=updates,expected_seal=snapshot['seal'])
        require(snapshot['cursor']['attempt']==updates*8,'P4B_UPDATE_CURSOR')
        policy=tensor_digest(core);controller=BatchController(store,schedule,policy)
        for batch in range(updates,250):
            def collect(slot,frozen):
                task=tasks[slot['task_id']];require(digest(task)==slot['task_digest'],'P4B_TASK_DRIFT')
                cfg=build_config(task,model_spec['method'],formal,frozen,receipt,slot=slot,model_spec=model_spec)
                ep,rows=run_job(root/f'job-{slot["attempt_index"]:04d}',task,cfg,core,receipt,formal=formal,slot=slot,model_spec=model_spec)
                reason=ep['checkpoint']['reason']
                return {'status':NATURAL.get(reason,'UNASSESSABLE' if reason=='STABILITY_UNASSESSABLE' else 'TECHNICAL_FAILURE'),
                        'transitions':trajectory(ep,rows) if reason in NATURAL else [],'summary':ep['summary'],
                        'episode_checkpoint':digest(ep['checkpoint'])}
            def update(batch_id,trajectories,refs):
                uid=batch_id+1
                # Guard capacity BEFORE optimizer may mutate memory.
                from .p4b_state import payload
                blobs=payload(core,optimizer);store.guard(sum(map(len,blobs.values()))*2+store.limit*2)
                store.append({'update_id':uid,'batch_refs':refs,'collection_policy':controller.policy},key=f'optimizer-intent-{uid:04d}')
                metrics=update_parameters(core,optimizer,trajectories)
                cursor={'epoch':min(125,(uid*8-1)//16+1),'attempt':uid*8,'segment':0}
                record=save_update(store,core,optimizer,update_id=uid,policy=tensor_digest(core),cursor=cursor,batch_refs=refs)
                store.append({'update_id':uid,'snapshot_seal':record['seal'],'metrics':metrics},key=f'update-result-{uid:04d}')
                return record
            controller.batch(batch,collect,update,lambda:tensor_digest(core));controller.policy=tensor_digest(core)
        return controller.denominator()


def launch(root,formal,tasks,receipt):
    """Six frozen models, all seeds retained. Any failure stops campaign."""
    from .persistence import JobLock
    from .p4b_storage import publish,encoded
    root=Path(root);require(root.exists(),'P4B_CAMPAIGN_ROOT_REQUIRED')
    identity=current_identity();import shutil
    admission(receipt,identity,shutil.disk_usage(root).free)
    require(formal['identity']==identity,'P4B_FORMAL_IDENTITY')
    with JobLock(root):
        require(not (root/'campaign-stop.json').exists(),'P4B_CAMPAIGN_STOPPED')
        try:
            return {m['model_id']:train_model(root/m['model_id'],formal,m,tasks,receipt) for m in formal['models']}
        except BaseException as exc:
            publish(root/'campaign-stop.json',encoded({'version':VERSION,'error':type(exc).__name__,'detail':str(exc)[:300]}));raise
