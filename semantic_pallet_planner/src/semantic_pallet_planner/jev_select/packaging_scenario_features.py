"""JM2-A1 public features and diagnostic action roles; no engine/transport imports.

Inputs are closed public snapshots. Completeness is a producer assertion bound to
an entire saved pool digest/count, not something inferred from two interventions.
Source-byte provenance is audited separately; no historical pool is reconstructed.
All outputs are A1 diagnostics, never T fragments, retrieval or execution permits.
"""
from __future__ import annotations

import copy
from decimal import Decimal
from functools import lru_cache
import json
import math
from pathlib import Path

from .packaging_versions import (JM_SCENARIO_INPUT, JM_SCENARIO_SIGNATURE,
                                JM_ACTION_CONTRAST, JM_SCENARIO_SCHEMAS)
from .packaging_jev_sampling import _validate, digest, SamplingError

COORDINATE='bottom_center_x_right_y_back_z_up_v1'
SCOPE='A1_DIAGNOSTICS_ONLY_NO_APPLICABILITY_OR_EXECUTION'
UNIMPLEMENTED=['connected_free_space','usable_exposed_top_surface',
               'load_bearing_paths','future_packable_volume','pct_reaction_features']
# Equality here is a conservative diagnostic condition, not a learned threshold.
STRUCTURAL_KEYS=['placed_count','placed_max_top_mm','placed_projection_union_ratio',
                 'placed_bbox_span_x_mm','placed_bbox_span_y_mm',
                 'placed_mean_center_x_mm','placed_mean_center_y_mm',
                 'placed_exact_face_contact_count','placed_top_level_count',
                 'placed_gross_stackable_face_area_mm2','placed_area_remaining_top_load_sum_kg']
ROLE_KEYS=['length_mm','width_mm','height_mm','mass_kg','max_top_load_kg',
           'stackable','oriented_length_mm','oriented_width_mm','oriented_height_mm',
           'x_over_length','y_over_width','base_over_height','yaw_deg']


class ScenarioError(ValueError):
    """Stable refusal code, with no private payload interpolation."""


def require(condition, code):
    if not condition:
        raise ScenarioError(code)


@lru_cache(maxsize=3)
def _schema(version):
    require(version in JM_SCENARIO_SCHEMAS,'UNKNOWN_SCENARIO_PROTOCOL')
    return json.loads((Path(__file__).with_name('schemas') /
                      (JM_SCENARIO_SCHEMAS[version]+'.schema.json')).read_text())


def validate(value):
    require(type(value) is dict,'SCENARIO_SCHEMA')
    try:
        digest(value)  # rejects NaN/Infinity before structural validation
        _validate(value,_schema(value.get('version')))
    except (SamplingError,ValueError,TypeError) as exc:
        if isinstance(exc,ScenarioError):
            raise
        raise ScenarioError('SCENARIO_SCHEMA') from exc
    if value['version']!=JM_SCENARIO_INPUT:
        require(value['record_digest']==digest({k:v for k,v in value.items()
                                               if k!='record_digest'}),'SCENARIO_SEAL')
    return value


def seal(value):
    value['record_digest']=digest(value)
    validate(value)
    return value


def _number(x):
    return type(x) in (int,float) and math.isfinite(x)


def _orientation(obj, size_key):
    pose=obj.get('pose');size=obj.get(size_key);original=obj.get('size_mm')
    if pose is not None and size is not None and original is not None:
        expected=original if pose['yaw_deg']==0 else [original[1],original[0],original[2]]
        require(size==expected,'ORIENTATION_SIZE_MISMATCH')


