"""Selected-action monitor. Importing this module never imports a numerical kernel.

Durability belongs to the shared episode checkpoint. This module owns frozen
monitor identity, exact-action credentials and validation without reassessment.
"""
from __future__ import annotations
from ..packaging_versions import EXACT_VERSION

import copy
import time
from dataclasses import asdict

from ..contracts import JevSelectError, digest, validate_schema

VERSION = 'jev_packaging_monitored_v5'
TERMINATIONS = {'UNSTABLE':'PREDICTED_STATIC_INSTABILITY',
                'UNASSESSABLE':'STABILITY_UNASSESSABLE','ERROR':'STABILITY_MONITOR_ERROR'}


def is_monitored(config):
    return config.get('version') in (VERSION, 'jev_packaging_remote_v6','jev_packaging_memory_v7','jev_packaging_contrast_v8','jev_packaging_memory_orders_v9','jev_packaging_evaluation_v10','jev_packaging_synthetic_v11', EXACT_VERSION)


def freeze(enabled=False):
    if type(enabled) is not bool:
        raise JevSelectError('stability_enabled_must_be_boolean')
    if not enabled:
        return dict(enabled=False, algorithm=None, kernel_config=None, algorithm_identity=None, execution_environment=None)
    try:
        # Deliberately explicit v2 imports. Never use the root legacy default.
        from .balance_adapter import algorithm_identity, assess_candidate
        from .balance_contracts import load_config
        cfg = load_config()
        ident = algorithm_identity()
        if ident['algorithm'] != 'pct_contact_network_v2':
            raise ValueError('unexpected algorithm')
        from .runtime import environment
        return dict(enabled=True, algorithm=cfg.algorithm, kernel_config=asdict(cfg),
                    algorithm_identity=ident, execution_environment=environment())
    except Exception as exc:
        raise JevSelectError('stability_preflight_failed', f'{type(exc).__name__}: {exc}') from exc


def load_monitor_config(*, data_identity, task_digest, method='local_geometry_test_double',
                        enabled=None, monitor_config=None):
    from ..packaging_runtime import load_runtime_config
    if monitor_config is not None:
        if set(monitor_config) != {'enabled'} or type(monitor_config['enabled']) is not bool:
            raise JevSelectError('invalid_monitor_options')
        if enabled is not None and enabled != monitor_config['enabled']:
            raise JevSelectError('stability_cli_config_conflict')
        enabled = monitor_config['enabled']
    cfg = load_runtime_config(data_identity=data_identity, task_digest=task_digest, method=method)
    cfg['version'] = VERSION
    cfg['stability_monitor'] = freeze(False if enabled is None else enabled)
    cfg['runtime_identity']['monitor_identity'] = digest(cfg['stability_monitor'])
    # Existing strategy identity already freezes source, original config and method.
    validate_schema('config', cfg)
    return cfg


def preflight(config):
    validate_schema('config', config)
    if config['version']==EXACT_VERSION:
        from ..packaging_exact_protocol import preflight_exact
        preflight_exact(config)
        return
    if config['version']=='jev_packaging_synthetic_v11':
        from ..packaging_synthetic_protocol import preflight_synthetic
        preflight_synthetic(config)
        return
    if config['version']=='jev_packaging_evaluation_v10':
        from ..packaging_evaluation_protocol import preflight_evaluation
        preflight_evaluation(config)
        return
    if config['version']=='jev_packaging_memory_orders_v9':
        from ..packaging_pilot_protocol import preflight_pilot
        preflight_pilot(config)
        return
    if config['version']=='jev_packaging_contrast_v8':
        from ..packaging_contrast_protocol import preflight_contrast
        preflight_contrast(config)
        return
    if config['version']=='jev_packaging_memory_v7':
        from ..packaging_memory_protocol import preflight_memory
        preflight_memory(config)
        return
    if config['version'] == 'jev_packaging_remote_v6':
        from ..packaging_remote import preflight_remote
        preflight_remote(config)
        return
    from ..packaging_runtime import load_runtime_config
    ids=config['runtime_identity']
    original=load_runtime_config(data_identity=ids['data_identity'],task_digest=ids['task_identity'],method=config['selector'])
    if any(ids[k]!=v for k,v in original['runtime_identity'].items()):
        raise JevSelectError('stability_runtime_source_or_strategy_changed')
    frozen = config['stability_monitor']
    if frozen != freeze(frozen['enabled']) or config['runtime_identity']['monitor_identity'] != digest(frozen):
        raise JevSelectError('stability_frozen_identity_changed')


