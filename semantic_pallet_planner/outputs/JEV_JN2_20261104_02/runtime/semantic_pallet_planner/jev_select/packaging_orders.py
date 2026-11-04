"""JN1-B versioned full-order adapter over the common JN0 job/episode runner.

The single-decision JN1-A driver is never called. One shared bounded request
ledger owns the batch budget; local methods receive no ledger or transport.
"""
from __future__ import annotations
import copy
import base64
import hashlib
from itertools import combinations
from pathlib import Path
import shutil

from .contracts import JevSelectError, digest, validate_schema, DecisionContext
from .ledger import read, write, exclusive
from .experiment import source_manifest, file_manifest
from . import packaging_experiment as common
from .packaging_remote import VERSION, REGISTRY, RequestLedger, load_remote_config, decision_record
from .packaging_protocol import selector_factory, CATEGORIES, METRICS_CONTRACT, termination_category
from .packaging_runtime import load_runtime_dataset, physical_manifest, evaluate_state
from .packaging_metrics import job_metrics, aggregate, distribution
from .selector import parse_response

PLAN='jev_packaging_full_order_plan_v2'
RUN='jev_packaging_full_order_run_v2'
METHODS=list(REGISTRY)
REPO=Path(__file__).resolve().parents[4]
STOP=common.STOP_CATEGORIES


def require(ok,code):
    if not ok:raise JevSelectError(code)


def task_order():
    old=read(REPO/'semantic_pallet_planner/outputs/JEV_JN0_20261103_02/plan/plan.json')
    seen=set();ids=[]
    for j in old['jobs']:
        if j['source_group_id'] not in seen:
            seen.add(j['source_group_id']);ids.append(j['task_id'])
    return ids[:2]


def parent_receipts():
    result={}
    for name in ('JEV_JN1_20261103_01','JEV_JN1_20261103_02'):
        root=REPO/'semantic_pallet_planner/outputs'/name
        result[name]={'handoff_digest':digest(read(root/'handoff.json')),
                      'manifest_sha256':hashlib.sha256((root/'delivery_manifest.json').read_bytes()).hexdigest()}
    require(read(REPO/'semantic_pallet_planner/outputs/JEV_JN1_20261103_02/source_delivery_readiness.json')['JN1_B_admitted'],'orders_parent_not_admitted')
    return result


def prepare(dataset, spec, output):
    require(set(spec)<= {'task_ids','watchdog'},'orders_unknown_spec')
    data=load_runtime_dataset(dataset);inv=common.inventory(dataset,data)
    ids=spec.get('task_ids',task_order())
    require(isinstance(ids,list) and 1<=len(ids)<=2 and ids==task_order()[:len(ids)],'orders_unregistered_tasks')
    tasks={t['task_id']:t for t in data['tasks']}
    require(all(i in tasks and tasks[i]['partition']=='train' for i in ids),'orders_not_train')
    require(len({tasks[i]['source_group_id'] for i in ids})==len(ids),'orders_duplicate_source')
    watchdog=spec.get('watchdog',{'max_events':10000,'max_active_wall_s':1800})
    jobs=[]
    for tid in ids:
        for method in METHODS:
            t=tasks[tid];cfg=load_remote_config(data_identity=data['data_identity'],task_digest=digest(t),method=method,enabled=True)
            jobs.append({'job_id':f'J{len(jobs):04d}','task_id':tid,'method_id':method,'task_digest':digest(t),'config':cfg,
                         'source_group_id':t['source_group_id'],'variant':t['layer']})
    limits={j['job_id']:len(tasks[j['task_id']]['items']) if j['method_id']=='jev_no_memory' else 0 for j in jobs}
    plan={'version':PLAN,'execution_version':VERSION,'dataset':common.relative(dataset),'data_identity':data['data_identity'],
          'task_ids':ids,'method_ids':METHODS,'jobs':jobs,'selection_rule':'first two different-source tasks in admitted JN0 frozen order',
          'selection_mode':'PARENT_FROZEN_ORDER','watchdog':watchdog,
          'termination_contract':'natural complete/empty/instability/range stop; any technical/interface/unknown/watchdog/cancel stops batch; no retry',
          'watchdog_boundary':'durable stages only; 1800s default covers up to18x30s request time plus IO/solver margin; same for all methods; not hard realtime',
          'source_manifest':source_manifest(),'physical_manifest':physical_manifest(),'method_contract':REGISTRY,
          'metrics_contract':dict(METRICS_CONTRACT,version='jev_packaging_full_order_metrics_v2',requests='shared ledger authoritative, including failures'),
          'inventory_digest':digest(inv),'request_budget':{'per_job':limits,'global':sum(limits.values()),'derivation':'<=one send per planned box; first failed selection/monitor/commit stops; singleton bypass; no retries'},
          'run_location':common.relative(Path(output).resolve().parent/'run'),'parent_receipts':parent_receipts(),
          'pilot_jobs':3,'credential_reference':'transport.credential:typesafe_api_key.md or TYPESAFE_API_KEY; no header persisted'}
    validate_schema('packaging_full_order_plan_v2',plan)
    root=common.new_output(output);write(root/'plan.json',plan);write(root/'task_inventory.json',inv)
    for tid in ids:write(root/'tasks'/f'{tid}.json',tasks[tid])
    for name in plan['source_manifest']:
        dest=root/'code_snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(Path(__file__).resolve().parents[1]/name,dest)
    write(root/'plan_receipt.json',{'version':PLAN,'plan_digest':digest(plan)})
    write(root/'delivery_manifest.json',file_manifest(root));validate_plan(root)
    return plan


