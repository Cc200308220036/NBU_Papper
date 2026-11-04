"""JN0 frozen full orders over run_episode, with explicit whole-matrix accounting."""
from __future__ import annotations
import copy
import hashlib
import shutil
import time
from pathlib import Path

from .contracts import JevSelectError, digest, validate_schema
from .ledger import read, write, exclusive
from .experiment import source_manifest, file_manifest
from .packaging_runtime import load_runtime_dataset, physical_manifest, evaluate_state
from .packaging_protocol import (PLAN_VERSION, RUN_VERSION, EXECUTION_VERSION, METHOD_REGISTRY,
                                 METRICS_CONTRACT, selector_factory, termination_category)
from .packaging_metrics import job_metrics, aggregate, paired
from .stability.monitor import load_monitor_config, preflight

# Source-checkout runner: module lives at <repo>/semantic_pallet_planner/src/
# semantic_pallet_planner/jev_select/. Resolve the module, never the caller cwd.
REPO = Path(__file__).resolve().parents[4]
STOP_CATEGORIES = frozenset(('ERROR','COMMIT_FAILURE','SELECTION_FAILURE','TECHNICAL_LIMIT','CANCELED'))


def require(ok, code):
    if not ok:
        raise JevSelectError(code)


def relative(path):
    return Path(path).resolve().relative_to(REPO).as_posix()


def new_output(path):
    require(not Path(path).is_symlink(), 'full_order_output_exists')
    path = Path(path).resolve()
    allowed = REPO/'semantic_pallet_planner/outputs'
    require(path.is_relative_to(allowed) and path != allowed, 'full_order_output_directory')
    require(not path.exists() and not path.is_symlink(), 'full_order_output_exists')
    # Archive policy is independent of filesystem safety. Resolve parent symlinks
    # before checking containment; mkdir without exist_ok also refuses races.
    path.mkdir(parents=True)
    return path


def inventory(dataset, data):
    """Private pre-run audit; never passed to a selector."""
    sources = read(Path(dataset)/'source_manifest.json')
    split = read(Path(dataset)/'split_manifest.json')
    rows=[]
    for task in sorted(data['tasks'],key=lambda t:t['task_id']):
        frozen = read(Path(dataset)/'tasks'/f"{task['task_id']}.json")
        masses=[i['mass_kg'] for i in task['items']]
        capacities=[i['top_load_limit_kg_synthetic'] for i in task['items']]
        rows.append({'task_id':task['task_id'],'source_group_id':task['source_group_id'],
            'source_order_key':task['source_order_key'],'variant':task['layer'],'partition':task['partition'],
            'exposure':'PREVIOUSLY_EXPOSED_TRAIN','feasibility_status':task['feasibility_status'],
            'items':len(task['items']),'mass_kg':sum(masses), 'mass_range_kg':[min(masses),max(masses)],
            'distinct_mass_count':len(set(masses)), 'distinct_capacity_count':len(set(capacities)),
            'capacity_range_kg':[min(capacities),max(capacities)],
            'nonstackable_count':sum(not i['stackable'] for i in task['items']),
            'attribute_provenance':[{'item_id':i['item_id'],'physical_provenance':i['physical_provenance'],
                'capacity_provenance':i['capacity_provenance'],'profile':i['packaging_profile_id']} for i in frozen['items']]})
    return {'version':'jev_packaging_task_inventory_v1','data_identity':data['data_identity'],
            'sources':sources,'split':split,'tasks':rows}


def select_tasks(task_inventory):
    # One per exposed source. Prefer the richest capacity/mass heterogeneity,
    # then larger orders and lexicographic ID. No trajectory outcomes involved.
    groups={}
    for t in task_inventory['tasks']:
        groups.setdefault(t['source_group_id'],[]).append(t)
    chosen=[]
    for group in sorted(groups):
        chosen.append(sorted(groups[group], key=lambda t:(-t['distinct_capacity_count'],
            -t['distinct_mass_count'],-t['items'],t['task_id']))[0]['task_id'])
    return chosen[:4]


