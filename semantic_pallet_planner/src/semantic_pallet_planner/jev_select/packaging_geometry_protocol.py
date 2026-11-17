"""GP5 plans and administrator-side task identities. No kernel freeze or permit issuer.

Development accepts only the byte-reproducible fixed synthetic catalogue. Kernel
launch and formal-order admission consume separate externally reviewed receipts.
"""
import copy
import hashlib
import json
from pathlib import Path

from .contracts import JevSelectError, canonical, digest, validate_schema
from .geometry_runtime_contracts import environment, same_native
from .packaging_versions import GEOMETRY_BACKENDS

DEVELOPMENT='DEVELOPMENT_SYNTHETIC_ONLY'
ACCEPTANCE='KERNEL_ACCEPTANCE_SYNTHETIC_ONLY'
ORDER='EXPOSED_TRAIN_LOCAL_ORDER_ONLY'
SCOPES=(DEVELOPMENT,ACCEPTANCE,ORDER)
TASK_IDS=('NEW_00100027_controlled_base','NEW_00100027_controlled_capacity_tight')
ADAPTER_VERSION='geometry_order_task_adapter_v1'


def require(ok,code):
    if not ok:raise JevSelectError(code)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def synthetic_task(case):
    """Small fixed catalogue. K02 fills the floor, so the second exact pose is reachable.

    This concretizes P0's illustrative container to 100x80x180; there is no
    remaining floor alternative and no Cxx-dependent or modified local policy.
    """
    require(case in ('K01','K02','K02_INT'),'geometry_synthetic_case')
    from .packaging_runtime import INSTRUCTION,DATA_VERSION
    items=[]
    for i in range(1 if case=='K01' else 2):
        items.append({'item_id':'synth_'+str(i+1),'mass_kg':1,'dimensions_mm':dict(zip(('length','width','height'),(100,80,60) if case=='K02_INT' else (100.0,80.0,60.0))),
            'stackable':True,'top_load_limit_kg_synthetic':10,'fragile':False,'weight_class':'medium','product_category':'general'})
    return {'version':'geometry_synthetic_order_task_v1','task_id':'GP5_SYNTH_'+case,
        'mode':'controlled_packaging','layer':'SYNTHETIC_FIXED','feasibility_status':'UNKNOWN',
        'instruction_text':INSTRUCTION,'regions':[],'reference_policy':{'version':DATA_VERSION,'rules':[]},
        'container':{'container_id':'GP5_SYNTH','coordinate_frame':'container_bottom_center',
            'length_mm':600 if case=='K01' else 100,'width_mm':400 if case=='K01' else 80,
            'max_height_mm':500 if case=='K01' else 180,'max_payload_kg':100},
        'items':items,'attributes':{o['item_id']:{'object_id':o['item_id'],'physical_top_load_limit_kg':10,
            'cargo_category':'general','packaging':{'reinforced':False},'labels':{'no_top_load':False,'max_top_load_kg':10}} for o in items}}


def adapter_digest():return digest({'version':ADAPTER_VERSION,'source_sha256':sha(Path(__file__).read_bytes()),
    'runtime_source_sha256':sha(Path(__file__).with_name('packaging_runtime.py').read_bytes())})


