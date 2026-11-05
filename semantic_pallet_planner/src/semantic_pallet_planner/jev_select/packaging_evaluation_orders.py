"""Six-method plan/run adapter over common._run_job; no parallel order engine.

run_validation accepts only constructed or frozen exposed development inputs and
explicit Fake transports. A frozen formal plan is consumable but NOT dispatched
by this JN4-A entry point (including its local methods).
"""
from pathlib import Path
import copy
import importlib.metadata
import platform
from .contracts import digest,validate_schema,DecisionContext,canonical
from .ledger import read,write,exclusive
from .experiment import source_manifest,file_manifest
from .packaging_source_audit import require,sha
from .packaging_evaluation_protocol import VERSION,VERSIONS,REGISTRY,METHODS,EvaluationLedger,load_evaluation_config,budget_identity
from .packaging_evaluation_memory import MemoryDriver
from .packaging_evaluation_plan import build_control,validate_control,budget_for_tasks
from .packaging_pilot_memory import NONE_DIGEST
from . import packaging_experiment as common
from . import packaging_orders as orders
from . import packaging_memory_pilot as pilot
from .packaging_protocol import CATEGORIES,selector_factory,termination_category
from .packaging_runtime import physical_manifest,evaluate_state
from .packaging_metrics import job_metrics
from .selector import parse_response
REPO=Path(__file__).resolve().parents[4]
PARENTS=pilot.PARENTS;FILES=pilot.FILES
STOP=common.STOP_CATEGORIES
GATE={**pilot.GATE,'version':'jev_evaluation_gate_v1','jobs':6,
      'exposure':'at least one sent nonempty E and paired unrelated-E body, T coverage reported; absence pauses without replacing sources'}


def location(path):
    path=Path(path).resolve()
    return path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else str(path)

def resolve(path):return Path(path) if Path(path).is_absolute() else REPO/path


def dependencies():
    return {'python':platform.python_version(),**{n:importlib.metadata.version(n) for n in ('numpy','scipy','jsonschema','cryptography')}}


def snapshots():
    from . import packaging_experience as T,packaging_contrast as E
    s={m:read(REPO/PARENTS[m]/FILES[m]) for m in ('T','E')}
    T.validate_snapshot(s['T']);E.validate_snapshot(s['E']);s['control']=build_control(s['E']);return s


def _scope(data,purpose):
    require(bool(data['tasks']),'evaluation_empty_plan')
    if purpose=='FIXTURE_ENGINEERING':
        require(data.get('fixture_only') is True and all(t['task_id'].startswith(('CONSTRUCTED','EVAL_')) for t in data['tasks']),'evaluation_not_constructed')
    elif purpose=='EXPOSED_DEVELOPMENT':
        from .packaging_runtime import load_runtime_dataset
        allowed=load_runtime_dataset(REPO/'semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02')
        require(data['data_identity']==allowed['data_identity'] and all(t in allowed['tasks'] and t['partition']=='train' for t in data['tasks']),'evaluation_not_frozen_development')
    elif purpose=='FROZEN_FORMAL_TEST':
        from .packaging_evaluation_data import load_dataset
        require('dataset_root' in data and 'trust_policy' in data and not data.get('fixture_only'),'evaluation_formal_data_required')
        checked=load_dataset(REPO/data['dataset_root'],repo=REPO,policy=data['trust_policy'])
        require(checked['data_identity']==data['data_identity'] and checked['tasks']==data['tasks'] and not checked['fixture_only'],'evaluation_formal_source_not_admitted')
    else:require(False,'evaluation_unknown_purpose')