def binding(state, candidate, event, config):
    return {'state_digest':digest(state),'candidate_digest':digest(candidate),
            'action_digest':digest(event['proposed_action']),
            'selection_digest':digest(event['selection']),
            'context_digest':digest(event['context']),
            'bundle_digest':digest(event['bundle']), 'decision_id':event['decision_id'],
            'config_digest':digest(config),'runtime_identity':copy.deepcopy(config['runtime_identity'])}


def selected_box(state, candidate):
    obj = next(p['item'] for p in state['pending_items'] if p['item']['item_id']==candidate['pick_item_id'])
    return {**copy.deepcopy(obj),'pose':copy.deepcopy(candidate['pose']),
            'oriented_size_mm':list(candidate['oriented_size_mm'])}


def exact_freeze():
    from .exact_adapter import algorithm_identity
    from .exact_contracts import load_config
    from .runtime import environment
    cfg=load_config()
    return dict(enabled=True,algorithm=cfg.algorithm,kernel_config=asdict(cfg),
        algorithm_identity=algorithm_identity(),execution_environment=environment())


def kernel_interface(algorithm):
    if algorithm=='pct_contact_network_v2':
        from . import balance_adapter as adapter, balance_contracts as contracts
        return adapter.assess_candidate,contracts.load_config,contracts.BalancedResult,'stability_result_v2.schema.json'
    if algorithm=='pct_exact_pose_network_v3':
        from . import exact_adapter as adapter, exact_contracts as contracts
        return adapter.assess_candidate,contracts.load_config,contracts.ExactResult,'stability_result_v3.schema.json'
    raise JevSelectError('unregistered_stability_algorithm')


def monitor_selected_action(state, candidate, event, config):
    frozen = config['stability_monitor']
    result = None
    if frozen['enabled']:
        assess_candidate,load_config,result_type,_=kernel_interface(frozen['algorithm'])
        from .geometry import state_from_runtime, box_from_runtime
        started=time.perf_counter()
        try:
            result = assess_candidate(state_from_runtime(state),
                box_from_runtime(selected_box(state,candidate)), load_config()).to_dict()
            status = result['status']
        except Exception as exc:
            # Startup failures were rejected before selection. Runtime exceptions
            # remain a persisted technical failure, never disable the monitor.
            status = 'ERROR'
            result = result_type(status='ERROR',reason_code='MONITOR_EXCEPTION',
                state_digest=digest(asdict(state_from_runtime(state))),
                candidate_digest=digest(asdict(box_from_runtime(selected_box(state,candidate)))),
                candidate_id=candidate['pick_item_id'],config_digest=digest(frozen['kernel_config']),
                algorithm_identity=copy.deepcopy(frozen['algorithm_identity']),baseline_status='NOT_ASSESSED',
                first_bad_prefix=None,failed_item_id=None,height_delta_mm=None,evaluated_pose=None,kernel_calls=0,
                diagnostics={'exception_type':type(exc).__name__,'detail':str(exc)[:240],
                             'kernel_geometry_calls_unknown':True},duration_s=time.perf_counter()-started).to_dict()
    else:
        status = 'DISABLED'
    row = {'version':'selected_action_monitor_v1','binding':binding(state,candidate,event,config),
           'status':status,'result':result,'attempted':True,'committed':False}
    row['result_digest'] = digest(result)
    row['credential_digest'] = digest(row)
    validate_monitor(row,state,candidate,event,config)
    return row


