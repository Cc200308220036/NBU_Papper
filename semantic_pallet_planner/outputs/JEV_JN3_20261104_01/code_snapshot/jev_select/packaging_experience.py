"""JN3-A evidence-backed trajectory memory. No credentials, LLM or episode dispatch.

Evidence loading is private. Retrieval accepts a closed public feature vector;
only MemoryView crosses the context boundary. Legacy business cards are excluded.
"""
from __future__ import annotations
import copy
import hashlib
import math
from datetime import datetime, timezone
from pathlib import Path
from .contracts import Snapshot, JevSelectError, canonical, digest, validate_schema
from .ledger import read

VERSION = 'jev_packaging_memory_v7'
METHOD = 'jev_with_trajectory'
SCHEMA = 'packaging_trajectory_v1'
RULE = {'version':'packaging_public_distance_v1',
        'features':['buffer_fill','placed_fill','mean_length','mean_width','mean_height','mean_mass','mean_capacity','stackable_fraction','candidate_height'],
        'scales':'container dimensions, payload; capacity uses max(payload,1); placed volume/container volume',
        'distance':'mean absolute normalized feature distance; score=1/(1+distance)',
        'minimum_score':0.5,'tie':'ascending public fragment digest','max_entries':1,
        'max_chars':12000,'max_utf8_bytes':16000,'item_max_chars':12000,'item_max_utf8_bytes':16000,
        'truncation':'whole entries only; never remove conditions, costs or limitations',
        'historical_result_budget':{'max_comparisons_per_entry':1,'metrics':['placed_items','placed_volume_ratio','placed_mass_kg','actual_height_mm','envelope_utilization'],
                                    'interpretation':'same observed outcome fields for future T/E; equal bytes do not establish fairness'}}
LIMITATIONS = ['POST_HOC_USER_REVISED_OBJECTIVE',
 'two previously exposed training sources; no unseen-source validation',
 'fixed local_geometry_test_double continuation; finite intervention, no causal or global optimum claim',
 'synthetic packaging load parameters; feasibility UNKNOWN',
 'historical observation only, not a recommendation or an action for the current task',
 'not a universal cross-box or rank rule; external memory is not weight updating']

class MemoryView(Snapshot):
    pass

class MemorySnapshotReceipt(Snapshot):
    pass


def require(ok, code):
    if not ok: raise JevSelectError(code)


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sealed(value, key):
    value=copy.deepcopy(value);value[key]=digest(value);return value


def verify_seal(value,key):
    require(value.get(key)==digest({k:v for k,v in value.items() if k!=key}), 'memory_digest_changed')


def evidence_reference(repo,path,pointer):
    p=Path(repo)/path; value=read(p)
    for key in pointer.strip('/').split('/') if pointer else []:
        value=value[int(key)] if isinstance(value,list) else value[key]
    return {'path':str(path),'file_sha256':sha(p),'json_pointer':pointer,'value_digest':digest(value)}


def validate_evidence(repo,ref):
    validate_schema('packaging_evidence_v1',ref)
    root=Path(repo).resolve();p=(root/ref['path']).resolve()
    require(p.is_relative_to(root),'memory_evidence_path')
    require(evidence_reference(root,ref['path'],ref['json_pointer'])==ref,'memory_evidence_changed')


def attributes(obj):
    return {k:copy.deepcopy(obj[k]) for k in ('dimensions_mm','mass_kg','stackable','top_load_limit_kg_synthetic')}


