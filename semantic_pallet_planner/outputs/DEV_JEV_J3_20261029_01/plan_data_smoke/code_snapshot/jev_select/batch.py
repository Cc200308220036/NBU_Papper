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
        adapted={'tasks':tasks,'business_spec':business_spec(),'split_manifest':{'version':'jev_constructed_split_v1','partition':'diagnostic'},
                 'input_audit':{'adapter':'constructed_v1','status':'PASS','source_file_manifest':{},'included_base_scenarios':6,'source_groups':6,'derived_tasks':6,'excluded_variants':[]}}
    else:
        if dataset_root is None:raise JevSelectError('dataset_root_required')
        adapted=DatasetOrderAdapter().load(dataset_root,spec_config=spec_config,split_manifest=split_manifest)
    all_tasks=adapted['tasks'];tasks,scope=_scope(all_tasks,profile,partitions,source_limit)
    validate_tasks(tasks)
    jobs=_jobs(tasks,methods,config['display_order_seed'])
    root=_new_output(output);root.mkdir(parents=True)
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
        adapted={'tasks':tasks,'business_spec':business_spec(),'split_manifest':{'version':'jev_constructed_split_v1','partition':'diagnostic'},
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
    if plan['partitions']!=partitions or plan['method_order_seed']!=config['display_order_seed']:raise JevSelectError('scope_or_order_changed')
    if any(m not in METHODS_V2 for m in plan['methods']) or len(set(plan['methods']))!=len(plan['methods']):raise JevSelectError('invalid_methods')
    return {'status':'PASS','scope':'J3_FROZEN_PLAN','planned_tasks':len(tasks),'planned_jobs':len(expected_jobs),
            'source_orders':len({t['source_order_key'] for t in tasks}),'role':plan['role'],'model_api_calls':0}
