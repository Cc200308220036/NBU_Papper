"""Independent reference interpreter: no executor/normalize/compiler imports.

Compute each box's downward forces recursively, instead of the runtime's
reverse-height aggregate propagation. Explicit reference policies are private.
"""
import copy
import itertools
from .common import canonical


def _accept(o,s):
    if 'all' in s:return s['all']
    if 'object_ids' in s:return o['object_id'] in s['object_ids']
    if 'and' in s:return all(_accept(o,c) for c in s['and'])
    if 'or' in s:return any(_accept(o,c) for c in s['or'])
    if 'not' in s:return not _accept(o,s['not'])
    op=next(iter(s));entry=s[op];a=o
    for part in entry['field'].split('.'):a=a[part]
    b=entry['value']
    return {'eq':lambda:a==b,'lt':lambda:a<b,'le':lambda:a<=b,'gt':lambda:a>b,'ge':lambda:a>=b}[op]()


def _box(o):
    p=o['pose'];dims=o['oriented_size_mm']
    return [(p['x_mm']-dims[0]/2,p['x_mm']+dims[0]/2),
            (p['y_mm']-dims[1]/2,p['y_mm']+dims[1]/2),(p['z_base_mm'],p['z_base_mm']+dims[2])]


def reference_state(objects,policy):
    boxes={o['object_id']:_box(o) for o in objects}
    loads={o['object_id']:0. for o in objects};edges={}
    for o in objects:
        identifier=o['object_id'];a=boxes[identifier];support={}
        for lower in objects:
            j=lower['object_id'];b=boxes[j]
            if identifier!=j and a[2][0]>1e-6 and abs(a[2][0]-b[2][1])<=1e-6:
                area=1.
                for axis in (0,1):area*=max(0,min(a[axis][1],b[axis][1])-max(a[axis][0],b[axis][0]))
                if area>0:support[j]=area
        total=sum(support.values())
        edges[identifier]=[(j,area/total) for j,area in support.items()]
    def distribute(identifier,weight,visiting):
        if identifier in visiting:raise ValueError('cyclic support graph')
        for lower,fraction in edges[identifier]:
            part=weight*fraction;loads[lower]+=part
            distribute(lower,part,visiting|{identifier})
    for o in objects:distribute(o['object_id'],o['mass_kg'],set())
    applicability={};active={};limits={};bad=[]
    for r in policy['rules']:
        if 'target' in r:applicability[r['rule_id']]=sorted(o['object_id'] for o in objects if _accept(o,r['target']))
        else:
            sides=sorted((r['left'],r['right']),key=canonical)
            applicability[r['rule_id']]={side:sorted(o['object_id'] for o in objects if _accept(o,expr)) for side,expr in zip(('left','right'),sides)}
    for o in objects:
        candidates=[r for r in policy['rules'] if 'target' in r and _accept(o,r['target'])]
        remaining=[]
        for r in candidates:
            if not any(r['rule_id'] in other['overrides'] for other in candidates):remaining.append(r)
        identifier=o['object_id'];active[identifier]=sorted(r['rule_id'] for r in remaining)
        thresholds=[]
        for r in remaining:
            if r['type']=='no_top_load':thresholds.append(0.)
            elif 'constant_kg' in r['limit']:thresholds.append(r['limit']['constant_kg'])
            else:thresholds.append(o['labels']['max_top_load_kg'])
        if thresholds:
            limits[identifier]=min(thresholds)
            if loads[identifier]-limits[identifier]>1e-6:bad.append('load:'+identifier)
    pairs=[]
    for a,b in itertools.combinations(objects,2):
        aa,bb=boxes[a['object_id']],boxes[b['object_id']]
        touches=False
        for axis in range(3):
            separation=min(abs(aa[axis][1]-bb[axis][0]),abs(bb[axis][1]-aa[axis][0]))
            overlap=all(min(aa[k][1],bb[k][1])-max(aa[k][0],bb[k][0])>1e-6 for k in range(3) if k!=axis)
            touches=touches or (separation<=1e-6 and overlap)
        forbidden=any(r['type']=='forbidden_contact' and ((_accept(a,r['left']) and _accept(b,r['right'])) or (_accept(b,r['left']) and _accept(a,r['right']))) for r in policy['rules'])
        if touches and forbidden:
            pair=sorted([a['object_id'],b['object_id']]);pairs.append(pair);bad.append('contact:'+':'.join(pair))
    return {'loads_kg':loads,'support_edges':{i:[[s,f] for s,f in e] for i,e in edges.items()},'limits_kg':limits,
            'applicable_objects':applicability,'active_rules':active,'contact_pairs':sorted(pairs),'violations':sorted(bad)}


