"""Runtime O4 evaluation. No hidden references, no state commits."""
import copy
from .common import O4Error
from .normalize import matches,resolve_limits,validate_policy

LOAD_EPS=1e-6
CONTACT_EPS=1e-6


def bounds(o):
    x,y,z=(o['pose'][k] for k in ('x_mm','y_mm','z_base_mm'))
    l,w,h=o['oriented_size_mm']
    return x-l/2,x+l/2,y-w/2,y+w/2,z,z+h


def reconstruct(objects):
    objects=copy.deepcopy(objects)
    loads={o['object_id']:0. for o in objects}
    edges={}
    for upper in objects:
        a=bounds(upper); supports=[]
        if a[4]>CONTACT_EPS:
            for lower in objects:
                if lower is upper:continue
                b=bounds(lower)
                if abs(b[5]-a[4])<=CONTACT_EPS:
                    area=max(0.,min(a[1],b[1])-max(a[0],b[0]))*max(0.,min(a[3],b[3])-max(a[2],b[2]))
                    if area>0:supports.append((lower['object_id'],area))
        total=sum(v for _,v in supports)
        edges[upper['object_id']]=[(i,a/total) for i,a in supports]
    for o in sorted(objects,key=lambda o:o['pose']['z_base_mm'],reverse=True):
        for i,fraction in edges[o['object_id']]:
            loads[i]+=(o['mass_kg']+loads[o['object_id']])*fraction
    return loads,edges


def contact(a,b):
    a,b=bounds(a),bounds(b)
    for axis in (0,2,4):
        if (abs(a[axis+1]-b[axis])<=CONTACT_EPS or abs(b[axis+1]-a[axis])<=CONTACT_EPS) and all(min(a[k+1],b[k+1])-max(a[k],b[k])>CONTACT_EPS for k in (0,2,4) if k!=axis):return True
    return False


def evaluate_state(objects,ast):
    validate_policy(ast)
    loads,edges=reconstruct(objects)
    limits,applicability,active=resolve_limits(objects,ast)
    violations=[]
    for identifier,limit in limits.items():
        if loads[identifier]>limit+LOAD_EPS:violations.append(f'load:{identifier}')
    pairs=set()
    for i,a in enumerate(objects):
        for b in objects[i+1:]:
            if not contact(a,b):continue
            for r in ast['rules']:
                if r['type']=='forbidden_contact' and ((matches(a,r['left']) and matches(b,r['right'])) or (matches(b,r['left']) and matches(a,r['right']))):
                    pairs.add(tuple(sorted((a['object_id'],b['object_id']))))
    violations += ['contact:'+':'.join(p) for p in sorted(pairs)]
    return {'loads_kg':loads,'support_edges':{i:[[s,f] for s,f in e] for i,e in edges.items()},'limits_kg':limits,
            'applicable_objects':applicability,'active_rules':active,'contact_pairs':[list(p) for p in sorted(pairs)],'violations':sorted(violations)}


def transition(req,candidate):
    found=[o for o in req['available_objects'] if o['object_id']==candidate['pick_item_id']]
    if len(found)!=1:raise O4Error('invalid_candidate','unknown pick object')
    o=copy.deepcopy(found[0]);o.update(pose=copy.deepcopy(candidate['pose']),oriented_size_mm=list(candidate['oriented_size_mm']))
    return [*copy.deepcopy(req['placed_objects']),o]


def evaluate_candidates(req,ast,candidates):
    validate_policy(ast,req)
    before=evaluate_state(req['placed_objects'],ast)
    values=[]
    for c in candidates:
        after=evaluate_state(transition(req,c),ast)
        values.append({'candidate_id':c['candidate_id'],'before':before,'after':after,
                       'new_violations':sorted(set(after['violations'])-set(before['violations'])),
                       'allowed':not after['violations']})
    return {'allowed_ids':sorted(v['candidate_id'] for v in values if v['allowed']),'evaluations':values}