def validate_input(value):
    validate(value);require(value['version']==JM_SCENARIO_INPUT,'WRONG_INPUT_PROTOCOL')
    state=value['state'];ids=[o['item_id'] for o in state['buffer']+state['placed_objects']]
    require(len(ids)==len(set(ids)),'DUPLICATE_OBJECT_ID')
    for obj in state['placed_objects']:
        _orientation(obj,'oriented_size_mm')
    pool=value['pool'];receipt=value['pool_receipt']
    if pool is None:
        require(receipt is None,'MISSING_FULL_POOL')
        return value
    require(receipt is not None and receipt['complete'] is True and
            receipt['count']==len(pool) and receipt['digest']==digest(pool),
            'INCOMPLETE_OR_CHANGED_POOL')
    require(len({c['candidate_id'] for c in pool})==len(pool),'DUPLICATE_CANDIDATE_ID')
    boxes={b['item_id']:b for b in state['buffer']}
    for c in pool:
        require(c['pick_item_id'] in boxes,'CANDIDATE_OBJECT_NOT_PUBLIC_BUFFER')
        _orientation(dict(c,size_mm=boxes[c['pick_item_id']].get('size_mm')),'oriented_size_mm')
    return value


def make_input(state, pool, *, expected_pool_count=None, expected_pool_digest=None):
    """Common canonical input; caller supplies full normalized-pool attestation.

    Missing pool is preserved as missing, not silently replaced by an empty pool.
    Missing optional public attributes/geometry remain missing. Unknown fields are
    rejected, preventing private/future/PCT fields entering the feature function.
    """
    receipt=None if pool is None else dict(complete=True,count=expected_pool_count,
                                         digest=expected_pool_digest)
    value=dict(version=JM_SCENARIO_INPUT,coordinate=COORDINATE,state=copy.deepcopy(state),
               pool=copy.deepcopy(pool),pool_receipt=receipt)
    return validate_input(value)


def normalized_saved_pool(pool):
    """Extract exact public actions; validate saved wrapper bytes, never recompute actions."""
    result=[]
    for row in pool:
        if 'frozen_candidate' in row:
            frozen=row['frozen_candidate']
            require(row.get('candidate_digest')==digest(frozen),'SAVED_CANDIDATE_CHANGED')
            require(all(row.get(k)==frozen.get(k) for k in
                        ('candidate_id','pick_item_id','pose','oriented_size_mm')),
                    'SAVED_CANDIDATE_CHANGED')
        result.append({k:copy.deepcopy(row[k]) for k in
                       ('candidate_id','pick_item_id','pose','oriented_size_mm')})
    return result


def from_saved_public(state, pool, *, expected_pool_count, expected_raw_pool_digest):
    """No probabilities, outcomes or private task are accepted by this adapter."""
    require(len(pool)==expected_pool_count and digest(pool)==expected_raw_pool_digest,
            'INCOMPLETE_OR_CHANGED_POOL')
    normalized=normalized_saved_pool(pool)
    return make_input(state,normalized,expected_pool_count=expected_pool_count,
                      expected_pool_digest=digest(normalized))


def from_current_public(state, criteria, *, expected_candidate_labels):
    """Adapter over existing public model_state/criteria, not a context builder.

    Existing local anonymous object IDs are preserved as identity, including
    distinct boxes with identical attributes. Original task IDs are not required.
    Public descriptive fields are allowlisted and unused fields never analyzed.
    """
    require(set(state)<=set(('assumptions','available_objects','buffer','container',
                'coordinate_convention','memories','objective','placed_objects','units')),
            'NONPUBLIC_STATE_FIELD')
    require(state.get('coordinate_convention')==COORDINATE,'COORDINATE_MISMATCH')
    require(set(criteria)==set(expected_candidate_labels) and
            len(criteria)==len(expected_candidate_labels),'INCOMPLETE_OR_CHANGED_POOL')
    def obj(o,placed):
        value={'item_id':o['object_id']}
        for k in ('mass_kg','max_top_load_kg','stackable'):
            if k in o:value[k]=copy.deepcopy(o[k])
        if o.get('dimensions_mm') is not None:
            d=o['dimensions_mm'];value['size_mm']=[d[k] for k in ('length','width','height')]
        if placed:
            for k in ('pose','oriented_size_mm'):
                if k in o:value[k]=copy.deepcopy(o[k])
            if 'current_top_load_kg' in o:
                value['area_current_top_load_kg']=copy.deepcopy(o['current_top_load_kg'])
            # Public remaining_top_load_kg uses effective permission (zero for
            # nonstackable boxes); saved area ledger uses raw packaging capacity.
            # Normalize only these observed scalars, never infer usable capacity.
            if _number(o.get('max_top_load_kg')) and _number(o.get('current_top_load_kg')):
                value['area_remaining_top_load_kg']=o['max_top_load_kg']-o['current_top_load_kg']
        return value
    public={'container':copy.deepcopy(state['container']),
            'buffer':[obj(x,False) for x in state['available_objects']],
            'placed_objects':[obj(x,True) for x in state['placed_objects']]}
    pool=[]
    for label,c in criteria.items():
        require(set(c)<=set(('features','load_changes','oriented_size_mm','pick_object','pose')),
                'NONPUBLIC_CANDIDATE_FIELD')
        pool.append(dict(candidate_id=label,pick_item_id=c['pick_object'],
                         pose=copy.deepcopy(c['pose']),oriented_size_mm=copy.deepcopy(c['oriented_size_mm'])))
    return make_input(public,pool,expected_pool_count=len(pool),expected_pool_digest=digest(pool))


