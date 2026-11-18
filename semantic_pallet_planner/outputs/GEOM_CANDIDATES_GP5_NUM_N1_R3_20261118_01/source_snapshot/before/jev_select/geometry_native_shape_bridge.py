"""Opt-in v17 publication identity and native-size proof; no generation/monitor.

FRESH reuses original oracle/transition/F0 functions. SAVED validates original
bytes and the complete evidence closure without invoking these functions.
"""
import copy
import math
import struct
from fractions import Fraction
from .contracts import canonical, digest, JevSelectError, validate_schema
from . import geometry_runtime_contracts as c

POLICY='geometry_native_shape_publication_policy_v3'
BRIDGE='geometry_runtime_native_shape_bridge_v3'
CONTENT='geometry_native_shape_candidate_content_v1'
PROOF='geometry_candidate_publication_proof_v3'
PUBLICATION='geometry_candidate_publication_v3'
IDENTITY='geometry_gp5_num_n0_identity_dag_design_v1'

def require(ok,detail,code='NUM_BRIDGE_IDENTITY_MISMATCH'):
    if not ok:raise JevSelectError(code,detail)

def B(raw):return c.sha(raw)
def L(value):return digest(value)
def H(kind,payload):return L({'domain':'geometry_native_shape_identity_r1/'+kind+'/v1','payload':payload})

def N(value):
    t=type(value)
    if value is None:return ['NULL']
    if t is bool:return ['BOOL',value]
    if t is str:return ['STR',value]
    if t is int:return ['INT',str(value)]
    if t is float:
        require(math.isfinite(value),'nonfinite native float')
        return ['FLOAT64',struct.pack('>d',value).hex()]
    if t is list:return ['LIST',[N(x) for x in value]]
    if t is dict:
        require(all(type(k) is str for k in value),'non-string native key')
        return ['DICT',[[k,N(value[k])] for k in sorted(value)]]
    raise JevSelectError('NUM_BRIDGE_SOURCE_INVALID','non-native value')

def unN(tree):
    require(type(tree) is list and tree,'invalid native tree')
    tag=tree[0]
    if tag=='NULL':v=None
    elif tag in ('BOOL','STR'):v=tree[1]
    elif tag=='INT':v=int(tree[1])
    elif tag=='FLOAT64':v=struct.unpack('>d',bytes.fromhex(tree[1]))[0]
    elif tag=='LIST':v=[unN(x) for x in tree[1]]
    elif tag=='DICT':
        require(len({x[0] for x in tree[1]})==len(tree[1]),'duplicate tree key')
        v={k:unN(x) for k,x in tree[1]}
    else:raise JevSelectError('NUM_BRIDGE_IDENTITY_MISMATCH','unknown native tag')
    require(N(v)==tree,'noncanonical native tree')
    return v

def signature(v):
    require(type(v) in (int,float) and (type(v) is int or math.isfinite(v)),'invalid numeric signature','NUM_BRIDGE_SOURCE_INVALID')
    q=Fraction(v)
    return {'native_type':'INT' if type(v) is int else 'FLOAT','integer_text':str(v) if type(v) is int else None,
        'binary64_be_hex':struct.pack('>d',v).hex() if type(v) is float else None,
        'numerator':str(q.numerator),'denominator':str(q.denominator)}

def restore_size(raw_size,dimensions,yaw):
    require(type(yaw) is int and yaw in (0,90),'yaw must be native 0/90','NUM_BRIDGE_SOURCE_INVALID')
    require(type(dimensions) is dict and set(dimensions)=={'length','width','height'} and type(raw_size) is list and len(raw_size)==3,'three dimensions required','NUM_BRIDGE_SOURCE_INVALID')
    axes=('length','width','height') if yaw==0 else ('width','length','height')
    target=[copy.deepcopy(dimensions[k]) for k in axes];proof=[]
    for i,(a,b) in enumerate(zip(raw_size,target)):
        sa,sb=signature(a),signature(b)
        require(a>0 and b>0,'nonpositive dimensions','NUM_BRIDGE_SOURCE_INVALID')
        try:exact=math.isfinite(float(b)) and Fraction(float(b))==Fraction(b)
        except (OverflowError,ValueError):exact=False
        require(exact,'source not exactly binary64 representable','NUM_BRIDGE_UNREPRESENTABLE')
        require(Fraction(a)==Fraction(b),'dimension rational mismatch','NUM_BRIDGE_VALUE_MISMATCH')
        if type(a) is type(b) is float:require(c.same_native(a,b),'float bit mismatch')
        proof.append({'axis_index':i,'source_axis':axes[i],'raw_signature':sa,'target_signature':sb,'value_equal':True})
    return target,proof