def prepare(data,output,*,purpose='FIXTURE_ENGINEERING',watchdog=None):
    _scope(data,purpose);require(len({t['task_id'] for t in data['tasks']})==len(data['tasks']),'evaluation_duplicate_task')
    snaps=snapshots();jobs=[]
    for task in data['tasks']:
        for method in METHODS:
            mode=REGISTRY[method]['mode'];refmode='E' if mode=='E_unrelated_control' else mode
            config=load_evaluation_config(data_identity=data['data_identity'],task_digest=digest(task),method=method,
                snapshot=None if mode=='none' else snaps[refmode],control=snaps['control'] if mode=='E_unrelated_control' else None,
                excluded_source_groups=[task['source_group_id']],enabled=True)
            jobs.append({'job_id':f'J{len(jobs):04d}','task_id':task['task_id'],'method_id':method,'task_digest':digest(task),'config':config})
    limits={j['job_id']:len(next(t for t in data['tasks'] if t['task_id']==j['task_id'])['items']) if REGISTRY[j['method_id']]['remote'] else 0 for j in jobs}
    from .packaging_reanalysis import RULE
    plan={'version':VERSIONS['plan'],'execution_version':VERSION,'purpose':purpose,'data':data,
       'task_ids':[t['task_id'] for t in data['tasks']],'method_ids':METHODS,'jobs':jobs,
       'source_manifest':source_manifest(),'dependencies':dependencies(),'physical_manifest':physical_manifest(),
       'snapshots':snaps,'request_budget':{'per_job':limits,'global':sum(limits.values())},
       'watchdog':watchdog or {'max_events':10000,'max_active_wall_s':1800},'gate_rule':GATE,'evaluation_rule':RULE,
       'run_location':location(Path(output).resolve().parent/'run'),'model_availability':'UNKNOWN_NOT_PROBED'}
    root=Path(output);require(not root.exists(),'evaluation_plan_output_exists')
    validate_schema('evaluation_orders_plan_v1',plan);write(root/'plan.json',plan)
    write(root/'plan_receipt.json',{'plan_digest':digest(plan)})
    write(root/'delivery_manifest.json',file_manifest(root));validate_plan(root);return plan


def validate_plan(root):
    root=Path(root);p=read(root/'plan.json');validate_schema('evaluation_orders_plan_v1',p)
    require(read(root/'delivery_manifest.json')==file_manifest(root) and read(root/'plan_receipt.json')=={'plan_digest':digest(p)},'evaluation_plan_bytes')
    require(p['source_manifest']==source_manifest() and p['dependencies']==dependencies() and p['physical_manifest']==physical_manifest(),'evaluation_runtime_identity_changed')
    _scope(p['data'],p['purpose']);require(p['method_ids']==METHODS and p['task_ids']==[t['task_id'] for t in p['data']['tasks']],'evaluation_plan_scope')
    require(p['snapshots']==snapshots() and p['gate_rule']==GATE,'evaluation_snapshot_or_gate_changed')
    from .packaging_reanalysis import RULE
    require(p['evaluation_rule']==RULE,'evaluation_metric_rule_changed')
    require([(j['task_id'],j['method_id']) for j in p['jobs']]==[(t,m) for t in p['task_ids'] for m in METHODS],'evaluation_matrix_changed')
    for i,j in enumerate(p['jobs']):
        t=next(t for t in p['data']['tasks'] if t['task_id']==j['task_id']);mode=REGISTRY[j['method_id']]['mode'];rm='E' if mode=='E_unrelated_control' else mode
        cfg=load_evaluation_config(data_identity=p['data']['data_identity'],task_digest=digest(t),method=j['method_id'],snapshot=None if mode=='none' else p['snapshots'][rm],control=p['snapshots']['control'] if mode=='E_unrelated_control' else None,excluded_source_groups=[t['source_group_id']],enabled=True)
        require(j=={'job_id':f'J{i:04d}','task_id':t['task_id'],'method_id':j['method_id'],'task_digest':digest(t),'config':cfg},'evaluation_job_changed')
    b=budget_for_tasks(p['data']['tasks']);require(p['request_budget']=={'per_job':b['per_job'],'global':b['shared_batch_max_sends']},'evaluation_budget_changed')
    return p


def saved_requests(root,plan):
    l=EvaluationLedger.__new__(EvaluationLedger);l.path=Path(root)/'request_ledger/requests.json'
    l.limits=plan['request_budget']['per_job'];l.max_sends=plan['request_budget']['global'];l.configs={j['job_id']:j['config'] for j in plan['jobs']}
    l._budget_digest=budget_identity(plan['request_budget'],l.configs)
    return l._load()['requests']


