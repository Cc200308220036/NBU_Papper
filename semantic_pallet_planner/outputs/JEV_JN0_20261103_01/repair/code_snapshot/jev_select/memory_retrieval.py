"""Frozen, shared R0/M0 BM25. Pure offline functions, no runtime integration."""
from __future__ import annotations

from collections import Counter
import math
from .contracts import JevSelectError, canonical, digest, validate_schema
from .memory_query import TOKENIZER_VERSION, tokenize, validate_query, evaluate_gates, validate_gates

RETRIEVAL_VERSION = 'bm25_public_query_v1'
INDEX_VERSION = 'jev_memory_index_v1'
DEFAULT_LIMITS = {'top_k':3, 'item_max_utf8_bytes':1600, 'total_max_utf8_bytes':4800}
INDEX_CONFIG = {'version':RETRIEVAL_VERSION, 'tokenizer_version':TOKENIZER_VERSION,
                'k1':1.2, 'b':0.75, 'idf':'log1p((n-df+0.5)/(df+0.5))',
                'query_tf':'binary', 'tie_break':'content_digest_ascending', **DEFAULT_LIMITS}


def card_text(card):
    if card['version'] not in ('jev_memory_card_v1','jev_memory_card_v2','jev_memory_card_v3','jev_memory_card_v4'):
        raise JevSelectError('unknown_memory_render_version')
    if card['version'] in ('jev_memory_card_v3','jev_memory_card_v4') and card['render_version'] != 'memory_prose_v2':
        raise JevSelectError('unknown_memory_render_version')
    return '\n'.join(f'{key}: {card[key]}' for key in
        ('applicability','advice','observed_evidence','limitations_counterexamples'))


def documents(value, mode):
    rows=[]
    for item in value['raw_history'] if mode == 'raw_history' else value['cards']:
        if mode == 'cards' and item['status'] != 'active': continue
        text = item['text'] if mode == 'raw_history' else card_text(item)
        gates = item.get('gates', [])
        validate_gates(gates)
        sources = ([{k:item[k] for k in ('source_group_id','episode_id','decision_id','export_digest')}]
                   if mode == 'raw_history' else item['evidence_refs'])
        rows.append({'document_id':item['history_id'] if mode == 'raw_history' else item['card_id'],
            'content_digest':digest(text), 'text':text, 'gates':gates,
            'source':sources, 'utf8_bytes':len(text.encode('utf-8'))})
    return sorted(rows, key=lambda r:(r['content_digest'],r['document_id']))


def build_index(value):
    """Build before freeze. Statistics include all documents, before query gates."""
    modes={}
    for mode in ('raw_history','cards'):
        docs=documents(value, mode); df=Counter(); entries=[]
        for d in docs:
            tf=Counter(tokenize(d['text'])); df.update(tf.keys())
            entries.append({**d,'term_counts':dict(sorted(tf.items())), 'length':sum(tf.values())})
        modes[mode]={'documents':entries,'document_frequency':dict(sorted(df.items())),
                     'document_count':len(entries), 'total_length':sum(d['length'] for d in entries)}
    result = {'version':INDEX_VERSION, 'config':INDEX_CONFIG, 'config_digest':digest(INDEX_CONFIG),
              'corpus_digest':value['corpus_digest'], 'modes':modes}
    history_version = value.get('history_preflight',{}).get('version','decision_event_self_contained_v1')
    if history_version == 'decision_event_columnar_v2' or any(c['version'] in ('jev_memory_card_v3','jev_memory_card_v4') for c in value['cards']):
        result.update(version='jev_memory_index_v2',render_contracts=sorted({
            history_version,*('memory_prose_v2' if c['version'] in ('jev_memory_card_v3','jev_memory_card_v4') else 'memory_prose_v1' for c in value['cards'])}))
    return result


