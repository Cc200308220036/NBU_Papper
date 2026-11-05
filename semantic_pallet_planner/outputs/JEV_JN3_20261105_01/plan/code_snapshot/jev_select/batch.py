"""J3 frozen batch plans, mixed local/real jobs and independent reconstruction."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import random
import shutil
import time

from .config import load_v2_config,is_v2
from .contracts import JevSelectError,digest,validate_schema
from .dataset import DatasetOrderAdapter,business_spec
from .ledger import read,write

METHODS_V2=('shared_geometry','shared_business_lexicographic','jev_choice')
FORMAL_PARTITIONS=('test_id','test_geometry_ood','test_semantic_ood')


def _scope(tasks,profile,partitions,source_limit):
    if profile=='constructed-eval':return tasks,[]
    allowed=tuple(partitions or (('train',) if profile=='dataset-dev' else ('validation',) if profile=='dataset-validation' else FORMAL_PARTITIONS))
    if not allowed or len(set(allowed))!=len(allowed) or any(p not in ('train','validation',*FORMAL_PARTITIONS) for p in allowed):
        raise JevSelectError('invalid_partitions')
    if profile=='dataset-dev' and any(p!='train' for p in allowed):raise JevSelectError('development_cannot_use_test_partition')
    if profile=='dataset-validation' and allowed!=('validation',):raise JevSelectError('validation_partition_mismatch')
    if profile=='dataset-orders' and any(p not in FORMAL_PARTITIONS for p in allowed):raise JevSelectError('formal_test_partition_mismatch')
    eligible=[t for t in tasks if t['partition'] in allowed]
    if source_limit is not None and (profile!='dataset-dev' or type(source_limit) is not int or source_limit<1):
        raise JevSelectError('source_limit_only_for_development')
    if profile=='dataset-dev':
        n=1 if source_limit is None else source_limit
        groups=list(dict.fromkeys(t['source_group_id'] for t in eligible))[:n]
        eligible=[t for t in eligible if t['source_group_id'] in groups]
    if not eligible:raise JevSelectError('empty_task_scope')
    return eligible,list(allowed)


def _jobs(tasks,methods,seed):
    result=[]
    for task in tasks:
        order=list(methods)
        random.Random(int(digest([seed,task['task_id'],'method_execution_order'])[:16],16)).shuffle(order)
        for method in order:
            result.append({'job_id':f'J{len(result):04d}','task_id':task['task_id'],'method':method,
                           'source_group_id':task['source_order_key'],'partition':task.get('partition','diagnostic'),
                           'business_configuration':task.get('business_configuration','diagnostic')})
    return result


def prepare_plan_v2(output,*,profile='dataset-orders',dataset_root=None,config=None,
                    spec_config=None,split_manifest=None,methods=METHODS_V2,mode='offline',
                    api_budget=None,partitions=None,source_limit=None,offline_scenario='normal'):
    from .experiment import _new_output,source_manifest,file_manifest,validate_tasks,InputAdapter
    config=load_v2_config() if config is None else copy.deepcopy(config)
    validate_schema('config',config)
    if not is_v2(config):raise JevSelectError('j3_requires_config_v2')
    if mode not in ('offline','remote'):raise JevSelectError('invalid_execution_mode')
    if not methods or len(set(methods))!=len(methods) or any(m not in METHODS_V2 for m in methods):raise JevSelectError('invalid_methods')
    if profile not in ('dataset-orders','dataset-dev','dataset-validation','constructed-eval'):raise JevSelectError('invalid_j3_profile')
    if offline_scenario not in ('normal','pick_last','invalid_choice','wrong_model','wrong_probabilities','non_json','timeout','http_429','http_529'):
        raise JevSelectError('invalid_offline_scenario')
    if mode=='remote':
        if api_budget!='unlimited' and (type(api_budget) is not int or not 1<=api_budget<=10000):raise JevSelectError('explicit_api_budget_required')
        limit=None if api_budget=='unlimited' else api_budget
    else:limit=None
    if profile=='constructed-eval':
        tasks,_,_=InputAdapter().load('constructed-smoke')
        for task in tasks:
            task.update(partition='diagnostic',business_configuration='diagnostic',feasibility_status='proven_infeasible' if task['negative'] else 'witness_available')
        adapted={'tasks':tasks,'business_spec':{'version':'constructed_manual_fixtures_v1','generator':'existing_e5_construct_tasks','attribute_source':'explicit_fixture_facts'},'split_manifest':{'version':'jev_constructed_split_v1','partition':'diagnostic'},
                 'input_audit':{'adapter':'constructed_v1','status':'PASS','source_file_manifest':{},'included_base_scenarios':6,'source_groups':6,'derived_tasks':6,'excluded_variants':[]}}
    else:
        if dataset_root is None:raise JevSelectError('dataset_root_required')
        adapted=DatasetOrderAdapter().load(dataset_root,spec_config=spec_config,split_manifest=split_manifest)
    all_tasks=adapted['tasks'];tasks,scope=_scope(all_tasks,profile,partitions,source_limit)
    validate_tasks(tasks)
    jobs=_jobs(tasks,methods,config['display_order_seed'])
    root=_new_output(output);root.mkdir(parents=True)
    input_identity={'adapter':adapted['input_audit']['adapter'],'source_file_manifest':adapted['input_audit']['source_file_manifest'],
                    'business_spec_digest':digest(adapted['business_spec']),'split_digest':digest(adapted['split_manifest']),
                    'all_tasks_digest':digest(all_tasks),'selected_tasks_digest':digest(tasks),'original_f_snapshot_used':False}
    config['experiment_binding']=digest([input_identity,jobs,profile,mode,{'global_attempts':limit,'per_job_attempts':limit},source_manifest()])
    write(root/'config.snapshot.json',config)
    write(root/'public/business_spec.json',adapted['business_spec'])
    write(root/'public/attribute_generation.json',adapted['business_spec'])
    write(root/'split_audit.json',adapted['input_audit'])
    write(root/'split_manifest.json',adapted['split_manifest'])
    write(root/'private/input_snapshot.json',{'tasks':tasks,'all_tasks':all_tasks})
    write(root/'private/reference_specs.json',{t['task_id']:t['reference_policy'] for t in tasks})
    if dataset_root is not None and profile!='constructed-eval':
        source=Path(dataset_root)
        for relative,expected in adapted['input_audit']['source_file_manifest'].items():
            path=source/relative
            if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise JevSelectError('dataset_changed_during_freeze')
            target=root/'private/dataset_snapshot'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    include={t['task_id'] for t in tasks}
    write(root/'inclusion_exclusion.json',{'included_task_ids':sorted(include),
         'excluded_tasks':[{'task_id':t['task_id'],'reason':'outside_frozen_partition_or_development_scope'} for t in all_tasks if t['task_id'] not in include],
         'excluded_variants':adapted['input_audit']['excluded_variants']})
    write(root/'input_manifest.json',{'adapter':adapted['input_audit']['adapter'],'source_file_manifest':adapted['input_audit']['source_file_manifest'],
         'business_spec_digest':digest(adapted['business_spec']),'split_digest':digest(adapted['split_manifest']),
         'all_tasks_digest':digest(all_tasks),'selected_tasks_digest':digest(tasks),'original_f_snapshot_used':False})
    registry=[{'task_id':t['task_id'],'task_digest':digest(t),'source_group_id':t['source_order_key'],
               'partition':t.get('partition','diagnostic'),'business_configuration':t.get('business_configuration','diagnostic')} for t in tasks]
    write(root/'task_registry.json',registry);write(root/'job_registry.json',jobs)
    sources=source_manifest();write(root/'source_manifest.json',sources)
    package=Path(__file__).resolve().parents[1]
    for relative in sources:
        target=root/'code_snapshot'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(package/relative,target)
    from .context import QUESTION_V2,OBJECTIVE_V2
    write(root/'feature_prompt_manifest.json',{'feature_version':config['feature_version'],'prompt_version':config['prompt_version'],
         'question':QUESTION_V2,'objective':OBJECTIVE_V2,'prompt_digest':digest([QUESTION_V2,OBJECTIVE_V2]),
         'business_attribute_source':config['business_attribute_source'],'memory_mode':'none'})
    plan={'version':'jev_plan_v2','experiment_protocol':config['experiment_protocol'],'profile':profile,'mode':mode,
          'partitions':scope,'source_limit':source_limit,'methods':list(methods),'jobs':jobs,'task_registry':registry,
          'offline_scenario':offline_scenario if mode=='offline' else None,
          'budget':{'global_attempts':limit,'per_job_attempts':limit},'workers':1,
          'cache_policy':'clear_generation_and_business_caches_before_each_job','method_order_seed':config['display_order_seed'],
          'input_manifest_digest':digest(read(root/'input_manifest.json')),'business_spec_digest':digest(adapted['business_spec']),
          'split_digest':digest(adapted['split_manifest']),'config_digest':digest(config),
          'role':'diagnostic' if profile=='constructed-eval' else 'development' if profile=='dataset-dev' else 'validation' if profile=='dataset-validation' else 'formal_test',
          'pricing':{'currency':'USD','input_per_million':.042,'output_per_million':0.,'source':'https://docs.typesafe.ai/models','verified_date':'2026-10-29'}}
    write(root/'plan.json',plan);write(root/'delivery_manifest.json',file_manifest(root))
    return validate_plan_v2(root)


def validate_plan_v2(plan_root):
    from .experiment import file_manifest,source_manifest,validate_tasks
    from .context import QUESTION_V2,OBJECTIVE_V2
    root=Path(plan_root)
    if file_manifest(root)!=read(root/'delivery_manifest.json'):raise JevSelectError('plan_changed')
    plan=read(root/'plan.json');config=read(root/'config.snapshot.json')
    validate_schema('config',config);validate_schema('plan_v2',plan)
    if not is_v2(config) or plan['experiment_protocol']!=config['experiment_protocol'] or plan['config_digest']!=digest(config):raise JevSelectError('plan_protocol_mismatch')
    if read(root/'source_manifest.json')!=source_manifest():raise JevSelectError('source_changed')
    for relative,expected in source_manifest().items():
        if hashlib.sha256((root/'code_snapshot'/relative).read_bytes()).hexdigest()!=expected:raise JevSelectError('source_snapshot_changed')
    if plan['profile']=='constructed-eval':
        from .experiment import InputAdapter
        tasks,_,_=InputAdapter().load('constructed-smoke')
        for t in tasks:t.update(partition='diagnostic',business_configuration='diagnostic',feasibility_status='proven_infeasible' if t['negative'] else 'witness_available')
        adapted={'tasks':tasks,'business_spec':{'version':'constructed_manual_fixtures_v1','generator':'existing_e5_construct_tasks','attribute_source':'explicit_fixture_facts'},'split_manifest':{'version':'jev_constructed_split_v1','partition':'diagnostic'},
                 'input_audit':{'adapter':'constructed_v1','status':'PASS','source_file_manifest':{},'included_base_scenarios':6,'source_groups':6,'derived_tasks':6,'excluded_variants':[]}}
    else:adapted=DatasetOrderAdapter().load(root/'private/dataset_snapshot',spec_config=root/'public/business_spec.json',split_manifest=root/'split_manifest.json')
    all_tasks=adapted['tasks'];tasks,partitions=_scope(all_tasks,plan['profile'],plan['partitions'],plan['source_limit'])
    snapshot=read(root/'private/input_snapshot.json')
    if snapshot!={'tasks':tasks,'all_tasks':all_tasks}:raise JevSelectError('frozen_inputs_changed')
    validate_tasks(tasks)
    expected_jobs=_jobs(tasks,plan['methods'],plan['method_order_seed'])
    registry=[{'task_id':t['task_id'],'task_digest':digest(t),'source_group_id':t['source_order_key'],
               'partition':t.get('partition','diagnostic'),'business_configuration':t.get('business_configuration','diagnostic')} for t in tasks]
    if plan['jobs']!=expected_jobs or read(root/'job_registry.json')!=expected_jobs or plan['task_registry']!=registry or read(root/'task_registry.json')!=registry:raise JevSelectError('plan_registry_changed')
    if read(root/'split_audit.json')!=adapted['input_audit'] or read(root/'split_manifest.json')!=adapted['split_manifest'] or read(root/'public/business_spec.json')!=adapted['business_spec'] or read(root/'public/attribute_generation.json')!=adapted['business_spec']:raise JevSelectError('input_audit_changed')
    included={t['task_id'] for t in tasks}
    expected_inclusion={'included_task_ids':sorted(included),'excluded_tasks':[{'task_id':t['task_id'],'reason':'outside_frozen_partition_or_development_scope'} for t in all_tasks if t['task_id'] not in included],
                        'excluded_variants':adapted['input_audit']['excluded_variants']}
    if read(root/'inclusion_exclusion.json')!=expected_inclusion:raise JevSelectError('inclusion_registry_changed')
    expected_input={'adapter':adapted['input_audit']['adapter'],'source_file_manifest':adapted['input_audit']['source_file_manifest'],
                    'business_spec_digest':digest(adapted['business_spec']),'split_digest':digest(adapted['split_manifest']),
                    'all_tasks_digest':digest(all_tasks),'selected_tasks_digest':digest(tasks),'original_f_snapshot_used':False}
    if read(root/'input_manifest.json')!=expected_input or plan['input_manifest_digest']!=digest(expected_input) or plan['business_spec_digest']!=expected_input['business_spec_digest'] or plan['split_digest']!=expected_input['split_digest']:raise JevSelectError('input_manifest_changed')
    if read(root/'private/reference_specs.json')!={t['task_id']:t['reference_policy'] for t in tasks}:raise JevSelectError('reference_specs_changed')
    expected_prompt={'feature_version':config['feature_version'],'prompt_version':config['prompt_version'],'question':QUESTION_V2,'objective':OBJECTIVE_V2,
                     'prompt_digest':digest([QUESTION_V2,OBJECTIVE_V2]),'business_attribute_source':config['business_attribute_source'],'memory_mode':'none'}
    if read(root/'feature_prompt_manifest.json')!=expected_prompt:raise JevSelectError('prompt_manifest_changed')
    expected_binding=digest([expected_input,expected_jobs,plan['profile'],plan['mode'],plan['budget'],source_manifest()])
    if config.get('experiment_binding')!=expected_binding:raise JevSelectError('experiment_binding_changed')
    expected_role='diagnostic' if plan['profile']=='constructed-eval' else 'development' if plan['profile']=='dataset-dev' else 'validation' if plan['profile']=='dataset-validation' else 'formal_test'
    if plan['role']!=expected_role:raise JevSelectError('plan_role_changed')
    if plan['mode']=='remote' and plan['offline_scenario'] is not None:raise JevSelectError('remote_cannot_use_offline_scenario')
    if plan['mode']=='offline' and plan['offline_scenario'] not in ('normal','pick_last','invalid_choice','wrong_model','wrong_probabilities','non_json','timeout','http_429','http_529'):raise JevSelectError('invalid_offline_scenario')
    if plan['budget']['global_attempts']!=plan['budget']['per_job_attempts']:raise JevSelectError('budget_policy_mismatch')
    if plan['partitions']!=partitions or plan['method_order_seed']!=config['display_order_seed']:raise JevSelectError('scope_or_order_changed')
    if any(m not in METHODS_V2 for m in plan['methods']) or len(set(plan['methods']))!=len(plan['methods']):raise JevSelectError('invalid_methods')
    return {'status':'PASS','scope':'J3_FROZEN_PLAN','planned_tasks':len(tasks),'planned_jobs':len(expected_jobs),
            'source_orders':len({t['source_order_key'] for t in tasks}),'role':plan['role'],'model_api_calls':0}


def _clear_job_caches():
    from semantic_pallet_planner.o4.extensions.e2.candidates import _cached_generation
    from semantic_pallet_planner.o4.extensions.e2.runtime import _cached_state
    from semantic_pallet_planner.o4.extensions.e2.reference import _cached_reference
    for function in (_cached_generation,_cached_state,_cached_reference):function.cache_clear()


def _identity(plan_root,plan):
    from .experiment import file_manifest
    return {'version':'jev_experiment_v2','mode':plan['mode'],'experiment_protocol':plan['experiment_protocol'],
            'plan_digest':digest(file_manifest(Path(plan_root))),'input_manifest_digest':plan['input_manifest_digest'],
            'business_spec_digest':plan['business_spec_digest'],'split_digest':plan['split_digest']}


def _save_decision(root,event,*,readonly=False):
    did=event['decision_id'];job=event['context']['local_binding']['job_id']
    pairs=[(root/'requests'/job/f'{did}.json',event['context']['request_body']),
           (root/'mappings'/job/f'{did}.json',event['context'])]
    for path,value in pairs:
        if path.exists():
            if read(path)!=value:raise JevSelectError('saved_request_or_mapping_changed')
        elif readonly:raise JevSelectError('missing_saved_request')
        else:write(path,value)
    return {p for p,v in pairs}


def _selector(config,ledger,job,plan,*,readonly=False,api_key_file=None):
    from .selector import JevSelector,LocalSelector
    if job['method']!='jev_choice':return LocalSelector(job['method'])
    if readonly:return JevSelector(config,ledger,job['job_id'])
    if plan['mode']=='offline':
        from .testing import OfflineTransport
        transport=OfflineTransport(config,plan['offline_scenario'])
    else:
        from .transport import JevTransport
        transport=JevTransport(config,api_key_file=api_key_file)
    return JevSelector(config,ledger,job['job_id'],transport)


def run_experiment_v2(plan_root,output,*,offline=False,remote=False,api_budget=None,api_key_file=None,resume=False,hook=None):
    from .experiment import _new_output,file_manifest,load_plan
    from .ledger import Ledger,exclusive
    from .episode import run_episode
    from .evaluation import aggregate_v2
    if (offline is True)==(remote is True):raise JevSelectError('explicit_execution_mode_required')
    plan,config,tasks=load_plan(plan_root)
    mode='remote' if remote else 'offline'
    if plan['mode']!=mode:raise JevSelectError('plan_mode_mismatch')
    if api_budget is not None and (None if api_budget=='unlimited' else api_budget)!=plan['budget']['global_attempts']:raise JevSelectError('runtime_budget_changed')
    root=Path(output).resolve();identity=_identity(plan_root,plan)
    if not resume:
        if remote and 'jev_choice' in plan['methods']:
            from .transport import credential
            credential(config['api_key_env'],api_key_file)
        root=_new_output(root);root.mkdir(parents=True);shutil.copytree(plan_root,root/'plan');write(root/'manifest.json',identity)
        statuses=[{**job,'status':'NOT_RUN','termination_reason':None} for job in plan['jobs']]
        write(root/'audit/jobs.json',statuses)
    elif not root.is_dir() or read(root/'manifest.json')!=identity:raise JevSelectError('resume_identity_changed')
    with exclusive(root):
        if (root/'delivery_manifest.json').exists():return replay_experiment_v2(root)
        saved_plan,saved_config,saved_tasks=load_plan(root/'plan')
        if (saved_plan,saved_config,saved_tasks)!=(plan,config,tasks):raise JevSelectError('run_plan_changed')
        tasks_by_id={t['task_id']:t for t in tasks}
        statuses=read(root/'audit/jobs.json')
        if [{k:r[k] for k in plan['jobs'][0]} for r in statuses]!=plan['jobs']:raise JevSelectError('job_registry_changed')
        ledger=Ledger(root,plan['budget'],hook=hook,origin='jev' if remote else 'test_double')
        rows=[]
        for index,job in enumerate(plan['jobs']):
            _clear_job_caches()
            job_id=job['job_id'];cfg=dict(config,selector=job['method']);task=tasks_by_id[job['task_id']]
            selector=_selector(cfg,ledger,job,plan,api_key_file=api_key_file)
            cp_path=root/'checkpoints'/f'{job_id}.json';cp=read(cp_path) if cp_path.exists() else None
            statuses[index].update(status='RUNNING',termination_reason=None);write(root/'audit/jobs.json',statuses)
            session_path=root/'timings'/f'{job_id}.json'
            sessions=read(session_path) if session_path.exists() else []
            for previous_session in sessions:
                if previous_session['finished_at'] is None and previous_session['status']=='RUNNING':
                    previous_session['status']='ABANDONED'
            session={'session_index':len(sessions),'started_at':time.time(),'finished_at':None,'wall_s':None,
                     'resume_validation_included':cp is not None,'status':'RUNNING','persistence_s':0.}
            sessions.append(session);write(session_path,sessions)
            start=time.perf_counter()
            def checkpoint(value):
                stamp=time.perf_counter();write(cp_path,value);session['persistence_s']+=time.perf_counter()-stamp
            def event_hook(phase,value):
                if phase=='decision_ready':_save_decision(root,value)
                if phase=='evaluation_failure':
                    path=root/'audit/evaluation_failures.json';failures=read(path) if path.exists() else []
                    failures.append({'job_id':job_id,'decision':value['decision'],'state_digest':digest(value['state']),
                                     'error':value['pending_event']['error'],'observed_at':time.time()});write(path,failures)
                if hook:hook(phase,value)
            try:
                result=run_episode(task,selector,cfg,job_id=job_id,method=job['method'],resume=cp,on_checkpoint=checkpoint,hook=event_hook)
                checkpoint(result['checkpoint'])
                if result['summary'] is None:
                    session['status']='FAILED'
                    statuses[index].update(status='FAILED',termination_reason='EVALUATION_ERROR')
                    write(root/'audit/jobs.json',statuses)
                    return {'status':'NEEDS_RECOVERY','scope':'J3_BATCH','job_id':job_id,'reason':'EVALUATION_ERROR',
                            'planned_jobs':len(plan['jobs']),'remaining_jobs':len(plan['jobs'])-index-1}
                episode_path=root/'episodes'/f'{job_id}.json'
                if episode_path.exists() and read(episode_path)!=result:raise JevSelectError('completed_episode_changed')
                write(episode_path,result)
                row=result['summary'];reason=row['termination_reason']
                execution='RECORDED' if reason in ('ALL_ITEMS_PLACED','STOP_NO_PHYSICAL_CANDIDATE') else 'FAILED'
                row=dict(row,job_id=job_id,execution_status=execution)
                rows.append(row)
                statuses[index].update(status=execution,termination_reason=reason)
                write(root/'audit/jobs.json',statuses)
                session['status']=execution
            except BaseException:
                session['status']='INTERRUPTED'
                statuses[index].update(status='INTERRUPTED');write(root/'audit/jobs.json',statuses)
                raise
            finally:
                session.update(finished_at=time.time(),wall_s=time.perf_counter()-start);write(session_path,sessions)
        aggregate=aggregate_v2(rows,ledger.data['attempts'],plan=plan,experiment_root=root)
        for name,value in aggregate.items():write(root/'metrics'/f'{name}.json',value)
        report=replay_experiment_v2(root,require_seal=False)
        write(root/'acceptance_report.json',report);write(root/'replay_report.json',report)
        write(root/'delivery_manifest.json',file_manifest(root))
        return report


def replay_experiment_v2(experiment_root,*,network_allowed=False,require_seal=True):
    from .experiment import file_manifest,load_plan
    from .ledger import Ledger
    from .episode import run_episode
    from .evaluation import aggregate_v2
    if network_allowed is not False:raise JevSelectError('replay_network_forbidden')
    root=Path(experiment_root)
    if require_seal and file_manifest(root)!=read(root/'delivery_manifest.json'):raise JevSelectError('experiment_changed')
    plan,config,tasks=load_plan(root/'plan')
    if read(root/'manifest.json')!=_identity(root/'plan',plan):raise JevSelectError('experiment_identity_changed')
    ledger=Ledger(root,plan['budget'],readonly=True,origin='jev' if plan['mode']=='remote' else 'test_double')
    jobs={j['job_id']:j for j in plan['jobs']};by_task={t['task_id']:t for t in tasks}
    for attempt in ledger.data['attempts']:
        if attempt['job_id'] not in jobs or jobs[attempt['job_id']]['method']!='jev_choice' or attempt['origin']!=ledger.origin:
            raise JevSelectError('attempt_job_or_origin_mismatch')
    rows=[];statuses=[];request_files=set()
    for job in plan['jobs']:
        _clear_job_caches()
        job_id=job['job_id'];cfg=dict(config,selector=job['method'])
        selector=_selector(cfg,ledger,job,plan,readonly=True)
        def event_hook(phase,event):
            if phase!='decision_ready':return
            request_files.update(_save_decision(root,event,readonly=True))
            if plan['mode']=='offline':
                from .testing import OfflineTransport
                for attempt in ledger.data['attempts']:
                    if attempt['job_id']!=job_id or attempt['decision_id']!=event['decision_id']:continue
                    saved=attempt['transport']
                    if saved is None:raise JevSelectError('incomplete_attempt')
                    if saved['error']=='interrupted_after_reservation':
                        if saved['status']!='UNKNOWN_IN_FLIGHT' or saved['network_attempted'] is not None or saved['raw_body_b64']!='':raise JevSelectError('invalid_interruption')
                    elif saved!=OfflineTransport(cfg,plan['offline_scenario']).complete(event['context']['request_body']):raise JevSelectError('offline_response_changed')
        saved=read(root/'episodes'/f'{job_id}.json')
        actual=run_episode(by_task[job['task_id']],selector,cfg,job_id=job_id,method=job['method'],expected_events=saved['events'],hook=event_hook)
        if actual!=saved or actual['checkpoint']!=read(root/'checkpoints'/f'{job_id}.json'):raise JevSelectError('episode_or_checkpoint_changed')
        row=actual['summary'];reason=row['termination_reason']
        status='RECORDED' if reason in ('ALL_ITEMS_PLACED','STOP_NO_PHYSICAL_CANDIDATE') else 'FAILED'
        rows.append(dict(row,job_id=job_id,execution_status=status))
        statuses.append({**job,'status':status,'termination_reason':reason})
    if ledger.used!={r['attempt_id'] for r in ledger.data['attempts']}:raise JevSelectError('orphan_attempts')
    if set((root/'requests').rglob('*.json'))|set((root/'mappings').rglob('*.json'))!=request_files:raise JevSelectError('request_registry_changed')
    if read(root/'audit/jobs.json')!=statuses:raise JevSelectError('job_statuses_changed')
    evaluation_audit=root/'audit/evaluation_failures.json'
    if evaluation_audit.exists():
        for failure in read(evaluation_audit):
            if set(failure)!={'job_id','decision','state_digest','error','observed_at'} or failure['job_id'] not in jobs:
                raise JevSelectError('evaluation_failure_audit_changed')
            jid=failure['job_id'];episode=read(root/'episodes'/f'{jid}.json')
            event=next((e for e in episode['events'] if e.get('decision_id')==f'{jid}_D{failure["decision"]:04d}'),None)
            if event is None or event['event']!='PLACE' or digest(event['after'])!=failure['state_digest'] or failure['error'].get('code')!='EVALUATION_ERROR':
                raise JevSelectError('evaluation_failure_state_changed')
            sessions=read(root/'timings'/f'{jid}.json')
            if failure['observed_at']<min(s['started_at'] for s in sessions) or failure['observed_at']>max(s['finished_at'] for s in sessions if s['finished_at'] is not None):
                raise JevSelectError('evaluation_failure_clock_changed')
    metrics=aggregate_v2(rows,ledger.data['attempts'],plan=plan,experiment_root=root)
    for name,value in metrics.items():
        if read(root/'metrics'/f'{name}.json')!=value:raise JevSelectError('derived_metrics_changed',name)
    summary=metrics['summary']
    report={'status':'PASS','scope':'J3_OFFLINE_ACCEPTANCE' if plan['mode']=='offline' else 'J3_REAL_COMPARISON',
            'role':plan['role'],'planned_jobs':len(plan['jobs']),'verified_jobs':len(rows),
            'source_orders':summary['source_orders'],'model_api_calls':summary['model_api_calls'],
            'offline_attempts':summary['offline_attempts'],'business_mode':'evaluate_only',
            'source_groups_not_cross_partition':True,'business_stop_events':0,
            'execution_failures':sum(r['execution_status']=='FAILED' for r in rows),
            'all_jobs_retained':True,'model_quality':'NOT_MEASURED' if plan['mode']=='offline' else 'EMPIRICAL_ORDER_COMPARISON',
            'served_models':summary['served_models'],'estimated_model_cost_usd':summary['estimated_model_cost_usd']}
    if any(r['termination_reason'] in ('business_rejection','STOP_NO_BUSINESS_CANDIDATE') for r in rows):raise JevSelectError('business_termination_in_eval_mode')
    if require_seal and (read(root/'acceptance_report.json')!=report or read(root/'replay_report.json')!=report):raise JevSelectError('acceptance_report_changed')
    return report


def preflight_v2(plan_root,*,api_key_file=None):
    from .experiment import load_plan
    from .episode import decision_inputs
    from .contracts import canonical
    from .transport import credential
    from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive,can_wait
    plan,config,tasks=load_plan(plan_root)
    job=next((j for j in plan['jobs'] if j['method']=='jev_choice'),plan['jobs'][0])
    task=next(t for t in tasks if t['task_id']==job['task_id'])
    state=initial(task['container'],config['buffer_capacity']);cursor=0
    while can_wait(state):
        if cursor<len(task['items']):
            item=task['items'][cursor];state=receive(state,item,task['attributes'][item['item_id']]);cursor+=1
        else:state=receive(state,eos=True)
    cfg=dict(config,selector=job['method'])
    req,policy,bundle,context=decision_inputs(state,task,cfg,job['job_id'],f"{job['job_id']}_D0000")
    ready=True;credential_present=None
    if plan['mode']=='remote' and 'jev_choice' in plan['methods']:
        try:credential(config['api_key_env'],api_key_file);credential_present=True
        except (OSError,JevSelectError):credential_present=False;ready=False
    model_jobs=[j for j in plan['jobs'] if j['method']=='jev_choice'];lookup={t['task_id']:t for t in tasks}
    return {'status':'PASS' if ready else 'NEEDS_API_KEY','scope':'J3_PREFLIGHT','model_api_calls':0,
            'planned_jobs':len(plan['jobs']),'planned_tasks':len(tasks),'model_jobs':len(model_jobs),
            'source_orders':len({t['source_order_key'] for t in tasks}),'credential_present':credential_present,
            'business_mode':'evaluate_only','first_physical_candidates':len(bundle.data['physical_candidates']),
            'first_selectable_candidates':len(bundle.data['selectable_candidates']),'first_route':context.data['route'],
            'first_request_bytes':len(canonical(context.data['request_body']).encode()),'budget':plan['budget'],
            'natural_model_attempt_upper_bound':sum(len(lookup[j['task_id']]['items']) for j in model_jobs),
            'requested_model':config['model'],'endpoint':config['endpoint'],'role':plan['role']}