def prepare_packaging_plan(dataset_root, run_spec, output):
    require(set(run_spec)<= {'task_ids','method_ids','watchdog'},'full_order_unknown_run_spec')
    data=load_runtime_dataset(dataset_root)
    inv=inventory(dataset_root,data)
    ids=run_spec.get('task_ids',select_tasks(inv)); methods=run_spec.get('method_ids',list(METHOD_REGISTRY))
    require(isinstance(ids,list) and 1<=len(ids)<=4 and len(set(ids))==len(ids),'full_order_task_scope')
    require(isinstance(methods,list) and methods==list(METHOD_REGISTRY),'full_order_local_pair_required')
    tasks={t['task_id']:t for t in data['tasks']}
    require(all(t in tasks and tasks[t]['partition']=='train' for t in ids),'full_order_unplanned_task')
    watchdog=run_spec.get('watchdog',{'max_events':10000,'max_active_wall_s':600})
    require(set(watchdog)=={'max_events','max_active_wall_s'} and type(watchdog['max_events']) is int
        and watchdog['max_events']>0 and type(watchdog['max_active_wall_s']) in (int,float)
        and watchdog['max_active_wall_s']>0,'full_order_invalid_watchdog')
    jobs=[]
    for tid in ids:
        for method in methods:
            task=tasks[tid]
            cfg=load_monitor_config(data_identity=data['data_identity'],task_digest=digest(task),method=method,enabled=True)
            preflight(cfg)
            jobs.append({'job_id':f'J{len(jobs):04d}','task_id':tid,'method_id':method,
                'task_digest':digest(task),'config':cfg,'source_group_id':task['source_group_id'],'variant':task['layer']})
    plan={'version':PLAN_VERSION,'execution_version':EXECUTION_VERSION,'dataset':relative(dataset_root),
        'data_identity':data['data_identity'],'task_ids':ids,'method_ids':methods,'jobs':jobs,
        'selection_rule':'one/source, descending distinct capacity then mass then size; lexicographic task ID; first four source groups',
        'selection_mode':'DETERMINISTIC_RULE' if 'task_ids' not in run_spec else 'EXPLICIT_PREREGISTERED',
        'watchdog':watchdog,'termination_contract':'natural complete/failure; watchdog TECHNICAL_LIMIT; cancellation CANCELED; unstarted NOT_RUN; stop batch on technical error',
        'watchdog_boundary':'event count and active wall checked at durable stages; no preemption inside a candidate/LP call',
        'source_manifest':source_manifest(),'physical_manifest':physical_manifest(),
        'method_contract':METHOD_REGISTRY,'metrics_contract':METRICS_CONTRACT,
        'inventory_digest':digest(inv)}
    validate_schema('packaging_full_order_plan_v1',plan)
    root=new_output(output)
    write(root/'plan.json',plan);write(root/'task_inventory.json',inv)
    for jid in jobs:
        write(root/'tasks'/f"{jid['task_id']}.json",tasks[jid['task_id']])
    package=Path(__file__).resolve().parents[1]
    for name in plan['source_manifest']:
        dest=root/'code_snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(package/name,dest)
    write(root/'plan_receipt.json',{'version':PLAN_VERSION,'plan_digest':digest(plan)})
    write(root/'delivery_manifest.json',file_manifest(root))
    validate_packaging_plan(root)
    return {'version':PLAN_VERSION,'plan':relative(root),'plan_digest':digest(plan),'planned_jobs':len(jobs),'task_ids':ids}