def validate_monitor(row, state, candidate, event, config, *, require_stable=False):
    expected_keys = {'version','binding','status','result','attempted','committed','result_digest','credential_digest'}
    if set(row) != expected_keys or row['version'] != 'selected_action_monitor_v1':
        raise JevSelectError('invalid_monitor_record')
    if (row['binding'] != binding(state,candidate,event,config) or
        row['result_digest'] != digest(row['result']) or
        row['credential_digest'] != digest({k:v for k,v in row.items() if k!='credential_digest'}) or
        row['attempted'] is not True or row['committed'] is not False):
        raise JevSelectError('monitor_binding_changed')
    enabled=config['stability_monitor']['enabled'];res=row['result']
    if not enabled:
        if row['status']!='DISABLED' or res is not None:raise JevSelectError('disabled_monitor_result')
    else:
        if row['status'] not in ('STABLE','UNSTABLE','UNASSESSABLE','ERROR') or res is None or res['status']!=row['status']:
            raise JevSelectError('invalid_monitor_status')
        from .geometry import state_from_runtime,box_from_runtime
        from importlib.resources import files
        import json
        from jsonschema import Draft202012Validator
        *_,schema_name=kernel_interface(config['stability_monitor']['algorithm'])
        schema=json.loads(files(__package__).joinpath('schemas',schema_name).read_text())
        Draft202012Validator(schema).validate(res)
        frozen=config['stability_monitor']
        if (res['algorithm_identity']!=frozen['algorithm_identity'] or
            res['config_digest']!=digest(frozen['kernel_config']) or
            res['state_digest']!=digest(asdict(state_from_runtime(state))) or
            res['candidate_digest']!=digest(asdict(box_from_runtime(selected_box(state,candidate))))):
            raise JevSelectError('kernel_result_binding_changed')
    if require_stable and row['status'] not in ('DISABLED','STABLE'):
        raise JevSelectError('monitor_commit_not_authorized')
    return row


def seal_checkpoint(cp):
    cp['record_digest']=digest({k:v for k,v in cp.items() if k!='record_digest'})
    return cp