def _bounds(o):
    p=o['pose'];x,y,z=(Decimal(str(p[k])) for k in ('x_mm','y_mm','z_base_mm'))
    l,w,h=map(lambda n:Decimal(str(n)),o['oriented_size_mm'])
    return x-l/2,x+l/2,y-w/2,y+w/2,z,z+h


def _union_area(rectangles):
    # Exact Decimal sweep of already saved rectangles; no feasibility/candidate check.
    xs=sorted({r[i] for r in rectangles for i in (0,1)});area=Decimal(0)
    for a,b in zip(xs,xs[1:]):
        intervals=sorted((r[2],r[3]) for r in rectangles if r[0]<b and r[1]>a)
        end=None;length=Decimal(0)
        for lo,hi in intervals:
            length+=max(Decimal(0),hi-max(lo,end if end is not None else lo))
            end=hi if end is None else max(end,hi)
        area+=(b-a)*length
    return float(area)


def build_signature(public_input):
    """The single history/current computation; deterministic, no caller mutation."""
    v=validate_input(public_input);s=v['state'];boxes=s['buffer'];placed=s['placed_objects'];pool=v['pool']
    c=s['container'];features={}
    def put(name,value=None,status='VALUE',reason='OBSERVED_PUBLIC_FACTS'):
        features[name]=dict(status=status,value=value,reason=reason)
    def aggregate(name,objects,field,fn,empty='EMPTY_POPULATION'):
        if not objects:put(name,status='NOT_APPLICABLE',reason=empty)
        elif any(o.get(field) is None for o in objects):put(name,status='MISSING',reason='MISSING_PUBLIC_'+field)
        else:put(name,fn([o[field] for o in objects]))
    put('buffer_count',len(boxes));put('placed_count',len(placed))
    for axis,i in [('length',0),('width',1),('height',2)]:
        aggregate('buffer_mean_'+axis+'_mm',boxes,'size_mm',lambda a,i=i:sum(x[i] for x in a)/len(a))
    for name,key in [('mass_kg','mass_kg'),('capacity_kg','max_top_load_kg'),('stackable_fraction','stackable')]:
        aggregate('buffer_mean_'+name if name!='stackable_fraction' else 'buffer_stackable_fraction',boxes,key,lambda a:sum(a)/len(a))
    geometry=all(o.get('pose') is not None and o.get('oriented_size_mm') is not None for o in placed)
    if geometry:
        rects=[_bounds(o) for o in placed];area=c['length_mm']*c['width_mm']
        put('placed_volume_ratio',sum(math.prod(o['oriented_size_mm']) for o in placed)/(area*c['max_height_mm']))
        put('placed_max_top_mm',max((float(r[5]) for r in rects),default=0))
        put('placed_projection_union_ratio',_union_area(rects)/area)
        put('placed_exact_face_contact_count',sum(a[5]==b[4] and min(a[1],b[1])>max(a[0],b[0]) and min(a[3],b[3])>max(a[2],b[2]) for a in rects for b in rects if a is not b))
        put('placed_top_level_count',len({r[5] for r in rects}))
        for axis,i in [('x',0),('y',2)]:
            put('placed_bbox_span_'+axis+'_mm',float(max((r[i+1] for r in rects),default=0)-min((r[i] for r in rects),default=0)))
            if placed:put('placed_mean_center_'+axis+'_mm',sum(o['pose'][axis+'_mm'] for o in placed)/len(placed))
            else:put('placed_mean_center_'+axis+'_mm',status='NOT_APPLICABLE',reason='EMPTY_POPULATION')
        if any(o.get('stackable') is None for o in placed):put('placed_gross_stackable_face_area_mm2',status='MISSING',reason='MISSING_PUBLIC_stackable')
        else:put('placed_gross_stackable_face_area_mm2',sum(o['oriented_size_mm'][0]*o['oriented_size_mm'][1] for o in placed if o['stackable']))
    else:
        for key in STRUCTURAL_KEYS[1:]+['placed_volume_ratio']:
            put(key,status='MISSING',reason='MISSING_PLACED_GEOMETRY')
    aggregate('placed_area_remaining_top_load_sum_kg',placed,'area_remaining_top_load_kg',sum)
    candidate_keys=['candidate_count','candidate_distinct_box_count','candidate_mean_base_mm',
                    'candidate_mean_top_mm','candidate_yaw90_fraction','candidate_floor_fraction']
    if pool is None:
        for key in candidate_keys:put(key,status='MISSING',reason='MISSING_FULL_POOL')
    else:
        put('candidate_count',len(pool));put('candidate_distinct_box_count',len({a['pick_item_id'] for a in pool}))
        for key,fn in [('candidate_mean_base_mm',lambda a:a['pose']['z_base_mm']),
                       ('candidate_mean_top_mm',lambda a:a['pose']['z_base_mm']+a['oriented_size_mm'][2]),
                       ('candidate_yaw90_fraction',lambda a:int(a['pose']['yaw_deg']==90)),
                       ('candidate_floor_fraction',lambda a:int(a['pose']['z_base_mm']==0))]:
            if pool:put(key,sum(fn(a) for a in pool)/len(pool))
            else:put(key,status='NOT_APPLICABLE',reason='EMPTY_POOL')
    missing=sorted(k for k,f in features.items() if f['status']=='MISSING')
    return seal(dict(version=JM_SCENARIO_SIGNATURE,scope=SCOPE,input_digest=digest(v),
                feature_spec_digest=digest(feature_spec()),stage='NONEMPTY' if placed else 'OPENING',
                features=features,missing_features=missing,status='INCOMPLETE' if missing else 'COMPLETE',
                not_implemented=UNIMPLEMENTED.copy()))