def retrieve(query, snapshot, mode, limits=None):
    """Return local audit, with only `memories` intended for future model injection."""
    from .memory_store import validate_snapshot
    validate_query(query)
    value=validate_snapshot(snapshot)
    if mode not in ('none','raw_history','cards'): raise JevSelectError('invalid_memory_mode')
    limits=DEFAULT_LIMITS.copy() if limits is None else dict(limits)
    if set(limits)!=set(DEFAULT_LIMITS) or any(type(v) is not int or v<0 or v>DEFAULT_LIMITS[k] for k,v in limits.items()) or limits['total_max_utf8_bytes']<2:
        raise JevSelectError('invalid_memory_limits')
    index=value.get('index')
    if index is None:
        # B0 only: empty text has no searchable index; never build a nonempty index at retrieval.
        if value['raw_history'] or value['cards']: raise JevSelectError('memory_index_required')
        index=build_index(value)
    data=mode_index(index,mode)
    ranked=[]; exclusions=[]; gates=[]
    for d in data['documents']:
        status, basis=evaluate_gates(d['gates'],query['facts'])
        identity={k:d[k] for k in ('document_id','content_digest','source','utf8_bytes')}
        gates.append({**identity,'status':status,'basis':basis})
        if status!='APPLICABLE':
            exclusions.append({**identity,'reason':status});continue
        score=bm25_score(query['tokens'],d,data)
        if score>0: ranked.append({**identity,'score':score,'text':d['text']})
        else: exclusions.append({**identity,'reason':'NO_MATCH'})
    ranked.sort(key=lambda r:(-r['score'],r['content_digest'],r['document_id']))
    memories=[]; selected=[]
    for rank,row in enumerate(ranked,1):
        row['rank']=rank
        if row['utf8_bytes']>limits['item_max_utf8_bytes']: reason='ITEM_TOO_LARGE'
        elif len(selected)>=limits['top_k']: reason='TOP_K_LIMIT'
        elif len(canonical(memories+[row['text']]).encode('utf-8'))>limits['total_max_utf8_bytes']: reason='TOTAL_BUDGET'
        else:
            memories.append(row['text']);selected.append(row);continue
        exclusions.append({**{k:row[k] for k in ('document_id','content_digest','source','utf8_bytes')},'reason':reason})
    result={'version':'jev_memory_retrieval_v1', 'retrieval_version':RETRIEVAL_VERSION,
        'query':query, 'query_digest':query['query_digest'], 'snapshot_digest':digest(value),
        'corpus_digest':value['corpus_digest'], 'index_digest':digest(index),
        'config_digest':index['config_digest'], 'mode_index_digest':digest(data), 'mode':mode, 'limits':limits,
        'gates':gates, 'ranking':ranked, 'exclusions':exclusions, 'selected':selected,
        'memories':memories,'injected_text_digest':digest(memories),
        'utf8_bytes':len(canonical(memories).encode('utf-8')),
        'status':'HIT' if selected else 'NO_MATCH',
        'source_groups':sorted({s['source_group_id'] for r in selected for s in r['source']})}
    result['retrieval_digest']=digest(result)
    validate_schema('memory_retrieval',result)
    return result


def preflight_memory(store, output):
    """Offline training coverage audit and migratable freeze, no data collection."""
    from pathlib import Path
    from .ledger import read, write
    from .memory_store import indexed_snapshot, freeze_snapshot, load_snapshot
    from .memory_query import build_query
    from .experiment import _new_output
    exports=[read(p) for p in sorted((Path(store)/'exports').glob('*.json'))]
    if not exports: raise JevSelectError('no_training_exports')
    snapshot=indexed_snapshot(exports)
    out=_new_output(output)
    out.mkdir(parents=True)
    freeze_snapshot(snapshot,out/'snapshot',evidence_exports=exports)
    loaded=load_snapshot(out/'snapshot',digest(snapshot.data))
    audits=[]
    for export in sorted(exports,key=digest):
        for event in export['events']:
            state=event['public_state']
            q=build_query(state,{'english_descriptions':state['business_requirements']['english_descriptions']},event['candidate_facts'])
            for mode in ('raw_history','cards'):
                first=retrieve(q,loaded,mode)
                if first != retrieve(q,loaded,mode): raise JevSelectError('nondeterministic_memory_retrieval')
                audits.append({'episode_id':export['episode_id'],'decision_id':event['decision_id'],**first})
    write(out/'retrieval_audit.json',audits)
    coverage={}
    for mode in ('raw_history','cards'):
        records=[a for a in audits if a['mode']==mode]
        source_counts=Counter(s['source_group_id'] for a in records for r in a['selected'] for s in r['source'])
        document_counts=Counter(r['content_digest'] for a in records for r in a['selected'])
        selected_count=sum(document_counts.values())
        coverage[mode]={'queries':len(records),'hit_queries':sum(a['status']=='HIT' for a in records),
            'selected_items':selected_count,'injected_canonical_utf8_bytes':sum(a['utf8_bytes'] for a in records),
            'source_selection_counts':dict(sorted(source_counts.items())),
            'document_selection_counts':dict(sorted(document_counts.items())),
            'maximum_document_share':max(document_counts.values())/selected_count if selected_count else None,
            'exclusion_reasons':dict(sorted(Counter(e['reason'] for a in records for e in a['exclusions']).items())),
            'applicability_status_counts':dict(sorted(Counter(g['status'] for a in records for g in a['gates']).items())),
            'service_usage_tokens':None}
    report={'status':'PASS','scope':'B1-A_OFFLINE_ONLY','coverage':coverage,
        'preflight':snapshot.data['history_preflight'],'snapshot_digest':digest(loaded.data),
        'index_digest':loaded.data['index_digest'],'retrieval_config':INDEX_CONFIG,
        'queries':len(audits)//2,'mode_queries':len(audits),'hit_queries':sum(a['status']=='HIT' for a in audits),
        'selected_items':sum(len(a['memories']) for a in audits),
        'source_coverage':sorted({s for a in audits for s in a['source_groups']}),
        'repeat_identical':True,'model_api_calls':0,'generation_status':'NOT_RUN',
        'benefit_status':'NOT_ESTABLISHED', 'runtime_integration':'NOT_RUN'}
    write(out/'preflight_report.json',report)
    return report