def validate_packaging_plan(plan_root):
    root=Path(plan_root); plan=read(root/'plan.json')
    validate_schema('packaging_full_order_plan_v1',plan)
    require(read(root/'plan_receipt.json')=={'version':PLAN_VERSION,'plan_digest':digest(plan)},'full_order_plan_digest_changed')
    require(file_manifest(root)==read(root/'delivery_manifest.json'),'full_order_plan_files_changed')
    require(plan['source_manifest']==source_manifest() and plan['physical_manifest']==physical_manifest(), 'full_order_source_or_physics_changed')
    require(all(hashlib.sha256((root/'code_snapshot'/n).read_bytes()).hexdigest()==h for n,h in plan['source_manifest'].items()), 'full_order_code_snapshot_changed')
    require(plan['method_contract']==METHOD_REGISTRY and plan['metrics_contract']==METRICS_CONTRACT,
            'full_order_contract_changed')
    data=load_runtime_dataset(REPO/plan['dataset'])
    inv=inventory(REPO/plan['dataset'],data)
    require(plan['data_identity']==data['data_identity'] and plan['inventory_digest']==digest(inv)
        and read(root/'task_inventory.json')==inv,'full_order_data_changed')
    require(plan['method_ids']==list(METHOD_REGISTRY),'full_order_unplanned_method')
    if plan['selection_mode']=='DETERMINISTIC_RULE':
        require(plan['task_ids']==select_tasks(inv),'full_order_selection_rule_changed')
    expected=[(t,m) for t in plan['task_ids'] for m in plan['method_ids']]
    require([(j['task_id'],j['method_id']) for j in plan['jobs']]==expected,'full_order_job_matrix_changed')
    for index,j in enumerate(plan['jobs']):
        task=next((t for t in data['tasks'] if t['task_id']==j['task_id']),None)
        require(task is not None and task['partition']=='train','full_order_unplanned_task')
        require(j['job_id']==f'J{index:04d}' and j['task_digest']==digest(task) and
            read(root/'tasks'/f"{j['task_id']}.json")==task and j['source_group_id']==task['source_group_id']
            and j['variant']==task['layer'],'full_order_task_identity_changed')
        require(j['config']==load_monitor_config(data_identity=data['data_identity'],task_digest=digest(task),
            method=j['method_id'],enabled=True),'full_order_config_changed')
    return plan


class _BoundaryStop(Exception):
    pass


def _run_job(task, entry, job, watchdog, *, selector=None, metrics_builder=None, hook=None):
    from .episode import run_episode
    cfg=entry['config'];jid=entry['job_id'];status=read(job/'status.json')
    cp=read(job/'checkpoint.json') if (job/'checkpoint.json').exists() else None
    accumulated=status['active_wall_s'];started=time.perf_counter()
    def elapsed():
        return accumulated+time.perf_counter()-started
    def checkpoint(value):
        nonlocal cp
        cp=value
        write(job/'checkpoint.json',value)
        if value['pending_event']:
            write(job/'stages'/value['pending_event']['decision_id']/(value['phase']+'.json'),value)
        status.update(active_wall_s=elapsed());write(job/'status.json',status)
        if value['reason'] is None and (len(value['events'])>=watchdog['max_events'] or elapsed()>=watchdog['max_active_wall_s']):
            raise _BoundaryStop()
    try:
        status.update(state='RUNNING',category='NOT_RUN');write(job/'status.json',status)
        ep=run_episode(task,selector_factory(entry['method_id']) if selector is None else selector,cfg,job_id=jid,method=entry['method_id'],
            resume=cp,on_checkpoint=checkpoint,hook=hook)
        cp=ep['checkpoint']
        status.update(state='FINISHED', category=termination_category(cp['reason'],cp['events']))
        write(job/'episode.json',ep)
    except _BoundaryStop:
        status.update(state='FINISHED',category='TECHNICAL_LIMIT')
    except KeyboardInterrupt:
        status.update(state='FINISHED',category='CANCELED',error={'type':'KeyboardInterrupt'})
    except Exception as exc:
        status.update(state='FINISHED',category='ERROR',error={'type':type(exc).__name__,'code':getattr(exc,'code','UNEXPECTED_ERROR'),'detail':str(exc)[:240]})
    finally:
        status.update(active_wall_s=elapsed());write(job/'status.json',status)
    if cp is not None:
        try:
            write(job/'checkpoint.json',cp)
            write(job/'final_layout.json',cp['state']['placed_items'])
            write(job/'physical_evaluation.json',evaluate_state(cp['state']))
            for e in cp['events']:
                if e.get('decision_id'):
                    write(job/'actions'/f"{e['decision_id']}.json",e)
            write(job/'metrics.json',(metrics_builder or job_metrics)(task,cfg,cp,status))
        except Exception as exc:
            failure=technical_failure('JOB_FINALIZATION',exc,checkpoint=cp,prior_status=status)
            write(job/'technical_failure.json',failure)
            status.update(state='FINISHED',category='ERROR',error=failure['error'])
            write(job/'status.json',status)
    return status


