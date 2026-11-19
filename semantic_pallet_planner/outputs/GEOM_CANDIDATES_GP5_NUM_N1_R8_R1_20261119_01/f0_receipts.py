"""Read-only v17 F0 receipts for every public route; no request construction."""
import hashlib,json
from collections import Counter
from pathlib import Path
ROUTES=('CHOICE_REQUIRED','SINGLETON_BYPASS','STOP_NO_PHYSICAL_CANDIDATE')
REQUEST_CONTRACTS={
    'CHOICE_REQUIRED':{'request_body':'OBJECT','request_fields':['model','questions','state'],'question_fields':['criteria','instructions','type'],'option_count':'AT_LEAST_TWO'},
    'SINGLETON_BYPASS':{'request_body':'NULL','request_fields':None,'question_fields':None,'option_count':'ONE'},
    'STOP_NO_PHYSICAL_CANDIDATE':{'request_body':'NULL','request_fields':None,'question_fields':None,'option_count':'ZERO'},
}

def f0_receipt(episode,config):
    from semantic_pallet_planner.jev_select.contracts import DecisionContext,digest
    from semantic_pallet_planner.jev_select.packaging_runtime import validate_runtime_context
    from semantic_pallet_planner.jev_select.geometry_runtime_contracts import same_native
    assert config['version']=='jev_packaging_geometry_order_v17' and config['feature_profile']=='F0_existing_facts'
    path=Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select/schemas/decision_context_v17.schema.json')
    schema=json.loads(path.read_bytes());item=schema['properties']['criteria']['patternProperties']['^C[0-9]{2}$']
    common={'runtime':config['version'],'context_version':'jev_decision_context_v17','feature_profile':config['feature_profile'],'model_state_fields':sorted(schema['properties']['model_state']['required']),'criteria_fields':sorted(item['required']),'feature_fields':sorted(item['properties']['features']['required']),'pose_fields':sorted(item['properties']['pose']['required']),'schema_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    rows=[]
    for index,event in enumerate(episode['events']):
        if event.get('context') is None:continue # Receive/EOS events have no decision.
        ctx=event['context'];route=ctx['route'];criteria=ctx['criteria'];req=ctx['request_body']
        assert ctx['version']==common['context_version'] and route in ROUTES,'F0_PROTOCOL_OR_ROUTE'
        # Original production validator verifies closed Schema, all stored public
        # digests, display labels, route/cardinality, request state/criteria/model.
        # No bundle reconstruction, provider, public-fact projection or physics.
        validate_runtime_context(DecisionContext.from_dict(ctx),config=config)
        assert sorted(ctx['model_state'])==common['model_state_fields']
        for option in criteria.values():
            assert sorted(option)==common['criteria_fields'] and sorted(option['features'])==common['feature_fields'] and sorted(option['pose'])==common['pose_fields'],'F0_PUBLIC_FIELDS'
        if route=='CHOICE_REQUIRED':
            assert type(req) is dict and len(criteria)>=2
            assert sorted(req)==REQUEST_CONTRACTS[route]['request_fields']
            assert sorted(req['questions'])==['next_action']
            question=req['questions']['next_action']
            assert sorted(question)==REQUEST_CONTRACTS[route]['question_fields']
            assert same_native(req['state'],ctx['model_state']) and same_native(question['criteria'],criteria),'F0_REQUEST_PUBLIC_BINDING'
            request_fields=sorted(req);question_fields=sorted(question)
        else:
            assert req is None and len(criteria)==(1 if route=='SINGLETON_BYPASS' else 0),'F0_NULL_ROUTE_CARDINALITY'
            request_fields=question_fields=None
        # If saved pool is present, verify option binding directly from stored
        # candidate metadata; do not regenerate candidates or rebuild requests.
        pool_check='NOT_AVAILABLE_CONTEXT_ONLY'
        if event.get('bundle') is not None:
            pool=event['bundle'];candidates=pool['selectable_candidates'];physical=pool['physical_candidates']
            assert same_native(candidates,physical),'F0_V17_PHYSICAL_SELECTABLE_POOL'
            assert len(candidates)==len(criteria),'F0_OPTION_POOL_CARDINALITY'
            by_id={c['candidate_id']:c for c in candidates};assert len(by_id)==len(candidates)
            mapped=[]
            for label,binding in ctx['display_mapping'].items():
                candidate=by_id[binding['candidate_id']];mapped.append(binding['candidate_id'])
                assert binding['pick_item_id']==candidate['pick_item_id'] and binding['candidate_digest']==digest(candidate),'F0_OPTION_CANDIDATE_BINDING'
                assert same_native(criteria[label]['pose'],candidate['pose']) and same_native(criteria[label]['oriented_size_mm'],candidate['oriented_size_mm']),'F0_OPTION_EXACT_ACTION'
            assert len(set(mapped))==len(candidates)
            pool_check='PASS_SAVED_POOL_MAPPING_DIGEST_EXACT_ACTION'
        rows.append({'event_index':index,'route':route,'candidate_count':len(criteria),'context_digest':digest(ctx),'public_state_digest':digest(ctx['model_state']),'criteria_digest':digest(criteria),'mapping_digest':digest(ctx['display_mapping']),'request_digest':digest(req),'request_body_is_null':req is None,'request_fields_applicable':route=='CHOICE_REQUIRED','request_fields':request_fields,'question_fields':question_fields,'shared_public_contract':common,'route_request_contract':REQUEST_CONTRACTS[route],'schema_and_public_route_binding':'PASS_ORIGINAL_VALIDATOR','saved_option_binding':pool_check})
    assert rows,'F0_NO_DECISION_CONTEXTS'
    return {'version':'geometry_num_n1_r6_f0_receipt_v1','backend':config['candidate_backend'],'method':config['selector'],'task_id':config['order_task_identity']['task_id'],'contract':common,'route_contracts':REQUEST_CONTRACTS,'route_counts':dict(Counter(r['route'] for r in rows)),'contexts':rows,'context_count':len(rows),'status':'PASS_SAVED_PUBLIC_FIELD_AND_ROUTE_CONTRACT','request_constructed':False,'contexts_dropped':0}

def compare_f0(receipts):
    pairs=[]
    for task in ('GP5_SYNTH_K02_INT',):
        for method in ('local_first_test_double',):
            rows=[r for r in receipts if r['task_id']==task and r['method']==method]
            assert len(rows)==2 and {r['backend'] for r in rows}=={'e2_original_v1','ems_surface_hybrid_v1'}
            assert rows[0]['contract']==rows[1]['contract'],'F0_PUBLIC_FIELD_CONTRACT_DISAGREEMENT'
            # Applicability is fixed per route, not determined by the other
            # backend's route presence or counts. Missing routes are not dropped.
            assert all(r['route_contracts']==REQUEST_CONTRACTS for r in rows),'F0_ROUTE_REQUEST_CONTRACT_DISAGREEMENT'
            for receipt in rows:
                for ctx in receipt['contexts']:
                    route=ctx['route'];assert ctx['shared_public_contract']==receipt['contract'] and ctx['route_request_contract']==REQUEST_CONTRACTS[route]
            pairs.append({'task_id':task,'method':method,'backends':[r['backend'] for r in rows],'shared_public_contract':rows[0]['contract'],'route_request_contracts':REQUEST_CONTRACTS,'backend_evidence':[{'backend':r['backend'],'route_counts':r['route_counts'],'contexts':r['contexts']} for r in rows],'status':'PASS_SAME_PROTOCOL_FIELD_CONTRACT','equal_route_counts_or_presence_required':False,'same_candidates_or_trajectory_required':False})
    return pairs