def validate_plan(root):
    root=Path(root);p=read(root/'plan.json');validate_schema('packaging_full_order_plan_v2',p)
    require(p['run_location']==common.relative(root.resolve().parent/'run') and p['parent_receipts']==parent_receipts(),'orders_run_location_or_parent_changed')
    require(read(root/'plan_receipt.json')=={'version':PLAN,'plan_digest':digest(p)},'orders_plan_digest_changed')
    require(file_manifest(root)==read(root/'delivery_manifest.json'),'orders_plan_files_changed')
    require(p['source_manifest']==source_manifest() and p['physical_manifest']==physical_manifest(),'orders_source_changed')
    require(all(hashlib.sha256((root/'code_snapshot'/n).read_bytes()).hexdigest()==h for n,h in p['source_manifest'].items()),'orders_snapshot_changed')
    require(p['task_ids']==task_order()[:len(p['task_ids'])] and p['method_ids']==METHODS and p['method_contract']==REGISTRY,'orders_scope_changed')
    data=load_runtime_dataset(REPO/p['dataset']);inv=common.inventory(REPO/p['dataset'],data)
    require(data['data_identity']==p['data_identity'] and digest(inv)==p['inventory_digest'] and read(root/'task_inventory.json')==inv,'orders_data_changed')
    require([(j['task_id'],j['method_id']) for j in p['jobs']]==[(t,m) for t in p['task_ids'] for m in METHODS],'orders_matrix_changed')
    expected_limits={}
    for i,j in enumerate(p['jobs']):
        t=next(t for t in data['tasks'] if t['task_id']==j['task_id'])
        require(j['job_id']==f'J{i:04d}' and t['partition']=='train' and digest(t)==j['task_digest'] and
                read(root/'tasks'/f"{j['task_id']}.json")==t and t['source_group_id']==j['source_group_id'] and t['layer']==j['variant'],'orders_task_changed')
        require(j['config']==load_remote_config(data_identity=data['data_identity'],task_digest=digest(t),method=j['method_id'],enabled=True),'orders_config_changed')
        expected_limits[j['job_id']]=len(t['items']) if j['method_id']=='jev_no_memory' else 0
    require(p['request_budget']['per_job']==expected_limits and p['request_budget']['global']==sum(expected_limits.values()),'orders_budget_changed')
    return p


class OrderLedger(RequestLedger):
    def __init__(self,root,budget,**kw):
        self.limits=budget['per_job'];super().__init__(root,max_sends=budget['global'],**kw)

    def _load(self):
        data=super()._load()
        for r in data['requests']:require(r['job_id'] in self.limits and self.limits[r['job_id']]>0,'orders_unregistered_request_job')
        for jid,limit in self.limits.items():
            require(sum(r['send_started'] for r in data['requests'] if r['job_id']==jid)<=limit,'orders_job_budget_exceeded')
        return data

    def record_reuse(self,row):
        events=saved_reuses(self.root.parent)
        events.append({'attempt_id':row['attempt_id'],'job_id':row['job_id'],'decision_id':row['decision_id'],
                       'binding_digest':row['binding_digest'],'state':row['state'],
                       'has_response':row['transport'] is not None and row['transport']['status']=='OK',
                       'has_selection':row['selection'] is not None})
        value={'version':'jev_full_order_request_reuses_v1','events':events}
        value['record_digest']=digest(value);write(self.root/'reuses.json',value)

    def admit_send(self,row):
        self.admit_request(row['job_id'],row['decision_id'])

    def admit_request(self,job_id,decision_id):
        require(job_id in self.limits and self.limits[job_id]>0,'orders_unregistered_request_job')
        require(sum(r['send_started'] for r in self.data['requests'] if r['job_id']==job_id)<self.limits[job_id],'orders_job_budget_exhausted')


