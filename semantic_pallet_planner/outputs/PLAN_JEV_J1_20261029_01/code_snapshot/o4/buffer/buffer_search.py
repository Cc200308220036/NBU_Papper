"""Bounded deterministic beam search over already-arrived objects only."""
import math
from ..common import digest,O4Error
from ..executor import evaluate_state,bounds
from ...evaluation.geometry_oracle import union_area
from .buffer_state import place,observation
from .buffer_candidates import pools,blocked_reason

DEFAULT={'search_depth':3,'beam_width':8,'max_successor_evaluations':256}


def validate_config(cfg,capacity=3):
    if set(cfg)!=set(DEFAULT) or any(type(v) is not int for v in cfg.values()):raise O4Error('invalid_search_config')
    if not (1<=cfg['search_depth']<=3 and 1<=cfg['beam_width']<=8 and 16*capacity<=cfg['max_successor_evaluations']<=256):
        raise O4Error('invalid_search_config')
    return cfg


def surface(s,ast):
    req=observation(s,'无额外业务硬约束。');objects=req['placed_objects']
    evaluated=evaluate_state(objects,ast);area=0.
    for o in objects:
        if not o['stackable']:continue
        limit=min(o['physical_top_load_limit_kg'],evaluated['limits_kg'].get(o['object_id'],math.inf))
        if limit-evaluated['loads_kg'][o['object_id']]<=1e-6:continue
        a=bounds(o);rectangles=[]
        for b in objects:
            if b is o:continue
            bb=bounds(b)
            if abs(bb[4]-a[5])<=1e-6:
                rect=(max(a[0],bb[0]),min(a[1],bb[1]),max(a[2],bb[2]),min(a[3],bb[3]))
                if rect[1]>rect[0] and rect[3]>rect[2]:rectangles.append(rect)
        area+=(a[1]-a[0])*(a[3]-a[2])-union_area(rectangles)
    height=max((bounds(o)[5] for o in objects),default=0.)
    c=s['container']
    return area/(c['length_mm']*c['width_mm']),height/c['max_height_mm']


def ranked(nodes,*,use_remaining):
    """Global maximum-anchored epsilon groups, never pairwise epsilon sort."""
    def extract(group,tier):
        if len(group)<=1 or tier==5:return sorted(group,key=lambda n:n['tie'])
        if tier==2 and not use_remaining:return extract(group,tier+1)
        result=[];remaining=list(group)
        while remaining:
            best=max(n['score'][tier] for n in remaining)
            tolerance=0. if tier in (0,2) else 1e-12
            tied=[n for n in remaining if n['score'][tier]>=best-tolerance]
            result.extend(extract(tied,tier+1));chosen={id(n) for n in tied}
            remaining=[n for n in remaining if id(n) not in chosen]
        return result
    return extract(list(nodes),0)


def search(s,text,ast,config,root_groups,root_audit,search_config=None):
    cfg=validate_config(search_config or DEFAULT,s['buffer_capacity'])
    before=digest(s);limit=cfg['max_successor_evaluations'];used=root_audit['evaluations']
    trace={'version':'o4_buffer_beam_v1','config':cfg,'evaluations':used,'search_truncated':False,
           'truncation_reasons':[],'nodes':[{'depth':0,'state_digest':before,'audit':root_audit}],
           'leaf_remaining_uniformly_skipped':False,'max_depth':0,'max_beam':1}
    total=math.fsum(math.prod(list(p['item']['dimensions_mm'].values())) for p in s['pending_items'])
    beam=[{'state':s,'path':[],'volume':0.,'tie':[],'score':[0,0,0,*surface(s,ast)[:1],-surface(s,ast)[1]]}]
    leaves=[]
    for depth in range(min(cfg['search_depth'],len(s['pending_items']))):
        children=[]
        for node in beam:
            if depth==0:groups,audit=root_groups,root_audit
            else:
                groups,audit=pools(node['state'],text,ast,config,limit-used)
                if groups is None:
                    trace['search_truncated']=True;trace['truncation_reasons'].append('expansion_budget_reserve')
                    leaves.append(node);continue
                used+=audit['evaluations']
                trace['nodes'].append({'depth':depth,'state_digest':digest(node['state']),'audit':audit})
            viable=[c for g in groups for c in g['eligible']]
            if not viable:leaves.append(node);continue
            for c in sorted(viable,key=lambda c:(c['arrival_index'],c['candidate_fingerprint'])):
                after=place(node['state'],c['raw'])
                v=node['volume']+math.prod(c['oriented_size_mm']);area,height=surface(after,ast)
                path=node['path']+[c]
                children.append({'state':after,'path':path,'volume':v,
                    'tie':node['tie']+[[c['arrival_index'],c['candidate_fingerprint']]],
                    'score':[len(path),v/total if total else 0.,0,area,-height]})
        if not children:break
        beam=ranked(children,use_remaining=False)[:cfg['beam_width']]
        trace['max_depth']=depth+1;trace['max_beam']=max(trace['max_beam'],len(beam))
    leaves.extend(beam)
    # Deduplicate leaves reached both at a dead end and the last active layer.
    unique={digest(n['tie']):n for n in leaves};leaves=list(unique.values())
    any_unknown=False
    for n in sorted(leaves,key=lambda n:n['tie']):
        if not n['state']['pending_items']:n['score'][2]=0;continue
        groups,audit=pools(n['state'],text,ast,config,limit-used)
        if groups is None:
            any_unknown=True;n['score'][2]=None
            trace['search_truncated']=True;trace['truncation_reasons'].append('leaf_budget_reserve')
        else:
            used+=audit['evaluations'];n['score'][2]=sum(g['business_count']>0 for g in groups)
            trace['nodes'].append({'depth':len(n['path']),'leaf_check':True,'state_digest':digest(n['state']),'audit':audit})
    trace['leaf_remaining_uniformly_skipped']=any_unknown
    best=ranked(leaves,use_remaining=not any_unknown)[0]
    trace['leaves']=[{'path':[c['candidate_id'] for c in n['path']],'score':n['score'],'tie':n['tie'],
                     'simulated_state_digest':digest(n['state'])} for n in leaves]
    trace['evaluations']=used
    trace['truncation_reasons']=sorted(set(trace['truncation_reasons']))
    trace['chosen_path']=[{'pick_item_id':c['pick_item_id'],'pose':c['pose'],'candidate_id':c['candidate_id']} for c in best['path']]
    if digest(s)!=before:raise O4Error('simulation_mutated_real_state')
    if used>limit:raise O4Error('search_budget_exceeded')
    return (best['path'][0],None,trace) if best['path'] else (None,blocked_reason(root_groups),trace)