def metrics(task,cfg,cp,status,requests,reuses=()):
    row=job_metrics(task,cfg,cp,status);events=cp['events']+([cp['pending_event']] if cp['pending_event'] else [])
    # Reuse diagnostic extraction through the reference trace, preserving U identity.
    projected=copy.deepcopy(events)
    for e in projected:
        if e.get('context'):
            e['context']['retrieval_receipt']['raw_retrieval']=e['context']['retrieval_receipt']['reference_receipt']['raw_retrieval']
    row.update(version='jev_evaluation_order_metrics_v1',origin='jev' if REGISTRY[cfg['selector']]['remote'] else 'LOCAL_TEST_DOUBLE_NOT_JEV',
      cost=orders.request_statistics(requests,reuses),memory_mode=cfg['memory_mode'],snapshot_digest=cfg['memory_snapshot_digest'],
      memory_metrics=pilot.exposure(projected,requests,cfg['memory_mode'],library_nonempty=bool(cfg['memory_index'])))
    validate_schema('evaluation_order_metrics_v1',row);return row


def collect(root,p):
    root=Path(root);jobs=[{'job_id':j['job_id'],'task_id':j['task_id'],'method_id':j['method_id'],**read(root/'jobs'/j['job_id']/'status.json')} for j in p['jobs']]
    stats=orders.request_statistics(saved_requests(root,p),orders.saved_reuses(root))
    return {'version':'jev_evaluation_summary_v1','planned_jobs':len(jobs),'job_ledger':jobs,
       'categories':{c:sum(j['category']==c for j in jobs) for c in CATEGORIES},'request_statistics':stats,
       'status':'ERROR' if any(j['category'] in STOP for j in jobs) or (root/'technical_failure.json').exists() else 'PASS_IN_EXECUTED_SCOPE',
       'scope':p['purpose'],'actual_model_api_calls':0 if p['purpose']!='FROZEN_FORMAL_TEST' else 'UNKNOWN'}


def gate(root,p):
    root=Path(root);rows=[read(root/'jobs'/j['job_id']/'status.json') for j in p['jobs'][:6]]
    closed=all(r['state']=='FINISHED' and r['category'] not in STOP|{'NOT_RUN'} for r in rows)
    exposure={}
    for j in p['jobs'][:6]:
        f=root/'jobs'/j['job_id']/'metrics.json'
        if f.exists():exposure[j['method_id']]=read(f)['memory_metrics']['actually_sent_nonempty_count']
    hit=all(exposure.get(m,0)>0 for m in ('jev_with_contrast_experience','jev_with_unrelated_E_control'))
    return {'version':'jev_evaluation_gate_v1','plan_digest':digest(p),'closed':closed,'exposure':exposure,
      'status':'STOP_TECHNICAL' if (root/'technical_failure.json').exists() else 'PASS' if closed and hit else 'DEFER_NO_EXPOSURE' if closed else 'STOP_TECHNICAL','benefit_used':False,
      'job_files_sha256':{str(f.relative_to(root)):sha(f) for j in p['jobs'][:6] for f in (root/'jobs'/j['job_id']).rglob('*') if f.is_file()}}


