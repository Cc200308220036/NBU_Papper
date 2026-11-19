"""Independent v16 identities, complete metrics and shared durable recovery.

No order engine or numerical algorithm lives here. Monitor identities are supplied
snapshots, validated as bytes/configuration; this module never calls exact_freeze.
"""
import copy
import math
from pathlib import Path

from .geometry_native_protocol import wire, is_native, identity_fields, config_fields
from .contracts import digest,validate_schema
from .geometry_runtime_contracts import environment,same_native
from .geometry_execution import GeometryStore
from .packaging_versions import GEOMETRY_ORDER_VERSION,GEOMETRY_NATIVE_VERSION
from .packaging_geometry_protocol import (DEVELOPMENT,ACCEPTANCE,ORDER,require,sha,
    adapt_task,validate_order_plan,validate_admission,draft_run)


def validate_monitor_snapshot(snapshot):
    # The config Schema validates fixed exact-v3 numerical parameters. Source
    # bytes are checked here without invoking either kernel identity/freezer.
    require(snapshot['enabled'] is True and snapshot['algorithm']=='pct_exact_pose_network_v3','geometry_order_monitor_required')
    identity=snapshot['algorithm_identity'];root=Path(__file__).parent/'stability'
    require(identity['algorithm']=='pct_exact_pose_network_v3' and identity['semantic_revision']=='exact_pose_contacts_global_equilibrium_v3','geometry_order_exact_required')
    names=identity['files_sha256']
    require({'exact_adapter.py','exact_contracts.py','balance_network.py'}<=set(names),'geometry_order_kernel_files')
    for rel,h in names.items():
        require(not Path(rel).is_absolute() and '..' not in Path(rel).parts,'geometry_kernel_identity_path')
        require(sha((root/rel).read_bytes())==h,'geometry_order_kernel_source_drift')
    require(identity['source_digest']==digest(names) and identity['dependency_digest']==digest(identity['dependencies']),'geometry_order_kernel_identity_digest')
    import importlib.metadata
    import scipy.optimize
    from scipy.optimize._highspy import _core
    deps=identity['dependencies']
    require(deps['numpy']==importlib.metadata.version('numpy') and deps['scipy']==importlib.metadata.version('scipy'),'geometry_order_dependency_versions')
    require(deps['highs_version']=='.'.join(str(getattr(_core,'HIGHS_VERSION_'+k)) for k in ('MAJOR','MINOR','PATCH')) and deps['highs_core_sha256']==sha(Path(_core.__file__).read_bytes()),'geometry_order_solver_dependency')
    for name,h in deps['scipy_python_sha256'].items():
        require(sha((Path(scipy.optimize.__file__).parent/name).read_bytes())==h,'geometry_order_solver_source')
    # Existing dependency/environment implementation performs identity reads only.
    from .stability.runtime import environment as monitor_environment
    require(same_native(snapshot['execution_environment'],monitor_environment()),'geometry_order_monitor_environment')


def load_order_config(plan,job_id,*,monitor_snapshot,admission,kernel_receipt=None):
    validate_admission(plan,monitor_snapshot,admission,kernel_receipt)
    job=next((j for j in plan['jobs'] if j['job_id']==job_id),None)
    require(job is not None,'geometry_order_job')
    task=next(t for t in plan['tasks'] if t['task_id']==job['task_id'])
    from .candidate_backends import load_geometry_config
    cfg=load_geometry_config(backend=job['backend'],data_identity=plan['data_identity'],
        task_identity=task['runtime_digest'],monitor_identity=digest(monitor_snapshot),method=job['method'])
    cfg.update(version=GEOMETRY_NATIVE_VERSION if is_native(plan) else GEOMETRY_ORDER_VERSION,construction_only=False,
        execution_version='geometry_order_execution_v1',experiment_protocol='geometry_order_run_v1',
        order_task_identity=copy.deepcopy(task),plan_digest=digest(plan),execution_scope=plan['scope'],
        admission_digest=digest(admission),kernel_receipt_digest=digest(kernel_receipt) if kernel_receipt else None,
        monitor_evidence='TEST_DOUBLE' if plan['scope']==DEVELOPMENT else 'REAL_KERNEL',
        stability_monitor=copy.deepcopy(monitor_snapshot))
    if is_native(plan):
        cfg.update(config_fields(),execution_version='geometry_order_execution_v2',experiment_protocol='geometry_order_run_v2')
    cfg['runtime_identity']['strategy_identity']=digest({k:v for k,v in cfg.items() if k!='runtime_identity'})
    preflight_order(cfg)
    return cfg