def saved_requests(root,plan):
    path=Path(root)/'request_ledger/requests.json'
    if not path.exists():return []
    # Validate without creating a lock file or writing any receipt.
    ledger=OrderLedger.__new__(OrderLedger);ledger.limits=plan['request_budget']['per_job']
    ledger.path=path;ledger.max_sends=plan['request_budget']['global']
    return ledger._load()['requests']


def saved_reuses(root):
    path=Path(root)/'request_ledger/reuses.json'
    if not path.exists():return []
    value=read(path)
    require(value['version']=='jev_full_order_request_reuses_v1' and value['record_digest']==digest({k:v for k,v in value.items() if k!='record_digest'}),'orders_reuse_receipt_changed')
    return value['events']


def request_statistics(rows,reuses=()):
    started=[r for r in rows if r['send_started']]
    real=[r for r in started if r['origin']=='jev']
    unknown=[r for r in rows if r['state'] in ('SENDING','UNKNOWN_SEND')]
    valid=[r for r in rows if r['selection'] and r['selection']['status']=='selected']
    failed=[r for r in rows if r['state']=='FAILED' or (r['selection'] and r['selection']['status'] in ('invalid_response','provider_failure'))]
    usage=[]
    for r in rows:
        u=(r['selection'] or {}).get('usage')
        if u is None and r['transport'] is not None and r['transport']['status']=='OK':
            # Usage remains observable even when an otherwise parseable label is rejected.
            from .transport import strict_json, validate_transport
            try:
                payload=strict_json(validate_transport(r['transport']));candidate=payload.get('usage') if isinstance(payload,dict) else None
                if isinstance(candidate,dict) and set(candidate)=={'input_tokens','output_tokens'} and all(type(x) is int and x>=0 for x in candidate.values()):u=candidate
            except (ValueError,TypeError):pass
        if u is not None:usage.append(u)
    return {'stored_request_reuses':len(reuses),'stored_response_reuses':sum(r['has_response'] for r in reuses),
            'stored_selection_reuses':sum(r['has_selection'] for r in reuses),'send_reservations':len(started),'network_attempts':sum(r['transport'] is not None and r['transport']['network_attempted'] is True for r in rows),
            'model_calls':sum(r['transport'] is not None and r['transport']['network_attempted'] is True for r in real),
            'valid_responses':len(valid),'failed_requests':len(failed),'unknown_sends':len(unknown),
            'model_cost_usd':'UNKNOWN' if real else 0,'memory_cost_usd':0,
            'usage':{'input_tokens':sum(u['input_tokens'] for u in usage),'output_tokens':sum(u['output_tokens'] for u in usage),'known_request_count':len(usage),'missing_request_count':len(started)-len(usage)},
            'request_latency_s':distribution([r['transport']['latency_s'] for r in rows if r['transport'] is not None]),
            'origins':sorted({r['origin'] for r in rows}),'models':sorted({r['model'] for r in rows})}


def metrics(task,config,cp,status,requests,reuses=()):
    row=job_metrics(task,config,cp,status)
    row.update(version='jev_packaging_full_order_metrics_v2',origin=REGISTRY[config['selector']]['origin'],cost=request_statistics(requests,reuses))
    events=cp['events']+([cp['pending_event']] if cp['pending_event'] else [])
    row['singleton_decisions']=sum(e.get('selection',{}).get('source')=='singleton' for e in events if e.get('selection'))
    row['stored_selection_count']=sum(e.get('selection') is not None for e in events)
    row['stored_response_reuse_policy']='stored result read only; no resend; reuse does not add network_attempts'
    return row


