"""Explicit v7 method route. Reuses durable v6 ledger and strict native parsing."""
from .contracts import JevSelectError, digest, validate_schema
from .packaging_experience import VERSION, METHOD, validate_view, MemoryView
from .packaging_remote import RequestLedger, load_remote_config
from .selector import result, parse_response, SelectionResult

VERSIONS={'execution':VERSION,'config':VERSION,'context':'jev_decision_context_v7',
          'candidate_bundle':'jev_candidate_bundle_v7','selection':'jev_selection_result_v7',
          'checkpoint':'jev_checkpoint_v7','metrics':'jev_packaging_memory_metrics_v1',
          'request_ledger':'jev_packaging_memory_requests_v1','run':'JN3-A_single_decision_v1'}
REGISTRY={METHOD:{'origin':'jev','model':'jev-1.14.0','mode':'T'}}


def load_memory_config(*,data_identity,task_digest,snapshot_digest,entry_digests,enabled=False):
    from .experiment import source_manifest
    c=load_remote_config(data_identity=data_identity,task_digest=task_digest,enabled=enabled)
    c.update(version=VERSION,selector=METHOD,memory_mode='T',memory_snapshot_digest=snapshot_digest,memory_entry_digests=sorted(entry_digests))
    c['runtime_identity']['strategy_identity']=digest({'config':{k:v for k,v in c.items() if k!='runtime_identity'},
                                                     'source':source_manifest(),'versions':VERSIONS})
    validate_schema('config',c);return c


def preflight_memory(config):
    i=config['runtime_identity']
    expected=load_memory_config(data_identity=i['data_identity'],task_digest=i['task_identity'],
                               snapshot_digest=config['memory_snapshot_digest'],entry_digests=config['memory_entry_digests'],enabled=config['stability_monitor']['enabled'])
    if config!=expected:raise JevSelectError('memory_frozen_identity_changed')


class MemoryRequestLedger(RequestLedger):
    ledger_version=VERSIONS['request_ledger']
    context_version=VERSIONS['context']

    @classmethod
    def identity(cls,context,job_id,decision_id):
        identity=super().identity(context,job_id,decision_id)
        v=validate_view(MemoryView.from_dict(context.data['memory_view']))
        if not v['entries']:raise JevSelectError('memory_request_empty')
        return {**identity,'snapshot_digest':v['snapshot_digest'],'memory_view_digest':v['view_digest'],
                'injected_digest':digest(v['entries'])}


class PackagingMemorySelector:
    def __init__(self,config,ledger,job_id,transport):
        self.config,self.ledger,self.job_id,self.transport=config,ledger,job_id,transport

    def select(self,context,*,decision_id):
        from .context import validate_context
        validate_context(context,config=self.config)
        b=context.data['local_binding']
        if b.get('job_id')!=self.job_id or b.get('decision_id')!=decision_id:raise JevSelectError('selector_identity_mismatch')
        if context.data['route']=='SINGLETON_BYPASS':return result(context,status='singleton',source='singleton',label='C01')
        attempt=self.ledger.request(context,self.job_id,decision_id,self.transport)
        if attempt['selection'] is not None:return SelectionResult.from_dict(attempt['selection'])
        selected=parse_response(context,attempt,self.config);self.ledger.save_selection(attempt,selected)
        return selected


def memory_selector_factory(method,*,config,transport,ledger,job_id):
    if method not in REGISTRY or config is None or config['version']!=VERSION or config['selector']!=method:
        raise JevSelectError('memory_unregistered_method_or_protocol')
    validate_schema('config',config)
    if not isinstance(ledger,MemoryRequestLedger) or not job_id:raise JevSelectError('memory_dependencies_required')
    return PackagingMemorySelector(config,ledger,job_id,transport)