def historical_fragment(row):
    """Whitelisted projection, with case-local roles and normalized historical geometry."""
    o=row['observable_conditions'];c=o['container'];axes=[c['length_mm'],c['width_mm'],c['max_height_mm']]
    def action(a):
        return {'box':attributes(a['item_attributes']),
                'size_over_container':[x/y for x,y in zip(a['oriented_size_mm'],axes)],
                'historical_center_over_container':[a['pose'][k]/v for k,v in zip(('x_mm','y_mm','z_base_mm'),axes)],
                'yaw_deg':a['pose']['yaw_deg']}
    fragment={'kind':'T','notice':LIMITATIONS[4],
              'condition':{'container':c,'buffer_capacity':o['buffer_capacity'],
                           'observed_buffer':[{'role':f'history_box_{i}',**attributes(b)} for i,b in enumerate(o['buffer'],1)],
                           'placed_count':len(o['placed'])},
              'historical_interventions':{'original':action(o['reference_action']),'alternative':action(o['alternative_action']),
                                           'relationship':'same box different position' if o['reference_action']['item_attributes']==o['alternative_action']['item_attributes'] else 'different boxes'},
              'geometry_convention':'historical center x/L,y/W and base z/H; normalized historical descriptions are not current hard actions',
              'fixed_followup':'local_geometry_test_double',
              'historical_result':{'reference':{k:row['facts_reference'][k] for k in RULE['historical_result_budget']['metrics']},
                                   'alternative':{k:row['facts_alternative'][k] for k in RULE['historical_result_budget']['metrics']},
                                   'delta':{k:row['facts_delta'][k] for k in RULE['historical_result_budget']['metrics']}},
              'evaluation_rule':'jev_branch_comparison_rule_v2','limitations':LIMITATIONS}
    require(not o['placed'],'memory_nonempty_history_projection_not_supported')
    return fragment


def query_from_facts(container, boxes, placed_volume, capacity, candidate_heights):
    require(boxes and capacity>0 and candidate_heights,'memory_query_empty')
    vals=[len(boxes)/capacity,placed_volume/(container['length_mm']*container['width_mm']*container['max_height_mm'])]
    n=len(boxes)
    vals += [sum(b['dimensions_mm'][k] for b in boxes)/n/container[axis] for k,axis in
             [('length','length_mm'),('width','width_mm'),('height','max_height_mm')]]
    vals += [sum(b['mass_kg'] for b in boxes)/n/max(container['max_payload_kg'],1),
             sum(b.get('effective_top_permission_kg',b.get('top_load_limit_kg_synthetic',0) if b['stackable'] else 0) for b in boxes)/n/max(container['max_payload_kg'],1),
             sum(b['stackable'] for b in boxes)/n,sum(candidate_heights)/len(candidate_heights)/container['max_height_mm']]
    q={'version':'packaging_public_query_v1','features':dict(zip(RULE['features'],vals))}
    validate_query(q);return q


def public_query(context):
    """Only an already restricted public model state and public criteria are read."""
    s=context.data['model_state'];cs=context.data['criteria']
    return query_from_facts(s['container'],s['available_objects'],
         sum(math.prod(o['oriented_size_mm']) for o in s['placed_objects']),s['buffer']['capacity'],
         [c['features']['resulting_max_height_mm'] for c in cs.values()])


def validate_query(q):
    validate_schema('packaging_memory_query_v1',q)
    require(all(type(x) in (int,float) and math.isfinite(x) and x>=0 for x in q['features'].values()),'memory_query_number')


