"""JN3-C explicit per-public-decision memory. No task/arrival stream is accepted.

Fresh decisions use the frozen T/E retrievers. Recovery validates the saved
query/view/receipt algebra and never invokes the retriever or driver again.
"""
from __future__ import annotations
import copy
from .contracts import Snapshot,DecisionContext,digest,canonical,validate_schema
from . import packaging_experience as T
from . import packaging_contrast as E

NONE_DIGEST=digest({'mode':'none','entries':[]})
RULE=T.RULE
STATE_FIELDS={'units','coordinate_convention','container','assumptions','placed_objects','available_objects','buffer','objective','memories'}

class PilotMemoryView(Snapshot):pass


def index(snapshot,mode):
    if mode=='none':return []
    s=T.validate_snapshot(snapshot) if mode=='T' else E.validate_snapshot(snapshot)
    cards=s['cases'] if mode=='T' else s['cards']
    return [{'case_digest':c['case_digest'],'public_digest':c['public_digest'],'query':c['retrieval_query'],
       'source_group':c['provenance']['source_group'],'fork_digest':c['provenance']['fork_digest'],
       'chars':len(canonical(c['public_fragment'])),'bytes':len(canonical(c['public_fragment']).encode())} for c in cards]


def query(state,criteria):
    T.require(set(state)==STATE_FIELDS and state['memories']==[],'pilot_nonpublic_or_recursive_query')
    # Only the already-public state and criteria are passed. No local binding/task.
    if not criteria:return None
    return T.public_query(DecisionContext.from_dict({'model_state':copy.deepcopy(state),'criteria':copy.deepcopy(criteria)}))


def view_from_entries(mode,snapshot_digest,query_digest,entries,reason):
    text=canonical(entries)
    return PilotMemoryView.from_dict(T.sealed({'version':'jev_pilot_memory_view_v1','mode':mode,'snapshot_digest':snapshot_digest,
        'query_digest':query_digest,'entries':entries,'reason':reason,'injected_chars':len(text),'injected_utf8_bytes':len(text.encode())},'view_digest'))


def validate_view(view,config):
    T.require(isinstance(view,PilotMemoryView),'pilot_explicit_view_required')
    v=view.data;validate_schema('pilot_memory_view_v1',v);T.verify_seal(v,'view_digest')
    T.require(v['mode']==config['memory_mode'] and v['snapshot_digest']==config['memory_snapshot_digest'],'pilot_view_identity_changed')
    for entry in v['entries']:
        T.require(v['mode']!='none','pilot_no_memory_nonempty')
        validate_schema('packaging_public_fragment_v1' if v['mode']=='T' else 'packaging_contrast_public_v1',entry)
        T.require(digest(entry) in config['memory_entry_digests'],'pilot_unfrozen_entry')
    text=canonical(v['entries'])
    T.require(v['injected_chars']==len(text) and v['injected_utf8_bytes']==len(text.encode()),'pilot_view_length_changed')
    T.require(len(v['entries'])<=RULE['max_entries'] and len(text)<=RULE['max_chars'] and len(text.encode())<=RULE['max_utf8_bytes'],'pilot_view_budget_exceeded')
    return v