def technical_failure(phase, exc, *, checkpoint=None, prior_status=None):
    """Independent receipt: never calls the failed derivation again."""
    return {'version':'jev_packaging_technical_failure_v1','phase':phase,
        'error':{'type':type(exc).__name__,'code':getattr(exc,'code','DERIVATION_ERROR'),'detail':str(exc)[:240]},
        'checkpoint_digest':digest(checkpoint) if checkpoint is not None else None,
        'prior_status':copy.deepcopy(prior_status)}


def job_derivation_failed(job, status, cp):
    path=job/'technical_failure.json'
    if not path.exists():
        return False
    failure=read(path)
    require(set(failure)=={'version','phase','error','checkpoint_digest','prior_status'} and
        failure['version']=='jev_packaging_technical_failure_v1' and failure['phase']=='JOB_FINALIZATION' and
        failure['checkpoint_digest']==digest(cp) and status['category']=='ERROR' and
        status['error']==failure['error'],'full_order_technical_receipt_changed')
    return True


def run_packaging_plan(plan_root, output, *, resume=False, task_ids=None, method_ids=None,
                       stop_after_jobs=None, continue_pending=False):
    """Bounded pauses retain the complete matrix; continuation needs an explicit flag.

    No transport parameter: JN0 cannot accidentally route a paid request.
    """
    plan=validate_packaging_plan(plan_root)
    require(task_ids is None or task_ids==plan['task_ids'],'full_order_unplanned_task')
    require(method_ids is None or method_ids==plan['method_ids'],'full_order_unplanned_method')
    require(stop_after_jobs is None or (type(stop_after_jobs) is int and
        1<=stop_after_jobs<=len(plan['jobs'])),'full_order_invalid_batch_boundary')
    require(not continue_pending or resume,'full_order_continuation_requires_resume')
    root=Path(output).resolve()
    if resume:
        require(root.is_dir(),'full_order_missing_run')
        receipt=read(root/'run_receipt.json')
        require(receipt=={'version':RUN_VERSION,'plan':relative(plan_root),'plan_digest':digest(plan)},'full_order_run_plan_changed')
        if (root/'technical_failure.json').exists():
            return {'status':'ERROR','planned_jobs':len(plan['jobs']),'technical_failure':read(root/'technical_failure.json')}
        if (root/'delivery_manifest.json').exists():
            validate_packaging_run(root)
            summary=read(root/'summary.json')
            if not continue_pending or not summary['categories']['NOT_RUN'] or any(summary['categories'][c] for c in STOP_CATEGORIES):
                return summary
    else:
        root=new_output(root)
        write(root/'run_receipt.json',{'version':RUN_VERSION,'plan':relative(plan_root),'plan_digest':digest(plan)})
        from .stability.runtime import environment
        write(root/'environment.json',environment())
        for j in plan['jobs']:
            job=root/'jobs'/j['job_id']
            write(job/'task.snapshot.json',read(Path(plan_root)/'tasks'/f"{j['task_id']}.json"))
            write(job/'config.snapshot.json',j['config'])
            write(job/'status.json',{'state':'NOT_RUN','category':'NOT_RUN','active_wall_s':0.,'error':None})
    from .dataset_j4 import offline_dataset_guard
    with exclusive(root), offline_dataset_guard() as counters:
        if (root/'delivery_manifest.json').exists():
            # Preserve the already-validated pilot closure before continuing.
            history=root/'batch_history'/f"B{len(list((root/'batch_history').glob('B*')))+1:04d}"
            for name in ('delivery_manifest.json','summary.json','job_ledger.json','paired_differences.json'):
                write(history/(name+'.snapshot.json'),read(root/name))
            (root/'delivery_manifest.json').unlink()
        try:
            for index,j in enumerate(plan['jobs']):
                if stop_after_jobs is not None and index>=stop_after_jobs:
                    break
                job=root/'jobs'/j['job_id'];status=read(job/'status.json')
                if status['state']=='FINISHED':
                    if status['category'] in STOP_CATEGORIES:
                        break
                    continue
                task=read(job/'task.snapshot.json')
                require(digest(task)==j['task_digest'] and read(job/'config.snapshot.json')==j['config'],'full_order_job_snapshot_changed')
                result=_run_job(task,j,job,plan['watchdog'])
                if result['category'] in STOP_CATEGORIES:
                    break
            write(root/'offline_guards.json',dict(counters))
            try:
                result=summarize_packaging_run(root)
            except Exception as exc:
                failure=technical_failure('BATCH_SUMMARY',exc)
                write(root/'technical_failure.json',failure)
                return {'status':'ERROR','planned_jobs':len(plan['jobs']),'technical_failure':failure}
            write(root/'delivery_manifest.json',file_manifest(root))
            try:
                validate_packaging_run(root)
            except Exception as exc:
                failure=technical_failure('BATCH_VALIDATION',exc)
                write(root/'technical_failure.json',failure)
                return {'status':'ERROR','planned_jobs':len(plan['jobs']),'technical_failure':failure}
            return result
        finally:
            # Persist guard evidence even if a derivation fails. Do not dispatch
            # another job or retry the failed derivation from this handler.
            if (root/'technical_failure.json').exists():
                write(root/'offline_guards.json',dict(counters))
                write(root/'delivery_manifest.json',file_manifest(root))