def run_validation(plan_root,output,*,transport_factory,resume=False,continue_pending=False,task_ids=None,method_ids=None):
    p=validate_plan(plan_root);root=Path(output)
    require(p['purpose']!='FROZEN_FORMAL_TEST','JN4_A_FORMAL_TEST_EXECUTION_FORBIDDEN')
    require(task_ids is None or task_ids==p['task_ids'],'evaluation_unplanned_task');require(method_ids is None or method_ids==METHODS,'evaluation_unplanned_method')
    require(location(root)==p['run_location'],'evaluation_run_location')
    require(not continue_pending or resume,'evaluation_continue_requires_resume')
    receipt={'version':VERSIONS['run'],'plan':location(plan_root),'plan_digest':digest(p)}
    if resume:
        require(read(root/'run_receipt.json')==receipt,'evaluation_resume_identity')
        require((root/'request_ledger/requests.json').exists(),'evaluation_missing_durable_ledger')
        if (root/'delivery_manifest.json').exists():
            validate_run(root)
            if read(root/'summary.json')['status']=='ERROR':return read(root/'summary.json')
            if not continue_pending:return read(root/'summary.json')
            require(read(root/'first_gate.json')==gate(root,p) and gate(root,p)['status']=='PASS','evaluation_first_gate_failed')
    else:
        require(not root.exists(),'evaluation_run_exists');write(root/'run_receipt.json',receipt)
        for j in p['jobs']:
            job=root/'jobs'/j['job_id'];task=next(t for t in p['data']['tasks'] if t['task_id']==j['task_id'])
            write(job/'task.snapshot.json',task);write(job/'config.snapshot.json',j['config'])
            write(job/'status.json',{'state':'NOT_RUN','category':'NOT_RUN','active_wall_s':0.,'error':None})
    with exclusive(root):
        if (root/'delivery_manifest.json').exists():(root/'delivery_manifest.json').unlink()
        configs={j['job_id']:j['config'] for j in p['jobs']};ledger=EvaluationLedger(root/'request_ledger',p['request_budget'],configs)
        for i,j in enumerate(p['jobs']):
            if i>=6 and not continue_pending:break
            job=root/'jobs'/j['job_id'];status=read(job/'status.json')
            if status['state']=='FINISHED':
                if status['category'] in STOP:break
                continue
            cfg=j['config'];mode=cfg['memory_mode'];refmode='E' if mode=='E_unrelated_control' else mode
            try:
                transport=transport_factory(cfg,j) if REGISTRY[j['method_id']]['remote'] else None
                require(transport is None or transport.origin=='test_double','evaluation_fake_transport_required')
                selector=selector_factory(j['method_id'],execution_version=VERSION,config=cfg,transport=transport,ledger=ledger,job_id=j['job_id'])
                driver=MemoryDriver(cfg,snapshot=None if mode=='none' else p['snapshots'][refmode],control=p['snapshots']['control'] if mode=='E_unrelated_control' else None)
            except Exception as exc:
                status.update(state='FINISHED',category='ERROR',error={'code':getattr(exc,'code','EVALUATION_INITIALIZATION_ERROR'),'detail':str(exc)[:240]})
                write(job/'status.json',status)
                break
            def builder(t,c,cp,s):
                requests=[r for r in ledger._load()['requests'] if r['job_id']==j['job_id']];reuses=[r for r in orders.saved_reuses(root) if r['job_id']==j['job_id']]
                return metrics(t,c,cp,s,requests,reuses)
            def hook(phase,event):
                if phase=='decision_ready':
                    trace={'context':event['context'],'bundle':event['bundle']};f=job/'decision_ready'/f"{event['decision_id']}.json"
                    if f.exists():require(read(f)==trace,'evaluation_durable_ready_changed')
                    else:write(f,trace)
            result=common._run_job(read(job/'task.snapshot.json'),j,job,p['watchdog'],selector=selector,metrics_builder=builder,hook=hook,memory_driver=driver)
            if result['category'] in STOP:break
            if result['category']=='UNASSESSABLE':
                reasons=read(job/'metrics.json')['monitor_reasons']
                if not reasons or not set(reasons)<=set(GATE['allowed_range_reasons']):
                    write(root/'technical_failure.json',{'reason':'UNREGISTERED_MONITOR_SCOPE'});break
        write(root/'summary.json',collect(root,p))
        if all(read(root/'jobs'/j['job_id']/'status.json')['state']=='FINISHED' for j in p['jobs'][:6]):write(root/'first_gate.json',gate(root,p))
        write(root/'delivery_manifest.json',file_manifest(root))
        try:
            validate_run(root)
        except Exception as exc:
            # A nominally successful episode is not a successful batch when its
            # durable records cannot be validated. Never publish a PASS gate.
            write(root/'technical_failure.json',common.technical_failure('EVALUATION_SAVED_VALIDATION',exc))
            write(root/'summary.json',collect(root,p))
            if (root/'first_gate.json').exists():write(root/'first_gate.json',gate(root,p))
            write(root/'delivery_manifest.json',file_manifest(root))
            raise
        return read(root/'summary.json')