def expected_trace(q,config,entries):
    """Saved-record mathematical audit, not a fresh retrieval dispatch."""
    rows=[]
    for c in config['memory_index']:
        excluded=c['source_group'] in config['excluded_source_groups'] or c['fork_digest'] in config['excluded_fork_digests']
        distance=sum(abs(q['features'][k]-c['query']['features'][k]) for k in RULE['features'])/len(RULE['features'])
        score=1/(1+distance)
        rows.append({'public_digest':c['public_digest'],'case_digest':c['case_digest'],'score':score,'excluded':excluded,'qualified':not excluded and score>=RULE['minimum_score']})
    rows.sort(key=lambda r:(-r['score'],r['public_digest']))
    sizes=[];accepted=[];chars=bytes_=2
    for row in rows:
        if not row['qualified']:continue
        c=next(c for c in config['memory_index'] if c['case_digest']==row['case_digest'])
        # Exact JSON array lengths, including commas and outer brackets.
        fullchars=chars+c['chars']+(1 if accepted else 0);fullbytes=bytes_+c['bytes']+(1 if accepted else 0)
        ok=len(accepted)<RULE['max_entries'] and c['chars']<=RULE['item_max_chars'] and c['bytes']<=RULE['item_max_utf8_bytes'] and fullchars<=RULE['max_chars'] and fullbytes<=RULE['max_utf8_bytes']
        sizes.append({'public_digest':c['public_digest'],'chars':c['chars'],'utf8_bytes':c['bytes'],'accepted':ok})
        if ok:accepted.append(c['public_digest']);chars=fullchars;bytes_=fullbytes
    T.require([digest(e) for e in entries]==accepted,'pilot_saved_hit_or_budget_changed')
    old_version='packaging_memory_view_v1' if config['memory_mode']=='T' else 'packaging_contrast_view_v1'
    text=canonical(entries)
    v=T.sealed({'version':old_version,'mode':config['memory_mode'],'snapshot_digest':config['memory_snapshot_digest'],'query_digest':digest(q),
               'entries':entries,'reason':'HIT' if entries else 'NO_QUALIFIED_COMPLETE_ENTRY','injected_chars':len(text),'injected_utf8_bytes':len(text.encode())},'view_digest')
    return {'query':q,'query_digest':digest(q),'rule':RULE,'snapshot_digest':config['memory_snapshot_digest'],
            'exclusions':{'source_groups':config['excluded_source_groups'],'fork_digests':config['excluded_fork_digests']},
            'candidates':rows,'length_handling':sizes,'view':v,'library_nonempty':bool(config['memory_index']),
            'retrieval_nonempty':bool(sizes),'injection_nonempty':bool(entries)}


def receipt(q,config,view,raw):
    return T.sealed({'version':'jev_pilot_retrieval_v1','mode':config['memory_mode'],'snapshot_digest':config['memory_snapshot_digest'],
        'query':q,'query_digest':digest(q),'view_digest':view.data['view_digest'],'raw_retrieval':raw,
        'status':'EMPTY_POOL' if q is None else 'NO_MEMORY_ASSIGNED' if config['memory_mode']=='none' else 'HIT' if view.data['entries'] else 'NO_COMPLETE_ISOLATED_HIT'},'receipt_digest')


def validate_receipt(saved,view,config,state,criteria):
    validate_schema('pilot_retrieval_v1',saved);T.verify_seal(saved,'receipt_digest');v=validate_view(view,config)
    public=copy.deepcopy(state);public['memories']=[];q=query(public,criteria)
    T.require(saved['query']==q and saved['query_digest']==digest(q),'pilot_saved_query_changed')
    raw=None
    if config['memory_mode']!='none' and q is not None:
        raw=expected_trace(q,config,v['entries'])
    else:T.require(not v['entries'],'pilot_empty_route_nonempty')
    expected_view=view_from_entries(config['memory_mode'],config['memory_snapshot_digest'],None if q is None else digest(q),v['entries'],
             'EMPTY_POOL' if q is None else 'NO_MEMORY_ASSIGNED' if config['memory_mode']=='none' else raw['view']['reason'])
    T.require(view.data==expected_view.data and saved==receipt(q,config,view,raw),'pilot_saved_retrieval_changed')
    return saved


class MemoryDriver:
    """Immutable snapshot dependency plus private source exclusion, no current task."""
    def __init__(self,config,*,snapshot=None):
        self.config=copy.deepcopy(config);self.mode=config['memory_mode']
        if self.mode=='none':T.require(snapshot is None,'pilot_none_snapshot_forbidden');self.snapshot=None
        else:
            value=T.validate_snapshot(snapshot,config['memory_snapshot_digest']) if self.mode=='T' else E.validate_snapshot(snapshot,config['memory_snapshot_digest'])
            self.snapshot=Snapshot.from_dict(value)
        T.require(index(self.snapshot,self.mode)==config['memory_index'],'pilot_memory_index_changed')
        self.calls=0

    def resolve(self,public_state,public_criteria):
        q=query(public_state,public_criteria);raw=None;entries=[]
        reason='EMPTY_POOL' if q is None else 'NO_MEMORY_ASSIGNED'
        if q is not None and self.mode!='none':
            retriever=T if self.mode=='T' else E
            old,raw=retriever.retrieve(q,self.snapshot,excluded_source_groups=self.config['excluded_source_groups'],excluded_fork_digests=self.config['excluded_fork_digests'])
            entries=old.data['entries'];reason=old.data['reason']
        self.calls+=1
        v=view_from_entries(self.mode,self.config['memory_snapshot_digest'],None if q is None else digest(q),entries,reason)
        saved=receipt(q,self.config,v,raw);validate_receipt(saved,v,self.config,public_state,public_criteria)
        return v,saved
