"""Contact geometry at the selected exact pose; never simulate a vertical drop.

The state remains in commit order. Only the solver's private node view is sorted
by height to satisfy its lower-before-upper contact topology. No path planning.
"""
from dataclasses import asdict
import hashlib
from importlib.resources import files
import math
import time
import numpy as np
from .balance_adapter import algorithm_identity as balanced_identity
from .balance_network import Node, Contact, solve_network, BalanceUnsupported, BalanceNumericalError
from .vendor.pct.convex_hull import ConvexHull
from .contracts import digest
from .geometry import to_kernel
from .exact_contracts import ExactConfig, ExactResult

def algorithm_identity():
    identity = balanced_identity()
    extra = ['exact_contracts.py', 'exact_adapter.py', 'schemas/stability_result_v3.schema.json']
    identity['files_sha256'].update({n:hashlib.sha256(files(__package__).joinpath(n).read_bytes()).hexdigest() for n in extra})
    identity.update(algorithm='pct_exact_pose_network_v3',
        semantic_revision='exact_pose_contacts_global_equilibrium_v3',
        source_digest=digest(identity['files_sha256']))
    return identity

def contact_network(boxes, container, cfg):
    """Build only real positive-area contacts; overhead gaps are not supports."""
    boxes = sorted(boxes, key=lambda b:(b.bottom_center_mm[2], b.item_id))
    geometry = {b.item_id:to_kernel(b,container) for b in boxes}
    for b in boxes:
        x,y,z=geometry[b.item_id]['corner_mm'];sx,sy,sz=b.size_mm
        if min(x,y,z)<0 or x+sx>container[0] or y+sy>container[1] or z+sz>container[2]:
            raise BalanceUnsupported('OUT_OF_BOUNDS')
    # Exact 3D overlap is invalid even when its thickness is below contact tolerance.
    for i,a in enumerate(boxes):
        ca=geometry[a.item_id]['corner_mm']
        for b in boxes[i+1:]:
            cb=geometry[b.item_id]['corner_mm']
            if all(min(ca[d]+a.size_mm[d],cb[d]+b.size_mm[d])>max(ca[d],cb[d]) for d in range(3)):
                raise BalanceUnsupported('PHYSICAL_OVERLAP')
    nodes=[];contacts=[]
    for b in boxes:
        x,y,z=geometry[b.item_id]['corner_mm'];sx,sy,sz=b.size_mm
        points=[]
        if abs(z)<=cfg.height_tolerance_mm:
            contacts.append(Contact(b.item_id,None,(x,y,x+sx,y+sy)))
            hull=None
        else:
            for lower in boxes:
                if lower.item_id==b.item_id:continue
                lx,ly,lz=geometry[lower.item_id]['corner_mm'];ls=lower.size_mm
                if abs(lz+ls[2]-z)>cfg.height_tolerance_mm:continue
                rect=(max(x,lx),max(y,ly),min(x+sx,lx+ls[0]),min(y+sy,ly+ls[1]))
                x0,y0,x1,y1=rect
                if x1<=x0 or y1<=y0:continue
                contacts.append(Contact(b.item_id,lower.item_id,rect))
                points.extend([(x0,y0),(x0,y1),(x1,y0),(x1,y1)])
            if not points:raise BalanceUnsupported('UNSUPPORTED_FLOATING_BOX')
            # Retain the original PCT hull and its 10% contraction, not a new tolerance.
            hull=np.asarray(ConvexHull(points),dtype=float)
            if len(hull)<3:raise BalanceUnsupported('DEGENERATE_SUPPORT_HULL')
            hull=(hull-(hull-np.mean(hull,axis=0))*0.1).tolist()
        nodes.append(Node(b.item_id,b.mass_kg,geometry[b.item_id]['center_mm'],
                          tuple(map(tuple,hull)) if hull is not None else None))
    return nodes,contacts

def assess_candidate(placed_state,candidate,config=None):
    start=time.perf_counter();cfg=config or ExactConfig()
    if not isinstance(cfg,ExactConfig):raise ValueError('EXPECTED_EXACT_CONFIG')
    cfg.__post_init__();identity=algorithm_identity();baseline='NOT_ASSESSED';stage='input'
    state_hash=candidate_hash=None;calls=0;diagnostics={};pose=None
    def result(status,reason):
        def safe(v):
            if isinstance(v,float) and not math.isfinite(v):return repr(v)
            if isinstance(v,dict):return {k:safe(x) for k,x in v.items()}
            if isinstance(v,(list,tuple)):return [safe(x) for x in v]
            return v
        return ExactResult(status,reason,state_hash,candidate_hash,getattr(candidate,'item_id',None),
            digest(asdict(cfg)),identity,baseline,None,None,0.0 if pose else None,pose,calls,
            safe(diagnostics),time.perf_counter()-start)
    try:
        placed_state.validate();candidate.validate()
        if candidate.item_id in {b.item_id for b in placed_state.placed}:raise ValueError('DUPLICATE_ITEM_ID')
        state_hash=digest(asdict(placed_state));candidate_hash=digest(asdict(candidate))
        scale=float(max(placed_state.container_mm[:2]))
        stage='baseline'
        if placed_state.placed:
            nodes,contacts=contact_network(placed_state.placed,placed_state.container_mm,cfg)
            calls+=1;old=solve_network(nodes,contacts,scale,cfg)
            baseline=old['status']
            if baseline!='STABLE':
                diagnostics=old['diagnostics']
                return result('UNASSESSABLE','BASELINE_'+old['reason_code'])
        baseline='STABLE';stage='candidate'
        nodes,contacts=contact_network((*placed_state.placed,candidate),placed_state.container_mm,cfg)
        geo=to_kernel(candidate,placed_state.container_mm)
        pose={'item_id':candidate.item_id,'kernel_corner_mm':list(geo['corner_mm']),
              'original_bottom_center_mm':list(candidate.bottom_center_mm),
              'oriented_size_mm':list(candidate.size_mm),'density_kg_mm3':geo['density_kg_mm3']}
        calls+=1;outcome=solve_network(nodes,contacts,scale,cfg)
        diagnostics={**outcome['diagnostics'],'geometry_revision':'exact_pose_v3',
            'contact_rectangles':[asdict(c) for c in contacts],
            'solver_node_order':[n.item_id for n in nodes],
            'evaluated_scope':'exact_pose_contact_network','vertical_drop_reconstruction':False}
        return result(outcome['status'],outcome['reason_code'])
    except BalanceUnsupported as exc:
        if stage=='baseline':baseline='UNASSESSABLE'
        diagnostics={'stage':stage,'detail':str(exc)}
        return result('UNASSESSABLE',('BASELINE_' if stage=='baseline' else '')+str(exc))
    except Exception as exc:
        if stage=='baseline':baseline='ERROR'
        diagnostics={**getattr(exc,'diagnostics',{}),'stage':stage,'exception_type':type(exc).__name__}
        return result('UNASSESSABLE' if stage=='input' else 'ERROR',
                      'INVALID_INPUT' if stage=='input' else str(exc) if isinstance(exc,BalanceNumericalError) else 'EXACT_KERNEL_ERROR')
