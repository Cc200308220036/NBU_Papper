"""P3 fixed local admission over the sole public run_episode engine.

New headers bind real models, features, environment, source and frozen plan.
Session accounting is append-only and separate from immutable monitor events.
"""
import copy
import importlib.metadata as metadata
import json
import math
from pathlib import Path
import time
import torch

from .contracts import digest, sha, read, require
from .execution import GeometrySelector, source_identity, strategy_identity
from .persistence import JobLock, JournalSink, atomic_new, read_records, fsync_dir
from .recovery import environment_identity, ROOT
from .saved import validate_checkpoint as validate_saved_checkpoint

TASKS=('NEW_00100027_controlled_base','NEW_00100090_controlled_heterogeneous')
METHODS={'geometry_b1':None,'pct_geo_b1':'pct_adapted_geo_v1','pct_load_b1':'pct_adapted_load_v1'}
TECHNICAL={'STABILITY_MONITOR_ERROR','STABILITY_UNASSESSABLE'}


def environment():
    result=environment_identity()
    result['torch']={'version':torch.__version__, 'record_digest':digest(metadata.distribution('torch').read_text('RECORD'))}
    return result


def build_config(task,method,plan_digest,model=None,mode='diagnostic'):
    from importlib.resources import files
    from semantic_pallet_planner.jev_select.stability.monitor import exact_freeze
    from semantic_pallet_planner.jev_select.packaging_runtime import physical_manifest
    from semantic_pallet_planner.jev_select.contracts import validate_schema
    require(task['task_id'] in TASKS and method in METHODS,'P3_SCOPE')
    config=json.loads(files('semantic_pallet_planner.jev_select').joinpath('configs/packaging_runtime_v4.json').read_text())
    monitor=exact_freeze()
    config.update(version='pct_p3_config_v1',buffer_capacity=1,model=None,selector=method,
        execution_spec_digest=task['execution_spec_digest'],model_identity=model,
        stability_monitor=monitor,p3_plan_digest=plan_digest,p3_mode=mode,
        runtime_identity={'data_identity':task['parent_data_identity'],'physical_identity':digest(physical_manifest()),
        'strategy_identity':strategy_identity(method),'task_identity':digest(task),'monitor_identity':digest(monitor)})
    validate_schema('config',config)
    return config


def preflight(config):
    from semantic_pallet_planner.jev_select.stability.monitor import exact_freeze
    from semantic_pallet_planner.jev_select.packaging_runtime import physical_manifest
    from semantic_pallet_planner.jev_select.contracts import validate_schema
    validate_schema('config',config)
    require(config['stability_monitor']==exact_freeze() and config['stability_monitor']['enabled'] is True,
            'P3_EXACT_MONITOR_DRIFT')
    require(config['runtime_identity']['monitor_identity']==digest(config['stability_monitor']) and
            config['runtime_identity']['physical_identity']==digest(physical_manifest()),'P3_PHYSICAL_DRIFT')
    require(config['runtime_identity']['strategy_identity']==strategy_identity(config['selector']),'P3_SOURCE_DRIFT')
    require((config['model_identity'] is None)==(config['selector']=='geometry_b1'),'P3_MODEL_REQUIRED')
    require(torch.get_num_threads()==1 and torch.are_deterministic_algorithms_enabled(),'P3_RUNTIME')


def model_binding(manifest,weights):
    m=read(manifest)
    require(sha(weights)==m['weights_sha256'],'P3_WEIGHT_BYTES')
    return {'manifest_path':str(manifest),'manifest_sha256':sha(manifest),'weights_path':str(weights),
            'weights_sha256':sha(weights),'features':m['feature_contract'],'model_version':m['model_version']}


def load_bound(binding):
    if binding is None:return None
    module='geo_model' if binding['model_version']=='pct_adapted_geo_v1' else 'load_model'
    from importlib import import_module
    loaded=import_module('pct_baseline.'+module).load_model(binding['manifest_path'],binding['weights_path'],
                    expected_manifest_sha256=binding['manifest_sha256'])
    require(loaded.manifest['weights_sha256']==binding['weights_sha256'] and loaded.manifest['feature_contract']==binding['features'],
            'P3_FEATURE_OR_WEIGHTS_DRIFT')
    return loaded