def _role(view, candidate):
    b=next(b for b in view['state']['buffer'] if b['item_id']==candidate['pick_item_id'])
    if any(b.get(k) is None for k in ('size_mm','mass_kg','max_top_load_kg','stackable')):return None
    c=view['state']['container'];size=b['size_mm'];oriented=candidate['oriented_size_mm'];p=candidate['pose']
    return dict(zip(ROLE_KEYS,[*size,b['mass_kg'],b['max_top_load_kg'],b['stackable'],*oriented,
                              p['x_mm']/c['length_mm'],p['y_mm']/c['width_mm'],
                              p['z_base_mm']/c['max_height_mm'],p['yaw_deg']]))


def _direction(a,b):
    return 'EQUAL' if a==b else 'INCREASE' if b>a else 'DECREASE'


def _relation(a,b):
    if a['pick_item_id']!=b['pick_item_id']:return 'CROSS_BOX_SELECTION'
    moved=any(a['pose'][k]!=b['pose'][k] for k in ('x_mm','y_mm','z_base_mm'))
    rotated=a['pose']['yaw_deg']!=b['pose']['yaw_deg']
    return ('SAME_BOX_TRANSLATION_AND_ROTATION' if moved and rotated else
            'SAME_BOX_TRANSLATION' if moved else 'SAME_BOX_ROTATION' if rotated else 'IDENTICAL_ACTION')