def summarize_packaging_run(run_root):
    root=Path(run_root)
    if (root/'delivery_manifest.json').exists():
        validate_packaging_run(root)
        return read(root/'summary.json')
    receipt=read(root/'run_receipt.json');plan=validate_packaging_plan(REPO/receipt['plan'])
    require(receipt['plan_digest']==digest(plan),'full_order_run_plan_changed')
    rows=[];ledger=[]
    for j in plan['jobs']:
        job=root/'jobs'/j['job_id'];s=read(job/'status.json')
        ledger.append({'job_id':j['job_id'],'task_id':j['task_id'],'method_id':j['method_id'],**s})
        if (job/'checkpoint.json').exists():
            cp=read(job/'checkpoint.json')
            if job_derivation_failed(job,s,cp):
                ledger[-1]['metrics']='NOT_AVAILABLE_DERIVATION_ERROR'
                continue
            # Finalize each job once. Summarization reads the durable metric;
            # standard validation independently derives and compares it later.
            rows.append(read(job/'metrics.json'))
        elif s['category']!='NOT_RUN':
            ledger[-1]['metrics']='NOT_AVAILABLE_NO_CHECKPOINT'
    summary=aggregate_saved_metrics(rows,ledger)
    write(root/'job_ledger.json',ledger);write(root/'summary.json',summary)
    write(root/'paired_differences.json',paired(rows))
    return summary


def aggregate_saved_metrics(rows, ledger):
    summary=aggregate(rows,len(ledger))
    summary['categories']={k:sum(s['category']==k for s in ledger) for k in summary['categories']}
    if any('metrics' in row for row in ledger):
        # Missing technical-failure metrics must not masquerade as zero selected
        # actions or zero coverage. Per-job status and receipt explain the gap.
        summary['selected_actions']='UNKNOWN'
        summary['assessable_coverage']='UNKNOWN'
    return summary


