"""Independent v15 manual-fixture execution identities and immutable blobs.

No solver, selector, order loop or physical engine is implemented here.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .contracts import JevSelectError, canonical, digest, validate_schema
from .geometry_runtime_contracts import environment, same_native
from .packaging_versions import GEOMETRY_RUN_VERSION, GEOMETRY_EXECUTION


def validate_fixture(task):
    keys={'version','fixture_only','container','items','attributes','instruction_text','regions','reference_policy','task_id','mode','layer','feasibility_status'}
    if (set(task)!=keys or task['version']!='jev_geometry_fixture_task_v1' or task['fixture_only'] is not True
        or task['regions']!=[] or task['reference_policy']!={'version':'jev_packaging_load_dataset_v1','rules':[]}):
        raise JevSelectError('geometry_manual_fixture_only')


def load_run_config(*,backend,task,data_identity,method='local_geometry_test_double',enabled=True):
    validate_fixture(task)
    from .candidate_backends import load_geometry_config
    from .stability.monitor import exact_freeze, freeze
    frozen=exact_freeze() if enabled else freeze(False)
    cfg=load_geometry_config(backend=backend,data_identity=data_identity,task_identity=digest(task),
        monitor_identity=digest(frozen),method=method)
    cfg.update(version=GEOMETRY_RUN_VERSION,construction_only=False,execution_version=GEOMETRY_EXECUTION,
        experiment_protocol='geometry_fixture_run_v1',fixture_task_digest=digest(task),stability_monitor=frozen)
    cfg['runtime_identity']['strategy_identity']=digest({k:v for k,v in cfg.items() if k!='runtime_identity'})
    validate_schema('config',cfg)
    return cfg


def preflight_run(config):
    validate_schema('config',config)
    from .candidate_backends import _identity,backend_config
    from .stability.monitor import exact_freeze,freeze
    from .geometry_runtime_contracts import PROFILE
    ids=config['runtime_identity']
    frozen=exact_freeze() if config['stability_monitor']['enabled'] else freeze(False)
    if (config['version']!=GEOMETRY_RUN_VERSION or config['numerical_profile']!=PROFILE
        or config['generator_config_digest']!=digest(backend_config(config['candidate_backend']))
        or any(ids[k]!=v for k,v in _identity().items())
        or not same_native(config['stability_monitor'],frozen)
        or ids['monitor_identity']!=digest(frozen)
        or ids['task_identity']!=config['fixture_task_digest']):
        raise JevSelectError('geometry_run_identity_drift')
    # Rebuild complete fixed options using the shared loader, without accepting
    # alternative budgets or a caller-signed strategy digest.
    from .candidate_backends import load_geometry_config
    expected=load_geometry_config(backend=config['candidate_backend'],data_identity=ids['data_identity'],
        task_identity=ids['task_identity'],monitor_identity=ids['monitor_identity'],method=config['selector'])
    expected.update(version=GEOMETRY_RUN_VERSION,construction_only=False,execution_version=GEOMETRY_EXECUTION,
        experiment_protocol='geometry_fixture_run_v1',fixture_task_digest=ids['task_identity'],stability_monitor=frozen)
    expected['runtime_identity']['strategy_identity']=digest({k:v for k,v in expected.items() if k!='runtime_identity'})
    if not same_native(expected,config):raise JevSelectError('geometry_run_config_drift')


def execution_binding(task,config):
    preflight_run(config);validate_fixture(task)
    if digest(task)!=config['fixture_task_digest']:raise JevSelectError('geometry_fixture_task_drift')
    v={'version':GEOMETRY_EXECUTION,'task_digest':digest(task),'config_digest':digest(config),
       'source_identity':config['runtime_identity']['source_identity'],'environment_digest':digest(environment()),
       'scope':'MANUAL_FIXTURE_ONLY'}
    validate_schema('geometry_execution_v1',v)
    return v


def validate_execution_identity(value,config):
    preflight_run(config)
    validate_schema('geometry_execution_v1',value)
    expected={'version':GEOMETRY_EXECUTION,'task_digest':config['fixture_task_digest'],
        'config_digest':digest(config),'source_identity':config['runtime_identity']['source_identity'],
        'environment_digest':digest(environment()),'scope':'MANUAL_FIXTURE_ONLY'}
    if not same_native(value,expected):raise JevSelectError('geometry_execution_binding_drift')


def validate_run_request(task,selector,config,method,store,on_checkpoint):
    from .packaging_runtime import LocalPackagingDouble,METHODS
    binding=execution_binding(task,config)
    if (type(selector) is not LocalPackagingDouble or selector.method!=method or method!=config['selector']
        or method not in METHODS or not isinstance(store,GeometryStore) or not callable(on_checkpoint)):
        raise JevSelectError('geometry_explicit_fixture_execution_required')
    return binding


class GeometryStore:
    """Content addressed, fsynced atomic bytes; no missing-file regeneration."""
    def __init__(self,root):self.root=Path(root);self.input_ref=None

    def put(self,raw):
        key=hashlib.sha256(raw).hexdigest();path=self.root/'blobs'/key
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            if path.read_bytes()!=raw:raise OSError('geometry existing blob corrupted')
        else:
            fd,tmp=tempfile.mkstemp(prefix='.geometry-',dir=path.parent)
            try:
                with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
                os.replace(tmp,path)
                fd=os.open(path.parent,os.O_RDONLY)
                try:os.fsync(fd)
                finally:os.close(fd)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
        if path.read_bytes()!=raw:raise OSError('geometry blob readback mismatch')
        return {'version':'geometry_blob_ref_v1','sha256':key}

    def get(self,ref):
        if (type(ref) is not dict or set(ref)!={'version','sha256'} or ref['version']!='geometry_blob_ref_v1'
            or type(ref['sha256']) is not str or len(ref['sha256'])!=64 or any(x not in '0123456789abcdef' for x in ref['sha256'])):
            raise JevSelectError('geometry_invalid_blob_reference')
        try:raw=(self.root/'blobs'/ref['sha256']).read_bytes()
        except OSError as exc:raise JevSelectError('geometry_missing_blob',str(exc)) from exc
        if hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise JevSelectError('geometry_blob_bytes_drift')
        return raw

    def put_json(self,v):return self.put(canonical(v).encode())
    def get_json(self,ref):
        raw=self.get(ref);v=json.loads(raw)
        if canonical(v).encode()!=raw:raise JevSelectError('geometry_blob_encoding_drift')
        return v

    def save_input(self,common):
        n,g,b=common
        self.input_ref=self.put_json({'version':'geometry_durable_input_v1','native':self.put(n),
            'geometry':self.put(g),'binding':b})
        self.verify_input(self.input_ref)
        return self.input_ref

    def verify_input(self,ref,config=None,state=None,observation=None):
        v=self.get_json(ref)
        if set(v)!={'version','native','geometry','binding'} or v['version']!='geometry_durable_input_v1':raise JevSelectError('geometry_input_blob_contract')
        n,g=self.get(v['native']),self.get(v['geometry'])
        if config is not None:
            from .candidate_backends import validate_common_input
            validate_common_input(n,g,v['binding'],config,state=state,observation=observation)
        return n,g,v['binding']

    def save_event(self,bundle):
        return self.put_json({'version':'geometry_durable_decision_v1','input':copy.deepcopy(self.input_ref),
            'bundle':bundle.data,'audit':bundle.audit,'telemetry':bundle.telemetry})

    def load_event(self,event,config):
        from .candidate_backends import GeometryCandidateBundle,validate_geometry_config_bundle
        from .candidates import validate_bundle
        v=self.get_json(event['geometry_ref'])
        if set(v)!={'version','input','bundle','audit','telemetry'} or v['version']!='geometry_durable_decision_v1':raise JevSelectError('geometry_decision_blob_contract')
        n,g,b=self.verify_input(v['input'],config,event['before'],event['observation'])
        bundle=GeometryCandidateBundle.from_artifacts(v['bundle'],v['audit'],v['telemetry'])
        if (not same_native(bundle.data,event['bundle']) or bundle.audit['native_bytes_hex']!=n.hex()
            or bundle.audit['geometry_bytes_hex']!=g.hex() or not same_native(bundle.audit['common_binding'],b)):
            raise JevSelectError('geometry_saved_bundle_drift')
        validate_geometry_config_bundle(config,bundle);validate_bundle(event['observation'],bundle)
        return bundle

    def save_checkpoint(self,cp):
        from .ledger import write,read
        write(self.root/'checkpoint.json',cp)
        fd=os.open(self.root,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
        if not same_native(read(self.root/'checkpoint.json'),cp):raise OSError('geometry checkpoint readback mismatch')


def validate_saved_checkpoint(cp,task,config,job_id,method,store):
    """Validate saved transitions on private copies; never reselect/reassess/commit."""
    from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive,place
    from semantic_pallet_planner.o4.extensions.e2.protocol import observation
    from semantic_pallet_planner.o4.extensions.e2.planning import action_for
    from .context import validate_context,resolve_display_id
    from .contracts import DecisionContext
    from .stability.monitor import validate_monitor
    from .packaging_runtime import evaluate_state
    validate_schema('checkpoint_v15',cp)
    if (cp['record_digest']!=digest({k:v for k,v in cp.items() if k!='record_digest'})
        or not same_native(cp['execution_binding'],execution_binding(task,config))
        or cp['config_digest']!=digest(config) or cp['task_digest']!=digest(task)
        or not same_native(cp['runtime_identity'],config['runtime_identity'])
        or cp['job_id']!=job_id or cp['method']!=method):raise JevSelectError('geometry_checkpoint_identity_drift')
    state=initial(task['container'],config['buffer_capacity']);cursor=decision=0;stopped=None
    def check(ev,before,committed,phase=None):
        if not same_native(ev['before'],before):raise JevSelectError('geometry_saved_before_drift')
        if ev['bundle'] is None:
            if committed or ev['selection'] is not None or not ev['error'] or ev['reason']!=ev['error']['code'] or not same_native(ev['after'],before):raise JevSelectError('geometry_saved_failure_drift')
            if ev['geometry_ref'] is not None:
                failure=store.get_json(ev['geometry_ref'])
                if failure['version']!='geometry_generation_failure_v1' or not same_native(failure['error'],ev['error']):raise JevSelectError('geometry_saved_failure_blob_drift')
                if failure['input'] is not None:store.verify_input(failure['input'],config,before,observation(before,task['instruction_text'],task['regions']))
            return before
        b=store.load_event(ev,config);req=observation(before,task['instruction_text'],task['regions'])
        if not same_native(req,ev['observation']):raise JevSelectError('geometry_saved_observation_drift')
        ctx=DecisionContext.from_dict(ev['context']);validate_context(ctx,req,b,config)
        if ev['decision_id']!=f'{job_id}_D{decision:04d}' or ctx.data['local_binding']['job_id']!=job_id or ctx.data['local_binding']['decision_id']!=ev['decision_id']:raise JevSelectError('geometry_saved_decision_drift')
        sel=ev['selection']
        if phase=='DECISION_READY' and (sel is not None or ev['monitor'] is not None or ev['proposed_action'] is not None):raise JevSelectError('geometry_ready_selection_drift')
        if phase in ('SELECTED','MONITORED','COMMITTED') and (sel is None or sel['status'] not in ('selected','singleton')):raise JevSelectError('geometry_pending_selection_missing')
        if sel is None or sel['status'] not in ('selected','singleton'):
            if ev['monitor'] is not None or ev['proposed_action'] is not None or committed:raise JevSelectError('geometry_unselected_action')
            if sel is not None:
                validate_schema('selection_result',sel)
                if sel['local_binding_digest']!=digest(ctx.data['local_binding']):raise JevSelectError('geometry_saved_selection_drift')
            if not same_native(ev['after'],before) or ev['action'] is not None:raise JevSelectError('geometry_unselected_mutation')
            if phase is None and (ev['reason']!= (sel['status'].upper() if sel is not None else 'STOP_NO_PHYSICAL_CANDIDATE')):raise JevSelectError('geometry_saved_selection_stop_drift')
            return before
        validate_schema('selection_result',sel)
        chosen=resolve_display_id(ctx,sel['selected_display_id'],req,b,config)
        if (sel['local_binding_digest']!=digest(ctx.data['local_binding']) or sel['selected_candidate_id']!=chosen['candidate_id']
            or not same_native(ev['proposed_action'],action_for(req,b.data['physical_candidates'],chosen))):raise JevSelectError('geometry_saved_action_drift')
        row=ev['monitor']
        if row is not None:validate_monitor(row,before,chosen,ev,config,require_stable=committed)
        if phase=='SELECTED' and row is not None or phase in ('MONITORED','COMMITTED') and row is None:raise JevSelectError('geometry_saved_phase_drift')
        if phase is None and not committed:
            reasons={'UNSTABLE':'PREDICTED_STATIC_INSTABILITY','UNASSESSABLE':'STABILITY_UNASSESSABLE','ERROR':'STABILITY_MONITOR_ERROR','DISABLED':'GEOMETRY_MONITOR_DISABLED'}
            expected_reason=reasons.get(row['status']) if row else None
            if expected_reason is None or ev['reason']!=expected_reason:raise JevSelectError('geometry_saved_monitor_stop_drift')
        if committed:
            if row is None or row['status']!='STABLE':raise JevSelectError('geometry_saved_commit_not_stable')
            if ev['reason'] is not None:raise JevSelectError('geometry_committed_reason_drift')
            after=place(copy.deepcopy(before),chosen)  # sole original buffer/physics implementation, private validation only
            if not same_native(ev['after'],after) or ev['action']!=ev['proposed_action']:raise JevSelectError('geometry_saved_after_drift')
            return after
        if not same_native(ev['after'],before) or ev['action'] is not None:raise JevSelectError('geometry_uncommitted_mutation')
        return before
    for ev in cp['events']:
        if stopped is not None or not same_native(ev['before'],state):raise JevSelectError('geometry_discontinuous_history')
        if ev['event']=='WAIT_RECEIVE':
            obj=task['items'][cursor];after=receive(state,obj,task['attributes'][obj['item_id']]);cursor+=1
        elif ev['event']=='EOS':after=receive(state,eos=True)
        else:
            after=check(ev,state,ev['event']=='PLACE');decision+=1;stopped=ev['reason']
            if not same_native(ev['business_after'],evaluate_state(after)):raise JevSelectError('geometry_saved_evaluation_drift')
        if not same_native(ev['after'],after):raise JevSelectError('geometry_saved_transition_drift')
        state=after
    pending=cp['pending_event'];phase=cp['phase']
    if pending is not None:
        if stopped or phase not in ('DECISION_READY','SELECTED','MONITORED','COMMITTED'):raise JevSelectError('geometry_pending_phase_drift')
        state=check(pending,state,phase=='COMMITTED',phase)
    elif phase not in ('READY','TERMINATED'):raise JevSelectError('geometry_missing_pending')
    if not same_native(cp['state'],state) or cp['cursor']!=cursor or cp['decision']!=decision:raise JevSelectError('geometry_saved_progress_drift')
    expected=stopped or ('ALL_ITEMS_PLACED' if pending is None and state['end_of_stream'] and not state['pending_items'] and cp['reason']=='ALL_ITEMS_PLACED' else None)
    if cp['reason']!=expected or (phase=='TERMINATED')!=(expected is not None):raise JevSelectError('geometry_saved_stop_drift')
    return cp