def content(candidate,side):
    q={k:v for k,v in candidate.items() if k not in ('candidate_id','candidate_fingerprint')}
    return H(side+'_content',{'version':CONTENT,'native_tree':N(q)})

def action_key(candidate):
    return [candidate['pick_item_id'],*[c.numeric_text(x) for x in candidate['oriented_size_mm']],candidate['pose']['yaw_deg'],
        *[c.numeric_text(candidate['pose'][k]) for k in ('x_mm','y_mm','z_base_mm')]]

def compare(a,b,*,size_paths=(),derived=False,path=''):
    """Full typed comparison; only declared size/derived numeric paths may differ."""
    if c.same_native(a,b):return []
    if type(a) is dict and type(b) is dict and set(a)==set(b):
        return sum((compare(a[k],b[k],size_paths=size_paths,derived=derived,path=path+'/'+str(k)) for k in sorted(a)),[])
    if type(a) is list and type(b) is list and len(a)==len(b):
        return sum((compare(x,y,size_paths=size_paths,derived=derived,path=path+'/'+str(i)) for i,(x,y) in enumerate(zip(a,b))),[])
    require((derived or path in size_paths) and type(a) in (int,float) and type(b) in (int,float), 'unallowed difference '+path,'NUM_BRIDGE_DERIVED_DISAGREEMENT' if derived else 'NUM_BRIDGE_UNALLOWED_CHANGE')
    require(Fraction(a)==Fraction(b) and struct.pack('>d',float(a))==struct.pack('>d',float(b)), 'derived rational/binary64 disagreement '+path,'NUM_BRIDGE_DERIVED_DISAGREEMENT')
    return [{'path':path,'raw_signature':signature(a),'published_signature':signature(b),'comparison':'E_AND_SAME_BINARY64','binary64_be_hex':struct.pack('>d',float(a)).hex()}]

class Artifacts:
    def __init__(self,blobs=None):self.blobs={} if blobs is None else copy.deepcopy(blobs);self.used=set()
    def put(self,value):
        raw=c.encode(value);key=B(raw);self.blobs[key]=raw.hex()
        require(c.same_native(c.decode(raw),value),'blob type/bit roundtrip')
        return {'version':'geometry_blob_ref_v1','sha256':key}
    def get(self,ref):
        require(type(ref) is dict and set(ref)=={'version','sha256'} and ref['version']=='geometry_blob_ref_v1','invalid ref')
        key=ref['sha256'];c.hash_string(key)
        require(key in self.blobs,'missing '+key,'NUM_BRIDGE_MISSING_ARTIFACT')
        raw=bytes.fromhex(self.blobs[key]);require(B(raw)==key,'blob bytes drift');self.used.add(key)
        return c.decode(raw)

def _core(store,kind,value):
    validate_schema('native_shape_'+kind,value)
    return store.put(value),H(kind,value)

def _derived(placed,criteria):
    from .packaging_runtime import layout_facts,geometry_facts
    loads,edges,geometry=layout_facts(placed)
    mass=sum(p['mass_kg'] for p in placed)
    bounds=[]
    for axis,k in enumerate(('x_mm','y_mm')):
        bounds.append(max(p['pose'][k]+p['oriented_size_mm'][axis]/2 for p in placed)-min(p['pose'][k]-p['oriented_size_mm'][axis]/2 for p in placed))
    height=max(p['pose']['z_base_mm']+p['oriented_size_mm'][2] for p in placed)
    return {'version':'geometry_native_shape_derived_facts_v3','item_count':len(placed),'volume_mm3':sum(math.prod(p['oriented_size_mm']) for p in placed),
        'mass_kg':mass,'max_height_mm':height,'envelope_volume_mm3':math.prod(bounds)*height,
        'centroid_mm':[sum(p['mass_kg']*geometry_facts(p['pose'],p['oriented_size_mm'])['centroid_mm'][axis] for p in placed)/mass for axis in range(3)],
        'layout_facts':{'loads':loads,'edges':edges,'geometry':geometry},'criteria_facts':criteria}

