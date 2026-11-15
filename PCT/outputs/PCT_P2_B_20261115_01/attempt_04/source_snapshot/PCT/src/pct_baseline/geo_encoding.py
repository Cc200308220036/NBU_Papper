"""pct_adapted_geo_v1 public-only 6/8/6 encoding and exact private lookup.

No candidate generation, physical checks, monitoring or order execution.
"""
import copy
from dataclasses import dataclass
import math
import numpy as np
from .contracts import require, digest

FEATURE_VERSION = 'pct_adapted_geo_v1'
FEATURE_CONTRACT = {
    'version': FEATURE_VERSION, 'placed':40, 'leaves':16, 'current':1,
    'dims':[6,8,6], 'coordinates':'container_bottom_center_mm_to_corner_mm',
    'Lref':'max(length_mm,width_mm,max_height_mm)',
    'placed_fields':'x0,y0,z0,x1,y1,z1',
    'leaf_fields':'x0,y0,z0,x1,y1,H,0,0',
    'current_fields':'1,0,0,sorted(l,w,h)',
    'numeric':'float64 transform then divide once then float32; normFactor=1',
    'mask':'slot8 true=valid, unscaled; empty placed slot0 valid zero',
    'order':'public display_mapping insertion order; no reorder/dedup/filter',
    'tie':'smallest valid index, exact probability tie',
}


def number(v, code='GEO_NONFINITE'):
    require(type(v) in (int,float) and math.isfinite(v),code)
    return np.float64(v)


def size3(values):
    require(isinstance(values,(list,tuple)) and len(values)==3,'GEO_SIZE_SHAPE')
    a=np.array([number(v) for v in values],dtype=np.float64)
    require(bool((a>0).all()),'GEO_NONPOSITIVE_SIZE')
    return a


def corner_coordinates(pose,size,container):
    require(set(pose)=={'x_mm','y_mm','z_base_mm','yaw_deg'},'GEO_POSE_FIELDS')
    require(type(pose['yaw_deg']) in (int,float) and pose['yaw_deg'] in (0,90),'GEO_YAW')
    x,y,z=(number(pose[k]) for k in ('x_mm','y_mm','z_base_mm'))
    l,w,h=size3(size)
    L,W,H=(number(container[k]) for k in ('length_mm','width_mm','max_height_mm'))
    require(L>0 and W>0 and H>0,'GEO_CONTAINER')
    a=np.array([x-l/2+L/2,y-w/2+W/2,z,x+l/2+L/2,y+w/2+W/2,z+h],dtype=np.float64)
    require(bool(np.isfinite(a).all()),'GEO_NONFINITE')
    # No clipping, snapping, tolerance adjustment or dropping over-bound nodes.
    require(bool((a[:3]>=0).all() and (a[3:]<=np.array([L,W,H])).all()),'GEO_BOUNDS')
    return a


def inverse_corner(corners,container):
    """Float64 diagnostic only. Actions always come from original lookup."""
    a=np.asarray(corners,dtype=np.float64)
    require(a.shape==(6,) and bool(np.isfinite(a).all()),'GEO_CORNER_SHAPE')
    return [float((a[0]+a[3])/2-container['length_mm']/2),
            float((a[1]+a[4])/2-container['width_mm']/2),float(a[2])]


@dataclass(frozen=True)
class EncodedGeometry:
    _record: dict

    @property
    def data(self):
        return copy.deepcopy(self._record)

    def tensor(self):
        import torch
        return torch.tensor(self._record['packed'],dtype=torch.float32).unsqueeze(0)

    def resolve(self,index):
        require(type(index) is int and 0<=index<len(self._record['mapping']),'GEO_INVALID_LEAF_INDEX')
        return copy.deepcopy(self._record['mapping'][index])