def create_job(task,config,binding,output,job_id):
    preflight(config);root=Path(output)
    require(not root.exists(),'P3_OUTPUT_EXISTS')
    require(config['model_identity']==(digest(binding) if binding else None),'P3_MODEL_CONFIG_BINDING')
    header={'version':'pct_p3_header_v1','job_id':job_id,'task':copy.deepcopy(task),'config':config,
            'model_binding':binding,'source':source_identity(),'environment':environment()}
    header['header_digest']=digest(header)
    root.mkdir(parents=True,exist_ok=False)
    for name in ('journal','records','sessions','decision_rng'):(root/name).mkdir()
    atomic_new(root/'header.json',header)
    return header


def check_header(h,current=True):
    require(set(h)=={'version','job_id','task','config','model_binding','source','environment','header_digest'} and
            h['version']=='pct_p3_header_v1' and h['header_digest']==digest({k:v for k,v in h.items() if k!='header_digest'}),'P3_HEADER')
    c=h['config'];t=h['task'];b=h['model_binding']
    require(t['task_id'] in TASKS and c['runtime_identity']['task_identity']==digest(t) and
            c['runtime_identity']['data_identity']==t['parent_data_identity'] and
            c['execution_spec_digest']==t['execution_spec_digest'],'P3_TASK_BINDING')
    require(c['model_identity']==(digest(b) if b else None),'P3_MODEL_BINDING')
    if b:
        require(b['model_version']==METHODS[c['selector']] and sha(b['manifest_path'])==b['manifest_sha256']
                and sha(b['weights_path'])==b['weights_sha256'],'P3_MODEL_DRIFT')
    if current:
        require(h['source']==source_identity() and h['environment']==environment(),'P3_SOURCE_ENVIRONMENT_DRIFT')
        preflight(c)


def validate_selection(context,selection,config):
    from semantic_pallet_planner.jev_select.contracts import validate_schema
    value=selection.data;validate_schema('selection_result',value)
    require(value['local_binding_digest']==digest(context.data['local_binding']) and not value['network_attempted']
            and not value['attempt_ids'] and value['error'] is None,'P3_SELECTION_BINDING')
    label=value['selected_display_id']
    require(label in context.data['display_mapping'] and
            value['selected_candidate_id']==context.data['display_mapping'][label]['candidate_id'],'P3_SELECTION_ACTION')
    singleton=context.data['route']=='SINGLETON_BYPASS'
    require(value['status']==('singleton' if singleton else 'selected') and
            value['source']==('singleton' if singleton else 'local_baseline' if config['selector']=='geometry_b1' else 'pct_local'),
            'P3_SELECTION_SOURCE')


def validate_checkpoint(cp,task,config,job_id,method):
    # Existing saved-state validator is generic over the b1 carriers and does
    # not grant execution admission or assume deterministic geometry selection.
    return validate_saved_checkpoint(cp,task,config,job_id,method)


def summarize_episode(task,config,method,state,events,reason):
    from .execution import summarize_episode as original
    result=original(task,config,method,state,events,reason)
    result.update(version='pct_p3_metrics_v1',scope='P3_FIXED_LOCAL_ONLY',
                  training='COLLECTION_ONLY' if config['p3_mode']=='training' else 'NOT_RUN',
                  policy_status='RANDOM_OR_SMALL_STEP_ENGINEERING_ONLY',policy_ranking_eligible=reason in (
                      'ALL_ITEMS_PLACED','STOP_NO_PHYSICAL_CANDIDATE','PREDICTED_STATIC_INSTABILITY'))
    return result