def validate_run(root):
    """Saved facts only: no transport, resolve, selection, candidates, PCT or commit."""
    root=Path(root);receipt=read(root/'run_receipt.json');validate_schema('evaluation_orders_run_v1',receipt)
    p=validate_plan(resolve(receipt['plan']));require(receipt['plan_digest']==digest(p),'evaluation_saved_plan_changed')
    require(file_manifest(root)==read(root/'delivery_manifest.json'),'evaluation_run_bytes')
    rows=saved_requests(root,p);used=set()
    for j in p['jobs']:
        job=root/'jobs'/j['job_id'];cfg=j['config'];task=read(job/'task.snapshot.json');status=read(job/'status.json')
        require(digest(task)==j['task_digest'] and read(job/'config.snapshot.json')==cfg,'evaluation_job_snapshot_changed')
        requests=[r for r in rows if r['job_id']==j['job_id']]
        if status['state']=='NOT_RUN':
            require(status['category']=='NOT_RUN' and not requests and not (job/'checkpoint.json').exists(),'evaluation_notrun_changed');continue
        if not (job/'checkpoint.json').exists():require(status['category'] in STOP,'evaluation_missing_checkpoint');continue
        cp=read(job/'checkpoint.json');common.validate_saved_checkpoint(cp,task,cfg,j['job_id'])
        if status['category'] not in STOP:require(status['category']==termination_category(cp['reason'],cp['events']),'evaluation_termination_changed')
        events=cp['events']+([cp['pending_event']] if cp['pending_event'] else [])
        for f in (job/'stages').glob('*/*.json'):
            old=read(f);common.validate_saved_checkpoint(old,task,cfg,j['job_id'])
            require(old['events']==cp['events'][:len(old['events'])],'evaluation_saved_stage_prefix')
            e=old['pending_event'];final=next(x for x in events if x.get('decision_id')==e['decision_id'])
            require(all(e[k]==final[k] for k in ('context','bundle','before')),'evaluation_saved_stage_context')
            if e['selection'] is not None:require(e['selection']==final['selection'],'evaluation_saved_choice_changed')
            if e['monitor'] is not None:require(e['monitor']==final['monitor'],'evaluation_saved_monitor_changed')
        for e in events:
            if not e.get('decision_id'):continue
            require(read(job/'decision_ready'/f"{e['decision_id']}.json")=={'context':e['context'],'bundle':e['bundle']},'evaluation_ready_record_changed')
            if e['selection'] and e['selection']['attempt_ids']:
                row=next((r for r in requests if r['decision_id']==e['decision_id']),None);require(row is not None,'evaluation_request_missing')
                identity=EvaluationLedger.identity(DecisionContext.from_dict(e['context']),j['job_id'],e['decision_id'])
                require(all(row[k]==v for k,v in identity.items()) and row['selection']==e['selection'] and parse_response(DecisionContext.from_dict(e['context']),row,cfg).data==e['selection'],'evaluation_response_binding')
                used.add(row['attempt_id'])
        require(read(job/'final_layout.json')==cp['state']['placed_items'] and read(job/'physical_evaluation.json')==evaluate_state(cp['state']),'evaluation_final_layout_changed')
        if (job/'technical_failure.json').exists():common.job_derivation_failed(job,status,cp)
        else:require(read(job/'metrics.json')==metrics(task,cfg,cp,status,requests,[r for r in orders.saved_reuses(root) if r['job_id']==j['job_id']]),'evaluation_metrics_changed')
    require(all(r['attempt_id'] in used or read(root/'jobs'/r['job_id']/'status.json')['category'] in STOP for r in rows),'evaluation_unbound_request')
    require(read(root/'summary.json')==collect(root,p),'evaluation_complete_denominator_changed')
    if (root/'first_gate.json').exists():require(read(root/'first_gate.json')==gate(root,p),'evaluation_saved_gate_changed')
    return {'status':'PASS','jobs':len(p['jobs']),'requests':len(rows),'scope':p['purpose'],'dispatch':'NONE_SAVED_FACTS_ONLY'}


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Saved v10 plan/run validation only; no run or model command in JN4-A.')
    parser.add_argument('command',choices=['validate-plan','validate-run']);parser.add_argument('--output',required=True)
    a=parser.parse_args()
    result=validate_plan(a.output) if a.command=='validate-plan' else validate_run(a.output)
    print(canonical({'status':'PASS','plan_digest':digest(result)} if a.command=='validate-plan' else result))
    if a.command=='validate-run' and read(Path(a.output)/'summary.json')['status']=='ERROR':raise SystemExit(1)

if __name__=='__main__':main()