def encode_geometry(context):
    """Consume only the current public state/criteria; mapping is audit-only.

    Caller validates the outer public context. Feature projection deliberately
    ignores load fields and any unrelated metadata (never receives a task).
    """
    v=context.data if hasattr(context,'data') else copy.deepcopy(context)
    require(v['version']=='jev_decision_context_b1_v1','GEO_CONTEXT_VERSION')
    state=v['model_state']; criteria=v['criteria']; mapping=v['display_mapping']
    require(state['units']['length']=='mm' and state['units']['mass']=='kg','GEO_UNITS')
    require(state['coordinate_convention']=='bottom_center_x_right_y_back_z_up_v1','GEO_COORDINATES')
    container=state['container']; Lref=max(number(container[k]) for k in ('length_mm','width_mm','max_height_mm'))
    require(Lref>0,'GEO_CONTAINER')
    available=state['available_objects']; placed=state['placed_objects']; pending=state['buffer']['pending']
    require(state['buffer']['capacity']==1 and len(available)==1 and len(pending)==1,'GEO_CURRENT_COUNT')
    require(pending[0]['object_id']==available[0]['object_id'] and pending[0]['slot']==0 and state['buffer']['end_of_stream'] is False,'GEO_CURRENT_BINDING')
    require(len(placed)<=40 and len(mapping)<=16,'GEO_NODE_CAPACITY')
    labels=list(mapping)
    require(sorted(labels)==[f'C{i:02d}' for i in range(1,len(labels)+1)] and set(criteria)==set(labels),'GEO_MAPPING_LABELS')
    expected_route='CHOICE_REQUIRED' if len(labels)>1 else 'SINGLETON_BYPASS' if labels else 'STOP_NO_PHYSICAL_CANDIDATE'
    require(v['route']==expected_route,'GEO_ROUTE')
    ids=[o['object_id'] for o in placed+available]
    require(len(ids)==len(set(ids)),'GEO_DUPLICATE_OBJECT')
    current=available[0]; dims=size3([current['dimensions_mm'][k] for k in ('length','width','height')])
    nodes=np.zeros((57,9),dtype=np.float64); lookup=[]; corners=[]
    if not placed: nodes[0,8]=1
    for i,o in enumerate(placed):
        s=size3(o['oriented_size_mm']); orig=size3([o['dimensions_mm'][k] for k in ('length','width','height')])
        oriented=orig if o['pose']['yaw_deg']==0 else orig[[1,0,2]]
        require(np.array_equal(s,oriented),'GEO_PLACED_ORIENTATION')
        a=corner_coordinates(o['pose'],s.tolist(),container)
        nodes[i,:6]=a/Lref;nodes[i,8]=1
    candidate_ids=set(); candidate_digests=set()
    for i,label in enumerate(labels):
        c=criteria[label];m=mapping[label]
        require(set(m)=={'candidate_id','pick_item_id','candidate_digest'},'GEO_MAPPING_FIELDS')
        require(isinstance(m['candidate_id'],str) and m['candidate_id'] and m['candidate_id'] not in candidate_ids,'GEO_DUPLICATE_CANDIDATE')
        require(isinstance(m['candidate_digest'],str) and len(m['candidate_digest'])==64 and m['candidate_digest'] not in candidate_digests,'GEO_DUPLICATE_DIGEST')
        candidate_ids.add(m['candidate_id']);candidate_digests.add(m['candidate_digest'])
        require(c['pick_object']==current['object_id'],'GEO_WRONG_CURRENT')
        s=size3(c['oriented_size_mm']); expected=dims if c['pose']['yaw_deg']==0 else dims[[1,0,2]]
        require(np.array_equal(s,expected),'GEO_ORIENTED_SIZE')
        a=corner_coordinates(c['pose'],s.tolist(),container); corners.append(a.tolist())
        nodes[40+i,:6]=np.array([*a[:5],number(container['max_height_mm'])])/Lref
        nodes[40+i,8]=1
        lookup.append({'leaf_index':i,'display_label':label,**copy.deepcopy(m),
                       'pose':copy.deepcopy(c['pose']),'oriented_size_mm':copy.deepcopy(c['oriented_size_mm']),
                       'actual_top_mm':float(a[5])})
    require(len({m['pick_item_id'] for m in lookup})<=1,'GEO_MULTIPLE_CURRENT_IDS')
    nodes[56,:6]=np.array([1.,0.,0.,*np.sort(dims)])/Lref;nodes[56,8]=1
    packed=nodes.astype(np.float32)
    require(bool(np.isfinite(packed).all()),'GEO_FLOAT32_OVERFLOW')
    feature={'version':FEATURE_VERSION,'packed':packed.tolist(),'valid_mask':(packed[:,8]==1).tolist()}
    return EncodedGeometry({**feature,'feature_digest':digest(feature),'Lref_mm':float(Lref),
        'mapping':lookup,'mapping_digest':digest(lookup),'actual_leaf_corners_mm_float64':corners,
        'empty_pool':not labels,'placed_count':len(placed),'candidate_count':len(labels)})


def verify_candidates(encoded,candidates):
    """Bind exact original candidate data without sending its diagnostics to net."""
    require(isinstance(candidates,list),'GEO_CANDIDATES_TYPE')
    require(len(candidates)==encoded.data['candidate_count'],'GEO_CANDIDATE_COUNT')
    by_id={c['candidate_id']:c for c in candidates}
    require(len(by_id)==len(candidates),'GEO_DUPLICATE_CANDIDATE')
    for row in encoded.data['mapping']:
        require(row['candidate_id'] in by_id,'GEO_CANDIDATE_MISSING')
        c=by_id[row['candidate_id']]
        require(digest(c)==row['candidate_digest'],'GEO_CANDIDATE_DIGEST')
        require(c['pick_item_id']==row['pick_item_id'] and c['pose']==row['pose'] and c['oriented_size_mm']==row['oriented_size_mm'],'GEO_EXACT_ACTION_CHANGED')
    return copy.deepcopy(by_id)