def pairs(rows):
    by={}
    for r in rows:by.setdefault(r['task_id'],{})[r['method_id']]=r
    result=[]
    for tid,methods in by.items():
        for a,b in combinations(METHODS,2):
            x,y=methods.get(a),methods.get(b)
            valid=bool(x and y and all(r['category'] in ('COMPLETE','EMPTY_POOL','PREDICTED_STATIC_INSTABILITY') for r in (x,y)))
            result.append({'task_id':tid,'methods':[a,b],'direction':f'{a} minus {b}','categories':{m:r['category'] for m,r in methods.items()},
                           'comparison_valid':valid,'invalid_reason':None if valid else 'NOT_RUN_OR_RANGE_OR_TECHNICAL_STOP',
                           'delta':{**{k:x['loading'][k]-y['loading'][k] for k in ('placed_items','placed_volume_ratio','placed_mass_ratio')},
                                    'fixed_container_utilization':x['fixed_container_utilization']-y['fixed_container_utilization'],
                                    'height_mm':x['actual_height_mm']-y['actual_height_mm'] if 'NA' not in (x['actual_height_mm'],y['actual_height_mm']) else 'NA',
                                    'envelope_utilization':x['envelope_utilization']-y['envelope_utilization'] if 'NA' not in (x['envelope_utilization'],y['envelope_utilization']) else 'NA'} if x and y else 'NOT_RUN',
                           'interpretation':'descriptive exposed-source trajectories, not causal branch or global optimality; equal full loading fixed utilization does not rank layouts'})
    return result


def record(event,task,cfg,plan,requests):
    base=decision_record(event);base.pop('record_digest')
    selected=event['selection']
    chosen=next((c for c in event['bundle']['physical_candidates'] if selected and c['candidate_id']==selected['selected_candidate_id']),None)
    base.update(version='jev_full_order_decision_v1',public_state=event['context']['model_state'],candidate_pool=event['bundle'],
                exact_candidate=chosen,before=event['before'],after=event['after'],
                source_group=task['source_group_id'],task_id=task['task_id'],data_identity=plan['data_identity'],
                config_digest=digest(cfg),source_manifest_digest=digest(plan['source_manifest']),execution_version=VERSION,
                arrival_cursor=event['before']['arrival_count'],buffer=event['before']['pending_items'],
                request_receipts=[r for r in requests if r['decision_id']==event['decision_id']],
                private_task_reference='task.snapshot.json (private; not selector input)')
    base['record_digest']=digest(base)
    validate_schema('packaging_full_order_decision_v1',base)
    return base


def export_decisions(job,task,cfg,cp,plan,rows,reuses=()):
    for r in rows:
        if r['transport'] is not None:
            path=job/'responses'/f"{r['decision_id']}.raw.json";path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(base64.b64decode(r['transport']['raw_body_b64']))
            write(job/'transports'/f"{r['decision_id']}.json",r['transport'])
    for event in cp['events']+([cp['pending_event']] if cp['pending_event'] else []):
        if event.get('decision_id'):
            write(job/'decisions'/f"{event['decision_id']}.json",record(event,task,cfg,plan,rows))
            write(job/'actions'/f"{event['decision_id']}.json",event)
    write(job/'request_ledger.json',{'version':'jev_job_request_view_v1','job_id':cp['job_id'],
                                   'requests':rows,'shared_ledger':'../../request_ledger/requests.json','statistics':request_statistics(rows,reuses)})


def collect(root,plan):
    rows=[];jobs=[];requests=saved_requests(root,plan)
    for j in plan['jobs']:
        job=Path(root)/'jobs'/j['job_id'];s=read(job/'status.json')
        jobs.append({'job_id':j['job_id'],'task_id':j['task_id'],'method_id':j['method_id'],**s})
        if (job/'metrics.json').exists() and not (job/'technical_failure.json').exists():rows.append(read(job/'metrics.json'))
        elif s['category']!='NOT_RUN':jobs[-1]['metrics']='UNKNOWN_TECHNICAL_FAILURE'
    summary=aggregate(rows,len(jobs));summary.update(version='jev_packaging_full_order_summary_v2',request_statistics=request_statistics(requests,saved_reuses(root)))
    summary['categories']={c:sum(j['category']==c for j in jobs) for c in CATEGORIES}
    summary.update(model_calls=summary['request_statistics']['model_calls'],model_cost_usd=summary['request_statistics']['model_cost_usd'])
    summary['status']='ERROR' if any(j['category'] in STOP for j in jobs) else 'PASS_IN_EXECUTED_SCOPE'
    if any('metrics' in j for j in jobs):summary.update(selected_actions='UNKNOWN',assessable_coverage='UNKNOWN')
    return rows,jobs,summary