def bind_contrast(history,a_id,b_id,*,current=None):
    """Enumerate diagnostic ordered-pair correspondences, never select an action.

    v1 requires exact structural-context equality and all role-attribute direction
    relations. This deliberately narrow rule provides no cross-state efficacy or
    applicability claim. Multiple matches are explicit, never silently resolved.
    """
    validate_input(history);current=history if current is None else current;validate_input(current)
    pool=history['pool'];require(pool is not None,'MISSING_FULL_POOL')
    index={a['candidate_id']:a for a in pool};require(a_id in index and b_id in index,'ACTION_NOT_IN_FULL_POOL')
    a,b=index[a_id],index[b_id];ar,br=_role(history,a),_role(history,b)
    hs,cs=build_signature(history),build_signature(current)
    features=hs['features'];conditions={k:features[k] for k in STRUCTURAL_KEYS}
    missing=[k for k in STRUCTURAL_KEYS if features[k]['status']=='MISSING' or cs['features'][k]['status']=='MISSING']
    changed=[k for k in STRUCTURAL_KEYS if features[k]!=cs['features'][k]]
    if history['state']['container']!=current['state']['container']:changed.append('container')
    relation=_relation(a,b);directions={k:_direction(ar[k],br[k]) for k in ROLE_KEYS} if ar is not None and br is not None else {}
    pairs=[];unmatched=[];status='NO_CORRESPONDENCE'
    if ar is None or br is None:status='MISSING_REQUIRED_FEATURE';unmatched=['HISTORICAL_ROLE_ATTRIBUTES']
    elif missing:status='MISSING_REQUIRED_FEATURE';unmatched=missing
    elif changed:status='STRUCTURE_MISMATCH';unmatched=changed
    elif current['pool'] is None:status='MISSING_REQUIRED_FEATURE';unmatched=['FULL_CURRENT_POOL']
    else:
        roles={p['candidate_id']:_role(current,p) for p in current['pool']}
        if any(r is None for r in roles.values()):
            status='MISSING_REQUIRED_FEATURE';unmatched=['CURRENT_ROLE_ATTRIBUTES']
        else:
            for ca in current['pool']:
                for cb in current['pool']:
                    if _relation(ca,cb)!=relation:continue
                    ra,rb=roles[ca['candidate_id']],roles[cb['candidate_id']]
                    if all(_direction(ra[k],rb[k])==directions[k] for k in ROLE_KEYS):
                        pairs.append(dict(A=ca['candidate_id'],B=cb['candidate_id']))
            if pairs:status='AMBIGUOUS_DIAGNOSTIC' if len(pairs)>1 else 'BOUND_DIAGNOSTIC_ONLY'
            else:unmatched=['ACTION_CONTRAST_ABSENT']
    # Identity derives from local object identity, never attribute equality.
    aliases={box['item_id']:'box_'+str(i+1) for i,box in enumerate(history['state']['buffer'])}
    return seal(dict(version=JM_ACTION_CONTRAST,scope=SCOPE,history_input_digest=digest(history),
          current_input_digest=digest(current),intervention=relation,
          roles={'A':dict(box_role=aliases[a['pick_item_id']],attributes=ar,exact_action=copy.deepcopy(a)),
                 'B':dict(box_role=aliases[b['pick_item_id']],attributes=br,exact_action=copy.deepcopy(b))},
          changed_attributes=[k for k,v in directions.items() if v!='EQUAL'],
          unchanged_attributes=[k for k,v in directions.items() if v=='EQUAL'],
          attribute_directions=directions,structural_conditions=conditions,
          container_condition=copy.deepcopy(history['state']['container']),
          correspondence_pairs=pairs,corresponding_candidates={r:sorted({p[r] for p in pairs}) for r in ('A','B')},
          unmatched_conditions=unmatched,status=status,ambiguity=len(pairs)>1,
          not_implemented=UNIMPLEMENTED.copy(),execution_eligible=False))


