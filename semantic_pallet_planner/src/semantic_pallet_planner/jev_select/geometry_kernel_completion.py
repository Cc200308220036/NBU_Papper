"""Closed completion coverage, independent of launching or issuing permits."""
from .geometry_native_protocol import wire, is_native, identity_fields, config_fields
from .contracts import digest,validate_schema
from .packaging_geometry_protocol import require,read_reference
from .packaging_versions import GEOMETRY_BACKENDS


def required_coverage(plan):
    require([t['task_id'] for t in plan['tasks']]==['GP5_SYNTH_K01','GP5_SYNTH_K02'],'geometry_completion_required_cases')
    rows=[]
    for job in plan['jobs']:
        require(job['method']=='local_first_test_double','geometry_completion_method')
        rows.append({'job_id':job['job_id'],'task_id':job['task_id'],'backend':job['backend'],
            'poses':([{'x_mm':-260,'y_mm':-150 if job['backend']=='e2_original_v1' else 150,'z_base_mm':0,'yaw_deg':90}] if job['task_id'].endswith('K01') else [{'x_mm':0,'y_mm':0,'z_base_mm':60*i,'yaw_deg':0} for i in range(2)]),
            'status':'STABLE','termination':'ALL_ITEMS_PLACED'})
    require(len(rows)==4 and len({r['job_id'] for r in rows})==4 and
        {(r['task_id'],r['backend']) for r in rows}=={(t,b) for t in ('GP5_SYNTH_K01','GP5_SYNTH_K02') for b in GEOMETRY_BACKENDS},'geometry_completion_matrix')
    return {**identity_fields(plan),'version':wire(plan,'geometry_kernel_required_coverage_v1'),'primary':rows,
        'recovery': [{'job_id':r['job_id'],'phase':phase} for r in rows if r['task_id']=='GP5_SYNTH_K01' for phase in ('SELECTED','MONITORED','COMMITTED')],
        'K03':'ADAPTER_ONLY_AND_PUBLIC_NEGATIVE_NOT_RUN_NOT_COMPLETION_CLAIM'}


def check_success(record,expected):
    cp=record['checkpoint'];cfg=record['config']
    require(cp['job_id']==expected['job_id'] and cfg['order_task_identity']['task_id']==expected['task_id']
        and cfg['candidate_backend']==expected['backend'] and cp['method']==cfg['selector']=='local_first_test_double','geometry_completion_job_binding')
    require(cp['phase']=='TERMINATED' and cp['reason']=='ALL_ITEMS_PLACED','geometry_completion_technical_stop')
    events=[e for e in cp['events'] if e.get('selection')]
    require(len(events)==len(expected['poses']) and len(cp['state']['placed_items'])==len(events)
        and cp['state']['end_of_stream'] and not cp['state']['pending_items'],'geometry_completion_commits')
    for event,pose in zip(events,expected['poses']):
        chosen=next((c for c in event['bundle']['physical_candidates'] if c['candidate_id']==event['selection']['selected_candidate_id']),None)
        require(chosen is not None and chosen['pose']==pose and chosen['oriented_size_mm']==([100,80,60] if pose['yaw_deg']==0 else [80,100,60]), 'geometry_completion_exact_action')
        row=event.get('monitor') or {}
        require(event['event']=='PLACE' and event['action']==event['proposed_action'] and row.get('status')=='STABLE'
            and row.get('result',{}).get('status')=='STABLE' and len(event['after']['placed_items'])==len(event['before']['placed_items'])+1,
            'geometry_completion_success_required')


def validate_completion(receipt,plan,log,validate_record):
    """validate_record must perform genuine identity/durable checks, including resumes."""
    coverage=required_coverage(plan)
    review=read_reference(receipt['review']);validate_schema(wire(plan,'geometry_kernel_completion_review_v1'),review)
    expected={'acceptance_plan_digest':digest(plan),'records_digest':digest(receipt['records']),
        'recovery_digest':digest(receipt['recovery']),'counter_log':receipt['counter_log'],'coverage_digest':digest(coverage)}
    require(all(review[k]==v for k,v in expected.items()),'geometry_completion_review_binding')
    require(len(receipt['records'])==4 and len({r['sha256'] for r in receipt['records']})==4,'geometry_completion_unique_records')
    records=[read_reference(r) for r in receipt['records']]
    require([r['checkpoint']['job_id'] for r in records]==[r['job_id'] for r in coverage['primary']],'geometry_completion_record_set')
    for record,row in zip(records,coverage['primary']):validate_record(record);check_success(record,row)
    recovery=receipt['recovery']
    require([{'job_id':r['job_id'],'phase':r['phase']} for r in recovery]==coverage['recovery'],'geometry_completion_recovery_set')
    for row in recovery:
        before=read_reference(row['before']);after=read_reference(row['after']);account=read_reference(row['accounting'])
        validate_schema(wire(plan,'geometry_order_accounting_v1'),account)
        expected=next(r for r in coverage['primary'] if r['job_id']==row['job_id'])
        require(before['phase']==row['phase'] and before['job_id']==row['job_id'],'geometry_completion_recovery_phase')
        # Validate both snapshots with the same shared durable transition validator.
        validate_record({**after,'checkpoint':before});validate_record(after);check_success(after,expected)
        require(account['job_id']==row['job_id'] and account['plan_digest']==digest(plan)
            and account['config_digest']==digest(after['config']),'geometry_completion_recovery_account')
        inv=account['invocations'];require(bool(inv),'geometry_completion_recovery_invocation')
        delta={'selector_calls':0,'singleton_executions':0,'monitor_entries':int(row['phase']=='SELECTED'),
            'monitor_reuses':int(row['phase']=='MONITORED'),'commit_attempts':int(row['phase']!='COMMITTED'),
            'commit_successes':int(row['phase']!='COMMITTED')}
        require(inv[-1]['resume_checkpoint_digest']==digest(before) and inv[-1]['result_checkpoint_digest']==digest(after['checkpoint']) and inv[-1]['resume_phase']==row['phase'] and inv[-1]['status']=='RETURNED' and inv[-1]['delta']==delta
            and all(account['cumulative'][k]==sum(i['delta'][k] for i in inv) for k in delta),'geometry_completion_recovery_delta')
        event=after['checkpoint']['events'][-1];pending=before['pending_event']
        require(event['selection']==pending['selection'] and event['proposed_action']==pending['proposed_action'],'geometry_completion_reselected')
        if row['phase']!='SELECTED':require(event['monitor']['result_digest']==pending['monitor']['result_digest'],'geometry_completion_remonitored')
    calls=log['calls'];ids={r['job_id'] for r in coverage['primary']}
    require(all(c.get('state')=='DONE' and c.get('job_id') in ids and c.get('index')==i for i,c in enumerate(calls)), 'geometry_completion_error_calls')
    require(all(sum(c['kind']=='assessment_entries' and c['job_id']==r['job_id'] for c in calls)==len(r['poses'])+int(r['task_id']=='GP5_SYNTH_K01') for r in coverage['primary']), 'geometry_completion_assessment_coverage')
    require(all(any(c['kind']=='solver_calls' and c['job_id']==r['job_id'] for c in calls) for r in coverage['primary']), 'geometry_completion_solver_coverage')
