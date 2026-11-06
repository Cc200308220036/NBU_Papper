"""JN3-C bounded three-method full orders over the common _run_job/run_episode.

This is a new plan/run adapter, not an order engine. No A/B single-decision
runner is dispatched. Formal source/task/snapshot budgets cannot be reset.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
from datetime import datetime,timezone
from pathlib import Path
import shutil
from .contracts import canonical,digest,validate_schema,DecisionContext
from .ledger import read,write,exclusive
from .experiment import source_manifest,file_manifest
from . import packaging_experiment as common
from . import packaging_orders as orders
from . import packaging_experience as T
from . import packaging_contrast as E
from .packaging_pilot_protocol import VERSION,VERSIONS,REGISTRY,METHODS,PilotLedger,load_pilot_config,budget_identity
from .packaging_pilot_memory import MemoryDriver,index,NONE_DIGEST
from .packaging_runtime import load_runtime_dataset,physical_manifest,evaluate_state
from .packaging_protocol import selector_factory,termination_category,CATEGORIES
from .packaging_metrics import job_metrics,aggregate
from .selector import parse_response

REPO=Path(__file__).resolve().parents[4]
PARENTS={'T':'semantic_pallet_planner/outputs/JEV_JN3_20261104_01','E':'semantic_pallet_planner/outputs/JEV_JN3_20261104_02'}
FILES={'T':'trajectory_snapshot.json','E':'contrast_snapshot.json'}
PLAN='jev_memory_order_plan_v1';RUN='jev_memory_order_run_v1'
STOP=common.STOP_CATEGORIES
RULE_VERSION='jev_branch_comparison_rule_v2'
RECOMMENDATION={'version':'jev_memory_pilot_recommendation_v1','DEFER':'technical stop/incomplete registered jobs/no actual memory exposure/no valid memory-vs-none comparison',
 'PROCEED':'all jobs closed, engineering validation clean and at least one valid T/E-vs-none v2 improvement; exploratory only, not E superiority',
 'REVISE':'engineering closed with exposure and valid comparisons, but no registered memory-vs-none improvement; retain zero/negative results and review research design without changing frozen experience'}
GATE={'version':'jev_memory_pilot_gate_rule_v1','jobs':3,'technical':'all first-task methods finished, saved-record validated, no STOP category or unknown send',
      'allowed_range_reasons':['POSE_HEIGHT_MISMATCH','DEGENERATE_SUPPORT_HULL','DEGENERATE_CONTACT','CONSERVATIVE_HULL_INFEASIBLE','CONSERVATIVE_HULL_BOUNDARY','NETWORK_INTERIOR_BOUNDARY','NETWORK_INFEASIBILITY_UNCERTIFIED'],
      'exposure':'at least one actual sent nonempty T/E body across the first task; singleton/view-only hits do not qualify',
      'benefit':'never a gate; complete/empty/instability/explained UNASSESSABLE may continue even if memory loses',
      'stop':'technical/identity/metric/recovery error, UNKNOWN_SEND, watchdog or cancel stops batch; no replacement task/threshold/card; remaining NOT_RUN'}


def parent_refs():
    from .packaging_comparisons import checked_manifest
    return {m:checked_manifest(REPO/n) for m,n in PARENTS.items()}


def task_order():
    plan=read(REPO/'semantic_pallet_planner/outputs/JEV_JN1_20261103_03/plan/plan.json')
    return [j['task_id'] for j in plan['jobs'] if j['method_id']=='jev_no_memory'][:2]


def prepare(dataset,spec,output):
    T.require(set(spec)<={'task_ids','watchdog','fixture_only'},'pilot_unknown_spec')
    fixture=spec.get('fixture_only',False);T.require(type(fixture) is bool,'pilot_fixture_flag')
    data=load_runtime_dataset(dataset);ids=spec.get('task_ids',task_order())
    T.require(isinstance(ids,list) and 1<=len(ids)<=2 and ids==task_order()[:len(ids)],'pilot_unregistered_tasks')
    if not fixture:T.require(ids==['NEW_00100153_source_difficult','NEW_00100150_source_difficult'],'pilot_formal_scope_changed')
    tasks={t['task_id']:t for t in data['tasks']};T.require(all(i in tasks and tasks[i]['partition']=='train' for i in ids),'pilot_not_train')
    T.require(len({tasks[i]['source_group_id'] for i in ids})==len(ids),'pilot_source_overlap')
    parents=parent_refs();snapshots={m:read(REPO/PARENTS[m]/FILES[m]) for m in ('T','E')}
    T.validate_snapshot(snapshots['T']);E.validate_snapshot(snapshots['E'])
    if not fixture:T.require(not any(c['fixture_only'] for c in snapshots['T']['cases']+snapshots['E']['cards']),'pilot_fixture_memory_as_real')
    watchdog=spec.get('watchdog',{'max_events':10000,'max_active_wall_s':1800})
    T.require(set(watchdog)=={'max_events','max_active_wall_s'} and type(watchdog['max_events']) is int and watchdog['max_events']>0 and watchdog['max_active_wall_s']>0,'pilot_watchdog_invalid')
    jobs=[]
    for tid in ids:
        task=tasks[tid]
        for method in METHODS:
            mode=REGISTRY[method]['mode'];snap=None if mode=='none' else snapshots[mode]
            cfg=load_pilot_config(data_identity=data['data_identity'],task_digest=digest(task),method=method,
                snapshot_digest=NONE_DIGEST if snap is None else snap['snapshot_digest'],memory_index=index(snap,mode),
                excluded_source_groups=[task['source_group_id']],enabled=True)
            jobs.append({'job_id':f'J{len(jobs):04d}','task_id':tid,'method_id':method,'source_group_id':task['source_group_id'],
                         'task_digest':digest(task),'config':cfg,'variant':task['layer'],'planned_items':len(task['items'])})
    budget={'per_job':{j['job_id']:j['planned_items'] for j in jobs},'global':sum(j['planned_items'] for j in jobs),
            'derivation':'one send reservation per planned box at most; failure ends order; no retry; unused sends do not permit extra jobs'}
    T.require(budget['global']<=99,'pilot_scope_exceeds_99')
    from .packaging_reanalysis import RULE
    p={'version':PLAN,'execution_version':VERSION,'frozen_at':datetime.now(timezone.utc).isoformat(),
       'dataset':common.relative(dataset),'data_identity':data['data_identity'],'fixture_only':fixture,'task_ids':ids,'method_ids':METHODS,
       'jobs':jobs,'request_budget':budget,'retrieval_rule':T.RULE,'information_budget':{'historical_result':T.RULE['historical_result_budget'],'same_limits':True,'differences':'T normalized historical location detail; E hypotheses and evidence counts; equal caps do not establish information equivalence'},'watchdog':watchdog,'gate_rule':GATE,'recommendation_rule':RECOMMENDATION,'evaluation_rule':RULE,'parent_refs':parents,
       'snapshots':{m:{'file':FILES[m],'snapshot_digest':snapshots[m]['snapshot_digest'],'file_sha256':T.sha(REPO/PARENTS[m]/FILES[m])} for m in ('T','E')},
       'source_manifest':source_manifest(),'physical_manifest':physical_manifest(),'method_registry':REGISTRY,
       'run_location':common.relative(Path(output).resolve().parent/'run'),
       'scope':'exposed development sources only; no effect-based task selection or experience updates; DeepSeek/reviewer calls zero',
       'credential_reference':'existing JevTransport typesafe_api_key.md; no header/key persistence'}
    validate_schema('pilot_plan_v1',p);root=common.new_output(output);write(root/'plan.json',p);write(root/'plan_receipt.json',{'version':PLAN,'plan_digest':digest(p)})
    for tid in ids:write(root/'tasks'/f'{tid}.json',tasks[tid])
    for m in ('T','E'):
        dest=root/'memories'/FILES[m];dest.parent.mkdir(exist_ok=True);shutil.copyfile(REPO/PARENTS[m]/FILES[m],dest)
    package=Path(__file__).resolve().parents[1]
    for n in p['source_manifest']:
        dest=root/'code_snapshot'/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(package/n,dest)
    algorithm=p['jobs'][0]['config']['stability_monitor']['algorithm_identity']['files_sha256']
    for n,h in algorithm.items():
        origin=package/'jev_select/stability'/n
        T.require(T.sha(origin)==h,'pilot_algorithm_source_changed')
        dest=root/'code_snapshot/jev_select/stability'/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(origin,dest)
    write(root/'algorithm_archive_manifest.json',algorithm)
    write(root/'delivery_manifest.json',file_manifest(root));validate_plan(root);return p


def validate_plan(root):
    root=Path(root);p=read(root/'plan.json');validate_schema('pilot_plan_v1',p)
    T.require(read(root/'plan_receipt.json')=={'version':PLAN,'plan_digest':digest(p)} and read(root/'delivery_manifest.json')==file_manifest(root),'pilot_plan_bytes_changed')
    T.require(p['source_manifest']==source_manifest() and p['physical_manifest']==physical_manifest(),'pilot_source_or_physics_changed')
    T.require(all(T.sha(root/'code_snapshot'/n)==h for n,h in p['source_manifest'].items()),'pilot_source_archive_changed')
    algorithm=p['jobs'][0]['config']['stability_monitor']['algorithm_identity']['files_sha256']
    T.require(read(root/'algorithm_archive_manifest.json')==algorithm and all(T.sha(root/'code_snapshot/jev_select/stability'/n)==h for n,h in algorithm.items()),'pilot_algorithm_archive_changed')
    from .packaging_reanalysis import RULE
    T.require(p['parent_refs']==parent_refs() and p['retrieval_rule']==T.RULE and p['information_budget']=={'historical_result':T.RULE['historical_result_budget'],'same_limits':True,'differences':'T normalized historical location detail; E hypotheses and evidence counts; equal caps do not establish information equivalence'} and p['evaluation_rule']==RULE and p['gate_rule']==GATE and p['recommendation_rule']==RECOMMENDATION and p['method_registry']==REGISTRY,'pilot_parent_or_rules_changed')
    T.require(p['run_location']==common.relative(root.resolve().parent/'run') and p['method_ids']==METHODS and p['task_ids']==task_order()[:len(p['task_ids'])],'pilot_scope_changed')
    if not p['fixture_only']:T.require(p['task_ids']==['NEW_00100153_source_difficult','NEW_00100150_source_difficult'],'pilot_formal_scope_changed')
    data=load_runtime_dataset(REPO/p['dataset']);tasks={t['task_id']:t for t in data['tasks']}
    T.require(data['data_identity']==p['data_identity'] and len({tasks[i]['source_group_id'] for i in p['task_ids']})==len(p['task_ids']),'pilot_data_changed')
    snaps={}
    for m in ('T','E'):
        ref=p['snapshots'][m];f=root/'memories'/FILES[m]
        T.require(ref['file']==FILES[m] and T.sha(f)==ref['file_sha256']==T.sha(REPO/PARENTS[m]/FILES[m]),'pilot_snapshot_reference_changed')
        snaps[m]=read(f)
        (T if m=='T' else E).validate_snapshot(snaps[m],ref['snapshot_digest'])
    T.require([(j['task_id'],j['method_id']) for j in p['jobs']]==[(i,m) for i in p['task_ids'] for m in METHODS],'pilot_matrix_changed')
    for i,j in enumerate(p['jobs']):
        task=tasks[j['task_id']];mode=REGISTRY[j['method_id']]['mode'];snap=None if mode=='none' else snaps[mode]
        expected=load_pilot_config(data_identity=data['data_identity'],task_digest=digest(task),method=j['method_id'],snapshot_digest=NONE_DIGEST if snap is None else snap['snapshot_digest'],
                   memory_index=index(snap,mode),excluded_source_groups=[task['source_group_id']],enabled=True)
        T.require(j['job_id']==f'J{i:04d}' and j['task_digest']==digest(task) and read(root/'tasks'/f"{j['task_id']}.json")==task and task['partition']=='train' and j['source_group_id']==task['source_group_id'] and j['planned_items']==len(task['items']) and j['config']==expected,'pilot_job_binding_changed')
    T.require(p['request_budget']['per_job']=={j['job_id']:j['planned_items'] for j in p['jobs']} and p['request_budget']['global']==sum(j['planned_items'] for j in p['jobs'])<=99,'pilot_budget_changed')
    return p


def saved_requests(root,plan):
    path=Path(root)/'request_ledger/requests.json'
    if not path.exists():return []
    l=PilotLedger.__new__(PilotLedger);l.path=path;l.limits=plan['request_budget']['per_job'];l.max_sends=plan['request_budget']['global'];l.configs={j['job_id']:j['config'] for j in plan['jobs']}
    l._budget_digest=budget_identity(plan['request_budget'],l.configs)
    return l._load()['requests']


def record(event,task,cfg,plan,requests):
    from .packaging_remote import decision_record
    base=decision_record(event);base.pop('record_digest')
    base.update(version='jev_memory_order_decision_v1',public_state=event['context']['model_state'],candidate_pool=event['bundle'],
         before=event['before'],after=event['after'],task_id=task['task_id'],source_group=task['source_group_id'],data_identity=plan['data_identity'],
         execution_version=VERSION,config_digest=digest(cfg),source_manifest_digest=digest(plan['source_manifest']),
         memory_view=event['context']['memory_view'],retrieval_receipt=event['context']['retrieval_receipt'],
         request_receipts=[r for r in requests if r['decision_id']==event['decision_id']],
         exact_candidate=next((c for c in event['bundle']['physical_candidates'] if event['selection'] and c['candidate_id']==event['selection']['selected_candidate_id']),None))
    base['record_digest']=digest(base);validate_schema('pilot_decision_v1',base);return base


def exposure(events,requests,mode,*,library_nonempty=False):
    decisions=[e for e in events if e.get('decision_id')];by={r['decision_id']:r for r in requests}
    rows=[]
    for e in decisions:
        c=e['context'];v=c['memory_view'];r=by.get(e['decision_id']);raw=c['retrieval_receipt']['raw_retrieval']
        sent=bool(r and r['send_started']);network=bool(r and r['transport'] and r['transport']['network_attempted'] is True)
        rows.append({'decision_id':e['decision_id'],'route':c['route'],'query_digest':c['local_binding']['query_digest'],
          'retrieval_digest':c['local_binding']['retrieval_digest'],'snapshot_digest':v['snapshot_digest'],'view_digest':v['view_digest'],
          'library_nonempty':library_nonempty,'qualified_retrieval_nonempty':bool(raw and raw['retrieval_nonempty']),
          'view_nonempty':bool(v['entries']),'request_body_nonempty':bool(c['request_body'] and c['request_body']['state']['memories']),
          'send_reserved':sent,'network_attempted':network,
          'nonempty_body_network_attempt':bool(network and c['request_body'] and c['request_body']['state']['memories']),
          'actually_sent_nonempty':bool(network and r['transport']['status']=='OK' and c['request_body'] and c['request_body']['state']['memories']),
          'injection_confirmation':'RESPONSE_RECEIVED' if network and r['transport']['status']=='OK' else 'UNKNOWN_SEND' if r and r['state'] in ('SENDING','UNKNOWN_SEND') else 'NOT_CONFIRMED',
          'chars':v['injected_chars'],'utf8_bytes':v['injected_utf8_bytes'],'entries':len(v['entries']),
          'selected_candidate_id':(e['selection'] or {}).get('selected_candidate_id'),
          'selected_box':next((x['pick_item_id'] for x in e['bundle']['physical_candidates'] if x['candidate_id']==(e['selection'] or {}).get('selected_candidate_id')),None),
          'selected_pose':next((x['pose'] for x in e['bundle']['physical_candidates'] if x['candidate_id']==(e['selection'] or {}).get('selected_candidate_id')),None),
          'public_entry_fields':[sorted(x) for x in v['entries']],
          'usage':r['selection']['usage'] if r and r['selection'] else 'UNKNOWN' if sent else 'NOT_SENT',
          'origin':r['origin'] if r else 'NOT_SENT',
          'monitor_status':(e.get('monitor') or {}).get('status'),'reason':c['retrieval_receipt']['status']})
    return {'mode':mode,'decisions':rows,'decision_count':len(rows),'view_nonempty_count':sum(r['view_nonempty'] for r in rows),
            'body_nonempty_count':sum(r['request_body_nonempty'] for r in rows),'actually_sent_nonempty_count':sum(r['actually_sent_nonempty'] for r in rows),
            'singleton_nonempty_view_count':sum(r['route']=='SINGLETON_BYPASS' and r['view_nonempty'] for r in rows)}


def metrics(task,cfg,cp,status,requests,reuses=()):
    row=job_metrics(task,cfg,cp,status);events=cp['events']+([cp['pending_event']] if cp['pending_event'] else [])
    row.update(version='jev_memory_order_metrics_v1',origin='jev',cost=orders.request_statistics(requests,reuses),
        memory_metrics=exposure(events,requests,cfg['memory_mode'],library_nonempty=bool(cfg['memory_index'])),memory_mode=cfg['memory_mode'],snapshot_digest=cfg['memory_snapshot_digest'])
    return row


def collect(root,plan):
    root=Path(root);rows=[];jobs=[]
    for j in plan['jobs']:
        job=root/'jobs'/j['job_id'];status=read(job/'status.json');entry={'job_id':j['job_id'],'task_id':j['task_id'],'method_id':j['method_id'],**status}
        if (job/'metrics.json').exists() and not (job/'technical_failure.json').exists():rows.append(read(job/'metrics.json'))
        elif status['category']!='NOT_RUN':entry['metrics']='UNKNOWN_TECHNICAL_FAILURE'
        jobs.append(entry)
    summary=aggregate(rows,len(plan['jobs']));summary.update(version='jev_memory_order_summary_v1',fixture_only=plan['fixture_only'],
        categories={c:sum(j['category']==c for j in jobs) for c in CATEGORIES},request_statistics=orders.request_statistics(saved_requests(root,plan),orders.saved_reuses(root)))
    summary.update(model_calls=summary['request_statistics']['model_calls'],model_cost_usd=summary['request_statistics']['model_cost_usd'],
        status='ERROR' if any(j['category'] in STOP for j in jobs) else 'PASS_IN_EXECUTED_SCOPE')
    if any('metrics' in j for j in jobs):summary.update(selected_actions='UNKNOWN',assessable_coverage='UNKNOWN')
    return rows,jobs,summary


def summarize(root,plan):
    from .packaging_pilot_analysis import pairs,behaviors
    root=Path(root);rows,jobs,summary=collect(root,plan)
    write(root/'job_ledger.json',jobs);write(root/'summary.json',summary)
    write(root/'paired_differences.json',pairs(root,plan,rows));write(root/'behavior_analysis.json',behaviors(root,plan))
    return summary


def pilot_gate(root,plan):
    root=Path(root);statuses=[read(root/'jobs'/j['job_id']/'status.json') for j in plan['jobs'][:3]]
    metrics_=[read(root/'jobs'/j['job_id']/'metrics.json') for j in plan['jobs'][:3] if (root/'jobs'/j['job_id']/'metrics.json').exists()]
    closed=all(s['state']=='FINISHED' and s['category'] not in STOP|{'NOT_RUN'} for s in statuses)
    seen=sum(m['memory_metrics']['actually_sent_nonempty_count'] for m in metrics_ if m['memory_mode'] in ('T','E'))
    technical=not (root/'technical_failure.json').exists() and not orders.request_statistics(saved_requests(root,plan))['unknown_sends']
    return {'version':'jev_memory_pilot_gate_v1','plan_digest':digest(plan),'rule':GATE,'closed':closed,'technical_ok':technical,
       'memory_actual_exposure_count':seen,'status':'PASS' if closed and technical and seen>0 else 'DEFER_NO_EXPOSURE' if closed and technical else 'STOP_TECHNICAL',
       'job_files_sha256':{str(f.relative_to(root)):T.sha(f) for j in plan['jobs'][:3] for f in sorted((root/'jobs'/j['job_id']).rglob('*')) if f.is_file()},
       'benefit_used_for_gate':False}


def run(plan_root,output,*,resume=False,continue_pending=False,transport_factory=None,api_key_file=None,task_ids=None,method_ids=None):
    plan=validate_plan(plan_root);root=Path(output).resolve()
    T.require(task_ids is None or task_ids==plan['task_ids'],'pilot_unplanned_task');T.require(method_ids is None or method_ids==METHODS,'pilot_unplanned_method')
    T.require(common.relative(root)==plan['run_location'],'pilot_unregistered_run_location');T.require(not continue_pending or resume,'pilot_continuation_requires_resume')
    T.require(plan['fixture_only']==(transport_factory is not None),'pilot_transport_mode_mismatch')
    if not plan['fixture_only'] and not resume:
        T.require(not (REPO/'semantic_pallet_planner/outputs/JEV_JN3_C_ACCOUNTING_V1/owner.json').exists(),'pilot_stage_already_registered_use_resume')
    if resume and any((root/'jobs').glob('*/checkpoint.json')):
        T.require((root/'request_ledger/requests.json').exists(),'pilot_missing_durable_request_ledger')
    receipt={'version':RUN,'plan':common.relative(plan_root),'plan_digest':digest(plan)};validate_schema('pilot_run_v1',receipt)
    if resume:
        T.require(read(root/'run_receipt.json')==receipt,'pilot_run_identity_changed')
        if (root/'technical_failure.json').exists():return read(root/'technical_failure.json')
        if (root/'delivery_manifest.json').exists():
            validate_run(root);result=read(root/'summary.json')
            if result['status']=='ERROR' or not continue_pending or not result['categories']['NOT_RUN']:return result
            T.require(read(root/'pilot_gate.json')==pilot_gate(root,plan) and read(root/'pilot_gate.json')['status']=='PASS','pilot_continuation_gate_failed')
    else:
        root=common.new_output(root);write(root/'run_receipt.json',receipt)
        from .stability.runtime import environment
        write(root/'environment.json',environment())
        for j in plan['jobs']:
            job=root/'jobs'/j['job_id'];write(job/'task.snapshot.json',read(Path(plan_root)/'tasks'/f"{j['task_id']}.json"));write(job/'config.snapshot.json',j['config'])
            write(job/'status.json',{'state':'NOT_RUN','category':'NOT_RUN','active_wall_s':0.,'error':None})
    # Formal batch ownership survives new windows/new output directory attempts.
    if not plan['fixture_only']:
        account=REPO/'semantic_pallet_planner/outputs/JEV_JN3_C_ACCOUNTING_V1';account.mkdir(parents=True,exist_ok=True)
        with exclusive(account):
            owner={'plan_digest':digest(plan),'run_location':plan['run_location'],'request_budget':plan['request_budget']}
            if (account/'owner.json').exists():T.require(read(account/'owner.json')==owner,'pilot_stage_budget_already_owned')
            else:write(account/'owner.json',owner)
    snapshots={m:read(Path(plan_root)/'memories'/FILES[m]) for m in ('T','E')}
    with exclusive(root):
        if (root/'delivery_manifest.json').exists():
            history=root/'batch_history'/f"B{len(list((root/'batch_history').glob('B*')))+1:04d}"
            for n in ('delivery_manifest.json','summary.json','job_ledger.json','paired_differences.json','behavior_analysis.json','pilot_gate.json'):
                write(history/(n+'.snapshot.json'),read(root/n))
            (root/'delivery_manifest.json').unlink()
        configs={j['job_id']:j['config'] for j in plan['jobs']};ledger=PilotLedger(root/'request_ledger',plan['request_budget'],configs)
        try:
            for i,j in enumerate(plan['jobs']):
                if i>=3 and not continue_pending:break
                job=root/'jobs'/j['job_id'];status=read(job/'status.json')
                if status['state']=='FINISHED':
                    if status['category'] in STOP:break
                    continue
                cfg=j['config'];task=read(job/'task.snapshot.json');mode=cfg['memory_mode']
                T.require(digest(task)==j['task_digest'] and read(job/'config.snapshot.json')==cfg,'pilot_job_changed')
                if transport_factory is None:
                    from .transport import JevTransport
                    transport=JevTransport(cfg,api_key_file=api_key_file)
                else:transport=transport_factory(cfg,j)
                T.require(transport.origin==('test_double' if plan['fixture_only'] else 'jev'),'pilot_transport_origin_mismatch')
                selector=selector_factory(j['method_id'],execution_version=VERSION,config=cfg,transport=transport,ledger=ledger,job_id=j['job_id'])
                driver=MemoryDriver(cfg,snapshot=None if mode=='none' else snapshots[mode])
                def builder(t,c,cp,s):
                    rows=[r for r in ledger._load()['requests'] if r['job_id']==j['job_id']];reuses=[r for r in orders.saved_reuses(root) if r['job_id']==j['job_id']]
                    orders.export_decisions(job,t,c,cp,plan,rows,reuses,record_builder=record)
                    return metrics(t,c,cp,s,rows,reuses)
                def hook(phase,event):
                    if phase=='decision_ready':
                        did=event['decision_id'];c=event['context'];trace={'context':c,'query':c['retrieval_receipt']['query'],'retrieval':c['retrieval_receipt'],'view':c['memory_view'],'body':c['request_body']}
                        path=job/'memory_decisions'/f'{did}.json'
                        if path.exists():T.require(read(path)==trace,'pilot_saved_trace_missing_or_changed')
                        else:
                            # The complete checkpoint context is durable before this callback.
                            write(path,trace)
                        for n,v in [('contexts',c),('requests',c['request_body'])]:write(job/n/f'{did}.json',v)
                result=common._run_job(task,j,job,plan['watchdog'],selector=selector,metrics_builder=builder,hook=hook,memory_driver=driver)
                if result['category'] in STOP:break
                if result['category']=='UNASSESSABLE':
                    reasons=common.unassessable_reasons_from_checkpoint(read(job/'checkpoint.json'))
                    T.require(bool(reasons) and set(reasons)<=set(GATE['allowed_range_reasons']),'pilot_unexplained_monitor_range')
            result=summarize(root,plan)
            write(root/'delivery_manifest.json',file_manifest(root));validate_run(root,check_gate=False)
            if all(read(root/'jobs'/j['job_id']/'status.json')['state']=='FINISHED' for j in plan['jobs'][:3]):
                write(root/'pilot_gate.json',pilot_gate(root,plan))
            write(root/'delivery_manifest.json',file_manifest(root));validate_run(root)
            return result
        except Exception as exc:
            failure=common.technical_failure('PILOT_SUMMARY_OR_VALIDATION',exc);write(root/'technical_failure.json',failure)
            jobs=[{'job_id':j['job_id'],'task_id':j['task_id'],'method_id':j['method_id'],**read(root/'jobs'/j['job_id']/'status.json')} for j in plan['jobs']]
            write(root/'job_ledger.json',jobs);summary={'status':'ERROR','planned_jobs':len(plan['jobs']),'categories':{c:sum(j['category']==c for j in jobs) for c in CATEGORIES},'technical_failure':failure,'request_statistics':orders.request_statistics(saved_requests(root,plan),orders.saved_reuses(root))}
            write(root/'summary.json',summary);write(root/'delivery_manifest.json',file_manifest(root));return summary


def validate_stage(old,cp,task,cfg,jid):
    validate_schema('checkpoint_v9',old)
    T.require(old['record_digest']==digest({k:v for k,v in old.items() if k!='record_digest'}) and
        old['job_id']==jid and old['method']==cfg['selector'] and old['task_digest']==digest(task) and old['config_digest']==digest(cfg) and old['runtime_identity']==cfg['runtime_identity'],'pilot_stage_identity_changed')
    prefix=old['events'];T.require(prefix==cp['events'][:len(prefix)],'pilot_stage_prefix_changed')
    event=old['pending_event'];T.require(event is not None and old['phase'] in ('DECISION_READY','SELECTED','MONITORED','COMMITTED'),'pilot_stage_phase_changed')
    final=next((e for e in cp['events'] if e.get('decision_id')==event['decision_id']),cp['pending_event'])
    T.require(final is not None and all(event[k]==final[k] for k in ('decision_id','before','context','bundle','observation','route')),'pilot_pre_send_context_changed')
    if old['phase']=='DECISION_READY':
        T.require(event['selection'] is None and event['proposed_action'] is None and event['monitor'] is None,'pilot_ready_selection_changed')
    else:
        T.require(event['selection']==final['selection'] and event['proposed_action']==final['proposed_action'],'pilot_saved_selection_changed')
        if old['phase']=='SELECTED':T.require(event['monitor'] is None,'pilot_selected_monitor_changed')
        else:T.require(event['monitor']==final['monitor'],'pilot_saved_monitor_overwritten')
    committed=old['phase']=='COMMITTED'
    T.require(event['event']==('PLACE' if committed else 'STOP') and event['business_after'] is None and event['reference_after'] is None,'pilot_stage_event_changed')
    if not committed:T.require(event['reason'] is None and event['error'] is None,'pilot_stage_pending_error_changed')
    expected_state=final['after'] if committed else final['before']
    T.require(old['state']==expected_state and event['after']==expected_state and
        event['action']==(final['action'] if committed else None),'pilot_stage_state_changed')
    T.require(old['cursor']==sum(e['event']=='WAIT_RECEIVE' for e in prefix) and old['decision']==sum(bool(e.get('decision_id')) for e in prefix),'pilot_stage_progress_changed')
    T.require(old['reason'] is None or (committed and old['reason']=='EVALUATION_ERROR'),'pilot_stage_reason_changed')
    return old


def validate_run(root,*,check_gate=True):
    """Read saved records only. No network, driver.resolve, candidates or commit."""
    root=Path(root);receipt=read(root/'run_receipt.json');validate_schema('pilot_run_v1',receipt)
    plan=validate_plan(REPO/receipt['plan']);T.require(receipt['plan_digest']==digest(plan) and common.relative(root)==plan['run_location'],'pilot_run_plan_changed')
    T.require(file_manifest(root)==read(root/'delivery_manifest.json'),'pilot_run_bytes_changed')
    requests=saved_requests(root,plan);used=set()
    for reuse in orders.saved_reuses(root):
        T.require(any(all(r[k]==reuse[k] for k in ('attempt_id','job_id','decision_id','binding_digest')) for r in requests),'pilot_reuse_binding_changed')
    for j in plan['jobs']:
        job=root/'jobs'/j['job_id'];status=read(job/'status.json');task=read(job/'task.snapshot.json');cfg=j['config']
        T.require(digest(task)==j['task_digest'] and read(job/'config.snapshot.json')==cfg,'pilot_saved_job_changed')
        jobrows=[r for r in requests if r['job_id']==j['job_id']]
        if status['state']=='NOT_RUN':
            T.require(status['category']=='NOT_RUN' and not jobrows and not (job/'checkpoint.json').exists(),'pilot_notrun_changed');continue
        if not (job/'checkpoint.json').exists():T.require(status['category'] in STOP,'pilot_missing_checkpoint');continue
        cp=read(job/'checkpoint.json');common.validate_saved_checkpoint(cp,task,cfg,j['job_id'])
        if status['category'] not in STOP:T.require(status['category']==termination_category(cp['reason'],cp['events']),'pilot_termination_changed')
        for f in (job/'stages').glob('*/*.json'):
            validate_stage(read(f),cp,task,cfg,j['job_id'])
        for ev in cp['events']+([cp['pending_event']] if cp['pending_event'] else []):
            if not ev.get('decision_id'):continue
            did=ev['decision_id'];c=ev['context'];trace={'context':c,'query':c['retrieval_receipt']['query'],'retrieval':c['retrieval_receipt'],'view':c['memory_view'],'body':c['request_body']}
            T.require(read(job/'memory_decisions'/f'{did}.json')==trace and read(job/'contexts'/f'{did}.json')==c and read(job/'requests'/f'{did}.json')==c['request_body'],'pilot_saved_trace_changed')
            T.require(read(job/'actions'/f'{did}.json')==ev and read(job/'decisions'/f'{did}.json')==record(ev,task,cfg,plan,jobrows),'pilot_saved_decision_changed')
            selected=ev['selection']
            if selected and selected['attempt_ids']:
                row=next((r for r in jobrows if r['decision_id']==did),None);T.require(row is not None,'pilot_missing_request')
                ctx=DecisionContext.from_dict(c);identity=PilotLedger.identity(ctx,j['job_id'],did)
                T.require(all(row[k]==v for k,v in identity.items()) and row['selection']==selected and parse_response(ctx,row,cfg).data==selected,'pilot_response_or_request_changed')
                used.add(row['attempt_id'])
        for row in jobrows:
            if row['transport'] is not None:
                import base64
                T.require((job/'responses'/f"{row['decision_id']}.raw.json").read_bytes()==base64.b64decode(row['transport']['raw_body_b64']) and read(job/'transports'/f"{row['decision_id']}.json")==row['transport'],'pilot_raw_response_changed')
        T.require(read(job/'final_layout.json')==cp['state']['placed_items'] and read(job/'physical_evaluation.json')==evaluate_state(cp['state']),'pilot_final_layout_changed')
        if (job/'technical_failure.json').exists():common.job_derivation_failed(job,status,cp);continue
        reuses=[r for r in orders.saved_reuses(root) if r['job_id']==j['job_id']]
        T.require(read(job/'metrics.json')==metrics(task,cfg,cp,status,jobrows,reuses),'pilot_metrics_changed')
        T.require(read(job/'request_ledger.json')=={'version':'jev_job_request_view_v1','job_id':j['job_id'],'requests':jobrows,'shared_ledger':'../../request_ledger/requests.json','statistics':orders.request_statistics(jobrows,reuses)},'pilot_job_request_view_changed')
    for row in requests:
        if row['attempt_id'] not in used:T.require(read(root/'jobs'/row['job_id']/'status.json')['category'] in STOP,'pilot_unbound_request')
    if (root/'technical_failure.json').exists():
        f=read(root/'technical_failure.json');T.require(f['phase']=='PILOT_SUMMARY_OR_VALIDATION' and read(root/'summary.json')['technical_failure']==f,'pilot_emergency_receipt_changed')
        return {'status':'TECHNICAL_FAILURE_PRESERVED','planned_jobs':len(plan['jobs']),'requests':len(requests)}
    from .packaging_pilot_analysis import pairs,behaviors
    rows,jobs,summary=collect(root,plan)
    T.require(read(root/'summary.json')==summary and read(root/'job_ledger.json')==jobs and read(root/'paired_differences.json')==pairs(root,plan,rows) and read(root/'behavior_analysis.json')==behaviors(root,plan),'pilot_saved_analysis_changed')
    if check_gate and (root/'pilot_gate.json').exists():T.require(read(root/'pilot_gate.json')==pilot_gate(root,plan),'pilot_gate_changed')
    return {'status':'PASS','jobs':len(plan['jobs']),'requests':len(requests),'validation':'saved facts only; no retrieval dispatch, selection, generation, commit, PCT or network'}


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','run','validate']);p.add_argument('--output',required=True);p.add_argument('--plan');p.add_argument('--dataset');p.add_argument('--resume',action='store_true');p.add_argument('--continue-pending',action='store_true');p.add_argument('--api-key-file');a=p.parse_args()
    if a.command=='prepare':result=prepare(a.dataset,{},a.output);result={'plan_digest':digest(result),'jobs':len(result['jobs']),'budget':result['request_budget']}
    elif a.command=='run':result=run(a.plan,a.output,resume=a.resume,continue_pending=a.continue_pending,api_key_file=a.api_key_file)
    else:result=validate_run(a.output)
    print(canonical(result))
if __name__=='__main__':main()