def preflight_order(config):
    from .candidate_backends import load_geometry_config
    validate_schema('config_v17' if is_native(config) else 'config_v16',config)
    ids=config['runtime_identity'];task=config['order_task_identity'];snapshot=config['stability_monitor']
    validate_monitor_snapshot(snapshot)
    require(ids['task_identity']==task['runtime_digest'] and ids['monitor_identity']==digest(snapshot),'geometry_order_task_identity')
    require((task['origin']=='SYNTHETIC_FIXED')==(config['execution_scope']!=ORDER),'geometry_order_origin_scope')
    require((config['monitor_evidence']=='TEST_DOUBLE')==(config['execution_scope']==DEVELOPMENT),'geometry_order_evidence_scope')
    require((config['kernel_receipt_digest'] is not None)==(config['execution_scope']==ORDER),'geometry_order_kernel_receipt_scope')
    expected=load_geometry_config(backend=config['candidate_backend'],data_identity=ids['data_identity'],
        task_identity=ids['task_identity'],monitor_identity=ids['monitor_identity'],method=config['selector'])
    expected.update({k:copy.deepcopy(config[k]) for k in ('version','construction_only','execution_version','experiment_protocol',
        'order_task_identity','plan_digest','execution_scope','admission_digest','kernel_receipt_digest','monitor_evidence','stability_monitor')})
    if is_native(config):expected.update(config_fields())
    expected['runtime_identity']['strategy_identity']=digest({k:v for k,v in expected.items() if k!='runtime_identity'})
    require(same_native(expected,config),'geometry_order_config_drift')


def execution_for_config(config,job_id):
    preflight_order(config)
    v={**identity_fields(config),'version':wire(config,'geometry_order_execution_v1'),'scope':config['execution_scope'],
        'task_digest':config['order_task_identity']['runtime_digest'],'config_digest':digest(config),
        'source_identity':config['runtime_identity']['source_identity'],'environment_digest':digest(environment()),
        'plan_digest':config['plan_digest'],'job_id':job_id,'admission_digest':config['admission_digest'],
        'kernel_receipt_digest':config['kernel_receipt_digest']}
    validate_schema(wire(config,'geometry_order_execution_v1'),v)
    return v


def validate_order_execution(value,config):
    validate_schema(wire(config,'geometry_order_execution_v1'),value)
    require(same_native(value,execution_for_config(config,value['job_id'])),'geometry_order_execution_drift')


class OrderStore(GeometryStore):
    decision_version='geometry_order_durable_decision_v1'
    def __init__(self,root,*,plan,job_id,adapted,monitor_snapshot,admission,kernel_receipt=None):
        super().__init__(root)
        if is_native(plan):self.decision_version='geometry_order_durable_decision_v2'
        # Frozen copies; mutating a caller's dictionaries never replaces authority.
        self._plan=copy.deepcopy(plan);self._job_id=job_id;self._raw=bytes(adapted['raw'])
        self._identity=copy.deepcopy(adapted['identity']);self._monitor=copy.deepcopy(monitor_snapshot)
        self._admission=copy.deepcopy(admission);self._kernel=copy.deepcopy(kernel_receipt)
    def authorize_config(self,config):
        expected=load_order_config(self._plan,self._job_id,monitor_snapshot=self._monitor,
            admission=self._admission,kernel_receipt=self._kernel)
        require(same_native(config,expected),'geometry_order_store_config')
        return execution_for_config(config,self._job_id)
    def load_event(self,event,config):
        self.authorize_config(config)
        return super().load_event(event,config)
    def validate_request(self,task,config):
        self.authorize_config(config)
        adapted=adapt_task(self._raw,origin=self._identity['origin'],expected_sha256=self._identity['raw_sha256'])
        require(same_native(adapted['identity'],config['order_task_identity'])
            and same_native(task,adapted['runtime']),'geometry_order_runtime_task_drift')
        return execution_for_config(config,self._job_id)