def validate_saved_checkpoint(cp, task, cfg, jid, *, fork_origin=None):
    """Saved bindings, state deltas and independent static area facts only.

    No CandidateProvider, selector, run_episode, commit_physical or PCT solver.
    """
    from .contracts import CandidateBundle,DecisionContext
    from .packaging_runtime import validate_runtime_context
    from .context import resolve_display_id
    from .stability.monitor import validate_monitor
    from semantic_pallet_planner.o4.extensions.e2.protocol import observation
    from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive
    validate_schema('checkpoint_v6' if cfg['version']=='jev_packaging_remote_v6' else 'checkpoint_v5',cp)
    require(cp['record_digest']==digest({k:v for k,v in cp.items() if k!='record_digest'}), 'full_order_checkpoint_digest_changed')
    require(cp['job_id']==jid and cp['method']==cfg['selector'] and cp['config_digest']==digest(cfg)
        and cp['task_digest']==digest(task) and cp['runtime_identity']==cfg['runtime_identity'],'full_order_checkpoint_binding_changed')
    state=initial(task['container'],cfg['buffer_capacity']);cursor=decision=0;stopped=None
    if fork_origin is not None:
        state=copy.deepcopy(fork_origin['state']);cursor=fork_origin['cursor']
    require((cp['pending_event'] is None and cp['phase'] in ('READY','TERMINATED')) or
        (cp['pending_event'] is not None and cp['phase'] in ('SELECTED','MONITORED','COMMITTED')),
        'full_order_invalid_phase')
    if cp['pending_event']:
        require((cp['phase']=='SELECTED') == (cp['pending_event']['monitor'] is None), 'full_order_monitor_phase_changed')
    rows=[*cp['events']]
    if cp['pending_event'] is not None:
        rows.append(cp['pending_event'])
    for index,e in enumerate(rows):
        require(stopped is None and e['before']==state,'full_order_state_discontinuity')
        pending=index==len(cp['events'])
        if e['event']=='WAIT_RECEIVE':
            item=task['items'][cursor];cursor+=1
            require(e['after']==receive(state,item,task['attributes'][item['item_id']]),'full_order_arrival_changed')
        elif e['event']=='EOS':
            require(e['after']==receive(state,eos=True),'full_order_eos_changed')
        else:
            require(e['decision_id']==f'{jid}_D{decision:04d}','full_order_decision_changed')
            req=observation(state,task['instruction_text'],task['regions'])
            require(e['observation']==req,'full_order_observation_changed')
            ctx=DecisionContext.from_dict(e['context']);bundle=CandidateBundle.from_dict(e['bundle'])
            validate_runtime_context(ctx,req,bundle,cfg)
            require(ctx.data['local_binding']['job_id']==jid and ctx.data['local_binding']['decision_id']==e['decision_id'],'full_order_context_changed')
            selected=e['selection']
            if selected:
                validate_schema('selection_result',selected)
                require(selected['local_binding_digest']==digest(ctx.data['local_binding']),'full_order_selection_changed')
                if selected['status'] in ('selected','singleton'):
                    chosen=resolve_display_id(ctx,selected['selected_display_id'],req,bundle,cfg)
                    require(chosen['candidate_id']==selected['selected_candidate_id'],'full_order_candidate_changed')
                    from semantic_pallet_planner.o4.extensions.e2.planning import action_for
                    require(e['proposed_action']==action_for(req,bundle.data['physical_candidates'],chosen),'full_order_exact_action_changed')
                    if e['monitor']:
                        validate_monitor(e['monitor'],state,chosen,e,cfg,require_stable=e['event']=='PLACE')
            if e['event']=='PLACE':
                require(e['monitor'] is not None and e['action']==e['proposed_action'],'full_order_commit_monitor_missing')
                pick=chosen['pick_item_id'];after=e['after']
                require([p for p in state['pending_items'] if p['item']['item_id']!=pick]==after['pending_items']
                    and after['placed_count']==state['placed_count']+1 and len(after['placed_items'])==len(state['placed_items'])+1,
                    'full_order_commit_count_changed')
                for key in state:
                    if key not in ('placed_items','pending_items','placed_count','event_index'):
                        require(after[key]==state[key],'full_order_commit_metadata_changed')
                require(after['event_index']==state['event_index']+1,'full_order_event_index_changed')
                for old,new in zip(state['placed_items'],after['placed_items']):
                    require({k:v for k,v in old.items() if k!='supported_load_kg'}==
                        {k:v for k,v in new.items() if k!='supported_load_kg'},'full_order_previous_item_changed')
                obj=after['placed_items'][-1]
                original=next(p['item'] for p in state['pending_items'] if p['item']['item_id']==pick)
                require(all(obj[k]==v for k,v in original.items()),'full_order_item_properties_changed')
                require(obj['item_id']==pick and obj['pose']==chosen['pose'] and obj['oriented_size_mm']==chosen['oriented_size_mm'], 'full_order_placement_changed')
                require(not evaluate_state(after)['violations'],'full_order_physical_violation')
            else:
                require(e['after']==state and e['action'] is None,'full_order_failed_action_committed')
            if not pending:
                require(e['business_after']==evaluate_state(e['after']),'full_order_evaluation_changed')
                stopped=e['reason'];decision+=1
                from .stability.monitor import TERMINATIONS
                if e.get('monitor') and e['monitor']['status'] in TERMINATIONS:
                    require(stopped==TERMINATIONS[e['monitor']['status']],'full_order_monitor_stop_changed')
        state=e['after']
    require(cp['state']==state and cp['cursor']==cursor and cp['decision']==decision,'full_order_progress_changed')
    require(cp['reason']==stopped or (cp['reason']=='ALL_ITEMS_PLACED' and not state['pending_items'] and state['end_of_stream'])
        or (cp['reason']=='EVALUATION_ERROR' and cp['phase']=='COMMITTED'),'full_order_stop_changed')
    return cp