def _base_proof(i,r,q,item,pointer,n,g,common,binding,raw_ref,generation_ref,axis,eq,raw_key):
    return {'version':PROOF,'ordinal':i,'backend':binding['candidate_backend'],'common_binding_digest':L(common),'backend_binding_digest':L(binding),
        'raw_pool_sha256':raw_ref['sha256'],'raw_candidate_digest':L(r),'raw_candidate_id':r['candidate_id'],'raw_candidate_fingerprint':r['candidate_fingerprint'],
        'source_item_pointer':pointer,'source_dimensions_digest':H('source_dimensions',{'source_native_sha256':B(n),'source_item_pointer':pointer,'native_tree':N(item['dimensions_mm'])}),
        'source_signatures':[signature(item['dimensions_mm'][k]) for k in ('length','width','height')],'target_signatures':[signature(x) for x in q['oriented_size_mm']],
        'raw_size_digest':H('raw_size',{'native_tree':N(r['oriented_size_mm'])}),'target_size_digest':H('target_size',{'native_tree':N(q['oriented_size_mm'])}),
        'axis_equalities':axis,'raw_action_key':raw_key,'publication_action_key':action_key(q),
        'allowed_changed_paths':['/oriented_size_mm/'+str(j) for j,(a,b) in enumerate(zip(r['oriented_size_mm'],q['oriented_size_mm'])) if not c.same_native(a,b)],
        'physical_and_derived_equivalence':eq,'raw_content_digest':content(r,'raw'),'published_content_digest':content(q,'published'),
        'native_sha256':B(n),'geometry_sha256':B(g),'raw_generation_ref':generation_ref}

def _fingerprint(p):
    return H('fingerprint',{'namespace':POLICY,'backend':p['backend'],'backend_binding_digest':p['backend_binding_digest'],'raw_pool_sha256':p['raw_pool_sha256'],
        'raw_candidate_digest':p['raw_candidate_digest'],'proof_core_digest':H('proof_core',p),'published_content_digest':p['published_content_digest'],'publication_action_key':p['publication_action_key']})

def _raw_key(generation,r,backend):
    if backend=='e2_original_v1':return None
    rows=[x for item in generation['audit']['items'] for x in item['raw_valid_candidates'] if x['candidate']['candidate_fingerprint']==r['candidate_fingerprint']]
    require(len(rows)==1,'raw action key missing or ambiguous')
    return rows[0]['action_key']