def feature_spec():
    """Machine-readable, finite feature contract; copied to the delivery package."""
    definitions={}
    def add(name,unit,population,formula,cost='O(B+P+C)'):
        definitions[name]=dict(unit=unit,population=population,formula=formula,cost=cost,
             missing='MISSING + null if required public fields/pool absent; never fill zero',
             empty='NOT_APPLICABLE + null for empty means; observed counts/union/extent/top-height are 0',
             boundary='finite nonnegative dimensions/mass/capacity; yaw 0/90; no physical feasibility inference',
             truncation='NONE; reject more than 256 buffer/placed objects or 512 candidates')
    for name,pop in [('buffer_count','buffer'),('placed_count','placed_objects'),('candidate_count','entire pool')]:add(name,'count',pop,'cardinality')
    for axis in ('length','width','height'):add('buffer_mean_'+axis+'_mm','mm','all buffer objects once','sum(size axis)/buffer count')
    for name,unit,key in [('buffer_mean_mass_kg','kg','mass_kg'),('buffer_mean_capacity_kg','kg','max_top_load_kg'),('buffer_stackable_fraction','ratio','stackable')]:add(name,unit,'all buffer objects once','arithmetic mean of '+key)
    add('placed_volume_ratio','ratio','all placed oriented boxes','sum(l*w*h)/(container L*W*H); not free-space estimate')
    add('placed_max_top_mm','mm','all placed boxes','max(base_z + oriented_height), 0 if empty')
    add('placed_projection_union_ratio','ratio','XY projections of all placed boxes','exact Decimal rectangle union area/(L*W); not connected free space','O(P^2 log P)')
    add('placed_exact_face_contact_count','count','ordered distinct placed box pairs','top_z(lower)==base_z(upper) and positive XY overlap; exact equality, no tolerance or force solve','O(P^2)')
    add('placed_top_level_count','count','all placed boxes','count distinct exact top_z values')
    for axis in ('x','y'):
        add('placed_bbox_span_'+axis+'_mm','mm','all placed boxes','max(axis high)-min(axis low), 0 if empty')
        add('placed_mean_center_'+axis+'_mm','mm','all placed boxes once','arithmetic mean of saved pose center; NOT_APPLICABLE if empty')
    add('placed_gross_stackable_face_area_mm2','mm^2','all placed boxes with stackable=true','sum(l*w); gross, does not subtract occlusion and is NOT usable exposed surface')
    add('placed_area_remaining_top_load_sum_kg','kg','all placed boxes once','sum public area_remaining_top_load_kg; accounting only, not future usable capacity')
    add('candidate_distinct_box_count','count','entire pool','distinct pick_item_id; identical attributes never merge distinct IDs')
    for name,unit,formula in [('candidate_mean_base_mm','mm','mean saved base_z'),('candidate_mean_top_mm','mm','mean saved base_z+oriented_height'),('candidate_yaw90_fraction','ratio','mean indicator yaw==90'),('candidate_floor_fraction','ratio','mean indicator base_z==0')]:add(name,unit,'entire pool; one sample per candidate, including multiple poses of one box',formula)
    return dict(version='jev_jm_scenario_feature_spec_v1',input_version=JM_SCENARIO_INPUT,
            signature_version=JM_SCENARIO_SIGNATURE,action_version=JM_ACTION_CONTRAST,
            coordinate=dict(version=COORDINATE,x='box XY center; right positive; origin container bottom center',
                            y='back positive',z='box base upward; mm',yaw='0/90 degrees; size axes swapped at 90'),
            features=definitions,not_implemented={k:dict(status='NOT_IMPLEMENTED',excluded_from_rules=True) for k in UNIMPLEMENTED},
            pool_completeness='trusted producer full-pool count+digest; saved bytes/projection mapping checked in evidence audit, never inferred from two branches',
            role_binding=dict(rule='exact STRUCTURAL_KEYS equality plus identical per-attribute comparison directions and intervention category; diagnostic only',
                              structural_keys=STRUCTURAL_KEYS,role_attributes=ROLE_KEYS,pair_cost='O(C^2)',
                              container_equality_required=True,
                              role_identity='first occurrence of distinct local buffer item_id; identical attributes never merge identities',
                              direction_order='exact numeric ordering; boolean false < true; no learned or physical tolerance',
                              role_units={k:('boolean' if k=='stackable' else 'degrees' if k=='yaw_deg' else 'ratio' if k in ('x_over_length','y_over_width','base_over_height') else 'kg' if k.endswith('_kg') else 'mm') for k in ROLE_KEYS},
                              missing='refuse correspondence if key context or either role missing',ambiguity='retain all ordered pairs and both candidate sets; no winner'),
            limits=dict(buffer=256,placed=256,candidates=512),scope=SCOPE)