def adapt_task(raw,*,origin,expected_sha256):
    """Raw bytes, normalized JSON and runtime view remain three distinct identities."""
    require(type(raw) is bytes and sha(raw)==expected_sha256,'geometry_task_raw_drift')
    try:
        def unique(pairs):
            d={}
            for k,v in pairs:
                require(k not in d,'geometry_task_duplicate_key');d[k]=v
            return d
        frozen=json.loads(raw,object_pairs_hook=unique)
    except (UnicodeError,ValueError) as exc:raise JevSelectError('geometry_task_json',str(exc)) from exc
    canonical(frozen)
    if origin=='SYNTHETIC_FIXED':
        matches=[synthetic_task(c) for c in ('K01','K02','K02_INT') if frozen.get('task_id')=='GP5_SYNTH_'+c]
        require(len(matches)==1 and same_native(frozen,matches[0]),'geometry_synthetic_catalogue_only')
        runtime=copy.deepcopy(frozen);group='SYNTHETIC_NOT_SOURCE'
    else:
        require(origin=='EXPOSED_TRAIN','geometry_task_origin')
        validate_schema('packaging_load_task_v1',frozen)
        require(frozen['task_id'] in TASK_IDS and frozen['partition']=='train'
            and frozen['source_group_id']=='SG_901bbb22f834c63f'
            and frozen['arrival_order']==[o['item_id'] for o in frozen['items']], 'geometry_order_task_scope')
        from .packaging_runtime import runtime_task
        runtime=runtime_task(frozen);group=frozen['source_group_id']
    identity={'origin':origin,'raw_sha256':sha(raw),'normalized_digest':digest(frozen),
        'runtime_digest':digest(runtime),'adapter_digest':adapter_digest(),'task_id':frozen['task_id'],'source_group_id':group}
    return {'identity':identity,'raw':raw,'frozen':frozen,'runtime':runtime}


def prepare_order_plan(adapted,*,data_identity,scope=ORDER):
    """Pure preparation. Formal and acceptance plans are always DRAFT here."""
    from .candidate_backends import _identity
    from .packaging_runtime import METHODS
    require(scope in SCOPES and 1<=len(adapted)<=2,'geometry_order_plan_scope')
    tasks=[copy.deepcopy(t['identity']) for t in adapted]
    jobs=[{'job_id':'J%02d'%i,'task_id':t['task_id'],'backend':b,'method':m}
        for i,(t,b,m) in enumerate((t,b,m) for t in tasks for b in GEOMETRY_BACKENDS for m in (METHODS[1:] if scope==ACCEPTANCE else METHODS))]
    plan={'version':'geometry_order_plan_v1','status':'DEVELOPMENT_READY' if scope==DEVELOPMENT else 'DRAFT',
        'scope':scope,'data_identity':data_identity,'source_identity':_identity()['source_identity'],
        'environment_digest':digest(environment()),'tasks':tasks,'jobs':jobs,'feature_profile':'F0_existing_facts',
        'event_limit':None,'extra_seeds':False,'model_calls_max':0,'assessment_limit':0 if scope==DEVELOPMENT else (152 if scope==ORDER else 12),
        'solver_limit':0 if scope==DEVELOPMENT else (8192 if scope==ORDER else 512),
        'call_ledger_path':None}
    validate_order_plan(plan)
    return plan


def validate_order_plan(plan):
    from .candidate_backends import _identity
    from .packaging_runtime import METHODS
    validate_schema('geometry_order_plan_v1',plan)
    require(plan['source_identity']==_identity()['source_identity'] and plan['environment_digest']==digest(environment()),'geometry_order_plan_identity')
    require(1<=len(plan['tasks'])<=2 and len({t['task_id'] for t in plan['tasks']})==len(plan['tasks']),'geometry_order_plan_tasks')
    expected=[{'job_id':'J%02d'%i,'task_id':t['task_id'],'backend':b,'method':m}
        for i,(t,b,m) in enumerate((t,b,m) for t in plan['tasks'] for b in GEOMETRY_BACKENDS for m in (METHODS[1:] if plan['scope']==ACCEPTANCE else METHODS))]
    require(same_native(plan['jobs'],expected) and len(expected)<=8,'geometry_order_matrix')
    synthetic=plan['scope']!=ORDER
    require(all(t['origin']==('SYNTHETIC_FIXED' if synthetic else 'EXPOSED_TRAIN') for t in plan['tasks']),'geometry_plan_task_scope')
    if plan['scope']==ACCEPTANCE:require(all(t['task_id'] in ('GP5_SYNTH_K01','GP5_SYNTH_K02') for t in plan['tasks']),'geometry_acceptance_catalogue')
    if not synthetic:require(tuple(t['task_id'] for t in plan['tasks'])==TASK_IDS,'geometry_order_fixed_tasks')
    if plan['scope']==DEVELOPMENT:
        require(plan['status']=='DEVELOPMENT_READY' and plan['assessment_limit']==plan['solver_limit']==0,'geometry_development_budget')
    else:
        require(plan['status'] in ('DRAFT','FROZEN') and 0<plan['assessment_limit']<=(152 if plan['scope']==ORDER else 12) and 0<plan['solver_limit']<=(8192 if plan['scope']==ORDER else 512),'geometry_real_budget')
    if plan['status']=='FROZEN':require(type(plan['call_ledger_path']) is str and bool(plan['call_ledger_path']),'geometry_shared_counter_ledger_required')
    return plan


