"""Public area-ledger load11/12/6 encoding. No stability pre-evaluation."""
import copy
import numpy as np
from .contracts import require, digest
from .geo_encoding import encode_geometry, EncodedGeometry, number, corner_coordinates, verify_candidates

FEATURE_VERSION='pct_adapted_load_v1'
FEATURE_CONTRACT={
    'version':FEATURE_VERSION,'placed':40,'leaves':16,'current':1,'dims':[11,12,6],
    'layout':'packed13: fields 0:11 placed, 0:12 leaf, 0:6 current; slot12 valid; unused slots zero',
    'placed_fields':'x0,y0,z0,x1,y1,z1,mass,stackable,capacity,current_top_load,remaining_top_load',
    'leaf_fields':'x0,y0,z0,x1,y1,z1,support_ratio,com_margin,resulting_max_height,max_after_area_load_utilization,min_affected_remaining,affected_support_applicable',
    'current_fields':'original_l,original_w,original_h,mass,stackable,capacity',
    'Lref':'max(length_mm,width_mm,max_height_mm)','Mref_kg':9,
    'numeric':'float64 transform and scale once then float32; no clipping',
    'aggregate':'strictly positive increment only; empty=0,0,false; zero capacity positive increment error',
    'mask':'slot12 true=valid; empty placed slot0 valid zero; padding zero invalid',
    'order':'public display_mapping insertion order; no reorder/dedup/filter',
    'tie':'smallest valid index, exact probability tie'}


def nonnegative(v):
    n=number(v,'LOAD_NONFINITE');require(n>=0,'LOAD_NEGATIVE');return n


def resource(o):
    mass=nonnegative(o['mass_kg']);cap=nonnegative(o['max_top_load_kg'])
    require(type(o['stackable']) is bool,'LOAD_STACKABLE_TYPE')
    used=nonnegative(o['current_top_load_kg']);remaining=nonnegative(o['remaining_top_load_kg'])
    effective=cap if o['stackable'] else 0
    require(np.isclose(used+remaining,effective,rtol=0,atol=1e-9),'LOAD_LEDGER_INCONSISTENT')
    return [mass/9,int(o['stackable']),cap/9,used/9,remaining/9]


def aggregate(changes,objects):
    require(isinstance(changes,list),'LOAD_CHANGES_TYPE')
    rows=[];seen=set()
    for c in changes:
        name=c['object_id'];require(name in objects and name not in seen,'LOAD_AFFECTED_OBJECT');seen.add(name)
        delta=nonnegative(c['increment_top_load_kg'])
        if delta>0:
            require(nonnegative(c['max_top_load_kg'])>0,'LOAD_ZERO_CAPACITY_POSITIVE_INCREMENT')
            require(objects[name]['stackable'],'LOAD_NONSTACKABLE_POSITIVE_INCREMENT')
        before=nonnegative(c['before_top_load_kg']);after=nonnegative(c['after_top_load_kg'])
        cap=nonnegative(c['max_top_load_kg']);remaining=nonnegative(c['remaining_top_load_kg'])
        o=objects[name]
        require(np.isclose(before,o['current_top_load_kg'],rtol=0,atol=1e-9) and cap==o['max_top_load_kg'] and
                np.isclose(after,before+delta,rtol=0,atol=1e-9),'LOAD_CHANGE_INCONSISTENT')
        effective=cap if o['stackable'] else 0
        require(np.isclose(remaining,effective-after,rtol=0,atol=1e-9),'LOAD_REMAINING_INCONSISTENT')
        if delta>0:
            require(cap>0,'LOAD_ZERO_CAPACITY_POSITIVE_INCREMENT')
            require(o['stackable'],'LOAD_NONSTACKABLE_POSITIVE_INCREMENT')
            rows.append((after/cap,remaining))
    return [max(x[0] for x in rows),min(x[1] for x in rows)/9,1] if rows else [0,0,0]


class EncodedLoad(EncodedGeometry):
    pass


def encode_load(context):
    # Reuse audited geometry checks and immutable mapping; never its H leaf slot.
    g=encode_geometry(context).data
    v=context.data if hasattr(context,'data') else copy.deepcopy(context)
    s=v['model_state'];L=g['Lref_mm'];nodes=np.zeros((57,13),dtype=np.float64)
    nodes[:,12]=g['valid_mask'];objects={o['object_id']:o for o in s['placed_objects']}
    for i,o in enumerate(s['placed_objects']):
        nodes[i,:6]=corner_coordinates(o['pose'],o['oriented_size_mm'],s['container'])/L
        nodes[i,6:11]=resource(o)
    cur=s['available_objects'][0];r=resource(cur)
    nodes[56,:6]=[*(number(cur['dimensions_mm'][k])/L for k in ('length','width','height')),*r[:3]]
    for i,row in enumerate(g['mapping']):
        c=v['criteria'][row['display_label']];f=c['features']
        ratio=number(f['support_ratio']);require(0<=ratio<=1,'LOAD_SUPPORT_RATIO')
        margin=number(f['com_margin_mm']);height=nonnegative(f['resulting_max_height_mm'])
        require(height>=row['actual_top_mm'] and height<=s['container']['max_height_mm'],'LOAD_RESULTING_HEIGHT')
        nodes[40+i,:6]=np.array(g['actual_leaf_corners_mm_float64'][i])/L
        nodes[40+i,6:]=[ratio,margin/L,height/L,*aggregate(c['load_changes'],objects),1]
    packed=nodes.astype(np.float32);require(bool(np.isfinite(packed).all()),'LOAD_FLOAT32_OVERFLOW')
    feature={'version':FEATURE_VERSION,'packed':packed.tolist(),'valid_mask':g['valid_mask']}
    return EncodedLoad({**g,**feature,'feature_digest':digest(feature),'Mref_kg':9})
