"""P4-A offline plan construction. No execution, model or transport imports.

Authentication reuses the existing capacity-one data projection. These new
versions deliberately have no registration in the public execution resolver.
"""
import copy
from collections import Counter
from pathlib import Path

from .contracts import canonical, digest, read, require, sha
from . import dataset

SEEDS=[11,23,37]
FIRST='NEW_00100027_controlled_base'
BASE='PCT/outputs/'
P3=BASE+'PCT_P3_20261115_01/'
QA=BASE+'PCT_P3_QA_20261115_01/'
VERSIONS={'training':'pct_p4a_training_plan_v1','evaluation':'pct_p4a_evaluation_template_v1'}
STATES=['NOT_RUN','RUNNING','COMPLETED','NATURAL_EMPTY_POOL','PREDICTED_STATIC_INSTABILITY',
        'UNASSESSABLE','TECHNICAL_FAILURE','UNKNOWN_SEND','CANCELLED','INCOMPLETE','NO_UPDATE']


def build_spec(repo):
    value=read(Path(repo)/'PCT/configs/p4a_plan_v1.json')
    require(value=={'version':'pct_p4a_build_spec_v1','ordering_seed':20261113,
                   'training_seeds':SEEDS,'epochs':125,'batch_orders':8,'selected_epoch':125,
                   'sending_admitted':False,'execution_admitted':False,
                   'storage_validation':'saved_P3_training_16_attempts_only'},'P4A_BUILD_SPEC_DRIFT')
    return value


def authenticated_catalog(repo):
    repo=Path(repo);parents,rows=dataset.authenticate(repo)
    legacy=repo/'PCT/outputs/PCT_P1_A_NBU_20261114_02/data'
    dataset.validate_data(repo,legacy,full_schema=True)
    archived=read(legacy/'dataset.json')
    spec=dataset.execution_spec(repo,repo/'PCT/configs/data_b1_v1.json')
    audit=read(repo/dataset.P0/'data_audit.json')
    syn=read(repo/dataset.SYN/'dataset.json')
    catalog=[];tasks=[]
    for row,parent,identity in rows:
        task=dataset.derive(row,parent,identity,spec);tasks.append(task)
        require(read(legacy/'tasks'/(task['task_id']+'.json'))==task,'P4A_DERIVED_DRIFT')
        train=row['path'].startswith(dataset.PACK+'/')
        catalog.append({'task_id':task['task_id'],'box_count':len(task['items']),
            'derived_task_digest':digest(task),'derived_seal':task['derived_task_digest'],
            'parent_path':row['path'],'parent_sha256':row['sha256'],'parent_digest':row['digest'],
            'parent_data_identity':identity,'original_order':row['original_order'],'source_group':row['source_group'],
            'source_component':row['conservative_component'],'variant':row['parent_layer'],
            'variant_family':row['original_order'] if train else None,
            'variant_siblings':[r['task_id'] for r,_,_ in rows if train and r['original_order']==row['original_order']],
            'parent_partition':row['partition'],'evaluation_layer':'training_in_sample' if train else 'exposed_familiar_prototype',
            'training_eligible':train,'exposure_use':row['purpose'],'independent_holdout':False,
            'source_relation':None if train else copy.deepcopy(syn['relations'][row['task_id']]),
            'feasibility':'UNKNOWN'})
    train=[t for t in catalog if t['training_eligible']]
    require(len(train)==16 and sum(t['box_count'] for t in train)==264 and len(catalog)==22
            and sum(t['box_count'] for t in catalog)==428,'P4A_DATA_DENOMINATOR')
    require(len({t['original_order'] for t in train})==4 and len({t['source_component'] for t in train})==3,'P4A_SOURCE_GROUPS')
    require(all(t['parent_partition']=='train' for t in train),'P4A_TRAIN_PARTITION')
    groups=[]
    for group in audit['component_groups']:
        members=[t for t in catalog if t['task_id'] in group['tasks']]
        components={t['source_component'] for t in members}
        require(len(components)==1,'P4A_GROUP_ID_DRIFT')
        groups.append({'component_id':next(iter(components)),'members':group['tasks'],
                       'relation_tokens':group['tokens'],'holdout_admitted':False})
    result={'version':'pct_p4a_data_catalog_v1','parents':parents,'capacity':1,'execution_spec':spec,
            'legacy_derived_data_identity':archived['data_identity'],'tasks':catalog,'groups':groups,
            'denominators':{'training_tasks':16,'training_boxes':264,'original_training_orders':4,
                            'conservative_training_components':3,'diagnostic_tasks':6,'diagnostic_boxes':164,
                            'diagnostic_components':1,'independent_holdout_sources':0},
            'interpretation':'parent test partition of familiar combinations is retained; exposed diagnostic use is not independent testing'}
    result['catalog_digest']=digest(result)
    return result,tasks


