"""E2 public geometry/gap-grid sampler. No AST, desired relation or private gap."""
import copy
import time
import json
from functools import lru_cache
from collections import defaultdict
from ....domain import internal_item,restore_placed
from ....planner.constraints import evaluate_pose,candidate_points
from ....planner.scoring import geometry_score
from ....evaluation.geometry_oracle import check_candidate
from ...buffer.buffer_state import physical
from ...common import digest,O4Error,canonical
from ..candidates import generate as region_generate,key

VERSION='o4_e2_public_boundary_grid_candidates_v1'
GRID=(0,50,100)


def _generate(state,pick,regions,config):
    started=time.perf_counter()
    if config.get('o4_e2',{}).get('sampling_grid_mm',list(GRID))!=list(GRID):
        raise O4Error('invalid_candidate_config','E2 public gap grid is frozen at [0,50,100]mm')
    base,base_audit=region_generate(state,pick,regions,config)
    case=physical(state,pick);item=internal_item(case['available_items'][0]);placed=restore_placed(case['placed_items'])
    settings=copy.deepcopy(config);settings['container']=state['container']
    pool={};strata=defaultdict(list);region_strata=defaultdict(list);attempted=0;rejections=defaultdict(int)
    levels=sorted({0.,*(p['z1'] for p in placed)})
    def evaluate(x,y,z,length,width,yaw):
        nonlocal attempted
        attempted+=1
        raw,reason=evaluate_pose(item,placed,x,y,z,length,width,yaw,settings)
        if raw is None:rejections[reason]+=1;return None
        c=raw['visible'];errors=check_candidate(case,{'container':state['container']},c)
        if errors:rejections['independent_physics']+=1;return None
        pool[key(c)]=c;return c
    for yaw in (0,90):
        length,width=item['dimensions'][:2] if yaw==0 else item['dimensions'][:2][::-1]
        # Enumerate public geometry ourselves before Top-K. In particular, do
        # not inherit an item-ID-dependent tie selection from the old Top-K.
        for x,y,z in candidate_points(placed,length,width,state['container']):evaluate(x,y,z,length,width,yaw)
        for r in sorted(regions,key=lambda r:r['region_id']):
            xs=(r['x_min_mm'],r['x_max_mm']-length,(r['x_min_mm']+r['x_max_mm']-length)/2)
            ys=(r['y_min_mm'],r['y_max_mm']-width,(r['y_min_mm']+r['y_max_mm']-width)/2)
            for x,y in sorted(set((x,y) for x in xs for y in ys)):
                for z in levels:
                    c=evaluate(x,y,z,length,width,yaw)
                    if c is not None:
                        px,py=c['pose']['x_mm'],c['pose']['y_mm']
                        if px-length/2>=r['x_min_mm']-1e-6 and px+length/2<=r['x_max_mm']+1e-6 and py-width/2>=r['y_min_mm']-1e-6 and py+width/2<=r['y_max_mm']+1e-6:
                            region_strata[(r['region_id'],yaw)].append(c)
    for p in placed:
        for yaw in (0,90):
            length,width=item['dimensions'][:2] if yaw==0 else item['dimensions'][:2][::-1]
            for gap in GRID:
                xs=(p['x0'],p['x1']-length,(p['x0']+p['x1']-length)/2)
                ys=(p['y0'],p['y1']-width,(p['y0']+p['y1']-width)/2)
                positions=[('left',p['x0']-length-gap,y) for y in ys]+[('right',p['x1']+gap,y) for y in ys]
                positions += [('front',x,p['y0']-width-gap) for x in xs]+[('back',x,p['y1']+gap) for x in xs]
                for side,x,y in sorted(set(positions)):
                    for z in levels:
                        c=evaluate(x,y,z,length,width,yaw)
                        if c is not None:strata[(gap,side)].append(c)
    def rank(c):return (-geometry_score(c),key(c))
    chosen={}
    # Up to twelve uniformly public directional/gap representatives; never
    # choose strata according to a method's AST, category, or desired direction.
    for group in sorted(strata):
        c=min(strata[group],key=rank)
        if len(chosen)<12:chosen.setdefault(key(c),c)
    # Public region strata are independent of the instruction as well.
    for group in sorted(region_strata):
        if len(chosen)==16:break
        c=min(region_strata[group],key=rank)
        chosen.setdefault(key(c),c)
    for c in sorted(pool.values(),key=rank):
        if len(chosen)==16:break
        chosen.setdefault(key(c),c)
    out=[]
    for c in sorted(chosen.values(),key=key):
        c=copy.deepcopy(c);c['candidate_fingerprint']=digest({'pick':pick,'pose':c['pose'],'size':c['oriented_size_mm'],'version':VERSION})
        c['candidate_id']='E2_'+c['candidate_fingerprint'][:16];out.append(c)
    return out,{'version':VERSION,'sampling_grid_mm':list(GRID),'baseline_candidates':base,
                'baseline_count':len(base),'public_enriched_physical_count':len(pool),
                'public_enumerated_candidates':[{k:c[k] for k in ('candidate_id','pick_item_id','pose','oriented_size_mm')} for c in sorted(pool.values(),key=key)],
                'public_enumeration_attempts':attempted,'boundary_strata':len(strata),'rejections':dict(rejections),
                'returned_count':len(out),'topk_truncated':len(pool)>16,'elapsed_seconds':time.perf_counter()-started}


@lru_cache(maxsize=64)
def _cached_generation(serialized):
    return _generate(*json.loads(serialized))


def generate(state,pick,regions,config):
    started=time.perf_counter()
    public_geometry={k:state[k] for k in ('container','pending_items','placed_items','event_index')}
    candidates,audit=copy.deepcopy(_cached_generation(canonical([public_geometry,pick,regions,config])))
    audit['elapsed_seconds']=time.perf_counter()-started
    audit['memoization']='exact_public_state_v1'
    return candidates,audit