def read_reference(ref):
    require(type(ref) is dict and set(ref)=={'path','sha256'},'geometry_receipt_reference')
    try:raw=Path(ref['path']).read_bytes()
    except OSError as exc:raise JevSelectError('geometry_missing_receipt',str(exc)) from exc
    require(sha(raw)==ref['sha256'],'geometry_receipt_bytes_drift')
    return json.loads(raw)


def validate_admission(plan,monitor_snapshot,admission,kernel_receipt=None):
    """Consume reviewed receipts, never mint a real launch or completion receipt.

    Kernel launch depends on external instruction + P1 QA, not its own completion.
    Formal orders additionally require accepted genuine kernel evidence.
    """
    validate_order_plan(plan)
    if plan['scope']==DEVELOPMENT:
        validate_schema('geometry_development_binding_v1',admission)
        require(admission=={'version':'geometry_development_binding_v1','scope':DEVELOPMENT,'evidence':'TEST_DOUBLE','plan_digest':digest(plan)}
            and kernel_receipt is None,'geometry_development_binding')
        return
    require(plan['status']=='FROZEN','geometry_order_draft_not_executable')
    name='geometry_kernel_launch_v1' if plan['scope']==ACCEPTANCE else 'geometry_order_admission_v1'
    validate_schema(name,admission)
    expected={'plan_digest':digest(plan),'source_identity':plan['source_identity'],'environment_digest':plan['environment_digest'],'monitor_digest':digest(monitor_snapshot),'scope':plan['scope']}
    require(all(admission[k]==v for k,v in expected.items()),'geometry_admission_binding')
    authorization=read_reference(admission['authorization']);review=read_reference(admission['review'])
    # These are distinct external records, not this plan or its numerical result.
    validate_schema('geometry_scope_authorization_v1',authorization)
    validate_schema('geometry_scope_review_v1',review)
    for doc in (authorization,review):
        require(doc.get('scope')==plan['scope'] and doc.get('plan_digest')==digest(plan)
            and doc.get('status')=='APPROVED','geometry_external_approval')
    if plan['scope']==ACCEPTANCE:
        require(kernel_receipt is None,'geometry_launch_not_completion')
    else:validate_real_kernel_receipt(kernel_receipt,plan,monitor_snapshot)