def input_identity(repo):
    repo=Path(repo)
    paths=[dataset.P0+'/p0_contract.json',dataset.P0+'/data_audit.json',dataset.P0+'/identity.json',
           dataset.PACK+'/manifest.json',dataset.PACK+'/source_manifest.json',dataset.SYN+'/dataset.json',
           'PCT/configs/data_b1_v1.json','PCT/configs/p4a_plan_v1.json',
           P3+'acceptance.json',P3+'identity.json',P3+'handoff.json',P3+'delivery_manifest.json',
           P3+'saved_audit.json',P3+'final_saved_audit.json',P3+'resource_metrics.json',
           QA+'quality_review.json',QA+'next_stage_admission.json',QA+'handoff.json',QA+'delivery_manifest.json',
           BASE+'PCT_P2_B_20261115_01/attempt_06/tests/model_manifest.json',
           BASE+'PCT_P2_C_20261115_01/attempt_03/tests/model_manifest.json']
    paths += [str(p.relative_to(repo)) for p in (repo/'PCT/src/pct_baseline').rglob('*.py')]
    paths += [str(p.relative_to(repo)) for p in (repo/'PCT/src/pct_baseline/schemas').glob('*.json')]
    paths += ['PCT/scripts/freeze_p4a.py','PCT/tests/test_p4a.py']
    paths += ['semantic_pallet_planner/src/semantic_pallet_planner/jev_select/'+n for n in
              ('episode.py','candidates.py','execution.py','packaging_versions.py','stability/monitor.py')]
    header=read(repo/P3/'attempt_02/jobs/diagnostic_geometry_b1_0/header.json')
    paths += ['semantic_pallet_planner/src/semantic_pallet_planner/jev_select/stability/'+name
              for name in header['config']['stability_monitor']['algorithm_identity']['files_sha256']]
    paths += ['Online-3D-BPP-PCT/Tools.py','PCT/src/pct_baseline/vendor/pct/upstream_manifest.json']
    return {p:sha(repo/p) for p in sorted(set(paths))}


def model_rows():
    return [{'model_id':f'pct_formal_{kind}_seed{seed}_epoch125_v1','method':method,'seed':seed,
             'feature_version':feature,'selected_epoch':125,'status':'PENDING_TRAINING','weights_sha256':None,
             'epochs':125,'attempts':2000,'action_cap':33000,'updates':250}
            for kind,method,feature in [('geo','pct_geo_b1','pct_adapted_geo_v1'),('load','pct_load_b1','pct_adapted_load_v1')]
            for seed in SEEDS]


def seal(value):
    value=copy.deepcopy(value);value['plan_digest']=digest(value);return value


def training_rules():
    return {'algorithm':'PCT-adapted+A2C','optimizer':{'name':'Adam','lr':0.0001,'max_grad_norm':0.5},
            'n':5,'gamma':1,'actor_coef':1,'critic_coef':1,'entropy_coef':0,
            'sampling':'categorical from frozen batch policy; seed all applicable RNG; restore decision RNG before sampling',
            'task_sampling':'each of 16 tasks once per epoch; equal task frequency, not equal source weighting; no score-based replacement',
            'traversal':'sort SHA256 canonical [seed,epoch,task_id], tie task_id; identical geo/load sequence for the same seed',
            'batch':'8 whole-order attempts with immutable policy snapshot; update only after complete valid batch',
            'reward':'10 * actually successfully committed volume / fixed container volume; failed placement reward 0',
            'returns':'disjoint chunks <=5; actual end-start length; each transition once; internal boundary bootstrap frozen V(next state)',
            'terminal':'natural completion/empty pool/predicted instability ends trajectory, bootstrap 0; empty pool done attaches to prior valid transition',
            'truncated':'explicit truncated=true and terminal=false; bootstrap next saved public state from collection snapshot; no fabricated terminal',
            'detach':'targets/bootstrap detach; actor advantage detach; critic gradients through current values only',
            'singleton':'actor weight 0; rewards/returns/critic retained; value-only forward counted separately, no policy-choice call',
            'empty':'no forward on empty pool; whole batch zero valid transitions => NO_UPDATE and stop diagnostic',
            'finite':'probabilities/loss/gradients/parameters must be finite; stop batch on violation',
            'technical_failure':'stop batch and campaign, retain partial shard and all remaining NOT_RUN slots; no implicit retry or replacement',
            'denominators':'all 6 models/12000 attempts/198000 action cap/1500 update slots retained; cancellation, incomplete, UNKNOWN_SEND, failure, NO_UPDATE distinct',
            'checkpoint_epochs':[25,50,75,100,125],'selection':'fixed final epoch125 for all six seeds, no best-epoch/seed selection on evaluation',
            'metrics':'per epoch complete/empty/instability/technical/unassessable/cancelled/not-run, full loading ratios, loss/value/entropy/gradient/time/cost; unknowns not zero',
            'resume':'atomic model+Adam+all applicable RNG+update ID+policy snapshot+epoch/task/attempt/segment cursor+batch-shard refs; no old order re-signing'}