def validate_order_request(task,selector,config,method,store,on_checkpoint,*,job_id=None):
    from .packaging_runtime import LocalPackagingDouble,METHODS
    preflight_order(config)
    require(type(store) is OrderStore and callable(on_checkpoint),'geometry_order_explicit_authority_required')
    require(type(selector) is LocalPackagingDouble and selector.method==method==config['selector'] and method in METHODS,'geometry_order_local_selector_required')
    binding=store.validate_request(task,config)
    require(job_id is None or job_id==binding['job_id'],'geometry_order_job_drift')
    if config['monitor_evidence']=='REAL_KERNEL':
        from .geometry_order_meter import current_counts
        current_counts(config['plan_digest'])
        from .geometry_order_accounting import snapshot
        require(snapshot(config)['status']=='OBSERVED','geometry_order_accounting_required')
    return binding


def run_order_job(plan,job_id,adapted,*,monitor_snapshot,admission,root,kernel_receipt=None,
                  resume=None,phase_credential=None,on_checkpoint=None,hook=None):
    """Gate before IO; root owns one frozen plan and its full job denominator."""
    import time
    from .ledger import read,write,exclusive
    from .packaging_geometry_protocol import update_run
    config=load_order_config(plan,job_id,monitor_snapshot=monitor_snapshot,admission=admission,kernel_receipt=kernel_receipt)
    root=Path(root);store=OrderStore(root/'jobs'/job_id,plan=plan,job_id=job_id,adapted=adapted,
        monitor_snapshot=monitor_snapshot,admission=admission,kernel_receipt=kernel_receipt)
    # Verify the administrator raw task before creating any execution artifacts.
    store.validate_request(adapted['runtime'],config)
    from .packaging_runtime import LocalPackagingDouble
    task=adapted['runtime'];selector=LocalPackagingDouble(config['selector'])
    callback=on_checkpoint if on_checkpoint is not None else lambda cp:None
    from .episode import run_episode
    def execute_accounted():
        from .geometry_order_accounting import invocation
        with invocation(store.root/'accounting.json',config,job_id,resume,phase_credential=phase_credential):
            result=execute()
            from .geometry_order_accounting import completed
            completed(config,result['checkpoint'])
            return result
    def execute():
        validate_order_request(task,selector,config,config['selector'],store,callback,job_id=job_id)
        return run_episode(task,selector,config,job_id=job_id,method=config['selector'],resume=resume,
            on_checkpoint=callback,geometry_store=store,hook=hook)
    root.mkdir(parents=True,exist_ok=True)
    with exclusive(root):
        plan_path=root/'plan.json'
        if plan_path.exists():require(same_native(read(plan_path),plan),'geometry_order_saved_plan_drift')
        else:write(plan_path,plan)
        run=read(root/'run.json') if (root/'run.json').exists() else draft_run(plan)
        prior=next(r for r in run['rows'] if r['job_id']==job_id)
        require(prior['status']=='NOT_RUN' or resume is not None,'geometry_order_duplicate_job_requires_checkpoint')
        raw_ref=store.put(adapted['raw']);raw_path=store.root/'blobs'/raw_ref['sha256']
        write(store.root/'task_identity.json',adapted['identity']);write(store.root/'config.json',config)
        run=update_run(run,plan,job_id,'RUNNING');write(root/'run.json',run)
        started=time.perf_counter()
        try:
            if plan['scope']==DEVELOPMENT:result=execute_accounted()
            else:
                from .geometry_order_meter import metered_run
                with metered_run(plan,job_id=job_id,monitor_snapshot=monitor_snapshot,admission=admission,kernel_receipt=kernel_receipt):result=execute_accounted()
        except BaseException as exc:
            status='CANCELLED' if isinstance(exc,KeyboardInterrupt) else 'TECHNICAL_FAILURE'
            write(root/'run.json',update_run(run,plan,job_id,status))
            write(store.root/'driver_failure.json',{'type':type(exc).__name__,'detail':str(exc)[:240],'no_implicit_retry':True})
            raise
        metric=result['summary']
        if metric is not None:
            metric['timings'].append({'segment':'invocation_wall_s','seconds':time.perf_counter()-started})
            validate_schema(wire(config,'geometry_order_metrics_v1'),metric)
            status='COMPLETE' if metric['completed'] else ('TECHNICAL_FAILURE' if metric['termination_class']=='TECHNICAL_FAILURE' else 'STOPPED')
            write(store.root/'metrics.json',metric)
        else:status='TECHNICAL_FAILURE'
        write(root/'run.json',update_run(run,plan,job_id,status,metric))
        write(store.root/'record.json',{'checkpoint':result['checkpoint'],'config':config,
            'raw_task':{'path':str(raw_path),'sha256':raw_ref['sha256']},'durable_root':str(store.root)})
        write(store.root/'episode.json',result)
        return result