class ModelSelector:
    def __init__(self,config,model,root,counters):
        self.config=copy.deepcopy(config);self.model=model;self.root=root;self.counts=counters;self.bound=None
        from . import geo_encoding,load_encoding
        self.encoding=geo_encoding if config['selector']=='pct_geo_b1' else load_encoding
        self.encode=self.encoding.encode_geometry if config['selector']=='pct_geo_b1' else self.encoding.encode_load

    def bind(self,event):
        from semantic_pallet_planner.jev_select.contracts import DecisionContext
        context=DecisionContext.from_dict(event['context'])
        from semantic_pallet_planner.jev_select.context import validate_context
        validate_context(context,config=self.config)
        e=self.encode(context);candidates=event['bundle']['selectable_candidates']
        require(digest(candidates)==context.data['local_binding']['physical_digest']==context.data['local_binding']['selectable_digest'],'P3_POOL_BINDING')
        by_id=self.encoding.verify_candidates(e,candidates)
        self.bound=(context,e,by_id)
        if e.data['candidate_count']==1 and self.config['p3_mode']=='training':
            self.record(context,event['decision_id'],singleton=True)

    def record(self,context,did,singleton=False):
        from semantic_pallet_planner.jev_select.selector import result,SelectionResult
        require(self.bound is not None and digest(self.bound[0].data)==digest(context.data),'P3_UNBOUND')
        _,e,by_id=self.bound
        path=self.root/'records'/(did+'.json')
        if path.exists():
            record=read(path);validate_record(record,context,self.config,self.model,self.encode,self.encoding.verify_candidates,by_id)
            self.counts['selection_record_reuses']+=1
            return SelectionResult.from_dict(record['selection'])
        self.model.check_identity()
        if singleton:
            index=0
            with torch.no_grad():
                _,_,_,hidden,dist=self.model._model.actor(e.tensor(),deterministic=True,normFactor=1,evaluate=True)
                value=self.model._model.critic(hidden)
            output={'probabilities':dist.probs[0].tolist(),'value':float(value.item()),'leaf_index':0}
            self.counts['singleton_critic_forwards']+=1
            selection=result(context,status='singleton',source='singleton',label=e.resolve(0)['display_label'])
        else:
            if self.config['p3_mode']=='training':
                rng_path=self.root/'decision_rng'/(did+'.json')
                if rng_path.exists():torch.set_rng_state(torch.tensor(read(rng_path)['torch_cpu'],dtype=torch.uint8))
                else:atomic_new(rng_path,{'torch_cpu':torch.get_rng_state().tolist()})
                with torch.no_grad():
                    _,indices,entropy,hidden,dist=self.model._model.actor(e.tensor(),deterministic=False,normFactor=1,evaluate=True)
                    value=self.model._model.critic(hidden)
                index=int(indices.item());output={'probabilities':dist.probs[0].tolist(),'value':float(value.item()),'leaf_index':index}
            else:
                output=self.model.infer([e])[0];index=output['leaf_index']
            self.counts['policy_choice_forwards']+=1
            row=e.resolve(index)
            data=result(context,status='selected',source='local_baseline',label=row['display_label']).data
            data.update(source='pct_local',probabilities={r['display_label']:output['probabilities'][r['leaf_index']] for r in e.data['mapping']},
                confidence=output['probabilities'][index],inference_receipt={'feature_digest':e.data['feature_digest'],
                'weights_sha256':self.model.manifest['weights_sha256'],'leaf_index':index,'inference_s':0.})
            selection=SelectionResult.from_dict(data)
        row=e.resolve(index)
        record={'version':'pct_p3_selection_v1','context_digest':digest(context.data),'model_identity':self.config['model_identity'],
                'encoding':e.data,'output':output,'selection':selection.data,'exact_candidate':by_id[row['candidate_id']]}
        record['record_digest']=digest(record)
        validate_record(record,context,self.config,self.model,self.encode,self.encoding.verify_candidates,by_id)
        atomic_new(path,record)
        return selection

    def select(self,context,*,decision_id):return self.record(context,decision_id)