def build_training(catalog,identity,spec):
    tasks=[t for t in catalog['tasks'] if t['training_eligible']];models=model_rows();schedules=[]
    for model in models:
        slots=[]
        for epoch in range(1,126):
            ordered=sorted(tasks,key=lambda t:(digest([model['seed'],epoch,t['task_id']]),t['task_id']))
            for task in ordered:
                index=len(slots)
                slots.append({'attempt_index':index,'epoch':epoch,'task_id':task['task_id'],
                              'task_digest':task['derived_task_digest'],'action_cap':task['box_count'],
                              'batch_id':index//8,'policy_snapshot_id':model['model_id']+f':before_update_{index//8:03d}',
                              'status':'NOT_RUN'})
        schedules.append({'model_id':model['model_id'],'attempts':slots})
    return seal({'version':VERSIONS['training'],'sending_admitted':False,'execution_admitted':False,
        'executor_status':'NOT_IMPLEMENTED_FORMAL_PROTOCOL','catalog_digest':catalog['catalog_digest'],
        'input_identity':identity,'build_spec':spec,'models':models,'schedules':schedules,'rules':training_rules(),
        'denominators':{'models':6,'tasks_per_epoch':16,'boxes_per_epoch':264,'attempts_per_model':2000,
                        'updates_per_model':250,'actions_per_model':33000,'total_attempts':12000,
                        'total_updates':1500,'total_action_cap':198000},'status_values':STATES})


