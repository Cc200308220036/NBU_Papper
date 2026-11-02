"""O4 selector validation, normalization and runtime execution semantics."""
import copy
import math
from .common import CATEGORIES,FIELDS,O4Error,canonical,field_value,validate


def validate_selector(expr, known_ids=None, depth=1):
    if depth>4: raise O4Error('invalid_ast','selector depth exceeds 4')
    op,value=next(iter(expr.items()))
    if op in ('and','or'):
        for child in value: validate_selector(child,known_ids,depth+1)
    elif op=='not': validate_selector(value,known_ids,depth+1)
    elif op=='object_ids':
        if known_ids is not None and not set(value)<=known_ids: raise O4Error('invalid_ast','unknown object')
    elif op!='all':
        kind=FIELDS[value['field']]; v=value['value']
        if op!='eq' and kind!='number': raise O4Error('invalid_ast','ordered comparison needs numeric field')
        if kind=='number' and (isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or v<0):
            raise O4Error('invalid_ast','invalid numeric selector')
        if kind=='boolean' and type(v) is not bool: raise O4Error('invalid_ast','boolean selector')
        if kind=='category' and v not in CATEGORIES: raise O4Error('invalid_ast','unknown category')
        if kind=='weight' and v not in ('light','medium','heavy'): raise O4Error('invalid_ast','unknown weight class')


def validate_policy(ast, observation=None):
    validate('policy',ast)
    ids=None if observation is None else {i['object_id'] for k in ('placed_objects','available_objects') for i in observation[k]}
    rules={r['rule_id']:r for r in ast['rules']}
    if len(rules)!=len(ast['rules']): raise O4Error('invalid_ast','duplicate rule id')
    for r in rules.values():
        for key in ('target','left','right'):
            if key in r: validate_selector(r[key],ids)
        if r['type']=='forbidden_contact' and r['overrides']:
            raise O4Error('invalid_ast','contact exceptions require selector exclusion')
        for other in r['overrides']:
            if other not in rules or rules[other]['priority']<=r['priority'] or rules[other]['type']=='forbidden_contact':
                raise O4Error('invalid_ast','invalid override reference, family or priority')
    return ast


def matches(obj, expr):
    op,value=next(iter(expr.items()))
    if op=='all': return True
    if op=='object_ids': return obj['object_id'] in value
    if op=='and': return all(matches(obj,e) for e in value)
    if op=='or': return any(matches(obj,e) for e in value)
    if op=='not': return not matches(obj,value)
    actual=field_value(obj,value['field']); target=value['value']
    if op=='eq': return actual==target
    if op=='lt': return actual<target
    if op=='le': return actual<=target
    if op=='gt': return actual>target
    if op=='ge': return actual>=target
    raise O4Error('invalid_ast','unknown selector')


def normalized_selector(expr):
    op,v=next(iter(expr.items()))
    if op in ('and','or'):
        children={canonical(normalized_selector(c)):normalized_selector(c) for c in v}
        return {op:[children[k] for k in sorted(children)]}
    if op=='not': return {op:normalized_selector(v)}
    if op=='object_ids': return {op:sorted(v)}
    return copy.deepcopy(expr)


def normalize_policy(ast, observation=None):
    validate_policy(ast,observation)
    # Replace rule IDs by semantic content and referenced semantic content.
    rules={r['rule_id']:r for r in ast['rules']}
    def norm(identifier):
        r=rules[identifier]
        out={k:copy.deepcopy(v) for k,v in r.items() if k not in ('rule_id','overrides','priority')}
        for k in ('target','left','right'):
            if k in out: out[k]=normalized_selector(out[k])
        if out.get('type')=='forbidden_contact':
            sides=sorted([out['left'],out['right']],key=canonical)
            out['left'],out['right']=sides
        out['overrides']=sorted([norm(k) for k in r['overrides']],key=canonical)
        return out
    return {'schema_version':'o4_normalized_v1','rules':sorted([norm(k) for k in rules],key=canonical)}


def resolve_limits(objects, ast):
    limits={}; applicability={}; active={}
    for r in ast['rules']:
        if 'target' in r: applicability[r['rule_id']]=sorted(o['object_id'] for o in objects if matches(o,r['target']))
        else:
            left,right=sorted([r['left'],r['right']],key=canonical)
            applicability[r['rule_id']]={'left':sorted(o['object_id'] for o in objects if matches(o,left)),
                                         'right':sorted(o['object_id'] for o in objects if matches(o,right))}
    for o in objects:
        applicable=[r for r in ast['rules'] if 'target' in r and matches(o,r['target'])]
        excluded={k for r in applicable for k in r['overrides']}
        effective=[r for r in applicable if r['rule_id'] not in excluded]
        active[o['object_id']]=sorted(r['rule_id'] for r in effective)
        vals=[0. if r['type']=='no_top_load' else r['limit'].get('constant_kg',o['labels']['max_top_load_kg']) for r in effective]
        if vals: limits[o['object_id']]=min(vals)
    return limits,applicability,active
