"""Standalone GP2 exact actions. Deliberately absent from provider/runtime routing."""
import copy
import hashlib
import json
import math
from collections import Counter
from decimal import Decimal, DecimalException
from fractions import Fraction
from ...domain import internal_item, restore_placed
from ..constraints import evaluate_pose
from ...evaluation.geometry_oracle import check_candidate
from . import build_space_index
from .contracts import AABB, DEFAULT_LIMITS, GeometryError, require, number, text, digest
from .input_adapter import adapt, binary, ADAPTER
from .reduction import reduce_candidates, action_order

BACKEND='ems_surface_hybrid_v1'
CONFIG={'version':'geometry_gp2_standalone_config_v1','backend':BACKEND,
        'budgets':DEFAULT_LIMITS,'yaw_degrees':[0,90],'per_item_top_k':16,'joint_top_k':48,
        'publish_quantum_mm':'0.001','rounding':'HALF_EVEN',
        'reducer':'yaw_floor_required_then_joint_group_coverage_v1',
        'support_ratio_min':0.7,'candidate_generator':{'geometry_score_weights':
        {'compactness':0.35,'height':0.25,'stability':0.25,'balance':0.15}}}
POSE=('x_mm','y_mm','z_base_mm')


def publish(v):
    # Fraction.__round__ is exact ties-to-even, independent of Decimal context.
    return Fraction(round(v*1000),1000)


def _finite_tree(value):
    if isinstance(value,float):
        require(math.isfinite(value),'nonfinite physical result')
    elif isinstance(value,dict):
        for v in value.values(): _finite_tree(v)
    elif isinstance(value,(list,tuple)):
        for v in value: _finite_tree(v)


def _physical_number(value, runtime):
    """Runtime exact arithmetic must not silently underflow at original physics."""
    try:
        result = float(value)
    except OverflowError:
        if runtime:
            raise GeometryError('RUNTIME_NUMBER_UNREPRESENTABLE', 'geometry binary64 overflow')
        raise
    if runtime and (not math.isfinite(result) or (value != 0 and result == 0)):
        raise GeometryError('RUNTIME_NUMBER_UNREPRESENTABLE', 'geometry binary64 overflow/underflow')
    return result


def generate(raw):
    """geometry_physical_input_v1 JSON bytes -> atomic result and independent sidecar.

    Only current public container/placed/buffer fields are accepted. The caller
    must project original saved JSON lexemes, never reserialize a float mapping.
    """
    return _generate(raw)


def _generate(raw, *, _point_limit=None):
    """Reduced point limit is a labelled test-only fault injection, not config."""
    return _generation_core(raw, adapt_input=adapt, _point_limit=_point_limit)