def build_evaluation(catalog,identity,spec,training):
    tasks=catalog['tasks'];order_seed=spec['ordering_seed']
    ordered=[next(t for t in tasks if t['task_id']==FIRST)]+sorted([t for t in tasks if t['task_id']!=FIRST],
             key=lambda t:(digest([order_seed,'task_block',t['task_id']]),t['task_id']))
    jobs=[]
    for block,task in enumerate(ordered):
        variants=[('geometry_b1',None,None,None)]
        variants += [(m['method'],m['seed'],None,m['model_id']) for m in model_rows()]
        variants += [('jev_none_b1',None,r,None) for r in range(3)]
        local=[]
        for method,seed,repeat,model_id in variants:
            suffix=f's{seed}' if seed is not None else f'r{repeat}' if repeat is not None else 'deterministic'
            jid=task['task_id']+'/'+method+'/'+suffix
            n=task['box_count'];pct=method.startswith('pct_');jev=method=='jev_none_b1'
            local.append({'job_id':jid,'block':block,'task_id':task['task_id'],'task_digest':task['derived_task_digest'],
                'source_component':task['source_component'],'source_layer':task['evaluation_layer'],
                'parent_partition':task['parent_partition'],'method':method,'seed':seed,'repeat':repeat,
                'model_id':model_id,'model_status':'PENDING_TRAINING' if pct else 'NA', 'weights_sha256':None,
                'box_count':n,'action_cap':n,'monitor_cap':n,'send_cap':n if jev else 0,'network_choice_cap':n if pct else 0,
                'sending_admitted':False,'execution_admitted':False,'status':'NOT_RUN',
                'p4c_probe_budget':1 if task['task_id']==FIRST and jev and repeat==0 else 0})
        local.sort(key=lambda j:(digest([order_seed,'slot',j['task_id'],j['method'],j['seed'],j['repeat']]),j['job_id']))
        if block==0:
            anchor=next(j for j in local if j['p4c_probe_budget']==1)
            local=[anchor]+[j for j in local if j!=anchor]
        for j in local:j['order_index']=len(jobs);jobs.append(j)
    return seal({'version':VERSIONS['evaluation'],'sending_admitted':False,'execution_admitted':False,
        'executor_status':'TEMPLATE_ONLY_NO_DISPATCH','catalog_digest':catalog['catalog_digest'],
        'input_identity':identity,'training_plan_digest':training['plan_digest'],'ordering_seed':order_seed,
        'ordering_rule':'first task block fixed, first slot Jev r0; remaining blocks SHA256 [seed,task_block,task_id]; within block SHA256 [seed,slot,task_id,method,seed,repeat]; tie IDs',
        'jobs':jobs,'denominators':{'tasks':22,'boxes':428,'slots':220,'training_in_sample_slots':160,
            'exposed_familiar_slots':60,'jev_send_cap':1284,'local_network_choice_cap':2568,'monitor_cap':4280},
        'status_values':STATES,'resume_and_failure':'one attempt per original slot; UNKNOWN_SEND consumes actual/unknown send balance and stops; no retry or replacement; P4-C one send is within first slot; P4-D resumes saved prefix/remaining budget',
        'derived_plan_contract':'after six genuine final epoch125 models pass P4-B, create a NEW plan binding actual model manifest/weights and approvals; preserve template and all slot IDs/order/caps; no P3 weights or fake SHA',
        'analysis':{'primary_direction':'pct_load_b1 - jev_none_b1','secondary':['pct_load_b1 - pct_geo_b1','learning_methods - geometry_b1'],
            'aggregation':'average repeats/seeds within task; average four variants within original order, then conservative component; describe familiar combinations separately',
            'ranking':'technical invalid pairs never rank partial layout; unassessable separate; retain all denominators; stable completion then volume ratio then count/mass and equivalent-loading height/envelope',
            'independence':'0 admitted unseen sources; no box/decision/seed/repeat as independent source; descriptive results only',
            'full_loading':'fixed-container utilization equal when same entire order loaded; compare additional layout metrics without low-loading height advantage'}})


def validate_plan(kind,value,catalog,identity,spec,training=None):
    from jsonschema import Draft202012Validator
    schema=read(Path(__file__).parent/'schemas'/f'p4a_{kind}_v1.schema.json')
    Draft202012Validator.check_schema(schema);Draft202012Validator(schema).validate(value)
    require(value['plan_digest']==digest({k:v for k,v in value.items() if k!='plan_digest'}),'P4A_PLAN_SEAL')
    expected=build_training(catalog,identity,spec) if kind=='training' else build_evaluation(catalog,identity,spec,training)
    require(value==expected,'P4A_PLAN_IDENTITY_OR_CONTRACT_DRIFT')
    require(value['sending_admitted'] is False and value['execution_admitted'] is False,'P4A_NO_EXECUTION')
    if kind=='training':
        for m,schedule in zip(value['models'],value['schedules']):
            require(len(schedule['attempts'])==2000 and sum(a['action_cap'] for a in schedule['attempts'])==33000,'P4A_ATTEMPT_BUDGET')
            require(set(Counter(a['task_id'] for a in schedule['attempts']).values())=={125},'P4A_TRAVERSAL')
    else:
        jobs=value['jobs'];require(len(jobs)==len({j['job_id'] for j in jobs})==220,'P4A_SLOTS')
        require(sum(j['send_cap'] for j in jobs)==1284 and sum(j['network_choice_cap'] for j in jobs)==2568,'P4A_EVAL_BUDGET')
        require(sum(j['p4c_probe_budget'] for j in jobs)==1 and jobs[0]['job_id']==FIRST+'/jev_none_b1/r0','P4A_PROBE_SLOT')
    return {'status':'PASS_PLAN_ONLY','kind':kind,'execution_admitted':False,'sending_admitted':False}


def require_executable(value):
    # Deliberately unconditional: a template is never a dispatch permit even
    # when someone edits a bool or re-signs its JSON digest.
    raise ValueError('P4A_PLAN_ONLY_NO_EXECUTOR_OR_SEND_ADMISSION')


def check_input_identity(repo,identity):
    repo=Path(repo).resolve()
    for name,expected in identity.items():
        path=(repo/name).resolve()
        require(not Path(name).is_absolute() and path.is_relative_to(repo) and
                path.is_file() and sha(path)==expected,'P4A_INPUT_IDENTITY_DRIFT:'+name)
    return True