def audit_reference(req,policy,candidates):
    before=reference_state(req['placed_objects'],policy);rows=[]
    for c in candidates:
        item=copy.deepcopy(next(i for i in req['available_objects'] if i['object_id']==c['pick_item_id']))
        item['pose']=copy.deepcopy(c['pose']);item['oriented_size_mm']=list(c['oriented_size_mm'])
        after=reference_state([*copy.deepcopy(req['placed_objects']),item],policy)
        rows.append({'candidate_id':c['candidate_id'],'before':before,'after':after,
                     'new_violations':sorted(set(after['violations'])-set(before['violations'])),'allowed':len(after['violations'])==0})
    return {'allowed_ids':sorted(r['candidate_id'] for r in rows if r['allowed']),'evaluations':rows}


def semantic_signature(policy):
    """ID/order invariant declarative comparison; deliberately independent."""
    lookup={r['rule_id']:r for r in policy['rules']}
    def selector(s):
        if 'and' in s or 'or' in s:
            op=next(iter(s));return {op:sorted({canonical(selector(c)) for c in s[op]})}
        if 'not' in s:return {'not':selector(s['not'])}
        if 'object_ids' in s:return {'object_ids':sorted(s['object_ids'])}
        return s
    def rule(r):
        out={k:v for k,v in r.items() if k not in ('rule_id','priority','overrides')}
        for key in ('target','left','right'):
            if key in out:out[key]=selector(out[key])
        if 'left' in out:
            out['left'],out['right']=sorted([out['left'],out['right']],key=canonical)
        out['overrides']=sorted([rule(lookup[k]) for k in r['overrides']],key=canonical)
        return out
    return sorted([rule(r) for r in policy['rules']],key=canonical)


def compare_policies(actual,reference,witness_objects=()):
    syntactic=actual==reference
    semantic=semantic_signature(actual)==semantic_signature(reference)
    # Enumerate declared finite facts, including thresholds not triggered now.
    witnesses=[]
    probes=list(witness_objects)
    if probes:
        prototype=probes[0]
        for category,reinforced,no_top,fragile in itertools.product(
                ('food','glassware','electronics','household_cleaner','general'),(False,True),(False,True),(False,True)):
            obj=copy.deepcopy(prototype)
            obj.update(cargo_category=category,fragile=fragile,packaging={'reinforced':reinforced},
                       labels={'no_top_load':no_top,'max_top_load_kg':3.})
            probes.append(obj)
    for o in probes:
        for load in (0.,.5,1.,2.,3.,5.,8.,20.):
            item=copy.deepcopy(o)
            # Zero-height-free witness uses an explicit upper object at target load.
            item.update(pose={'x_mm':0,'y_mm':0,'z_base_mm':0,'yaw_deg':0},oriented_size_mm=[100,100,100])
            top=copy.deepcopy(item);top['object_id']='__witness_top__';top['mass_kg']=load;top['pose']['z_base_mm']=100
            a=reference_state([item,top],actual);b=reference_state([item,top],reference)
            if a['limits_kg']!=b['limits_kg'] or a['violations']!=b['violations']:witnesses.append({'object_id':o['object_id'],'load_kg':load})
    return {'raw_ast_equal':syntactic,'semantic_equal':semantic,'finite_domain_equal':not witnesses,
            'probe_scope':'observed objects plus 40 category/boolean combinations x 8 load values; not an equivalence proof',
            'probe_count':len(probes)*8,'counterexamples':witnesses}