def build_snapshot(repo,parent,*,frozen_at=None):
    root=Path(repo);parent=Path(parent)
    from .packaging_comparisons import checked_manifest
    binding=checked_manifest(parent)
    receipt=read(parent/'comparison_dataset_receipt_v2.json');review=read(parent/'experience_candidate_review.json')
    require(receipt['JN3_A_input_ready'] and receipt['experience_input_status']=='READY_IN_DECLARED_SCOPE','memory_parent_not_ready')
    require(receipt['review_digest']==digest(review),'memory_review_binding')
    require(receipt['approved_input_ids']==['F00_B02','F02_B02'],'memory_input_scope_changed')
    cases=[]
    for approved in review['records']:
        if not approved['approved']:continue
        cid=approved['comparison_id'];require(cid in receipt['approved_input_ids'],'memory_unapproved_input')
        record_path=(parent/'comparisons_v2'/f'{cid}.json').relative_to(root)
        r=read(root/record_path)
        verify_seal(r,'record_digest')
        require(digest(r)==approved['record_digest'] and all(approved['checks'].values()),'memory_review_changed')
        require(r['label_v1']=='trade_off' and r['evaluation']['label_v2']=='improved','memory_label_changed')
        facts=approved['facts']
        require(facts['observable_conditions']==r['observable_conditions'],'memory_observation_changed')
        for name,loc in r['provenance']['receipts'].items():
            rec=read(root/loc['path']);require(digest(rec)==loc['digest'],'memory_branch_binding')
            verify_seal(rec,'record_digest')
        data={'observable_conditions':r['observable_conditions'],**{'facts_'+k:facts[k] for k in ('reference','alternative','delta')}}
        fragment=historical_fragment(data);o=r['observable_conditions']
        query=query_from_facts(o['container'],o['buffer'],0,o['buffer_capacity'],
                              [a['oriented_size_mm'][2]+a['pose']['z_base_mm'] for a in (o['reference_action'],o['alternative_action'])])
        # Every leaf fact is separately addressable; full raw historical originals remain private.
        refs={}
        def leaves(value,prefix):
            if isinstance(value,dict):
                for k,v in value.items():yield from leaves(v,prefix+'/'+k)
            elif isinstance(value,list):
                for i,v in enumerate(value):yield from leaves(v,prefix+'/'+str(i))
            else:yield prefix
        review_path=(parent/'experience_candidate_review.json').relative_to(root)
        idx=review['records'].index(approved)
        for pointer in leaves(facts,'/records/'+str(idx)+'/facts'):
            refs[pointer]=evidence_reference(root,review_path,pointer)
        case=sealed({'version':SCHEMA,'kind':'T','review_status':'APPROVED','fixture_only':False,
           'public_fragment':fragment,'public_digest':digest(fragment),'retrieval_query':query,
           'provenance':{'comparison_id':cid,'source_group':r['source_group'],**r['provenance']},
           'private_original':facts,'evidence':refs},'case_digest')
        cases.append(case)
    require(len(cases)==2,'memory_case_count')
    result=sealed({'version':'packaging_memory_snapshot_v1','mode':'T','case_schema':SCHEMA,
        'build_version':'packaging_programmatic_builder_v1','build_method':'deterministic evidence projection; no LLM',
        'generation_model':None,'generation_cost_usd':0,'review_status':'APPROVED',
        'source_groups':sorted({c['provenance']['source_group'] for c in cases}),
        'parent':binding,'retrieval_rule':RULE,'frozen_at':frozen_at or datetime.now(timezone.utc).isoformat(),
        'cases':cases,'limitations':LIMITATIONS},'snapshot_digest')
    validate_snapshot(result);return MemorySnapshotReceipt.from_dict(result)


def validate_snapshot(s,expected=None):
    if isinstance(s,Snapshot):s=s.data
    validate_schema('packaging_memory_snapshot_v1',s);verify_seal(s,'snapshot_digest')
    require(expected is None or expected==s['snapshot_digest'],'memory_snapshot_changed')
    require(s['mode']=='T','memory_E_execution_not_supported')
    require(s['retrieval_rule']==RULE and s['review_status']=='APPROVED','memory_rule_or_review_changed')
    for c in s['cases']:
        validate_schema('packaging_trajectory_v1',c);verify_seal(c,'case_digest')
        require(c['review_status']=='APPROVED' and c['kind']=='T','memory_unapproved_entry')
        validate_schema('packaging_public_fragment_v1',c['public_fragment'])
        require(c['public_digest']==digest(c['public_fragment']),'memory_public_changed')
        # Reconstruct the public whitelist from preserved private facts.
        p=c['private_original'];require(c['public_fragment']==historical_fragment({'observable_conditions':p['observable_conditions'],**{'facts_'+k:p[k] for k in ('reference','alternative','delta')}}),'memory_projection_changed')
        validate_query(c['retrieval_query'])
        o=p['observable_conditions']
        expected_query=query_from_facts(o['container'],o['buffer'],0,o['buffer_capacity'],
            [a['oriented_size_mm'][2]+a['pose']['z_base_mm'] for a in (o['reference_action'],o['alternative_action'])])
        require(c['retrieval_query']==expected_query,'memory_index_features_changed')
    require(s['source_groups']==sorted({c['provenance']['source_group'] for c in s['cases']}),'memory_source_groups_changed')
    return s