def summarize(root):
    root=Path(root)
    if (root/'delivery_manifest.json').exists():validate_run(root);return read(root/'summary.json')
    receipt=read(root/'run_receipt.json');plan=validate_plan(REPO/receipt['plan'])
    rows,jobs,summary=collect(root,plan)
    write(root/'job_ledger.json',jobs);write(root/'summary.json',summary);write(root/'paired_differences.json',pairs(rows))
    index=[]
    for j in plan['jobs']:
        for path in sorted((root/'jobs'/j['job_id']/'decisions').glob('*.json')):
            d=read(path)
            index.append({'job_id':j['job_id'],'task_id':j['task_id'],'method':j['method_id'],'source_group':j['source_group_id'],
                          'decision_id':d['decision_id'],'record':path.relative_to(root).as_posix(),'record_digest':digest(d),
                          'choice_count':len(d['available_candidate_ids']),'selected_candidate_id':d['selected_candidate_id'],
                          'rank_availability':d['ranking_availability'],'monitor_status':(d['monitor'] or {}).get('status','NOT_RUN'),
                          'eligible_training_decision':len(d['available_candidate_ids'])>=2 and d['selected_candidate_id'] is not None and read(root/'jobs'/j['job_id']/'status.json')['category'] not in STOP})
    write(root/'decision_index.json',index)
    return summary


def run(plan_root,output,*,resume=False,continue_pending=False,transport_factory=None,api_key_file=None,task_ids=None,method_ids=None):
    plan=validate_plan(plan_root)
    require(task_ids is None or task_ids==plan['task_ids'],'orders_unplanned_task')
    require(method_ids is None or method_ids==METHODS,'orders_unplanned_method')
    require(not continue_pending or resume,'orders_continue_requires_resume')
    root=Path(output).resolve()
    require(common.relative(root)==plan['run_location'],'orders_unregistered_run_location')
    receipt={'version':RUN,'plan':common.relative(plan_root),'plan_digest':digest(plan)}
    validate_schema('packaging_full_order_run_v2',receipt)
    if resume:
        require(read(root/'run_receipt.json')==receipt,'orders_run_identity_changed')
        if (root/'technical_failure.json').exists():return {'status':'ERROR','technical_failure':read(root/'technical_failure.json')}
        if (root/'delivery_manifest.json').exists():
            validate_run(root)
            summary=read(root/'summary.json')
            if not continue_pending or summary['status']=='ERROR' or not summary['categories']['NOT_RUN']:return summary
            require((root/'pilot_gate.json').exists() and read(root/'pilot_gate.json')==pilot_gate(root,plan),'orders_pilot_gate_required')
    else:
        root=common.new_output(root);write(root/'run_receipt.json',receipt)
        from .stability.runtime import environment
        write(root/'environment.json',environment())
        for j in plan['jobs']:
            job=root/'jobs'/j['job_id'];write(job/'task.snapshot.json',read(Path(plan_root)/'tasks'/f"{j['task_id']}.json"))
            write(job/'config.snapshot.json',j['config']);write(job/'status.json',{'state':'NOT_RUN','category':'NOT_RUN','active_wall_s':0.,'error':None})
    with exclusive(root):
        if (root/'delivery_manifest.json').exists():
            history=root/'pilot_snapshot'
            for n in ('delivery_manifest.json','summary.json','job_ledger.json','paired_differences.json','decision_index.json'):
                write(history/(n+'.snapshot.json'),read(root/n))
            (root/'delivery_manifest.json').unlink()
        ledger=OrderLedger(root/'request_ledger',plan['request_budget'])
        try:
            for i,j in enumerate(plan['jobs']):
                if i>=3 and not continue_pending:break
                job=root/'jobs'/j['job_id'];status=read(job/'status.json')
                if status['state']=='FINISHED':
                    if status['category'] in STOP:break
                    continue
                task=read(job/'task.snapshot.json');cfg=j['config']
                require(digest(task)==j['task_digest'] and read(job/'config.snapshot.json')==cfg,'orders_job_changed')
                transport=None
                if j['method_id']=='jev_no_memory':
                    if transport_factory is not None:transport=transport_factory(cfg,j)
                    else:
                        from .transport import JevTransport
                        transport=JevTransport(cfg,api_key_file=api_key_file)
                selector=selector_factory(j['method_id'],execution_version=VERSION,config=cfg,
                                          transport=transport,ledger=ledger if transport is not None else None,job_id=j['job_id'])
                def builder(t,c,cp,s):
                    requests=[r for r in ledger._load()['requests'] if r['job_id']==j['job_id']]
                    reuses=[r for r in saved_reuses(root) if r['job_id']==j['job_id']]
                    export_decisions(job,t,c,cp,plan,requests,reuses)
                    return metrics(t,c,cp,s,requests,reuses)
                def hook(phase,event):
                    if phase=='decision_ready':
                        did=event['decision_id'];write(job/'contexts'/f'{did}.json',event['context'])
                        write(job/'requests'/f'{did}.json',event['context']['request_body'])
                result=common._run_job(task,j,job,plan['watchdog'],selector=selector,metrics_builder=builder,hook=hook)
                if result['category'] in STOP:break
            result=summarize(root)
            if all(read(root/'jobs'/j['job_id']/'status.json')['state']=='FINISHED' for j in plan['jobs'][:3]) and result['status']!='ERROR':
                write(root/'pilot_gate.json',pilot_gate(root,plan))
            write(root/'delivery_manifest.json',file_manifest(root));validate_run(root)
            return result
        except Exception as exc:
            failure=common.technical_failure('BATCH_SUMMARY_OR_VALIDATION',exc)
            write(root/'technical_failure.json',failure);write(root/'delivery_manifest.json',file_manifest(root))
            return {'status':'ERROR','planned_jobs':len(plan['jobs']),'technical_failure':failure}