def _order_timing_totals(events,monitors):
    """Numeric timing rows only, without inventing unmeasured durations.

    Bare segment names denote complete sums over applicable decision events
    (or monitor results). Missing/null samples make the sum incomplete: emit
    only its measured subtotal under ``measured_partial/<segment>``. If no
    sample was measured, omit the row; absence means unavailable, never zero.
    Arrival events without decision timings are not timing samples. Original
    event fields, including measured zero and legal null, remain untouched.
    """
    def aggregate(key,values):
        measured=[v for v in values if v is not None]
        if any(type(v) not in (int,float) for v in measured):
            raise TypeError('invalid order timing sample: '+key)
        if not measured:return []
        name=key if len(measured)==len(values) else 'measured_partial/'+key
        return [{'segment':name,'seconds':sum(measured)}]

    samples=[e.get('timings',{}) for e in events if e.get('decision_id') or e.get('timings')]
    timings=[]
    for key in sorted({k for sample in samples for k in sample if k.endswith('_s')}):
        timings.extend(aggregate(key,[sample.get(key) for sample in samples]))
    timings.extend(aggregate('monitor_result_duration_s',[
        (r.get('result') or {}).get('duration_s') for r in monitors]))
    return timings


def order_metrics(task,config,method,state,events,reason):
    placed=state['placed_items'];items=task['items'];container=state['container']
    planned_volume=sum(math.prod(o['dimensions_mm'].values()) for o in items)
    volume=sum(math.prod(o['oriented_size_mm']) for o in placed)
    planned_mass=sum(o['mass_kg'] for o in items);mass=sum(o['mass_kg'] for o in placed)
    height=max((o['pose']['z_base_mm']+o['oriented_size_mm'][2] for o in placed),default=0)
    envelope=None
    if placed:
        axes=[]
        for axis,k in enumerate(('x_mm','y_mm')):
            axes.append(max(o['pose'][k]+o['oriented_size_mm'][axis]/2 for o in placed)-min(o['pose'][k]-o['oriented_size_mm'][axis]/2 for o in placed))
        envelope=volume/(math.prod(axes)*height)
    complete=len(placed)==len(items)
    require(not complete or reason=='ALL_ITEMS_PLACED','geometry_order_completion_reason')
    if reason=='ALL_ITEMS_PLACED':require(complete and state['end_of_stream'] and not state['pending_items'],'geometry_order_incomplete_eos')
    category={'ALL_ITEMS_PLACED':'COMPLETE','STOP_NO_PHYSICAL_CANDIDATE':'NO_CANDIDATE',
        'PREDICTED_STATIC_INSTABILITY':'PREDICTED_STATIC_INSTABILITY','STABILITY_UNASSESSABLE':'UNASSESSABLE',
        'CANCELLED':'CANCELLED'}.get(reason,'TECHNICAL_FAILURE')
    ratios={'placed_item_ratio':len(placed)/len(items),'placed_volume_ratio':volume/planned_volume,'placed_mass_ratio':mass/planned_mass}
    bad=next((e for e in events if (e.get('monitor') or {}).get('status')=='UNSTABLE'),None)
    rows=[e['monitor'] for e in events if e.get('monitor')]
    marked=sum((r.get('result') or {}).get('diagnostics',{}).get('TEST_DOUBLE') is True for r in rows)
    # solver calls are never inferred from an adapter's kernel_calls field.
    # A real run must attach the independent persistent meter; absent => reject summary.
    if config['monitor_evidence']=='REAL_KERNEL':
        # True counters are supplied by the scoped run meter at future acceptance.
        from .geometry_order_meter import current_counts
        counts=current_counts(config['plan_digest'])
    else:counts={'assessment_entries':0,'solver_calls':0,'test_double_assessments':marked}
    timings=_order_timing_totals(events,rows)
    value={**identity_fields(config),'version':wire(config,'geometry_order_metrics_v1'),'task_id':task['task_id'],'candidate_backend':config['candidate_backend'],
        'method':method,'scope':config['execution_scope'],'monitor_evidence':config['monitor_evidence'],
        'runtime_identity':copy.deepcopy(config['runtime_identity']),'planned_items':len(items),'arrived_items':state['arrival_count'],
        'placed_items':len(placed),'planned_volume_mm3':planned_volume,'placed_volume_mm3':volume,'planned_mass_kg':planned_mass,
        'placed_mass_kg':mass,**ratios,'fixed_container_utilization':volume/(container['length_mm']*container['width_mm']*container['max_height_mm']),
        'max_height_mm':height,'envelope_utilization':envelope,'envelope_status':'APPLICABLE' if placed else 'NA_EMPTY',
        'completed':complete,'termination_reason':reason,'termination_class':category,
        'predicted_instability_progress':None if bad is None else {'decision_id':bad['decision_id'],
            'failed_item_id':bad['selection']['selected_candidate_id'],**ratios},'counts':counts,'timings':timings,
        'cost':{'model_calls':0,'service_cost':'NA_NO_SERVICE_CALL','local_compute_cost':'UNKNOWN'},'global_infeasibility_proven':False}
    if bad is not None:
        value['predicted_instability_progress']['failed_item_id']=next(c['pick_item_id'] for c in bad['bundle']['physical_candidates'] if c['candidate_id']==bad['selection']['selected_candidate_id'])
    from .geometry_order_accounting import snapshot
    value['accounting']=snapshot(config)
    if config['monitor_evidence']=='REAL_KERNEL':
        from .geometry_order_meter import current_increment
        value['kernel_count_scope']={'basis':'PERSISTENT_JOB_CUMULATIVE_AND_INVOCATION_DELTA','cumulative':counts,'invocation_delta':current_increment(config['plan_digest'])}
    else:
        value['kernel_count_scope']={'basis':'DEVELOPMENT_REAL_CALLS_FORBIDDEN','cumulative':{'assessment_entries':0,'solver_calls':0},'invocation_delta':{'assessment_entries':0,'solver_calls':0}}
    validate_schema(wire(config,'geometry_order_metrics_v1'),value)
    return value
