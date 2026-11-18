"""v10 central six-method route. Shared Choice, ledger and physical engine."""
from .contracts import digest,validate_schema
from .packaging_source_audit import require
from .packaging_remote import load_remote_config
from .packaging_pilot_protocol import PilotLedger,budget_identity
from .packaging_memory_protocol import PackagingMemorySelector
from .packaging_evaluation_plan import REGISTRY as DESIGN,validate_control
from .packaging_pilot_memory import NONE_DIGEST
VERSION='jev_packaging_evaluation_v10'
REGISTRY={m:{'origin':v['origin'],'model':'jev-1.14.0','mode':v['memory'],'remote':v['remote']} for m,v in DESIGN.items()}
METHODS=list(REGISTRY)
VERSIONS={'execution':VERSION,'context':'jev_decision_context_v10','candidate_bundle':'jev_candidate_bundle_v10',
 'selection':'jev_selection_result_v10','checkpoint':'jev_checkpoint_v10','ledger':'jev_evaluation_requests_v1',
 'metrics':'jev_evaluation_order_metrics_v1','plan':'jev_evaluation_orders_plan_v1','run':'jev_evaluation_orders_run_v1'}


def load_evaluation_config(*,data_identity,task_digest,method,snapshot=None,control=None,
                           excluded_source_groups=(),excluded_fork_digests=(),enabled=False):
    from .experiment import source_manifest
    from .packaging_pilot_memory import index
    require(method in REGISTRY,'evaluation_unknown_method');mode=REGISTRY[method]['mode']
    refmode='E' if mode=='E_unrelated_control' else mode
    refindex=index(snapshot,refmode)
    require(mode!='none' or (snapshot is None and control is None),'evaluation_none_snapshot')
    require(mode=='E_unrelated_control' or control is None,'evaluation_unexpected_control')
    controls=[]
    if mode=='E_unrelated_control':
        validate_control(control,snapshot);controls=control['entries']
    reference_digest=NONE_DIGEST if snapshot is None else snapshot['snapshot_digest']
    snapshot_digest=control['snapshot_digest'] if control is not None else reference_digest
    c=load_remote_config(data_identity=data_identity,task_digest=task_digest,enabled=enabled)
    c.update(version=VERSION,selector=method,memory_mode=mode,memory_reference_mode=refmode,
       memory_snapshot_digest=snapshot_digest,reference_snapshot_digest=reference_digest,
       memory_index=refindex,memory_entry_digests=sorted(x['public_digest'] for x in (controls if controls else refindex)),
       control_entries=controls,excluded_source_groups=list(excluded_source_groups),excluded_fork_digests=list(excluded_fork_digests))
    c['runtime_identity']['strategy_identity']=digest({'config':{k:v for k,v in c.items() if k!='runtime_identity'},'source':source_manifest(),'versions':VERSIONS})
    validate_schema('config',c);return c


def preflight_evaluation(config):
    from .experiment import source_manifest
    validate_schema('config',config)
    require(config['selector'] in REGISTRY and config['memory_mode']==REGISTRY[config['selector']]['mode'],'evaluation_method_mode')
    ref=dict(config);i=ref['runtime_identity']
    expected=digest({'config':{k:v for k,v in ref.items() if k!='runtime_identity'},'source':source_manifest(),'versions':VERSIONS})
    require(i['strategy_identity']==expected,'evaluation_source_or_strategy_changed')
    # Authenticate every inherited base knob without manufacturing a v9 config.
    base=load_remote_config(data_identity=i['data_identity'],task_digest=i['task_identity'],enabled=config['stability_monitor']['enabled'])
    require(all(config[k]==v for k,v in base.items() if k not in ('version','selector','memory_mode','runtime_identity')),'evaluation_base_changed')
    require(all(i[k]==v for k,v in base['runtime_identity'].items() if k!='strategy_identity'),'evaluation_physics_changed')


class EvaluationLedger(PilotLedger):
    ledger_version=VERSIONS['ledger'];context_version=VERSIONS['context']
    def request(self,context,job_id,decision_id,transport):
        require(job_id in self.configs and REGISTRY[self.configs[job_id]['selector']]['remote'],'evaluation_local_or_unplanned_send')
        return super().request(context,job_id,decision_id,transport)


class LocalEvaluationSelector:
    def __init__(self,config,job_id):self.config,self.job_id=config,job_id
    def select(self,context,*,decision_id):
        from .context import validate_context
        from .selector import result,baseline_label
        validate_context(context,config=self.config)
        require(context.data['local_binding']['job_id']==self.job_id and context.data['local_binding']['decision_id']==decision_id,'evaluation_local_binding')
        label=baseline_label(context,'shared_geometry') if self.config['selector']=='local_geometry_test_double' else min(context.data['criteria'])
        from .selector import SelectionResult
        selected=result(context,status='selected',source='test_double',label=label).data
        selected['requested_model']=None
        validate_schema('selection_result',selected)
        return SelectionResult.from_dict(selected)


def selector_factory(method,*,config,transport,ledger,job_id):
    require(method in REGISTRY and config['version']==VERSION and config['selector']==method,'evaluation_selector_route')
    preflight_evaluation(config)
    if not REGISTRY[method]['remote']:
        require(transport is None,'evaluation_local_transport_forbidden')
        return LocalEvaluationSelector(config,job_id)
    require(isinstance(ledger,EvaluationLedger) and job_id in ledger.configs,'evaluation_ledger_required')
    return PackagingMemorySelector(config,ledger,job_id,transport)