def validate_checkpoint(cp, task, config, job_id, method):
    """Validate saved transitions using original physics, no selector or LP calls.

    This only reconstructs private copies. The returned durable state is reused;
    no committed event is dispatched again by the episode.
    """
    from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive
    from semantic_pallet_planner.o4.extensions.e2.protocol import observation
    from semantic_pallet_planner.o4.extensions.e2.planning import action_for
    from ..contracts import CandidateBundle,DecisionContext
    from ..context import resolve_display_id
    from ..selector import SelectionResult
    from ..execution import commit_physical
    from ..packaging_runtime import validate_runtime_context,evaluate_state
    if config['version'] in ('jev_packaging_remote_v6','jev_packaging_memory_v7','jev_packaging_contrast_v8','jev_packaging_memory_orders_v9','jev_packaging_evaluation_v10','jev_packaging_synthetic_v11', EXACT_VERSION):
        from ..packaging_experiment import validate_saved_checkpoint
        return validate_saved_checkpoint(cp, task, config, job_id)
    validate_schema('checkpoint_v5',cp)
    if (cp['record_digest']!=digest({k:v for k,v in cp.items() if k!='record_digest'}) or
        cp['job_id']!=job_id or cp['method']!=method or cp['task_digest']!=digest(task) or
        cp['config_digest']!=digest(config) or cp['runtime_identity']!=config['runtime_identity']):
        raise JevSelectError('monitored_checkpoint_identity_changed')
    state=initial(task['container'],config['buffer_capacity']);cursor=decision=0;stopped=None

    def check_event(event, before, committed):
        req=observation(before,task['instruction_text'],task['regions'])
        if event['observation']!=req or event['before']!=before:
            raise JevSelectError('saved_observation_changed')
        ctx=DecisionContext.from_dict(event['context']);bundle=CandidateBundle.from_dict(event['bundle'])
        validate_runtime_context(ctx,req,bundle,config)
        if event['decision_id']!=f'{job_id}_D{decision:04d}' or ctx.data['local_binding']['decision_id']!=event['decision_id'] or ctx.data['local_binding']['job_id']!=job_id:
            raise JevSelectError('saved_decision_changed')
        selection=event['selection']
        if selection is None or selection['status'] not in ('selected','singleton'):
            if event['monitor'] is not None or event['proposed_action'] is not None:raise JevSelectError('unselected_monitor')
            return before
        validate_schema('selection_result',selection)
        if selection['local_binding_digest']!=digest(ctx.data['local_binding']):raise JevSelectError('saved_selection_changed')
        chosen=resolve_display_id(ctx,selection['selected_display_id'],req,bundle,config)
        if chosen['candidate_id']!=selection['selected_candidate_id'] or event['proposed_action']!=action_for(req,bundle.data['physical_candidates'],chosen):
            raise JevSelectError('saved_action_changed')
        row=event['monitor']
        if row is not None:validate_monitor(row,before,chosen,event,config,require_stable=committed)
        if committed:
            if row is None:raise JevSelectError('missing_commit_monitor')
            after=commit_physical(before,task['regions'],req,bundle,ctx,SelectionResult.from_dict(selection),config,monitor=row,monitor_event=event)
            if event['action']!=event['proposed_action'] or event['after']!=after:raise JevSelectError('saved_commit_changed')
            return after
        if event['after']!=before or event['action'] is not None:raise JevSelectError('uncommitted_state_changed')
        if row is not None and row['status'] in TERMINATIONS and event['reason'] not in (None,TERMINATIONS[row['status']]):
            raise JevSelectError('saved_termination_changed')
        return before

    for event in cp['events']:
        if stopped is not None or event['before']!=state:raise JevSelectError('stopped_or_discontinuous_history')
        if event['event']=='WAIT_RECEIVE':
            item=task['items'][cursor];after=receive(state,item,task['attributes'][item['item_id']]);cursor+=1
        elif event['event']=='EOS':after=receive(state,eos=True)
        else:
            after=check_event(event,state,event['event']=='PLACE');decision+=1
            if event['business_after']!=evaluate_state(after):raise JevSelectError('saved_evaluation_changed')
            stopped=event['reason']
            row=event['monitor']
            if row and row['status'] in TERMINATIONS and stopped!=TERMINATIONS[row['status']]:raise JevSelectError('missing_monitor_termination')
        if event['after']!=after:raise JevSelectError('saved_transition_changed')
        state=after
    pending=cp['pending_event'];phase=cp['phase']
    if pending is not None:
        if stopped or phase not in ('SELECTED','MONITORED','COMMITTED'):raise JevSelectError('invalid_pending_phase')
        after=check_event(pending,state,phase=='COMMITTED')
        if (phase=='SELECTED') != (pending['monitor'] is None):raise JevSelectError('invalid_monitor_phase')
        state=after
    elif phase not in ('READY','TERMINATED'):raise JevSelectError('missing_pending_event')
    if cp['state']!=state or cp['cursor']!=cursor or cp['decision']!=decision:raise JevSelectError('saved_progress_changed')
    expected=stopped or ('ALL_ITEMS_PLACED' if pending is None and cp['reason']=='ALL_ITEMS_PLACED' and state['end_of_stream'] and not state['pending_items'] else None)
    if pending is not None and phase=='COMMITTED' and cp['reason']=='EVALUATION_ERROR' and pending.get('error',{}).get('code')=='EVALUATION_ERROR':
        expected='EVALUATION_ERROR'
    if cp['reason']!=expected:raise JevSelectError('saved_stop_changed')
    if (phase=='TERMINATED') != (expected is not None and expected!='EVALUATION_ERROR'):raise JevSelectError('saved_terminal_phase_changed')
    return cp