def validate_real_kernel_receipt(receipt,order_plan,monitor_snapshot):
    require(receipt is not None,'geometry_real_kernel_receipt_required')
    validate_schema('geometry_real_kernel_receipt_v1',receipt)
    require(all(receipt[k]==v for k,v in {'source_identity':order_plan['source_identity'],
        'environment_digest':order_plan['environment_digest'],'monitor_digest':digest(monitor_snapshot)}.items()),'geometry_kernel_receipt_identity')
    acceptance=read_reference(receipt['acceptance_plan']);launch=read_reference(receipt['launch'])
    require(acceptance['scope']==ACCEPTANCE,'geometry_kernel_receipt_scope')
    validate_admission(acceptance,monitor_snapshot,launch)
    review=read_reference(receipt['review'])
    require(review.get('status')=='APPROVED' and review.get('scope')==ACCEPTANCE
        and review.get('acceptance_plan_digest')==digest(acceptance),'geometry_kernel_review')
    counts=receipt['counts']
    require(0<counts['assessment_entries']<=acceptance['assessment_limit'] and
        0<counts['solver_calls']<=acceptance['solver_limit'] and counts['test_double_assessments']==0,'geometry_real_counts')
    log=read_reference(receipt['counter_log'])
    require(log.get('counts')==counts and log.get('plan_digest')==digest(acceptance)
        and log.get('evidence')=='REAL_KERNEL','geometry_real_counter_log')
    calls=log.get('calls',[])
    require(bool(calls) and all(r.get('state') in ('DONE','ERROR') for r in calls) and
        all(sum(r.get('kind')==kind for r in calls)==counts[kind] for kind in ('assessment_entries','solver_calls')),'geometry_real_call_reservations')
    require(bool(receipt['records']),'geometry_real_records_missing')
    total=0;backends=set()
    for ref in receipt['records']:
        record=read_reference(ref);cp=record['checkpoint'];config=record['config']
        require(cp['version']=='jev_checkpoint_v16' and cp['phase']=='TERMINATED'
            and config['execution_scope']==ACCEPTANCE and config['monitor_evidence']=='REAL_KERNEL'
            and config['plan_digest']==digest(acceptance),'geometry_real_record_scope')
        from .geometry_order_execution import preflight_order
        preflight_order(config);backends.add(config['candidate_backend'])
        require(set(record)=={'checkpoint','config','raw_task','durable_root'},'geometry_real_record_contract')
        raw_ref=record['raw_task'];read_reference(raw_ref)
        adapted=adapt_task(Path(raw_ref['path']).read_bytes(),origin='SYNTHETIC_FIXED',expected_sha256=raw_ref['sha256'])
        from .geometry_order_execution import OrderStore
        store=OrderStore(record['durable_root'],plan=acceptance,job_id=cp['job_id'],adapted=adapted,monitor_snapshot=monitor_snapshot,admission=launch)
        store.validate_request(adapted['runtime'],config)
        from .geometry_execution import validate_saved_checkpoint
        validate_saved_checkpoint(cp,adapted['runtime'],config,cp['job_id'],cp['method'],store)
        for event in cp['events']:
            row=event.get('monitor')
            if row is None:continue
            res=row.get('result')
            require(res is not None and 'TEST_DOUBLE' not in canonical(res)
                and res['version']=='pct_stability_result_v3'
                and res['algorithm_identity']==monitor_snapshot['algorithm_identity'],'geometry_test_double_not_real')
            require(row['result_digest']==digest(res) and row['credential_digest']==digest({k:v for k,v in row.items() if k!='credential_digest'}),'geometry_real_record_drift')
            total+=1
    require(total>0 and total<=counts['assessment_entries'] and backends==set(GEOMETRY_BACKENDS),'geometry_real_record_denominator')


def draft_run(plan):
    validate_order_plan(plan)
    value={'version':'geometry_order_run_v1','plan_digest':digest(plan),
        'rows':[{'job_id':j['job_id'],'status':'NOT_RUN','metrics':None} for j in plan['jobs']]}
    validate_schema('geometry_order_run_v1',value)
    return value


def update_run(run,plan,job_id,status,metrics=None):
    require(run['plan_digest']==digest(plan) and [r['job_id'] for r in run['rows']]==[j['job_id'] for j in plan['jobs']],'geometry_run_denominator')
    value=copy.deepcopy(run);row=next((r for r in value['rows'] if r['job_id']==job_id),None)
    require(row is not None,'geometry_run_job')
    job=next(j for j in plan['jobs'] if j['job_id']==job_id)
    if metrics is not None:
        require(metrics['task_id']==job['task_id'] and metrics['method']==job['method'] and metrics['candidate_backend']==job['backend'] and metrics['scope']==plan['scope'],'geometry_run_metrics_binding')
        require((status=='COMPLETE')==metrics['completed'],'geometry_run_completion_status')
    else:require(status in ('NOT_RUN','RUNNING','TECHNICAL_FAILURE','CANCELLED'),'geometry_run_metrics_required')
    row.update(status=status,metrics=metrics)
    validate_schema('geometry_order_run_v1',value)
    return value
