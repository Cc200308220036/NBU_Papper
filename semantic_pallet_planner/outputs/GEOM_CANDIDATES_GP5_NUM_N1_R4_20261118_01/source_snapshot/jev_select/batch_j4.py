"""J4 frozen five-method lifecycle, retrieval records and offline recovery."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from .config import load_v3_config, is_v3, config_for_memory, memory_mode_for_method
from .contracts import JevSelectError, digest, validate_schema
from .ledger import read, write, exclusive, Ledger
from .memory_store import empty_snapshot, validate_snapshot, freeze_snapshot, load_snapshot

METHODS = ('shared_geometry', 'shared_business_lexicographic', 'jev_no_memory')
REGISTERED_METHODS = (*METHODS, 'jev_raw_history', 'jev_memory_cards')


def assets_manifest():
    root=Path(__file__).resolve().parent
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root/'viewer').glob('*')) if p.is_file() and p.suffix in ('.html','.js','.css','.mjs')}


def prepare_j4(output, *, profile='constructed-dev', mode='offline', dataset_root=None,
               source_limit=4, methods=METHODS, config=None, memory=None, api_budget=None,
               offline_scenario='normal', verification='records', task_limit=None, task_ids=None,
               spec_config=None, difficulty=None):
    from .experiment import _new_output, source_manifest, file_manifest, InputAdapter, validate_tasks
    from .batch import _jobs, _scope
    from .context import QUESTION_V3, OBJECTIVE_V2
    from .dataset import DatasetOrderAdapter
    SCENARIOS = ("normal", "pick_last", "invalid_choice", "wrong_model", "wrong_probabilities", "non_json", "timeout", "http_429", "http_529")
    if profile not in ('constructed-dev','dev') or mode not in ('offline','remote'):
        raise JevSelectError('invalid_j4_scope')
    if not methods or len(set(methods))!=len(methods) or any(m not in REGISTERED_METHODS for m in methods):
        raise JevSelectError('invalid_j4_methods')
    if verification!='records':raise JevSelectError('j4_b0_only_records_verification')
    if offline_scenario not in SCENARIOS:raise JevSelectError('invalid_offline_scenario')
    if mode=='remote' and (type(api_budget) is not int or not 1<=api_budget<=10000):
        raise JevSelectError('explicit_finite_api_budget_required')
    cfg=load_v3_config() if config is None else dict(config)
    validate_schema('config',cfg)
    if not is_v3(cfg) or cfg['memory_mode']!='none':raise JevSelectError('j4_b0_requires_v3_no_memory')
    from .memory_store import indexed_snapshot
    snapshot=empty_snapshot()
    experience=indexed_snapshot([]) if memory is None else load_snapshot(memory,remote=mode=='remote')
    validate_snapshot(experience,remote=mode=='remote')
    snapshots={m:experience if memory_mode_for_method(m)!='none' else snapshot for m in methods}
    bindings={m:memory_binding(snapshots[m],m) for m in methods}
    if profile=='constructed-dev':
        if spec_config is not None or difficulty is not None: raise JevSelectError('business_spec_requires_dataset_profile')
        tasks=InputAdapter().load('constructed-smoke')[0]
        for t in tasks:t.update(partition='diagnostic',business_configuration='diagnostic')
        adapted={'input_audit':{'adapter':'constructed_v1'},'split_manifest':{},'business_spec':{}}
        partitions=[]
    else:
        if dataset_root is None:raise JevSelectError('dataset_root_required')
        adapted=DatasetOrderAdapter().load(dataset_root,spec_config=spec_config,difficulty=difficulty)
        tasks,partitions=_scope(adapted['tasks'],'dataset-dev',None,source_limit)
    if task_ids is not None:
        if not task_ids or len(set(task_ids))!=len(task_ids) or not set(task_ids).issubset({t['task_id'] for t in tasks}):
            raise JevSelectError('invalid_explicit_task_selection')
        tasks = [t for t in tasks if t['task_id'] in task_ids]
    if task_limit is not None:
        if type(task_limit) is not int or task_limit<1:raise JevSelectError('invalid_task_limit')
        tasks=tasks[:task_limit]
    validate_tasks(tasks)
    jobs=_jobs(tasks,methods,cfg['display_order_seed'])
    cfg.update(memory_snapshot_digest=digest(snapshot.data), memory_corpus_digest=snapshot.data['corpus_digest'])
    cfg['experiment_binding']=digest([tasks,jobs,mode,api_budget,cfg,bindings,source_manifest(),assets_manifest()])
    root=_new_output(output);root.mkdir(parents=True)
    freeze_snapshot(snapshot,root/'memory')
    if any(memory_mode_for_method(m)!='none' for m in methods):
        exports=[] if memory is None else [read(p) for p in sorted((Path(memory)/'evidence').glob('*.json'))]
        artifacts = {} if memory is None else {str(p.relative_to(Path(memory)/'artifacts')):read(p)
            for p in (Path(memory)/'artifacts').rglob('*.json')}
        freeze_snapshot(experience,root/'memory_experience',evidence_exports=exports,artifacts=artifacts)
    write(root/'config.snapshot.json',cfg)
    write(root/'private/input_snapshot.json',{'tasks':tasks})
    write(root/'input_manifest.json',{'tasks_digest':digest(tasks),'input_audit':adapted['input_audit']})
    write(root/'split_manifest.json',adapted['split_manifest']);write(root/'public/business_spec.json',adapted['business_spec'])
    registry=[{'task_id':t['task_id'],'task_digest':digest(t),'source_group_id':t['source_order_key'],
               'partition':t['partition'],'business_configuration':t['business_configuration']} for t in tasks]
    plan={'version':'jev_plan_v3','experiment_protocol':cfg['experiment_protocol'],'profile':profile,'mode':mode,
          'partitions':partitions,'source_limit':source_limit,'task_limit':task_limit,'methods':list(methods),'jobs':jobs,'task_registry':registry,
          'offline_scenario':offline_scenario if mode=='offline' else None,
          'budget':{'global_attempts':api_budget or 128,'per_job_attempts':api_budget or 32},'workers':1,
          'cache_policy':'clear_generation_and_business_caches_before_each_job','method_order_seed':cfg['display_order_seed'],
          'input_manifest_digest':digest(read(root/'input_manifest.json')),'business_spec_digest':digest(adapted['business_spec']),
          'split_digest':digest(adapted['split_manifest']),'config_digest':digest(cfg),'role':'diagnostic' if profile=='constructed-dev' else 'development',
          'pricing':{'currency':'USD','input_per_million':.042,'output_per_million':0.,'source':'historical_reference_not_current_billing','verified_date':'2026-10-29'},
          'memory_snapshot_digest':digest(snapshot.data),'memory_bindings':bindings,'verification':'records'}
    validate_schema('plan_v3',plan)
    write(root/'plan.json',plan);write(root/'source_manifest.json',source_manifest());write(root/'assets_manifest.json',assets_manifest())
    package=Path(__file__).resolve().parents[1]
    for rel in source_manifest():
        target=root/'code_snapshot'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(package/rel,target)
    for rel in assets_manifest():
        target=root/'code_snapshot/jev_select'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(Path(__file__).parent/rel,target)
    write(root/'prompt.json',{'question':QUESTION_V3,'objective':OBJECTIVE_V2})
    write(root/'delivery_manifest.json',file_manifest(root))
    validate_plan_j4(root)
    return {'status':'PASS','scope':'J4_B1_FROZEN_PLAN','planned_tasks':len(tasks),'planned_jobs':len(jobs),'model_api_calls':0}


def validate_plan_j4(root):
    from .experiment import file_manifest, source_manifest, validate_tasks
    from .batch import _jobs
    from .context import QUESTION_V3, OBJECTIVE_V2
    root=Path(root)
    if file_manifest(root)!=read(root/'delivery_manifest.json'):raise JevSelectError('j4_plan_changed')
    plan=read(root/'plan.json');cfg=read(root/'config.snapshot.json')
    validate_schema('plan_v3',plan);validate_schema('config',cfg)
    if not is_v3(cfg) or plan['config_digest']!=digest(cfg):raise JevSelectError('j4_config_changed')
    if source_manifest()!=read(root/'source_manifest.json') or assets_manifest()!=read(root/'assets_manifest.json'):
        raise JevSelectError('source_changed')
    snapshot=load_snapshot(root/'memory',plan['memory_snapshot_digest'],remote=plan['mode']=='remote')
    if cfg['memory_snapshot_digest']!=digest(snapshot.data) or cfg['memory_corpus_digest']!=snapshot.data['corpus_digest']:raise JevSelectError('plan_memory_mismatch')
    if 'memory_bindings' in plan and set(plan['memory_bindings'])!=set(plan['methods']):raise JevSelectError('plan_memory_methods_changed')
    tasks=read(root/'private/input_snapshot.json')['tasks'];validate_tasks(tasks)
    if (plan['jobs']!=_jobs(tasks,plan['methods'],cfg['display_order_seed']) or
            read(root/'input_manifest.json')['tasks_digest']!=digest(tasks) or
            plan['input_manifest_digest']!=digest(read(root/'input_manifest.json'))):raise JevSelectError('j4_inputs_changed')
    if read(root/'prompt.json')!={'question':QUESTION_V3,'objective':OBJECTIVE_V2}:raise JevSelectError('j4_prompt_changed')
    snapshots={}
    for method in plan['methods']:
        binding=plan.get('memory_bindings',{}).get(method)
        selected=load_snapshot(root/binding['path'],binding['snapshot_digest'],remote=plan['mode']=='remote') if binding else snapshot
        if binding and binding!=memory_binding(selected,method):raise JevSelectError('plan_memory_binding_changed')
        snapshots[method]=selected
    if 'jev_raw_history' in snapshots and 'jev_memory_cards' in snapshots and snapshots['jev_raw_history'].data['corpus_digest']!=snapshots['jev_memory_cards'].data['corpus_digest']:
        raise JevSelectError('memory_corpus_arm_mismatch')
    return plan,cfg,tasks,snapshots


def preflight_j4(plan_root, *, api_key_file=None):
    from .episode import decision_inputs
    from semantic_pallet_planner.o4.buffer.buffer_state import initial, receive, can_wait
    plan,cfg,tasks,memory=validate_plan_j4(plan_root);task=tasks[0];job=plan['jobs'][0]
    state=initial(task['container'],3);cursor=0
    while can_wait(state):
        if cursor<len(task['items']):
            item=task['items'][cursor];state=receive(state,item,task['attributes'][item['item_id']]);cursor+=1
        else:state=receive(state,eos=True)
    arms={};base=None
    from .contracts import canonical
    for method in plan['methods']:
        context=decision_inputs(state,task,config_for_memory(cfg,method,memory[method]),'PREFLIGHT','PREFLIGHT_D0000',memory_snapshot=memory[method])[3]
        data=context.data;body=data['request_body']
        if body is not None:
            body['state'].pop('memories')
            if base is not None and canonical(body)!=base:raise JevSelectError('memory_arm_public_body_mismatch')
            base=canonical(body)
        arms[method]={'candidates':len(data['criteria']),'physical_digest':data['local_binding']['physical_digest'],
            'query_digest':data['retrieval']['query_digest'],'selected_items':len(data['model_state']['memories']),
            'canonical_utf8_bytes':data['retrieval']['utf8_bytes'],'status':data['retrieval']['status']}
    lookup={t['task_id']:t for t in tasks}
    return {'status':'PASS','scope':'J4_B1_PREFLIGHT','credential_readiness':'NOT_CHECKED_OFFLINE_PREFLIGHT','model_api_calls':0,
            'planned_jobs':len(plan['jobs']),'memory_bindings':plan.get('memory_bindings',{}),
            'first_candidates':len(context.data['criteria']),'arms':arms,'public_body_equal':True,
            'natural_choice_upper_bound':sum(len(lookup[j['task_id']]['items']) for j in plan['jobs'] if j['method'].startswith('jev_'))}


def audit_records_j4(root):
    """Validate stored bindings, response parsing, poses and denominators, no simulation."""
    from .context import validate_context
    from .contracts import DecisionContext, CandidateBundle
    from .selector import parse_response
    root=Path(root);plan,cfg,tasks,memory=validate_plan_j4(root/'plan')
    attempts=Ledger(root,plan['budget'],readonly=True).data['attempts'];by_attempt={a['attempt_id']:a for a in attempts}
    jobs=read(root/'audit/jobs.json');rows=[];placements=0
    if (len(jobs)!=len(plan['jobs']) or
            [{k:j[k] for k in expected} for j,expected in zip(jobs,plan['jobs'])]!=plan['jobs']):
        raise JevSelectError('j4_job_denominator_changed')
    for job in plan['jobs']:
        ep=read(root/'episodes'/f"{job['job_id']}.json")
        if ep['job_id']!=job['job_id'] or ep['summary']['task_id']!=job['task_id'] or ep['summary']['selector_backend']!=job['method']:
            raise JevSelectError('record_job_identity_changed')
        if read(root/'checkpoints'/f"{job['job_id']}.json")!=ep['checkpoint']:raise JevSelectError('record_checkpoint_changed')
        row=dict(ep['summary'],job_id=job['job_id'],execution_status='RECORDED' if ep['summary']['termination_reason'] in ('ALL_ITEMS_PLACED','STOP_NO_PHYSICAL_CANDIDATE') else 'FAILED')
        validate_schema('order_metrics_v3',row);validate_schema('checkpoint_v3',ep['checkpoint'])
        if ep['checkpoint']['config_digest']!=digest(config_for_memory(cfg,job['method'],memory[job['method']])):raise JevSelectError('record_checkpoint_config_changed')
        if ep['checkpoint']['memory_snapshot_digest']!=digest(memory[job['method']].data):raise JevSelectError('record_memory_changed')
        cfg_job=config_for_memory(cfg,job['method'],memory[job['method']])
        frozen=memory_binding(memory[job['method']],job['method'])
        expected_identity={k:frozen[k] for k in ('corpus_digest','index_digest','mode_index_digest')}
        expected_identity.update(retrieval_config_digest=frozen['config_digest'],memory_mode=frozen['mode'],retrieval_version=cfg_job['retrieval_version'])
        if ep['checkpoint'].get('memory_identity')!=expected_identity:raise JevSelectError('record_checkpoint_memory_identity_changed')
        prefix=None;count=0
        for e in ep['events']:
            if prefix is not None and prefix!=e['before']:raise JevSelectError('record_state_discontinuity')
            prefix=e['after']
            if not e.get('context'):continue
            ctx=DecisionContext.from_dict(e['context'])
            validate_context(ctx,e['observation'],CandidateBundle.from_dict(e['bundle']),cfg_job)
            from .memory_retrieval import validate_saved_retrieval
            if 'retrieval' in ctx.data:
                validate_saved_retrieval(ctx.data['retrieval'],snapshot=memory[job['method']])
                if read(root/'retrievals'/job['job_id']/f"{e['decision_id']}.json")!=ctx.data['retrieval']:
                    raise JevSelectError('record_retrieval_changed')
            did=e['decision_id']
            if ctx.data['local_binding'].get('job_id')!=job['job_id'] or ctx.data['local_binding'].get('decision_id')!=did:
                raise JevSelectError('record_decision_identity_changed')
            if read(root/'mappings'/job['job_id']/f'{did}.json')!=ctx.data:raise JevSelectError('record_mapping_changed')
            if read(root/'requests'/job['job_id']/f'{did}.json')!=ctx.data['request_body']:raise JevSelectError('record_request_changed')
            sel=e.get('selection')
            if not sel:continue
            validate_schema('selection_result',sel)
            if sel['local_binding_digest']!=digest(ctx.data['local_binding']):raise JevSelectError('record_selection_changed')
            if sel['attempt_ids']:
                a=by_attempt[sel['attempt_ids'][0]]
                if a['job_id']!=job['job_id'] or a['decision_id']!=did or a['body_digest']!=digest(ctx.data['request_body']) or a['binding_digest']!=digest(ctx.data['local_binding']):raise JevSelectError('record_attempt_changed')
                if parse_response(ctx,a,cfg_job).data!=sel:raise JevSelectError('record_response_changed')
            if e['event']=='PLACE':
                count+=1;entry=ctx.data['display_mapping'][sel['selected_display_id']];c=ctx.data['criteria'][sel['selected_display_id']]
                placed=[o for o in e['after']['placed_items'] if o['item_id']==entry['pick_item_id']]
                if len(placed)!=1 or placed[0]['pose']!=c['pose'] or e['action']!=e['proposed_action'] or e['action']['candidate_id']!=entry['candidate_id']:
                    raise JevSelectError('record_action_changed')
        if count!=row['placed_items'] or prefix!=ep['final_state']:raise JevSelectError('record_final_state_changed')
        from .memory_retrieval import memory_statistics
        if row.get('memory_statistics')!=memory_statistics(ep['events']):raise JevSelectError('record_memory_metrics_changed')
        if ep['checkpoint']['events']!=ep['events'] or ep['checkpoint']['state']!=ep['final_state'] or ep['checkpoint']['reason']!=row['termination_reason']:
            raise JevSelectError('record_checkpoint_binding_changed')
        placements+=count;rows.append(row)
    return {'status':'PASS','scope':'J4_SAVED_RECORDS_NO_REPLAY','verified_jobs':len(rows),'verified_placements':placements,
            'new_model_calls':0,'candidate_regenerations':0,'environment_steps':0},rows


def run_j4(plan_root, output, *, offline=False, remote=False, api_key_file=None, resume=False, hook=None):
    from .experiment import _new_output, file_manifest
    from .batch import _clear_job_caches
    from .episode import run_episode
    from .selector import LocalSelector,JevSelector
    from .transport import JevTransport
    from .evaluation import aggregate
    plan,cfg,tasks,memory=validate_plan_j4(plan_root)
    if offline==remote or plan['mode']!=('remote' if remote else 'offline'):raise JevSelectError('explicit_matching_mode_required')
    root=Path(output).resolve()
    identity=digest([plan,cfg])
    if not resume:
        root=_new_output(root);root.mkdir(parents=True);shutil.copytree(plan_root,root/'plan')
        write(root/'identity.json',{'digest':identity});write(root/'audit/jobs.json',[dict(j,status='NOT_RUN') for j in plan['jobs']])
    elif read(root/'identity.json')!={'digest':identity}:raise JevSelectError('resume_identity_changed')
    with exclusive(root):
        if (root/'delivery_manifest.json').exists():
            from .dataset_j4 import verify_seal
            if verify_seal(root)['status']!='PASS':raise JevSelectError('experiment_files_changed')
            return audit_records_j4(root)[0]
        ledger=Ledger(root,plan['budget'],origin='jev' if remote else 'test_double',hook=hook)
        jobs=read(root/'audit/jobs.json');lookup={t['task_id']:t for t in tasks}
        for index,job in enumerate(plan['jobs']):
            _clear_job_caches();jid=job['job_id'];cfg_job=config_for_memory(cfg,job['method'],memory[job['method']])
            if job['method'].startswith('jev_'):
                if offline:
                    from .testing import OfflineTransport
                    transport=OfflineTransport(cfg_job,plan['offline_scenario'])
                else:transport=JevTransport(cfg_job,api_key_file=api_key_file)
                selector=JevSelector(cfg_job,ledger,jid,transport)
            else:selector=LocalSelector(job['method'])
            cp_path=root/'checkpoints'/f'{jid}.json'
            def checkpoint(value):write(cp_path,value)
            def event_hook(phase,value):
                if phase=='decision_ready':
                    did=value['decision_id'];ctx=value['context']
                    write(root/'requests'/jid/f'{did}.json',ctx['request_body'])
                    write(root/'mappings'/jid/f'{did}.json',ctx)
                    write(root/'retrievals'/jid/f'{did}.json',ctx['retrieval'])
                if hook:hook(phase,value)
            # Completed jobs still undergo checkpoint identity/reconstruction validation on resume.
            cp=read(cp_path) if cp_path.exists() else None
            if cp:
                saved_events=cp['events']+([cp['pending_event']] if cp['pending_event'] else [])
                for saved in saved_events:
                    if not saved.get('context'):continue
                    did=saved['decision_id'];ctx=saved['context']
                    from .context import validate_context
                    from .contracts import DecisionContext
                    validate_context(DecisionContext.from_dict(ctx),config=cfg_job)
                    for path,value in ((root/'mappings'/jid/f'{did}.json',ctx),
                        (root/'requests'/jid/f'{did}.json',ctx['request_body']),
                        (root/'retrievals'/jid/f'{did}.json',ctx['retrieval'])):
                        if path.exists() and read(path)!=value:raise JevSelectError('saved_decision_files_changed')
                        if not path.exists():write(path,value)
            jobs[index]['status']='RUNNING';write(root/'audit/jobs.json',jobs)
            ep=run_episode(lookup[job['task_id']],selector,cfg_job,job_id=jid,method=job['method'],
                           resume=cp,on_checkpoint=checkpoint,hook=event_hook,memory_snapshot=memory[job['method']])
            if ep['summary'] is None:
                jobs[index]['status']='NEEDS_RECOVERY';write(root/'audit/jobs.json',jobs)
                return {'status':'NEEDS_RECOVERY','job_id':jid}
            checkpoint(ep['checkpoint'])
            write(root/'episodes'/f'{jid}.json',ep)
            jobs[index]['status']='RECORDED' if ep['summary']['termination_reason'] in ('ALL_ITEMS_PLACED','STOP_NO_PHYSICAL_CANDIDATE') else 'FAILED'
            write(root/'audit/jobs.json',jobs)
        report,rows=audit_records_j4(root)
        write(root/'metrics/rows.json',rows)
        summary=aggregate(rows,ledger.data['attempts'],mode=plan['mode'],pricing=plan['pricing'])
        summary.update(version='jev_metrics_v3',experiment_protocol=cfg['experiment_protocol'],business_mode='evaluate_only',
            cache_policy=plan['cache_policy'],planned_tasks=len(tasks),complete_jobs=sum(r['completed'] for r in rows),
            clean_completed_jobs=sum(r['clean_completed'] for r in rows),execution_failures=sum(r['execution_status']=='FAILED' for r in rows),
            role=plan['role'],workers=1,unknown_delivery_attempts=sum(a['state']=='UNKNOWN_IN_FLIGHT' for a in ledger.data['attempts']))
        from .memory_retrieval import memory_statistics
        summary['memory_statistics']=memory_statistics([e for p in (root/'episodes').glob('*.json') for e in read(p)['events']])
        validate_schema('metrics_v3',summary)
        write(root/'metrics/summary.json',summary);write(root/'record_audit.json',report)
        write(root/'verification_report.json',dict(report,verification='records',full_replay_performed=False))
        from .viewer import build_process_viewer
        build_process_viewer([read(root/'episodes'/f"{j['job_id']}.json") for j in plan['jobs']],root/'process',source_root=root)
        write(root/'delivery_manifest.json',file_manifest(root))
        return report


def memory_binding(snapshot, method):
    from .memory_retrieval import snapshot_index, mode_index
    index=snapshot_index(snapshot);mode=memory_mode_for_method(method)
    return {'path':'memory' if mode=='none' else 'memory_experience','snapshot_digest':digest(snapshot.data),
            'corpus_digest':snapshot.data['corpus_digest'],'index_digest':digest(index),
            'mode_index_digest':digest(mode_index(index,mode)), 'config_digest':index['config_digest'],
            'mode':mode,'fixture_only':snapshot.data['fixture_only']}