def snapshot_index(snapshot):
    value=snapshot.data
    return value.get('index') or build_index(value)


def mode_index(index, mode):
    return {'documents':[], 'document_frequency':{}, 'document_count':0, 'total_length':0} if mode=='none' else index['modes'][mode]


def validate_saved_retrieval(saved, query=None, snapshot=None, mode=None, limits=None):
    """Verify a durable result without querying/ranking/selecting again.

    The ledger binds this result's digest before sending. Validate public query,
    frozen document identities, literal texts, scores and budget at every reuse.
    """
    validate_schema('memory_retrieval',saved)
    validate_query(saved['query'])
    if saved['retrieval_digest']!=digest({k:v for k,v in saved.items() if k!='retrieval_digest'}):
        raise JevSelectError('saved_retrieval_changed')
    if saved['query_digest']!=saved['query']['query_digest'] or (query is not None and query!=saved['query']):
        raise JevSelectError('saved_query_changed')
    if mode is not None and mode!=saved['mode'] or limits is not None and limits!=saved['limits']:
        raise JevSelectError('saved_retrieval_config_changed')
    texts=[r['text'] for r in saved['selected']]
    if texts!=saved['memories'] or digest(texts)!=saved['injected_text_digest'] or len(canonical(texts).encode())!=saved['utf8_bytes']:
        raise JevSelectError('saved_injected_text_changed')
    lim=saved['limits']
    if len(texts)>lim['top_k'] or any(len(t.encode())>lim['item_max_utf8_bytes'] for t in texts) or saved['utf8_bytes']>lim['total_max_utf8_bytes']:
        raise JevSelectError('saved_memory_budget_changed')
    if saved['ranking']!=sorted(saved['ranking'],key=lambda r:(-r['score'],r['content_digest'],r['document_id'])):
        raise JevSelectError('saved_ranking_changed')
    if any(r not in saved['ranking'] for r in saved['selected']): raise JevSelectError('saved_selection_changed')
    if snapshot is not None:
        from .memory_store import validate_snapshot
        value=validate_snapshot(snapshot);index=snapshot_index(snapshot);data=mode_index(index,saved['mode'])
        expected={'snapshot_digest':digest(value),'corpus_digest':value['corpus_digest'],
                  'index_digest':digest(index),'mode_index_digest':digest(data),'config_digest':index['config_digest']}
        if any(saved[k]!=v for k,v in expected.items()):raise JevSelectError('saved_memory_identity_changed')
        docs={d['document_id']:d for d in data['documents']}
        expected_gates=[]
        for d in data['documents']:
            status,basis=evaluate_gates(d['gates'],saved['query']['facts'])
            expected_gates.append({**{k:d[k] for k in ('document_id','content_digest','source','utf8_bytes')},'status':status,'basis':basis})
        if saved['gates']!=expected_gates:raise JevSelectError('saved_gates_changed')
        for r in saved['ranking']:
            d=docs.get(r['document_id'])
            if not d or any(r[k]!=d[k] for k in ('text','content_digest','source','utf8_bytes')) or r['score']!=bm25_score(saved['query']['tokens'],d,data):
                raise JevSelectError('saved_document_changed')
    return saved


def bm25_score(tokens, document, data):
    n=data['document_count'];avg=data['total_length']/n if n else 0
    score=0.0
    for term in tokens:
        tf=document['term_counts'].get(term,0)
        if tf:
            df=data['document_frequency'][term]
            score+=math.log1p((n-df+0.5)/(df+0.5))*tf*2.2/(tf+1.2*(.25+.75*document['length']/avg))
    return score


def memory_statistics(events):
    """Actual saved decisions, including stopped/failed jobs; not policy benefit."""
    groups={}
    for mode in ('none','raw_history','cards'):
        rows=[e['context']['retrieval'] for e in events if e.get('context',{} ) and 'retrieval' in e['context'] and e['context']['retrieval']['mode']==mode]
        docs=Counter(r['content_digest'] for a in rows for r in a['selected'])
        sources=Counter(s['source_group_id'] for a in rows for r in a['selected'] for s in r['source'])
        count=sum(docs.values())
        groups[mode]={'decisions':len(rows),'hit_decisions':sum(bool(a['memories']) for a in rows),
            'injected_items':count,'body_utf8_bytes':sum(r['utf8_bytes'] for a in rows for r in a['selected']),
            'canonical_utf8_bytes':sum(a['utf8_bytes'] for a in rows),
            'gate_status_counts':dict(sorted(Counter(g['status'] for a in rows for g in a['gates']).items())),
            'exclusion_reason_counts':dict(sorted(Counter(e['reason'] for a in rows for e in a['exclusions']).items())),
            'top3_source_counts':dict(sorted(sources.items())),'covered_source_groups':len(sources),
            'document_counts':dict(sorted(docs.items())), 'maximum_document_share':max(docs.values())/count if count else None,
            'service_usage_tokens':None}
    return groups