def empty_view(snapshot_digest,query_digest=None):
    return MemoryView.from_dict(sealed({'version':'packaging_memory_view_v1','mode':'T','snapshot_digest':snapshot_digest,
        'query_digest':query_digest,'entries':[],'reason':'EMPTY','injected_chars':2,'injected_utf8_bytes':2},'view_digest'))


def validate_view(view,expected=None):
    require(isinstance(view,MemoryView),'memory_explicit_view_required')
    v=view.data;validate_schema('packaging_memory_view_v1',v);verify_seal(v,'view_digest')
    require(v['mode']=='T','memory_E_execution_not_supported')
    require(expected is None or expected==v['snapshot_digest'],'memory_snapshot_changed')
    for entry in v['entries']:validate_schema('packaging_public_fragment_v1',entry)
    rendered=canonical(v['entries'])
    require(len(rendered)==v['injected_chars'] and len(rendered.encode())==v['injected_utf8_bytes'],'memory_length_changed')
    require(len(v['entries'])<=RULE['max_entries'] and len(rendered)<=RULE['max_chars'] and len(rendered.encode())<=RULE['max_utf8_bytes'],'memory_budget_exceeded')
    return v


def retrieve(query,snapshot,*,excluded_source_groups=(),excluded_fork_digests=(),rule=None):
    validate_query(query);s=validate_snapshot(snapshot)
    rule=RULE if rule is None else rule
    require(rule==RULE,'memory_unregistered_retrieval_rule')
    rows=[]
    for c in s['cases']:
        excluded=c['provenance']['source_group'] in excluded_source_groups or c['provenance']['fork_digest'] in excluded_fork_digests
        distance=sum(abs(query['features'][k]-c['retrieval_query']['features'][k]) for k in RULE['features'])/len(RULE['features'])
        rows.append({'public_digest':c['public_digest'],'case_digest':c['case_digest'],'score':1/(1+distance),
                     'excluded':excluded,'qualified':not excluded and 1/(1+distance)>=rule['minimum_score']})
    rows.sort(key=lambda r:(-r['score'],r['public_digest']))
    entries=[];lengths=[]
    for r in rows:
        if not r['qualified']:continue
        c=next(c for c in s['cases'] if c['case_digest']==r['case_digest']);entry=c['public_fragment']
        text=canonical(entry);full=canonical(entries+[entry])
        accept=(len(entries)<rule['max_entries'] and len(text)<=rule['item_max_chars'] and len(text.encode())<=rule['item_max_utf8_bytes'] and len(full)<=rule['max_chars'] and len(full.encode())<=rule['max_utf8_bytes'])
        lengths.append({'public_digest':r['public_digest'],'chars':len(text),'utf8_bytes':len(text.encode()),'accepted':accept})
        if accept:entries.append(entry)
    rendered=canonical(entries)
    v=sealed({'version':'packaging_memory_view_v1','mode':'T','snapshot_digest':s['snapshot_digest'],
       'query_digest':digest(query),'entries':entries,'reason':'HIT' if entries else 'NO_QUALIFIED_COMPLETE_ENTRY',
       'injected_chars':len(rendered),'injected_utf8_bytes':len(rendered.encode())},'view_digest')
    view=MemoryView.from_dict(v);validate_view(view)
    return view,{'query':query,'query_digest':digest(query),'rule':rule,'snapshot_digest':s['snapshot_digest'],
       'exclusions':{'source_groups':list(excluded_source_groups),'fork_digests':list(excluded_fork_digests)},
       'candidates':rows,'length_handling':lengths,'view':v,'library_nonempty':bool(s['cases']),
       'retrieval_nonempty':bool(lengths),'injection_nonempty':bool(entries)}
