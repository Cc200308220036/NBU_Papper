"""v11 explicit synthetic purpose and order-level memory scope; same physical engine."""
from .contracts import digest, validate_schema
from .packaging_source_audit import require
from .packaging_evaluation_protocol import REGISTRY, METHODS, LocalEvaluationSelector, EvaluationLedger
from .packaging_evaluation_protocol import load_evaluation_config
from .packaging_memory_protocol import PackagingMemorySelector
from .packaging_synthetic_data import MEMORY_SCOPE

VERSION='jev_packaging_synthetic_v11'
PURPOSE='FROZEN_SYNTHETIC_EVALUATION'
VERSIONS={'execution':VERSION,'context':'jev_decision_context_v11','candidate_bundle':'jev_candidate_bundle_v11',
 'selection':'jev_selection_result_v11','checkpoint':'jev_checkpoint_v11','ledger':'jev_synthetic_requests_v1',
 'plan':'jev_synthetic_orders_plan_v1','run':'jev_synthetic_orders_run_v1'}


def load_synthetic_config(*,data_identity,task_digest,method,relation,purpose=PURPOSE,snapshot=None,control=None,enabled=True):
    from .experiment import source_manifest
    require(purpose in (PURPOSE,'SYNTHETIC_ENGINEERING'),'synthetic_config_purpose')
    require(relation['memory_scope_version']==MEMORY_SCOPE,'synthetic_memory_scope')
    c=load_evaluation_config(data_identity=data_identity,task_digest=task_digest,method=method,snapshot=snapshot,control=control,
       excluded_source_groups=relation['order_related_source_groups'],excluded_fork_digests=relation['excluded_fork_digests'],enabled=enabled)
    c.update(version=VERSION,memory_scope_version=MEMORY_SCOPE,source_relation_digest=digest(relation),evaluation_purpose=purpose)
    c['runtime_identity']['strategy_identity']=digest({'config':{k:v for k,v in c.items() if k!='runtime_identity'},'source':source_manifest(),'versions':VERSIONS})
    validate_schema('config',c);return c


def preflight_synthetic(c):
    from .experiment import source_manifest
    from .packaging_remote import load_remote_config
    validate_schema('config',c);i=c['runtime_identity']
    require(c['memory_mode']==REGISTRY[c['selector']]['mode'],'synthetic_method_mode')
    require(i['strategy_identity']==digest({'config':{k:v for k,v in c.items() if k!='runtime_identity'},'source':source_manifest(),'versions':VERSIONS}),'synthetic_strategy_changed')
    base=load_remote_config(data_identity=i['data_identity'],task_digest=i['task_identity'],enabled=c['stability_monitor']['enabled'])
    require(all(c[k]==v for k,v in base.items() if k not in ('version','selector','memory_mode','runtime_identity')),'synthetic_base_changed')
    require(all(i[k]==v for k,v in base['runtime_identity'].items() if k!='strategy_identity'),'synthetic_physical_changed')


class SyntheticLedger(EvaluationLedger):
    ledger_version=VERSIONS['ledger'];context_version=VERSIONS['context']
    def __init__(self,root,budget,configs,**kw):
        require(all(c['version']==VERSION for c in configs.values()),'synthetic_ledger_protocol')
        super().__init__(root,budget,configs,**kw)

    def statistics(self):
        from .packaging_orders import saved_reuses
        return request_accounting(self._load()['requests'],saved_reuses(self.root.parent))


def selector_factory(method,*,config,transport,ledger,job_id):
    preflight_synthetic(config)
    require(method==config['selector'] and method in REGISTRY,'synthetic_method_route')
    if not REGISTRY[method]['remote']:
        require(transport is None,'synthetic_local_transport');return LocalEvaluationSelector(config,job_id)
    require(isinstance(ledger,SyntheticLedger) and job_id in ledger.configs,'synthetic_ledger_required')
    return PackagingMemorySelector(config,ledger,job_id,transport)


def request_accounting(rows,reuses=()):
    """Durable origins/outcomes, never infer zero real calls from purpose."""
    from .packaging_orders import request_statistics
    result=request_statistics(rows,reuses)
    real=[r for r in rows if r['origin']=='jev' and r['send_started']]
    unknown=[r for r in real if r['state'] in ('SENDING','UNKNOWN_SEND') or r['transport'] is None or r['transport']['network_attempted'] is None]
    known=sum(r['transport'] is not None and r['transport']['network_attempted'] is True for r in real if r not in unknown)
    result.update(known_real_model_calls=known,unknown_real_send_count=len(unknown),
      actual_model_api_calls='UNKNOWN' if unknown else known,
      real_model_call_interval={'minimum':known,'maximum':known+len(unknown)},
      model_cost_usd='UNKNOWN' if real else 0)
    return result