def _generation_core(raw, *, adapt_input, identity_namespace='original_lexemes_v1',
                     _point_limit=None):
    """The sole proposal/check/reduction engine shared by the two source contracts.

    adapt_input returns (exact view, native physical view, exact state, internal
    geometry bytes, input identity). Runtime wrappers never call the old adapt.
    """
    if identity_namespace not in ('original_lexemes_v1','runtime_snapshot_v1'):
        raise GeometryError('INVALID_GEOMETRY_INPUT', 'unknown core source contract')
    runtime = identity_namespace == 'runtime_snapshot_v1'
    audit={'version':'geometry_runtime_generation_audit_v1' if runtime else 'geometry_generation_audit_v1',
           'adapter':'geometry_runtime_snapshot_adapter_v1' if runtime else ADAPTER,
           'config_digest':digest(CONFIG),'input_digest':None,
           'source_bytes_sha256':hashlib.sha256(raw).hexdigest() if type(raw) is bytes else None,
           'spaces':[], 'items':[], 'space_index_builds':0,
           'definitions':{'raw_point_attempts':'per item, source/host/yaw/point instances before dedup',
           'unique_actions':'representable published keys including physical rejects',
           'raw_valid_candidates':'unique actions passing proposal, published and independent checks',
           'final_candidates':'unique per-item reducer output, at most 16; joint at most 48'},
           'test_only_point_limit':_point_limit}
    result={'version':'geometry_runtime_generation_v1' if runtime else 'geometry_gp2_generation_v1',
            'backend':BACKEND,'status':'ERROR',
            'candidates':[],'audit':audit,'error':None}
    try:
        exact, physical, state, geometry_bytes, identity=adapt_input(raw)
        audit['input_digest']=identity
        settings={k:copy.deepcopy(CONFIG[k]) for k in ('support_ratio_min','candidate_generator')}
        settings['container']=physical['container']
        placed=restore_placed(physical['placed_items'])
        if runtime:
            audit['ledger_views'] = {
                'saved':[{k:copy.deepcopy(p[k]) for k in ('item_id','supported_load_kg','support_fractions')}
                         for p in physical['placed_items']],
                'rebuilt':[{'item_id':p['item_id'],'supported_load_kg':p['supported_load_kg'],
                            'support_fractions':[{'item_id':sid,'fraction':f} for sid,f in p['supports']]}
                           for p in placed]}
        # Rebuild oracle ledger with domain.restore_placed; do not feed rounded
        # saved ledger values back into either physical admission path.
        oracle_placed=copy.deepcopy(physical['placed_items'])
        for saved,p in zip(oracle_placed,placed):
            require(saved['supported_load_kg'] in (p['supported_load_kg'],round(p['supported_load_kg'],3)), 'saved load contradicts restored ledger')
            expected={sid:frac for sid,frac in p['supports']}
            edges=saved['support_fractions']
            require(len(edges)==len(expected) and {e['item_id'] for e in edges}==set(expected), 'saved support IDs contradict restored ledger')
            require(all(e['fraction'] in (expected[e['item_id']],round(expected[e['item_id']],9)) for e in edges), 'saved support fractions contradict restored ledger')
            saved['supported_load_kg']=p['supported_load_kg']
            saved['support_fractions']=[{'item_id':sid,'fraction':f} for sid,f in p['supports']]
        # Validate the existing ordered prefix using the original admission code.
        for i,p in enumerate(placed):
            prior,_=evaluate_pose(p['item'],restore_placed(physical['placed_items'][:i]),p['x0'],p['y0'],p['z0'],p['x1']-p['x0'],p['y1']-p['y0'],p['yaw'],settings)
            require(prior is not None,'invalid placed physical prefix')
        index=build_space_index(geometry_bytes)
        audit['space_index_builds']=1
        audit['space_index']=index
        if index['status']=='ERROR':
            raise GeometryError(index['error']['code'],index['error']['detail'])
        audit['spaces']=index['spaces']
        spaces=[(s,AABB(tuple(Fraction(v) for v in s['bounds_mm']))) for s in index['spaces']]
        levels={Fraction(0)} | {box.bounds[5] for box,_ in state.placed}
        out=[]
        for src in sorted(exact['buffer_items'],key=lambda i:i['arrival_index']):
            physical_src = (next(p for p in physical['buffer_items'] if p['item_id']==src['item_id'])
                            if runtime else binary(src))
            item=internal_item(physical_src)
            pool={}; seen=set(); outcomes={}; rejects=Counter()
            ia={'item_id':src['item_id'],'raw_point_attempts':0,'space_skips':0,
                'unrepresentable_proposals':0,'proposal_rejections':[], 'raw_valid_candidates':[],
                'unique_actions':0,'raw_valid_count':0,'final_candidates':'NOT_PUBLISHED','enumeration_complete':False}
            audit['items'].append(ia)
            dims=[number(src['dimensions_mm'][k]) for k in ('length','width','height')]
            limit=DEFAULT_LIMITS['raw_point_attempts_per_item'] if _point_limit is None else _point_limit
            for yaw in (0,90):
                l,w,h=dims if yaw==0 else (dims[1],dims[0],dims[2])
                for space,host in spaces:
                    a,b,z,d,e,f=host.bounds
                    if z not in levels or d-a<l or e-b<w or f-z<h:
                        ia['space_skips']+=1
                        continue
                    points=((a,b,z),(d-l,b,z),(a,e-w,z),(d-l,e-w,z),((a+d-l)/2,(b+e-w)/2,z))
                    for source in space['source_types']:
                        for pi,(x,y,z) in enumerate(points):
                            if ia['raw_point_attempts']>=limit:
                                raise GeometryError('GEOMETRY_BUDGET_EXCEEDED','raw_point_attempts_per_item')
                            ia['raw_point_attempts']+=1
                            center=(x+l/2,y+w/2,z)
                            pub=tuple(publish(v) for v in center)
                            key=(src['item_id'],text(l),text(w),text(h),str(yaw),*(text(v) for v in pub))
                            seen.add(key)
                            ia['unique_actions']=len(seen)
                            ref={'host_id':space['space_id'],'source_type':source,'point_index':pi,
                                 'proposal_corner_mm':[text(v) for v in (x,y,z)]}
                            def reject(reason, unrepresentable=False):
                                rejects[reason]+=1
                                ia['proposal_rejections'].append(dict(ref,action_key=list(key),reason=reason))
                                outcomes.setdefault(key,set()).add(reason)
                                if unrepresentable:
                                    ia['unrepresentable_proposals']+=1
                            proposed,reason=evaluate_pose(item,placed,*(_physical_number(v,runtime) for v in (x,y,z,l,w)),yaw,settings)
                            if proposed is None:
                                reject(reason); continue
                            _finite_tree(proposed)
                            box=AABB((pub[0]-l/2,pub[1]-w/2,pub[2],pub[0]+l/2,pub[1]+w/2,pub[2]+h))
                            if pub[2]!=z or not host.contains(box):
                                reject('POSE_REPRESENTATION_REJECTED',True); continue
                            checked,reason=evaluate_pose(item,placed,*(_physical_number(v,runtime) for v in
                                (pub[0]-l/2,pub[1]-w/2,pub[2],l,w)),yaw,settings)
                            if checked is None:
                                reject('POSE_REPRESENTATION_REJECTED',True); continue
                            candidate=checked['visible']
                            _finite_tree(checked)
                            if any(number(Decimal(str(candidate['pose'][k])))!=v for k,v in zip(POSE,pub)):
                                reject('POSE_REPRESENTATION_REJECTED',True); continue
                            case={'available_items':[copy.deepcopy(physical_src)],'placed_items':oracle_placed}
                            errors=check_candidate(case,{'container':physical['container']},candidate)
                            if errors:
                                ia['check_disagreement']=dict(ref,action_key=list(key),errors=errors)
                                raise GeometryError('PHYSICAL_CHECK_DISAGREEMENT',','.join(errors))
                            outcomes.setdefault(key,set()).add('VALID')
                            if key not in pool:
                                fp=digest({'backend':BACKEND,'input':identity,'action':key,
                                           **({'source_contract':identity_namespace} if runtime else {})})
                                candidate['candidate_id']=('GR1_' if runtime else 'G2_')+fp[:24]
                                candidate['candidate_fingerprint']=fp
                                pool[key]={'action_key':list(key),'candidate':candidate,'geometry_score':checked['geometry_score'],
                                           'sources':set(),'host_ids':set(),'proposal_refs':[]}
                            ia['raw_valid_count']=len(pool)
                            r=pool[key]
                            r['sources'].add(source); r['host_ids'].add(space['space_id']); r['proposal_refs'].append(ref)
            hosts={s['space_id']:h for s,h in spaces}
            for r in pool.values():
                r['sources']=sorted(r['sources']); r['host_ids']=sorted(r['host_ids'])
                def host_rank(sid):
                    b=hosts[sid].bounds
                    return ((b[3]-b[0])*(b[4]-b[1])*(b[5]-b[2]),b)
                r['representative_host']=min(r['host_ids'],key=host_rank)
            records=sorted(pool.values(),key=action_order)
            final,coverage=reduce_candidates(records)
            ia.update(enumeration_complete=True,unique_actions=len(seen),raw_valid_candidates=records,final_candidates=len(final),
                      final_action_keys=[r['action_key'] for r in final],coverage=coverage,
                      rejection_counts=dict(sorted(rejects.items())),
                      unique_action_outcomes=[{'action_key':list(k),'outcomes':sorted(v)} for k,v in sorted(outcomes.items())],
                      raw_valid_count=len(records),
                      geometric_equivalence_count=len({tuple(r['action_key'][:4]+r['action_key'][5:]) for r in records}))
            out.extend(r['candidate'] for r in final)
        require(len(out)<=48,'joint candidate bound')
        result.update(status='OK' if out else 'OK_EMPTY',candidates=out)
    except GeometryError as exc:
        result['error']={'code':exc.code,'detail':exc.detail}
    except (DecimalException,OverflowError,ZeroDivisionError) as exc:
        result['error']={'code':'UNSUPPORTED_GEOMETRY_NUMBER','detail':type(exc).__name__}
    except (ValueError,UnicodeError) as exc:
        result['error']={'code':'INVALID_GEOMETRY_INPUT','detail':str(exc)}
    audit['outcome']=result['status']
    audit['semantic_digest']=digest(audit)
    return result