def publish_native_shape_pool_v3(n,g,common,binding,raw_generation_raw,raw_pool_raw,*,config):
    from .geometry_runtime_input import validate_runtime_views_v1
    from ..evaluation.geometry_oracle import check_candidate
    from ..evaluation.state import apply_candidate
    from ..o4.buffer.buffer_state import physical
    from .packaging_runtime import _project_public_facts
    views=validate_runtime_views_v1(n,g);state=views['native']['current_state'];obs=views['native']['observation']
    raw=c.decode(raw_pool_raw);generation=c.decode(raw_generation_raw)
    require(generation['status'] in ('OK','OK_EMPTY') and (bool(raw)==(generation['status']=='OK')),'raw status/pool mismatch')
    if config['candidate_backend']!='e2_original_v1':require(c.same_native(raw,generation['candidates']),'raw pool/generation mismatch')
    store=Artifacts();nr=store.put(c.decode(n));gr=store.put(c.decode(g));rr=store.put(raw);genref=store.put(generation)
    targets=[];afters=[[],[]];axes=[];items=[];pointers=[]
    for i,r in enumerate(raw):
        matches=[(j,x['item']) for j,x in enumerate(state['pending_items']) if x['item']['item_id']==r['pick_item_id']]
        require(len(matches)==1,'source pending item missing','NUM_BRIDGE_SOURCE_INVALID');j,item=matches[0]
        q=copy.deepcopy(r);q['oriented_size_mm'],axis=restore_size(r['oriented_size_mm'],item['dimensions_mm'],r['pose']['yaw_deg'])
        for side,candidate in enumerate((r,q)):
            case=physical(copy.deepcopy(state),r['pick_item_id'])
            errors=check_candidate(case,{'container':state['container']},candidate)
            require(not errors,'oracle disagreement '+str(errors),'NUM_BRIDGE_PHYSICAL_DISAGREEMENT')
            afters[side].append(apply_candidate(case,candidate))
        compare(afters[0][-1],afters[1][-1],size_paths=['/'+str(len(state['placed_items']))+'/oriented_size_mm/'+str(k) for k in range(3)])
        targets.append(q);axes.append(axis);items.append(item);pointers.append('/current_state/pending_items/'+str(j)+'/item')
    # Same original private projection, same order/seed, using the already computed afters.
    projections=[_project_public_facts(config,obs,{'selectable_candidates':pool},shadow_afters={c['candidate_id']:a for c,a in zip(pool,after)}) for pool,after in ((raw,afters[0]),(targets,afters[1]))]
    compare(projections[0][1],projections[1][1])
    sizepaths=['/'+label+'/oriented_size_mm/'+str(k) for label in projections[0][2] for k in range(3)]
    compare(projections[0][2],projections[1][2],size_paths=sizepaths)
    mappings=[];published=[]
    for i,(r,q) in enumerate(zip(raw,targets)):
        core=[];derived=[];cd=[content(r,'raw'),content(q,'published')]
        for side in range(2):
            core.append({'version':'geometry_native_shape_shadow_state_v3','side':('RAW','PUBLISHED')[side],'ordinal':i,'source_native_sha256':B(n),
                'candidate_content_digest':cd[side],'placed_items':N(afters[side][i])})
            criteria=next(v for k,v in projections[side][2].items() if projections[side][3][k]['candidate_id']==r['candidate_id'])
            derived.append({'version':'geometry_native_shape_derived_facts_v3','source_native_sha256':B(n),'candidate_content_digest':cd[side],'native_tree':N(_derived(afters[side][i],criteria))})
        cr=[_core(store,'shadow_core',x) for x in core];dr=[_core(store,'derived_core',x) for x in derived]
        equalities=compare(unN(derived[0]['native_tree']),unN(derived[1]['native_tree']),derived=True)
        eq={'version':'geometry_native_shape_shadow_evidence_v3','raw_after_ref':cr[0][0],'published_after_ref':cr[1][0],'raw_derived_ref':dr[0][0],'published_derived_ref':dr[1][0],
            'raw_after_digest':cr[0][1],'published_after_digest':cr[1][1],'raw_derived_digest':dr[0][1],'published_derived_digest':dr[1][1],
            'raw_oracle_errors':[],'published_oracle_errors':[],'allowed_difference_paths':[x['path'] for x in equalities],'derived_equalities':equalities}
        key=_raw_key(generation,r,config['candidate_backend'])
        if key is not None:require(key==action_key(q),'raw/publication action key disagreement')
        p=_base_proof(i,r,q,items[i],pointers[i],n,g,common,binding,rr,genref,axes[i],eq,key)
        validate_schema('native_shape_proof_core',p);pref=store.put(p);pd=H('proof_core',p);fp=_fingerprint(p)
        q['candidate_id']='GP5N3_'+fp;q['candidate_fingerprint']=fp
        wrappers=[]
        for side,candidate in enumerate((r,q)):
            w={'version':'geometry_native_shape_shadow_binding_v1','side':('RAW','PUBLISHED')[side],'ordinal':i,'source_native_sha256':B(n),'candidate_content_digest':cd[side],
                'candidate_digest':L(candidate),'shadow_core_ref':cr[side][0],'shadow_core_digest':cr[side][1],'derived_core_ref':dr[side][0],'derived_core_digest':dr[side][1],'proof_core_digest':pd}
            wrappers.append(_core(store,'shadow_binding',w))
        final={'version':'geometry_native_shape_final_binding_v1','ordinal':i,'raw_pool_sha256':rr['sha256'],'raw_candidate_digest':L(r),'raw_content_digest':cd[0],'published_content_digest':cd[1],
            'proof_core_ref':pref,'proof_core_digest':pd,'published_candidate_id':q['candidate_id'],'published_fingerprint':fp,'published_candidate_digest':L(q),
            'raw_shadow_binding_ref':wrappers[0][0],'raw_shadow_binding_digest':wrappers[0][1],'published_shadow_binding_ref':wrappers[1][0],'published_shadow_binding_digest':wrappers[1][1]}
        fr,fd=_core(store,'final_binding',final)
        mappings.append({k:final[k] for k in ('ordinal','proof_core_ref','proof_core_digest','published_candidate_id','published_fingerprint','published_candidate_digest','raw_candidate_digest','raw_content_digest','published_content_digest')} | {'final_binding_ref':fr,'final_binding_digest':fd})
        published.append(q)
    require(len({x['candidate_id'] for x in published})==len(raw) and len({tuple(action_key(x)) for x in published})==len(raw),'duplicate ID/key','NUM_BRIDGE_MAPPING_INVALID')
    pub={'version':PUBLICATION,'identity_contract':IDENTITY,'policy':POLICY,'bridge':BRIDGE,'config_digest':L(config),'source_identity':config['runtime_identity']['source_identity'],
        'environment_digest':L(c.environment()),'common_binding_digest':L(common),'backend_binding_digest':L(binding),'native_sha256':B(n),'geometry_sha256':B(g),
        'raw_generation_ref':genref,'raw_pool_ref':rr,'native_ref':nr,'geometry_ref':gr,'ordered_mappings':mappings,'published_pool_digest':L(published),
        'validation_counts':{'oracle_checks':2*len(raw),'shadow_apply_calls':2*len(raw),'derived_projection_calls':2*len(raw),'status':'COMPLETED'}}
    validate_schema('native_shape_publication',pub)
    return published,{'record':pub,'digest':H('publication',pub),'blobs':store.blobs}


