"""JN3-B explicit E route reusing the shared Choice selector and single-send ledger."""
from .contracts import digest,validate_schema
from .packaging_remote import RequestLedger,load_remote_config
from .packaging_memory_protocol import PackagingMemorySelector
from .packaging_contrast import VERSION,METHOD,EMemoryView,validate_view
from .packaging_experience import require
VERSIONS={'execution':VERSION,'config':VERSION,'context':'jev_decision_context_v8','candidate_bundle':'jev_candidate_bundle_v8',
 'selection':'jev_selection_result_v8','checkpoint':'jev_checkpoint_v8','metrics':'jev_packaging_contrast_metrics_v1',
 'request_ledger':'jev_packaging_contrast_requests_v1','run':'JN3-B_single_decision_v1'}
REGISTRY={METHOD:{'origin':'jev','model':'jev-1.14.0','mode':'E'}}


def load_contrast_config(*,data_identity,task_digest,snapshot_digest,entry_digests,enabled=False):
    from .experiment import source_manifest
    c=load_remote_config(data_identity=data_identity,task_digest=task_digest,enabled=enabled)
    c.update(version=VERSION,selector=METHOD,memory_mode='E',memory_snapshot_digest=snapshot_digest,memory_entry_digests=sorted(entry_digests))
    c['runtime_identity']['strategy_identity']=digest({'config':{k:v for k,v in c.items() if k!='runtime_identity'},'source':source_manifest(),'versions':VERSIONS})
    validate_schema('config',c);return c


def preflight_contrast(c):
    i=c['runtime_identity'];expected=load_contrast_config(data_identity=i['data_identity'],task_digest=i['task_identity'],snapshot_digest=c['memory_snapshot_digest'],entry_digests=c['memory_entry_digests'],enabled=c['stability_monitor']['enabled'])
    require(c==expected,'contrast_frozen_identity_changed')


class ContrastRequestLedger(RequestLedger):
    ledger_version=VERSIONS['request_ledger'];context_version=VERSIONS['context']
    @classmethod
    def identity(cls,context,job_id,decision_id):
        identity=super().identity(context,job_id,decision_id)
        v=validate_view(EMemoryView.from_dict(context.data['memory_view']));require(v['entries'],'contrast_empty_request')
        return {**identity,'snapshot_digest':v['snapshot_digest'],'memory_view_digest':v['view_digest'],'injected_digest':digest(v['entries'])}


def contrast_selector_factory(method,*,config,transport,ledger,job_id):
    require(method in REGISTRY and config is not None and config['version']==VERSION and config['selector']==method,'contrast_unregistered_method')
    validate_schema('config',config);require(isinstance(ledger,ContrastRequestLedger) and job_id,'contrast_dependencies_required')
    return PackagingMemorySelector(config,ledger,job_id,transport)