def validate_packaging_run(run_root):
    root=Path(run_root);receipt=read(root/'run_receipt.json');plan_root=REPO/receipt['plan']
    plan=validate_packaging_plan(plan_root)
    require(receipt=={'version':RUN_VERSION,'plan':relative(plan_root),'plan_digest':digest(plan)},'full_order_run_plan_changed')
    require(file_manifest(root)==read(root/'delivery_manifest.json'),'full_order_run_files_changed')
    rows=[];ledger=[]
    for j in plan['jobs']:
        job=root/'jobs'/j['job_id'];status=read(job/'status.json');task=read(job/'task.snapshot.json');cfg=read(job/'config.snapshot.json')
        require(digest(task)==j['task_digest'] and cfg==j['config'],'full_order_job_snapshot_changed')
        require(set(status)=={'state','category','active_wall_s','error'} and status['state'] in ('NOT_RUN','FINISHED')
            and status['active_wall_s']>=0,'full_order_invalid_status')
        ledger.append({'job_id':j['job_id'],'task_id':j['task_id'],'method_id':j['method_id'],**status})
        if not (job/'checkpoint.json').exists():
            require(status['category'] in ('NOT_RUN','ERROR','CANCELED'),'full_order_missing_checkpoint')
            if status['category']!='NOT_RUN':ledger[-1]['metrics']='NOT_AVAILABLE_NO_CHECKPOINT'
            continue
        cp=read(job/'checkpoint.json');validate_saved_checkpoint(cp,task,cfg,j['job_id'])
        if status['category'] not in ('TECHNICAL_LIMIT','CANCELED','ERROR'):
            require(status['category']==termination_category(cp['reason'],cp['events']), 'full_order_termination_changed')
        if status['category']=='TECHNICAL_LIMIT':
            require(len(cp['events'])>=plan['watchdog']['max_events'] or status['active_wall_s']>=plan['watchdog']['max_active_wall_s'], 'full_order_unjustified_limit')
        require(status['state']=='FINISHED' and status['category']!='NOT_RUN','full_order_status_checkpoint_mismatch')
        for e in cp['events']:
            if e.get('decision_id'):
                require(read(job/'actions'/f"{e['decision_id']}.json")==e,'full_order_action_changed')
        for p in sorted((job/'stages').glob('*/*.json')):
            stage=read(p);validate_saved_checkpoint(stage,task,cfg,j['job_id'])
            require(stage['events']==cp['events'][:len(stage['events'])],'full_order_stage_prefix_changed')
            pending=stage['pending_event']
            final=next((e for e in cp['events'] if e.get('decision_id')==pending['decision_id']),cp['pending_event'])
            require(final is not None,'full_order_stage_missing')
            for k in ('before','bundle','context','selection','proposed_action'):
                require(final[k]==pending[k],'full_order_stage_binding_changed')
            if pending['monitor']:
                require(pending['monitor']==final['monitor'],'full_order_saved_monitor_overwritten')
        require(read(job/'final_layout.json')==cp['state']['placed_items'] and
            read(job/'physical_evaluation.json')==evaluate_state(cp['state']),'full_order_final_layout_changed')
        if (job/'episode.json').exists():
            ep=read(job/'episode.json')
            require(ep['checkpoint']==cp and ep['events']==cp['events'] and ep['final_state']==cp['state'],'full_order_episode_changed')
        if job_derivation_failed(job,status,cp):
            ledger[-1]['metrics']='NOT_AVAILABLE_DERIVATION_ERROR'
            continue
        metrics=job_metrics(task,cfg,cp,status)
        require(read(job/'metrics.json')==metrics,'full_order_metrics_changed');rows.append(metrics)
    expected=aggregate_saved_metrics(rows,ledger)
    require(read(root/'job_ledger.json')==ledger and read(root/'summary.json')==expected
        and read(root/'paired_differences.json')==paired(rows),'full_order_summary_changed')
    return {'status':'PASS','jobs':len(plan['jobs']),'verification':'saved records only; no dispatch, candidate generation, selection, physical commit or LP'}
