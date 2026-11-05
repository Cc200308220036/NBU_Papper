"""v10 explicit per-decision view, including paired unrelated E placebo.

Reuses frozen v9 retrieval algebra on genuine T/E; replacement is explicit and
persisted, never mislabeled as an evidence card. Validation never re-retrieves.
"""
import copy
from .contracts import Snapshot,digest,canonical,validate_schema
from .packaging_source_audit import require
from . import packaging_pilot_memory as base
from .packaging_evaluation_plan import validate_control
from .packaging_experience import sealed,verify_seal,RULE

class PilotMemoryView(Snapshot):pass


def reference_config(config):
    c=copy.deepcopy(config);c.update(memory_mode=c['memory_reference_mode'],memory_snapshot_digest=c['reference_snapshot_digest'],
       memory_entry_digests=sorted(x['public_digest'] for x in c['memory_index']))
    return c


def converted(reference_view,config):
    r=reference_view.data;entries=r['entries']
    if config['memory_mode']=='E_unrelated_control':
        pairs={x['reference_public_digest']:x for x in config['control_entries']}
        require(all(digest(e) in pairs for e in entries),'evaluation_missing_paired_control')
        entries=[pairs[digest(e)]['public_fragment'] for e in entries]
    text=canonical(entries)
    require(len(text)<=RULE['max_chars'] and len(text.encode())<=RULE['max_utf8_bytes'],'evaluation_view_limit')
    return PilotMemoryView.from_dict(sealed({'version':'jev_evaluation_memory_view_v1','mode':config['memory_mode'],
       'snapshot_digest':config['memory_snapshot_digest'],'query_digest':r['query_digest'],'entries':entries,
       'reason':r['reason'],'injected_chars':len(text),'injected_utf8_bytes':len(text.encode())},'view_digest'))


def validate_view(view,config):
    require(isinstance(view,PilotMemoryView),'evaluation_explicit_view_required')
    v=view.data;validate_schema('evaluation_memory_view_v1',v);verify_seal(v,'view_digest')
    require(v['mode']==config['memory_mode'] and v['snapshot_digest']==config['memory_snapshot_digest'],'evaluation_view_snapshot')
    require(all(digest(e) in config['memory_entry_digests'] for e in v['entries']),'evaluation_unfrozen_entry')
    return v


def validate_receipt(saved,view,config,state,criteria):
    validate_schema('evaluation_retrieval_v1',saved);verify_seal(saved,'receipt_digest');validate_view(view,config)
    ref=base.PilotMemoryView.from_dict(saved['reference_view'])
    base.validate_receipt(saved['reference_receipt'],ref,reference_config(config),state,criteria)
    require(converted(ref,config).data==view.data,'evaluation_conversion_changed')
    expected=make_receipt(ref,saved['reference_receipt'],view)
    require(expected==saved,'evaluation_saved_receipt_changed')
    return saved


def make_receipt(reference_view,reference_receipt,view):
    r=reference_receipt
    return sealed({'version':'jev_evaluation_retrieval_v1','query':r['query'],'query_digest':r['query_digest'],
       'view_digest':view.data['view_digest'],'status':r['status'],
       'reference_view':reference_view.data,'reference_receipt':r},'receipt_digest')


class MemoryDriver:
    def __init__(self,config,*,snapshot=None,control=None):
        self.config=copy.deepcopy(config);self.mode=config['memory_mode'];self.calls=0
        if self.mode=='E_unrelated_control':
            validate_control(control,snapshot)
            require(control['snapshot_digest']==config['memory_snapshot_digest'] and control['entries']==config['control_entries'],'evaluation_control_identity')
        else:require(control is None,'evaluation_unexpected_control_snapshot')
        self.reference=base.MemoryDriver(reference_config(config),snapshot=snapshot)
    def resolve(self,public_state,public_criteria):
        r,receipt=self.reference.resolve(public_state,public_criteria);self.calls+=1
        v=converted(r,self.config);saved=make_receipt(r,receipt,v)
        validate_receipt(saved,v,self.config,public_state,public_criteria)
        return v,saved
