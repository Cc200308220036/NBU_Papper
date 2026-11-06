"""v12 exact-pose synthetic protocol. Old v11 schema/config remain closed."""
from .packaging_versions import EXACT_VERSION,EXACT_CONTEXT
from .contracts import digest,validate_schema
from .packaging_source_audit import require
from .packaging_synthetic_protocol import load_synthetic_config, request_accounting
from .packaging_evaluation_protocol import REGISTRY,EvaluationLedger,LocalEvaluationSelector
from .packaging_memory_protocol import PackagingMemorySelector
from .stability.monitor import exact_freeze

VERSIONS={'execution':EXACT_VERSION,'context':EXACT_CONTEXT,'monitor':'pct_exact_pose_network_v3',
 'ledger':'jev_exact_synthetic_requests_v2','plan':'jev_synthetic_supplement_plan_v2'}

def strategy(config):
    from .experiment import source_manifest
    return digest({'config':{k:v for k,v in config.items() if k!='runtime_identity'},
                   'source':source_manifest(),'versions':VERSIONS})

def load_exact_config(**kwargs):
    require(kwargs.get('enabled',True) is True,'exact_monitor_must_be_enabled')
    c=load_synthetic_config(**kwargs)
    c.update(version=EXACT_VERSION,stability_monitor=exact_freeze())
    c['runtime_identity']['monitor_identity']=digest(c['stability_monitor'])
    c['runtime_identity']['strategy_identity']=strategy(c)
    validate_schema('config',c)
    return c

def preflight_exact(c):
    from .packaging_remote import load_remote_config
    validate_schema('config',c);i=c['runtime_identity']
    require(c['version']==EXACT_VERSION and c['memory_mode']==REGISTRY[c['selector']]['mode'],'exact_method')
    require(i['strategy_identity']==strategy(c),'exact_strategy_identity')
    require(c['stability_monitor']==exact_freeze() and i['monitor_identity']==digest(c['stability_monitor']),'exact_monitor_identity')
    base=load_remote_config(data_identity=i['data_identity'],task_digest=i['task_identity'],enabled=True)
    require(all(c[k]==v for k,v in base.items() if k not in ('version','selector','memory_mode','runtime_identity','stability_monitor')),'exact_base_changed')
    require(all(i[k]==v for k,v in base['runtime_identity'].items() if k not in ('strategy_identity','monitor_identity')),'exact_physical_changed')

class ExactLedger(EvaluationLedger):
    ledger_version=VERSIONS['ledger'];context_version=EXACT_CONTEXT
    def __init__(self,root,budget,configs,**kwargs):
        require(all(c['version']==EXACT_VERSION for c in configs.values()),'exact_ledger_protocol')
        super().__init__(root,budget,configs,**kwargs)
    def statistics(self):
        from .packaging_orders import saved_reuses
        return request_accounting(self._load()['requests'],saved_reuses(self.root.parent))

def selector_factory(method,*,config,transport,ledger,job_id):
    preflight_exact(config)
    require(method==config['selector'] and method in REGISTRY,'exact_method_route')
    if not REGISTRY[method]['remote']:
        require(transport is None,'exact_local_transport')
        return LocalEvaluationSelector(config,job_id)
    require(isinstance(ledger,ExactLedger) and job_id in ledger.configs,'exact_ledger_binding')
    return PackagingMemorySelector(config,ledger,job_id,transport)
