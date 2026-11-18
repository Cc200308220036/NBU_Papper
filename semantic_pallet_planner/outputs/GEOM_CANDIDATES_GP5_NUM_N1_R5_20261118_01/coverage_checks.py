"""Coverage receipts; evaluated only inside the separately authorized fixed suite."""
import copy,hashlib,json,struct
from fractions import Fraction
from pathlib import Path

def conversion_case(tag,values,yaw):
    from semantic_pallet_planner.jev_select import geometry_native_shape_bridge as b
    from semantic_pallet_planner.jev_select.geometry_runtime_contracts import same_native
    from jsonschema import Draft202012Validator
    target=list(values) if yaw==0 else [values[1],values[0],values[2]]
    raw=[float(target[0]),float(target[1]),target[2]]
    metadata={'oriented_size_mm':raw,'pose':{'x_mm':-0.0,'y_mm':1,'z_base_mm':0.0,'yaw_deg':yaw},'item':'C_METADATA_ONLY'}
    before=copy.deepcopy(metadata)
    actual,axes=b.restore_size(raw,dict(zip(('length','width','height'),values)),yaw)
    metadata['oriented_size_mm']=actual
    assert same_native(before['pose'],metadata['pose']) and before['item']==metadata['item']
    assert same_native(actual,target) and same_native(b.unN(b.N(actual)),target)
    for i,(a,t,row) in enumerate(zip(raw,target,axes)):
        assert Fraction(a)==Fraction(t) and row['axis_index']==i and row['value_equal'] is True
        assert row['source_axis']==(('length','width','height') if yaw==0 else ('width','length','height'))[i]
        assert type(actual[i]) is type(t)
        if type(t) is float:assert struct.pack('>d',actual[i])==struct.pack('>d',t)
        for sig,value in ((row['raw_signature'],a),(row['target_signature'],t)):
            assert Fraction(int(sig['numerator']),int(sig['denominator']))==Fraction(value)
            assert same_native(sig,b.signature(value))
    schema_path=Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select/schemas/native_shape_proof_core.schema.json')
    schema=json.loads(schema_path.read_bytes())['properties']['axis_equalities'];validator=Draft202012Validator(schema)
    validator.validate(axes);closed=[]
    for name,path in [('axis',(0,)),('signature',(0,'raw_signature'))]:
        bad=copy.deepcopy(axes);node=bad
        for k in path:node=node[k]
        node['UNRECOGNIZED']=True
        errors=list(validator.iter_errors(bad));assert errors
        closed.append({'node':name,'rejected_by':[e.validator for e in errors]})
    # Actual production H/N/B operations on C-only metadata, without literal
    # physical proofs or a claimed complete production publication.
    nodes=[]
    def node(name,deps,payload):
        assert set(deps)<={n['name'] for n in nodes}
        v={'version':'gp5_num_n1_r5_C_metadata_v1','dependencies':{n['name']:n['digest'] for n in nodes if n['name'] in deps},'value':payload}
        first=b.H('C_metadata/'+name,v);second=b.H('C_metadata/'+name,copy.deepcopy(v));assert first==second
        nodes.append({'name':name,'dependencies':deps,'payload':v,'digest':first,'blob_sha256':b.B(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())})
    node('raw',[],b.N(before));node('source',[],b.N(values));node('target',['raw','source'],b.N(actual));node('axes',['raw','source','target'],axes);node('binding',['target','axes'],{'untouched_pose':b.N(metadata['pose'])})
    target_input={'native_tree':b.N(actual)};d=b.H('target_size',target_input)
    assert d==b.H('target_size',copy.deepcopy(target_input)) and d!=b.H('raw_size',target_input)
    different=copy.deepcopy(actual);different[0]=int(different[0]) if type(different[0]) is float else float(different[0])
    assert d!=b.H('target_size',{'native_tree':b.N(different)})
    # This receipt establishes typed metadata dependencies only. Full production
    # proof/core/final closure is verified from E saved artifacts, never invented.
    return {'case':tag+str(yaw),'raw':raw,'target':actual,'axis_equalities':axes,'target_digest':d,'dependency_nodes':nodes,'production_dependency_contract':production_identity_contract_receipt(),'closed_schema_negative':closed,'schema_source_sha256':hashlib.sha256(schema_path.read_bytes()).hexdigest(),'requirements':{'exact_dimensions':'PASS','axis_yaw':'PASS','native_types':'PASS','float_bits':'PASS','untouched_fields':'PASS','digest_repeat_and_domain_and_type_sensitivity':'PASS','acyclic_typed_metadata_dependencies':'PASS','production_source_schema_dependency_boundaries':'PASS_STATIC','closed_axis_and_signature_schema':'PASS'},'boundary':'PURE_C_METADATA_NOT_PHYSICAL_PUBLICATION_PROOF'}