def validate_record(r,context,config,model,encode,verify,by_id):
    require(r['version']=='pct_p3_selection_v1' and r['record_digest']==digest({k:v for k,v in r.items() if k!='record_digest'})
            and r['context_digest']==digest(context.data) and r['model_identity']==config['model_identity'],'P3_RECORD_BINDING')
    e=encode(context);require(r['encoding']==e.data,'P3_RECORD_ENCODING')
    output=r['output'];p=output['probabilities'];i=output['leaf_index'];row=e.resolve(i);n=e.data['candidate_count']
    require(len(p)==16 and all(type(v) in (float,int) and math.isfinite(v) and 0<=v<=1 for v in p)
            and abs(sum(p)-1)<1e-5 and all(v==0 for v in p[n:]) and p[i]>0
            and math.isfinite(output['value']),'P3_RECORD_PROBABILITIES')
    if config['p3_mode']=='diagnostic':require(i==max(range(n),key=lambda j:p[j]),'P3_ARGMAX')
    s=r['selection'];require(s['selected_candidate_id']==row['candidate_id'] and r['exact_candidate']==by_id[row['candidate_id']], 'P3_RECORD_EXACT_ACTION')
    from semantic_pallet_planner.jev_select.selector import SelectionResult
    validate_selection(context,SelectionResult.from_dict(s),config)
    if n>1:
        require(s['inference_receipt']['weights_sha256']==model.manifest['weights_sha256'] and
                s['inference_receipt']['feature_digest']==e.data['feature_digest'] and
                s['inference_receipt']['leaf_index']==i and s['confidence']==p[i] and
                s['probabilities']=={row['display_label']:p[row['leaf_index']] for row in e.data['mapping']},'P3_RECEIPT')


def admit_execution(task,selector,config,*,execution,job_id,method,resume,on_checkpoint,
                    expected_events,training_fork,memory_snapshot,memory_view,memory_driver):
    require(isinstance(on_checkpoint,JournalSink) and on_checkpoint.lock.stream is not None,'P3_LOCKED_JOURNAL')
    h=on_checkpoint.header;check_header(h)
    require(all(x is None for x in (expected_events,training_fork,memory_snapshot,memory_view,memory_driver)),'P3_NO_REMOTE_MEMORY_FORK')
    require(execution=={'version':'pct_p3_execution_v1','header_digest':h['header_digest']} and task==h['task'] and config==h['config']
            and method==config['selector'] and job_id==h['job_id'],'P3_ADMISSION_BINDING')
    require(resume==(on_checkpoint.rows[-1]['checkpoint'] if on_checkpoint.rows else None),'P3_JOURNAL_TAIL_REQUIRED')
    require(selector.config==config and isinstance(selector,GeometrySelector if method=='geometry_b1' else ModelSelector),'P3_SELECTOR')


def verify_model_records(root,cp,config,model):
    if cp is None or model is None:return
    from semantic_pallet_planner.jev_select.contracts import DecisionContext
    from . import geo_encoding,load_encoding
    module=geo_encoding if config['selector']=='pct_geo_b1' else load_encoding
    encode=module.encode_geometry if config['selector']=='pct_geo_b1' else module.encode_load
    events=list(cp['events'])+([cp['pending_event']] if cp['pending_event'] else [])
    for event in events:
        selection=event.get('selection')
        if selection is None:continue
        if selection['status']=='singleton' and config['p3_mode']=='diagnostic':continue
        context=DecisionContext.from_dict(event['context'])
        record=read(Path(root)/'records'/(event['decision_id']+'.json'))
        by_id=module.verify_candidates(encode(context),event['bundle']['selectable_candidates'])
        validate_record(record,context,config,model,encode,module.verify_candidates,by_id)
        require(record['selection']==selection,'P3_DURABLE_SELECTION_RECORD_CHANGED')


def check_journal_stages(rows):
    allowed={'READY':{'READY','DECISION_READY','TERMINATED'},'DECISION_READY':{'SELECTED','TERMINATED'},
             'SELECTED':{'MONITORED'},'MONITORED':{'COMMITTED','TERMINATED'},
             'COMMITTED':{'READY','TERMINATED'},'TERMINATED':set()}
    for old,new in zip(rows,rows[1:]):
        a=old['checkpoint'];b=new['checkpoint']
        require(b['phase'] in allowed[a['phase']] and b['events'][:len(a['events'])]==a['events'], 'P3_JOURNAL_HISTORY')
        require(len(b['events'])-len(a['events']) in (0,1),'P3_JOURNAL_EVENT_GAP')
        pending=a['pending_event']
        if pending:
            nxt=b['pending_event'] or (b['events'][-1] if len(b['events'])>len(a['events']) else None)
            require(nxt is not None and nxt['decision_id']==pending['decision_id'],'P3_PENDING_REPLACED')
            for key in ('before','observation','bundle','context','selection','proposed_action','monitor'):
                if pending[key] is not None:require(nxt[key]==pending[key],'P3_PENDING_FACT_OVERWRITTEN')