def validate_native_shape_publication_v3(n,g,common,binding,published,publication,*,config):
    """SAVED_IDENTITY_ONLY: inspect frozen bytes/proofs, never republish/physics."""
    c.closed(publication,{'record','digest','blobs'});pub=publication['record'];validate_schema('native_shape_publication',pub)
    require(H('publication',pub)==publication['digest'],'publication semantic digest')
    expected={'version':PUBLICATION,'identity_contract':IDENTITY,'policy':POLICY,'bridge':BRIDGE,'config_digest':L(config),'source_identity':config['runtime_identity']['source_identity'],
        'environment_digest':L(c.environment()),'common_binding_digest':L(common),'backend_binding_digest':L(binding),'native_sha256':B(n),'geometry_sha256':B(g),'published_pool_digest':L(published)}
    require(all(c.same_native(pub[k],v) for k,v in expected.items()),'publication roots drift')
    store=Artifacts(publication['blobs']);raw=store.get(pub['raw_pool_ref']);generation=store.get(pub['raw_generation_ref'])
    require(c.encode(store.get(pub['native_ref']))==n and c.encode(store.get(pub['geometry_ref']))==g,'input bytes')
    require(generation['status'] in ('OK','OK_EMPTY') and bool(raw)==(generation['status']=='OK'),'saved raw status')
    if config['candidate_backend']!='e2_original_v1':require(c.same_native(raw,generation['candidates']),'raw generation pool')
    require(len(raw)==len(published)==len(pub['ordered_mappings']),'pool mapping cardinality','NUM_BRIDGE_MAPPING_INVALID')
    state=c.decode(n)['current_state']
    for i,(r,q,m) in enumerate(zip(raw,published,pub['ordered_mappings'])):
        p=store.get(m['proof_core_ref']);validate_schema('native_shape_proof_core',p);pd=H('proof_core',p)
        matches=[(j,x['item']) for j,x in enumerate(state['pending_items']) if x['item']['item_id']==r['pick_item_id']]
        require(len(matches)==1,'source item');j,item=matches[0]
        target,axis=restore_size(r['oriented_size_mm'],item['dimensions_mm'],r['pose']['yaw_deg'])
        tmp=copy.deepcopy(r);tmp['oriented_size_mm']=target
        require(c.same_native({k:v for k,v in tmp.items() if k not in ('candidate_id','candidate_fingerprint')},{k:v for k,v in q.items() if k not in ('candidate_id','candidate_fingerprint')}),'raw/P unallowed fields')
        eq=p['physical_and_derived_equivalence'];validate_schema('native_shape_equivalence',eq)
        ep=_base_proof(i,r,q,item,'/current_state/pending_items/'+str(j)+'/item',n,g,common,binding,pub['raw_pool_ref'],pub['raw_generation_ref'],axis,eq,_raw_key(generation,r,config['candidate_backend']))
        require(c.same_native(p,ep),'saved proof mismatch')
        require(p['raw_action_key'] is None or p['raw_action_key']==action_key(q),'saved raw key')
        require(q['candidate_fingerprint']==_fingerprint(p) and q['candidate_id']=='GP5N3_'+_fingerprint(p),'final candidate identity')
        cd=[content(r,'raw'),content(q,'published')];cores=[];derived=[];wrappers=[]
        final=store.get(m['final_binding_ref']);validate_schema('native_shape_final_binding',final)
        for side,name in enumerate(('raw','published')):
            cr=store.get(eq[name+'_after_ref']);dr=store.get(eq[name+'_derived_ref'])
            validate_schema('native_shape_shadow_core',cr);validate_schema('native_shape_derived_core',dr)
            require(H('shadow_core',cr)==eq[name+'_after_digest'] and H('derived_core',dr)==eq[name+'_derived_digest'],'core semantic digest')
            require(cr['side']==('RAW','PUBLISHED')[side] and cr['ordinal']==i and cr['source_native_sha256']==dr['source_native_sha256']==B(n) and cr['candidate_content_digest']==dr['candidate_content_digest']==cd[side],'core binding')
            cores.append(unN(cr['placed_items']));derived.append(unN(dr['native_tree']))
            w=store.get(final[name+'_shadow_binding_ref']);validate_schema('native_shape_shadow_binding',w)
            ew={'version':'geometry_native_shape_shadow_binding_v1','side':cr['side'],'ordinal':i,'source_native_sha256':B(n),'candidate_content_digest':cd[side],'candidate_digest':L((r,q)[side]),
                'shadow_core_ref':eq[name+'_after_ref'],'shadow_core_digest':eq[name+'_after_digest'],'derived_core_ref':eq[name+'_derived_ref'],'derived_core_digest':eq[name+'_derived_digest'],'proof_core_digest':pd}
            require(c.same_native(w,ew) and H('shadow_binding',w)==final[name+'_shadow_binding_digest'],'final shadow binding')
        compare(cores[0],cores[1],size_paths=['/'+str(len(state['placed_items']))+'/oriented_size_mm/'+str(k) for k in range(3)])
        changes=compare(derived[0],derived[1],derived=True)
        require(c.same_native(eq['derived_equalities'],changes) and eq['allowed_difference_paths']==[x['path'] for x in changes],'derived proofs')
        require(all(c.same_native(final[k],m[k]) for k in m if k not in ('final_binding_ref','final_binding_digest')) and final['version']=='geometry_native_shape_final_binding_v1' and final['raw_pool_sha256']==pub['raw_pool_ref']['sha256'] and H('final_binding',final)==m['final_binding_digest'],'final mapping binding')
        require(m['ordinal']==i and m['proof_core_digest']==pd and m['raw_candidate_digest']==L(r) and m['raw_content_digest']==cd[0] and m['published_content_digest']==cd[1] and m['published_candidate_digest']==L(q) and m['published_candidate_id']==q['candidate_id'] and m['published_fingerprint']==q['candidate_fingerprint'],'mapping fields')
    require(len({x['candidate_id'] for x in published})==len(raw) and len({tuple(action_key(x)) for x in published})==len(raw),'mapping duplicate','NUM_BRIDGE_MAPPING_INVALID')
    require(pub['validation_counts']=={'oracle_checks':2*len(raw),'shadow_apply_calls':2*len(raw),'derived_projection_calls':2*len(raw),'status':'COMPLETED'},'validation counters')
    require(store.used==set(store.blobs),'unknown/unreachable blobs')
    return raw,generation