def f0_receipt(episode,config):
    from semantic_pallet_planner.jev_select.contracts import validate_schema,digest
    assert config['version']=='jev_packaging_geometry_order_v17' and config['feature_profile']=='F0_existing_facts'
    rows=[]
    for index,event in enumerate(episode['events']):
        if event.get('context') is None:continue
        ctx=event['context'];validate_schema('decision_context',ctx)
        req=ctx['request_body'];question=req['questions']['next_action'];criteria=ctx['criteria']
        assert req['state']==ctx['model_state'] and question['criteria']==criteria
        signatures=[]
        for row in criteria.values():
            signatures.append({'keys':sorted(row),'features':sorted(row['features']),'pose':sorted(row['pose']),'load_changes':sorted({k for x in row['load_changes'] for k in x})})
        # Candidate count/IDs, positions, scores and state values are evidence,
        # never required equal across diverging backend trajectories.
        contract={'runtime':config['version'],'context_version':ctx['version'],'feature_profile':config['feature_profile'],'request_fields':sorted(req),'question_fields':sorted(question),'model_state_fields':sorted(ctx['model_state']),'criteria_fields':sorted({k for x in signatures for k in x['keys']}),'feature_fields':sorted({k for x in signatures for k in x['features']}),'pose_fields':sorted({k for x in signatures for k in x['pose']})}
        rows.append({'event_index':index,'context_digest':digest(ctx),'request_digest':digest(req),'contract':contract,'candidate_count':len(criteria),'context_schema':'decision_context_v17','schema_check':'PASS','public_fact_values_compared':False})
    assert rows and all(r['contract']==rows[0]['contract'] for r in rows)
    return {'backend':config['candidate_backend'],'method':config['selector'],'task_id':config['order_task_identity']['task_id'],'contract':rows[0]['contract'],'contexts':rows,'status':'PASS_SAVED_PUBLIC_FIELD_CONTRACT'}

def compare_f0(receipts):
    pairs=[]
    for task in ('GP5_SYNTH_K02_INT','GP5_SYNTH_K02'):
        for method in ('local_geometry_test_double','local_first_test_double'):
            rows=[r for r in receipts if r['task_id']==task and r['method']==method]
            assert len(rows)==2 and {r['backend'] for r in rows}=={'e2_original_v1','ems_surface_hybrid_v1'}
            assert rows[0]['contract']==rows[1]['contract'],'F0_PUBLIC_FIELD_CONTRACT_DISAGREEMENT'
            pairs.append({'task_id':task,'method':method,'backends':[r['backend'] for r in rows],'contract':rows[0]['contract'],'context_refs':[r['contexts'] for r in rows],'status':'PASS_FIELD_CONTRACT_ONLY','same_candidates_required':False})
    return pairs

def production_identity_contract_receipt():
    """Read actual closed schemas/AST dependency boundaries, not physical proof."""
    import ast
    root=Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select')
    source=root/'geometry_native_shape_bridge.py';tree=ast.parse(source.read_bytes())
    functions={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
    returned=next(n for n in functions['_base_proof'].body if isinstance(n,ast.Return)).value
    fields={k.value for k in returned.keys};schema=json.loads((root/'schemas/native_shape_proof_core.schema.json').read_bytes())
    assert fields==set(schema['properties'])==set(schema['required'])
    assert schema['additionalProperties'] is False
    forbidden={'published_candidate_id','published_candidate_digest','published_fingerprint','final_binding_ref','candidate_digest'}
    assert not fields.intersection(forbidden),'PROOF_FINAL_ID_BACK_EDGE'
    contracts={}
    for name in ('shadow_core','derived_core','shadow_binding','final_binding','publication'):
        path=root/'schemas'/('native_shape_'+name+'.schema.json');s=json.loads(path.read_bytes())
        assert s['additionalProperties'] is False and set(s['required'])==set(s['properties'])
        contracts[name]={'schema_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'fields':sorted(s['properties'])}
    assert 'candidate_digest' not in contracts['shadow_core']['fields']
    assert 'candidate_digest' in contracts['shadow_binding']['fields']
    assert {'proof_core_ref','raw_shadow_binding_ref','published_shadow_binding_ref','published_candidate_digest'}<=set(contracts['final_binding']['fields'])
    fp=ast.unparse(functions['_fingerprint'])
    assert "H('proof_core', p)" in fp and 'final_binding' not in fp
    assert "if k not in ('candidate_id', 'candidate_fingerprint')" in ast.unparse(functions['content'])
    dependencies={'external':[],'raw_and_source':['external'],'content':['raw_and_source'],'shadow_derived_cores':['content'],'equivalence':['shadow_derived_cores'],'proof':['equivalence','content','raw_and_source'],'fingerprint':['proof','content'],'final_candidate':['fingerprint','content'],'shadow_wrappers':['final_candidate','shadow_derived_cores','proof'],'final_binding':['shadow_wrappers','final_candidate','proof'],'publication':['final_binding','external']}
    seen=set()
    for name,deps in dependencies.items():assert set(deps)<=seen;seen.add(name)
    return {'status':'PASS_SOURCE_SCHEMA_DEPENDENCY_BOUNDARIES','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'actual_proof_fields':sorted(fields),'forbidden_back_edges':sorted(forbidden),'schema_contracts':contracts,'topological_dependency_order':dependencies,'boundary':'STATIC_CONTRACT_PLUS_C_TYPED_METADATA; FULL_PHYSICAL_PROOF_ONLY_FROM_E_SAVED_REFERENCE_VALIDATOR'}
