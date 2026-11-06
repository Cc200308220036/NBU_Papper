"""JN3-C unified execution protocol: identical base Choice, explicit none/T/E."""
from .contracts import digest,validate_schema
from .packaging_experience import require
from .packaging_remote import load_remote_config
from .packaging_memory_protocol import PackagingMemorySelector
from .packaging_orders import OrderLedger
from .packaging_pilot_memory import PilotMemoryView,validate_view,validate_receipt,NONE_DIGEST
VERSION='jev_packaging_memory_orders_v9'
REGISTRY={'jev_no_memory':{'origin':'jev','model':'jev-1.14.0','mode':'none'},
          'jev_with_trajectory':{'origin':'jev','model':'jev-1.14.0','mode':'T'},
          'jev_with_contrast_experience':{'origin':'jev','model':'jev-1.14.0','mode':'E'}}
METHODS=list(REGISTRY)
VERSIONS={'execution':VERSION,'config':VERSION,'context':'jev_decision_context_v9','candidate_bundle':'jev_candidate_bundle_v9',
          'selection':'jev_selection_result_v9','checkpoint':'jev_checkpoint_v9','request_ledger':'jev_pilot_requests_v1',
          'metrics':'jev_packaging_memory_order_metrics_v1','plan':'jev_memory_order_plan_v1','run':'jev_memory_order_run_v1'}


def load_pilot_config(*,data_identity,task_digest,method,snapshot_digest,memory_index,excluded_source_groups,excluded_fork_digests=(),enabled=False):
    from .experiment import source_manifest
    require(method in REGISTRY,'pilot_unregistered_method');mode=REGISTRY[method]['mode']
    require((mode=='none' and snapshot_digest==NONE_DIGEST and not memory_index) or mode in ('T','E'),'pilot_mode_snapshot_mismatch')
    c=load_remote_config(data_identity=data_identity,task_digest=task_digest,enabled=enabled)
    c.update(version=VERSION,selector=method,memory_mode=mode,memory_snapshot_digest=snapshot_digest,
        memory_index=memory_index,memory_entry_digests=sorted(x['public_digest'] for x in memory_index),
        excluded_source_groups=list(excluded_source_groups),excluded_fork_digests=list(excluded_fork_digests))
    c['runtime_identity']['strategy_identity']=digest({'config':{k:v for k,v in c.items() if k!='runtime_identity'},'source':source_manifest(),'versions':VERSIONS})
    validate_schema('config',c);return c


def preflight_pilot(c):
    i=c['runtime_identity']
    expected=load_pilot_config(data_identity=i['data_identity'],task_digest=i['task_identity'],method=c['selector'],snapshot_digest=c['memory_snapshot_digest'],memory_index=c['memory_index'],
         excluded_source_groups=c['excluded_source_groups'],excluded_fork_digests=c['excluded_fork_digests'],enabled=c['stability_monitor']['enabled'])
    require(c==expected,'pilot_frozen_identity_changed')


def budget_identity(budget,configs):
    return digest({'budget':budget,'configs':{k:digest(v) for k,v in configs.items()}})


class PilotLedger(OrderLedger):
    ledger_version=VERSIONS['request_ledger'];context_version=VERSIONS['context']
    def __init__(self,root,budget,configs,**kw):
        self.configs=configs;self._budget_digest=budget_identity(budget,configs)
        super().__init__(root,budget,**kw)

    def _save(self,data):
        if 'budget_digest' not in data and not data['requests']:data['budget_digest']=self._budget_digest
        require(data.get('budget_digest')==self._budget_digest,'pilot_ledger_budget_identity_changed')
        return super()._save(data)

    def _load(self):
        data=super()._load()
        require(data.get('budget_digest')==self._budget_digest,'pilot_ledger_budget_identity_changed')
        return data

    def request(self,context,job_id,decision_id,transport):
        from .context import validate_context
        require(job_id in self.configs,'pilot_unregistered_job')
        validate_context(context,config=self.configs[job_id])
        return super().request(context,job_id,decision_id,transport)

    @classmethod
    def identity(cls,context,job_id,decision_id):
        v=context.data;validate_schema('decision_context',v);b=v['local_binding']
        require(v['version']==cls.context_version and b['job_id']==job_id and b['decision_id']==decision_id and v['route']=='CHOICE_REQUIRED','pilot_request_binding_mismatch')
        value={'context_digest':digest(v),'body_digest':digest(v['request_body']),'binding_digest':digest(b),'state_digest':digest(v['model_state']),'mapping_digest':digest(v['display_mapping'])}
        return {**value,'query_digest':v['local_binding']['query_digest'],'retrieval_digest':v['local_binding']['retrieval_digest'],
                'snapshot_digest':v['memory_view']['snapshot_digest'],'memory_view_digest':v['memory_view']['view_digest'],
                'injected_digest':digest(v['model_state']['memories'])}


def pilot_selector_factory(method,*,config,transport,ledger,job_id):
    require(method in REGISTRY and config is not None and config['version']==VERSION and config['selector']==method,'pilot_unregistered_method_or_protocol')
    validate_schema('config',config);require(isinstance(ledger,PilotLedger) and job_id,'pilot_remote_dependencies_required')
    return PackagingMemorySelector(config,ledger,job_id,transport)