def pilot_gate(root,plan):
    require(all(read(Path(root)/'jobs'/j['job_id']/'status.json')['category'] not in STOP|{'NOT_RUN'} for j in plan['jobs'][:3]),'orders_pilot_failed')
    return {'version':'jev_full_order_pilot_gate_v1','plan_digest':digest(plan),
            'job_files_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for j in plan['jobs'][:3] for p in sorted((Path(root)/'jobs'/j['job_id']).rglob('*')) if p.is_file()},
            'scope':'first task all three methods closed and standard-validated before continuation'}


def validate_run(root):
    root=Path(root);receipt=read(root/'run_receipt.json');validate_schema('packaging_full_order_run_v2',receipt)
    plan=validate_plan(REPO/receipt['plan']);require(receipt['plan_digest']==digest(plan) and common.relative(root.resolve())==plan['run_location'],'orders_run_plan_changed')
    require(file_manifest(root)==read(root/'delivery_manifest.json'),'orders_run_files_changed')
    require(not (root/'technical_failure.json').exists(),'orders_batch_technical_failure')
    requests=saved_requests(root,plan);used=set();expected_index=[]
    for reuse in saved_reuses(root):
        require(any(all(r[k]==reuse[k] for k in ('attempt_id','job_id','decision_id','binding_digest')) for r in requests),'orders_reuse_binding_changed')
    for j in plan['jobs']:
        job=root/'jobs'/j['job_id'];status=read(job/'status.json');cfg=j['config'];task=read(job/'task.snapshot.json')
        require(digest(task)==j['task_digest'] and read(job/'config.snapshot.json')==cfg,'orders_job_snapshot_changed')
        if status['category']=='NOT_RUN':
            require(status['state']=='NOT_RUN' and not (job/'checkpoint.json').exists(),'orders_notrun_changed');continue
        if not (job/'checkpoint.json').exists():require(status['category'] in STOP,'orders_missing_checkpoint');continue
        cp=read(job/'checkpoint.json');common.validate_saved_checkpoint(cp,task,cfg,j['job_id'])
        if status['category'] not in STOP:require(status['category']==termination_category(cp['reason'],cp['events']),'orders_termination_changed')
        for stage in (job/'stages').glob('*/*.json'):
            old=read(stage);common.validate_saved_checkpoint(old,task,cfg,j['job_id'])
            require(old['events']==cp['events'][:len(old['events'])],'orders_stage_prefix_changed')
            event=old['pending_event'];final=next((e for e in cp['events'] if e.get('decision_id')==event['decision_id']),cp['pending_event'])
            require(final is not None and all(event[k]==final[k] for k in ('before','context','bundle','selection','proposed_action')),'orders_stage_binding_changed')
            if event['monitor']:require(event['monitor']==final['monitor'],'orders_monitor_overwritten')
        jobrows=[r for r in requests if r['job_id']==j['job_id']]
        for r in jobrows:
            if r['transport'] is not None:
                require((job/'responses'/f"{r['decision_id']}.raw.json").read_bytes()==base64.b64decode(r['transport']['raw_body_b64']) and
                        read(job/'transports'/f"{r['decision_id']}.json")==r['transport'],'orders_raw_response_changed')
        for e in cp['events']+([cp['pending_event']] if cp['pending_event'] else []):
            if not e.get('decision_id'):continue
            require(read(job/'actions'/f"{e['decision_id']}.json")==e,'orders_action_changed')
            require(read(job/'contexts'/f"{e['decision_id']}.json")==e['context'] and read(job/'requests'/f"{e['decision_id']}.json")==e['context']['request_body'],'orders_public_request_changed')
            expected_record=record(e,task,cfg,plan,jobrows)
            require(read(job/'decisions'/f"{e['decision_id']}.json")==expected_record,'orders_decision_record_changed')
            selected=e['selection']
            if selected and selected['attempt_ids']:
                r=next((r for r in jobrows if r['decision_id']==e['decision_id']),None)
                require(r is not None,'orders_missing_request_receipt')
                identity=RequestLedger.identity(DecisionContext.from_dict(e['context']),j['job_id'],e['decision_id'])
                require(all(r[k]==v for k,v in identity.items()),'orders_request_identity_changed')
                require(r['selection']==selected and parse_response(DecisionContext.from_dict(e['context']),r,cfg).data==selected,'orders_response_mapping_changed')
                used.add(r['attempt_id'])
        require(read(job/'final_layout.json')==cp['state']['placed_items'] and read(job/'physical_evaluation.json')==evaluate_state(cp['state']),'orders_final_state_changed')
        if (job/'technical_failure.json').exists():
            require(status['category']=='ERROR','orders_derivation_failure_hidden');continue
        require(read(job/'metrics.json')==metrics(task,cfg,cp,status,jobrows,[r for r in saved_reuses(root) if r['job_id']==j['job_id']]),'orders_metrics_changed')
        require(read(job/'request_ledger.json')=={'version':'jev_job_request_view_v1','job_id':j['job_id'],'requests':jobrows,
                                                'shared_ledger':'../../request_ledger/requests.json','statistics':request_statistics(jobrows,[r for r in saved_reuses(root) if r['job_id']==j['job_id']])},'orders_job_request_view_changed')
    # An interrupted response can precede a persisted selection; only running/error
    # jobs may own such requests. Completed natural jobs must bind every request.
    for r in requests:
        if r['attempt_id'] not in used:
            require(read(root/'jobs'/r['job_id']/'status.json')['category'] in STOP,'orders_unbound_request')
    rows,jobs,summary=collect(root,plan)
    require(read(root/'summary.json')==summary and read(root/'job_ledger.json')==jobs and read(root/'paired_differences.json')==pairs(rows),'orders_aggregate_changed')
    if (root/'pilot_gate.json').exists():require(read(root/'pilot_gate.json')==pilot_gate(root,plan),'orders_pilot_changed')
    # Independently reconstruct index fields, without rewriting any artifacts.
    for j in plan['jobs']:
        for path in sorted((root/'jobs'/j['job_id']/'decisions').glob('*.json')):
            d=read(path);expected_index.append({'job_id':j['job_id'],'task_id':j['task_id'],'method':j['method_id'],'source_group':j['source_group_id'],
                'decision_id':d['decision_id'],'record':path.relative_to(root).as_posix(),'record_digest':digest(d),'choice_count':len(d['available_candidate_ids']),
                'selected_candidate_id':d['selected_candidate_id'],'rank_availability':d['ranking_availability'],
                'monitor_status':(d['monitor'] or {}).get('status','NOT_RUN'),
                'eligible_training_decision':len(d['available_candidate_ids'])>=2 and d['selected_candidate_id'] is not None and read(root/'jobs'/j['job_id']/'status.json')['category'] not in STOP})
    require(read(root/'decision_index.json')==expected_index,'orders_decision_index_changed')
    return {'status':'PASS','jobs':len(plan['jobs']),'decisions':len(expected_index),'validation':'saved records only, no dispatch/generation/commit/PCT/network'}