def run_job(root,cut_phase=None):
    from semantic_pallet_planner.jev_select.episode import run_episode
    root=Path(root);started=time.perf_counter()
    with JobLock(root) as lock:
        h,rows=read_records(root);check_header(h);check_journal_stages(rows)
        c=h['config'];task=h['task'];cp=rows[-1]['checkpoint'] if rows else None
        if cp:validate_checkpoint(cp,task,c,h['job_id'],c['selector'])
        if (root/'commit_intent.json').exists():
            intent=read(root/'commit_intent.json')
            require(cp is not None and cp['phase']=='COMMITTED' and cp['pending_event']['decision_id']==intent['decision_id']
                    and digest(cp['pending_event']['before'])==intent['before_digest'] and digest(cp['pending_event']['selection'])==intent['selection_digest'],'P3_COMMIT_OUTCOME_UNKNOWN')
            (root/'commit_intent.json').unlink();fsync_dir(root)
        counts={k:0 for k in ('candidate_generations','candidate_actions','choice_steps','singleton_steps','policy_choice_forwards',
                  'singleton_critic_forwards','selection_record_reuses','saved_selection_reuses','monitor_calls','saved_monitor_reuses','commits')}
        model=load_bound(h['model_binding'])
        verify_model_records(root,cp,c,model)
        selector=GeometrySelector(c) if model is None else ModelSelector(c,model,root,counts)
        seq=len(list((root/'sessions').glob('*.json')))
        receipt={'version':'pct_p3_session_v1','start_phase':cp['phase'] if cp else 'NOT_STARTED',
                 'start_checkpoint_digest':digest(cp) if cp else None,'counts':counts,'status':'STARTED'}
        atomic_new(root/'sessions'/f'{seq:04d}_start.json',receipt)
        sink=JournalSink(root,h,rows,lock)
        initial_pending=cp['pending_event'] if cp else None
        if cp and cp['phase'] in ('SELECTED','MONITORED'):
            counts['saved_selection_reuses']+=1
            if cp['phase']=='MONITORED':counts['saved_monitor_reuses']+=1
        def hook(phase,value):
            if phase=='decision_ready':
                did=value['decision_id']
                reused=initial_pending is not None and initial_pending['decision_id']==did
                route=value['route']
                if route=='CHOICE_REQUIRED':counts['choice_steps']+=1
                if route=='SINGLETON_BYPASS':counts['singleton_steps']+=1
                if model is not None and (not reused or cp['phase']=='DECISION_READY'):selector.bind(value)
            if phase=='after_checkpoint':
                if value['phase']=='DECISION_READY':
                    counts['candidate_generations']+=1
                    counts['candidate_actions']+=len(value['pending_event']['bundle']['physical_candidates'])
                if value['phase']=='MONITORED':counts['monitor_calls']+=1
                if value['phase']=='COMMITTED':counts['commits']+=1
            if phase=='before_commit':sink.hook(phase,value)
            if phase=='after_checkpoint' and cut_phase and value['phase']==cut_phase:
                raise PlannedCut(cut_phase)
        try:
            ep=run_episode(task,selector,c,job_id=h['job_id'],method=c['selector'],resume=cp,
                           on_checkpoint=sink,hook=hook,extension_execution={'version':'pct_p3_execution_v1','header_digest':h['header_digest']})
            validate_checkpoint(ep['checkpoint'],task,c,h['job_id'],c['selector'])
            verify_model_records(root,ep['checkpoint'],c,model)
            if not (root/'episode.json').exists():atomic_new(root/'episode.json',ep)
            else:require(read(root/'episode.json')['checkpoint']==ep['checkpoint'],'P3_EPISODE_CHANGED')
            receipt['status']='FINISHED';return ep
        except PlannedCut:
            receipt['status']='PLANNED_CUT';return None
        except BaseException as exc:
            receipt.update(status='TECHNICAL_FAILURE',exception_type=type(exc).__name__,detail=str(exc)[:500]);raise
        finally:
            receipt['elapsed_s']=time.perf_counter()-started
            receipt['end_checkpoint_digest']=digest(sink.rows[-1]['checkpoint']) if sink.rows else None
            receipt['counts']=counts
            atomic_new(root/'sessions'/f'{seq:04d}_end.json',receipt)

class PlannedCut(BaseException):pass
