"""REV1 saved-public F-S floor descriptors. No candidate construction or execution.

Raw bytes are sealed before parsing. Decimal reads JSON number lexemes; Fraction
performs arithmetic without Decimal context rounding. Numeric output is exact
finite decimal text. Runtime observations never enter semantic digests.
"""
from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import time

from .packaging_versions import JM_FS_INPUT, JM_FS_RESULT, JM_FS_ALGORITHM, JM_FS_SCHEMAS

COORDINATE = 'bottom_center_x_right_y_back_z_up_v1'
BUDGET = dict(per_descriptor_q=1000000, scope_q=10000000,
              intersection_bound=20000000, maximal_rectangles=100000)
NUMBER = r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
SCOPE = 'GEOMETRY_DIAGNOSTIC_ONLY_NO_APPLICABILITY_OR_EXECUTION'


class GeometryError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise GeometryError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode())


def _pairs(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result, 'DUPLICATE_JSON_KEY')
        result[k] = v
    return result


def parse_saved(raw, expected_sha256):
    require(type(raw) is bytes and sha(raw) == expected_sha256, 'INPUT_DIGEST_MISMATCH')
    try:
        return json.loads(raw, parse_int=Decimal, parse_float=Decimal,
                          object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(GeometryError('NONFINITE_NUMBER')))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, GeometryError):
            raise
        raise GeometryError('INVALID_JSON') from exc


def number(value):
    require(type(value) in (int, Decimal, str), 'NUMBER_TYPE')
    if type(value) is str:
        require(re.fullmatch(NUMBER, value) is not None, 'NUMBER_SYNTAX')
    n = Decimal(value)
    require(n.is_finite(), 'NONFINITE_NUMBER')
    return Fraction(n)


def text(n):
    """Exact terminating decimal, independent of Decimal's global precision."""
    n = Fraction(n)
    sign = '-' if n < 0 else ''
    numerator, denominator = abs(n.numerator), n.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    require(denominator == 1, 'NONTERMINATING_INTERNAL_NUMBER')
    scale = max(twos, fives)
    digits = str(numerator * 2 ** (scale - twos) * 5 ** (scale - fives))
    if scale:
        digits = digits.zfill(scale + 1)
        digits = (digits[:-scale] + '.' + digits[-scale:]).rstrip('0').rstrip('.')
    return sign + digits if n else '0'


def normalize(value):
    if type(value) is Decimal:
        return text(number(value))
    if isinstance(value, list):
        return [normalize(x) for x in value]
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    return value


def validate_schema(value, name):
    """Closed local subset; validates Decimal lexemes without float conversion."""
    spec = json.loads((Path(__file__).with_name('schemas') / (name + '.schema.json')).read_text())
    def check(v, s):
        supported = {'$schema','title','type','properties','required','additionalProperties','items',
                     'minItems','maxItems','minLength','pattern','enum','const','anyOf',
                     'minimum','exclusiveMinimum'}
        require(not set(s) - supported, 'UNSUPPORTED_SCHEMA_KEYWORD')
        if 'anyOf' in s:
            for branch in s['anyOf']:
                try:
                    check(v, branch)
                    return
                except GeometryError:
                    pass
            raise GeometryError('SCHEMA')
        if 'const' in s:
            require(type(v) is type(s['const']) and v == s['const'], 'SCHEMA')
        if 'enum' in s:
            require(any((type(v) is type(x) or type(v) is Decimal and type(x) is int) and v == x for x in s['enum']), 'SCHEMA')
        kind = s.get('type')
        types = dict(object=dict, array=list, string=str, boolean=bool, null=type(None), integer=int)
        if kind == 'number':
            require(type(v) in (int, Decimal, float), 'SCHEMA')
            if type(v) is float:
                require(math.isfinite(v), 'NONFINITE_NUMBER')
            else:
                number(v)
        elif kind == 'integer':
            require(type(v) is int or type(v) is Decimal and v.is_finite() and v == v.to_integral_value(), 'SCHEMA')
        elif kind:
            require(type(v) is types[kind], 'SCHEMA')
        if kind == 'object':
            require(set(s['required']) <= set(v), 'SCHEMA_MISSING_FIELD')
            require(s.get('additionalProperties') is False and set(v) <= set(s['properties']), 'SCHEMA_EXTRA_FIELD')
            for k, x in v.items():
                check(x, s['properties'][k])
        if kind == 'array':
            require(s.get('minItems', 0) <= len(v) <= s.get('maxItems', len(v)), 'SCHEMA_ARRAY_BOUND')
            for x in v:
                check(x, s['items'])
        if kind == 'string':
            require(len(v) >= s.get('minLength', 0), 'SCHEMA')
            if 'pattern' in s:
                require(re.fullmatch(s['pattern'], v) is not None, 'SCHEMA')
        if 'minimum' in s:
            require(v >= s['minimum'], 'SCHEMA')
        if 'exclusiveMinimum' in s:
            require(v > s['exclusiveMinimum'], 'SCHEMA')
    check(value, spec)
    return value


def from_saved_public(state_raw, pool_raw, *, state_sha256, pool_sha256,
                      mode='FULL_POOL', contrast=None):
    """Project existing A1 public geometry only; never read private task/future data.

    Original A1 public schema is checked before dropping packaging attributes.
    Saved pool rows are opaque except exact actions; no scores are consumed.
    """
    state = parse_saved(state_raw, state_sha256)
    pool = parse_saved(pool_raw, pool_sha256)
    require(type(pool) is list, 'SAVED_POOL_TYPE')
    actions = []
    for row in pool:
        require(type(row) is dict, 'SAVED_POOL_TYPE')
        try:
            actions.append({k: row[k] for k in ('candidate_id','pick_item_id','pose','oriented_size_mm')})
        except KeyError as exc:
            raise GeometryError('SAVED_ACTION_MISSING') from exc
    # The old input permits explicit null observations; missing optional values
    # remain distinguishable from malformed required structures in the new input.
    old = dict(version='jev_jm_scenario_input_v1', coordinate=COORDINATE,
               state=state, pool=actions, pool_receipt=dict(complete=True, count=len(pool), digest=pool_sha256))
    validate_schema(old, 'jm_scenario_input_v1')
    def obj(o, placed):
        keys = ('item_id','size_mm','pose','oriented_size_mm') if placed else ('item_id','size_mm')
        return {k: o.get(k) for k in keys}
    v = dict(version=JM_FS_INPUT, coordinate=COORDINATE, precision='SAVED_LEXEMES',
             state=dict(container={k:state['container'][k] for k in ('length_mm','width_mm','max_height_mm')},
                        buffer=[obj(o, False) for o in state['buffer']],
                        placed_objects=[obj(o, True) for o in state['placed_objects']]),
             pool=actions, descriptor_scope=dict(mode=mode, contrast=contrast),
             provenance=dict(state_sha256=state_sha256, pool_sha256=pool_sha256))
    raw = json.dumps(normalize(v), sort_keys=True, separators=(',', ':')).encode()
    return raw, sha(raw)


def bounds(o):
    p = o['pose']
    x,y,z = (number(p[k]) for k in ('x_mm','y_mm','z_base_mm'))
    l,w,h = map(number, o['oriented_size_mm'])
    return (x-l/2, x+l/2, y-w/2, y+w/2, z, z+h)


def overlap(a, b):
    return a[0] < b[1] and b[0] < a[1] and a[2] < b[3] and b[2] < a[3]


def volume_overlap(a, b):
    return overlap(a,b) and a[4] < b[5] and b[4] < a[5]


def direction(a, b):
    if a is None or b is None:
        return 'UNKNOWN'
    a,b = set(a),set(b)
    return ('B_STRICT_SUPERSET' if b > a else 'A_STRICT_SUPERSET' if a > b else
            'NO_DIRECTION' if a == b else 'TRADEOFF')


def _descriptor(domain, occupied, height):
    obstacles = sorted(set(tuple(b[:4]) for b in occupied if b[4] < height and b[5] > 0))
    xs = sorted({domain[0],domain[1]} | {x for b in obstacles for x in b[:2]})
    ys = sorted({domain[2],domain[3]} | {y for b in obstacles for y in b[2:]})
    q = len(xs)*(len(xs)-1)//2 * (len(ys)*(len(ys)-1)//2)
    return dict(xs=xs, ys=ys, obstacles=obstacles, q=q, m=len(obstacles),
                height=height, occupied=occupied)


def _descriptor_items(descriptors):
    return sorted(descriptors.items())


def _rectangles(d, counters, remaining_output):
    xs,ys,obs = d['xs'],d['ys'],d['obstacles']
    def empty(r):
        counters['emptiness_tests'] += 1
        for b in obs:
            counters['intersection_tests'] += 1
            if overlap(r,b):
                return False
        return True
    maximal = []
    # Four neighbor expansions include maximality cost in the preflight 5Q bound.
    for i,j in itertools.combinations(range(len(xs)),2):
        for k,l in itertools.combinations(range(len(ys)),2):
            counters['enumerated_rectangles'] += 1
            r = (xs[i],xs[j],ys[k],ys[l])
            if not empty(r):
                continue
            neighbors = []
            if i: neighbors.append((xs[i-1],xs[j],ys[k],ys[l]))
            if j+1 < len(xs): neighbors.append((xs[i],xs[j+1],ys[k],ys[l]))
            if k: neighbors.append((xs[i],xs[j],ys[k-1],ys[l]))
            if l+1 < len(ys): neighbors.append((xs[i],xs[j],ys[k],ys[l+1]))
            if any(empty(n) for n in neighbors):
                continue
            maximal.append(r)
            if len(maximal) > remaining_output:
                raise GeometryError('OUTPUT_BOUND_EXCEEDED')
    return sorted(maximal)


def clearance(r, occupied, height):
    """Low-level net-height probe on validated exact geometry; degenerate is NA.

    Not invoked per enumerated rectangle: descriptor obstruction at its query
    height already certifies that height. Probe costs len(occupied) XY tests.
    """
    if r[0]>=r[1] or r[2]>=r[3]:
        return None
    hits = [b[4] for b in occupied if overlap(r,b)]
    return min([height] + hits)


def _prepare(v):
    s=v['state']; c=s['container']
    dims=[number(c[k]) for k in ('length_mm','width_mm','max_height_mm')]
    require(all(x>0 for x in dims), 'NONPOSITIVE_SIZE')
    L,W,H=dims; domain=(-L/2,L/2,-W/2,W/2)
    ids=[o['item_id'] for o in s['buffer']+s['placed_objects']]
    require(len(set(ids))==len(ids),'DUPLICATE_OBJECT_ID')
    unknown = v['precision']=='UNKNOWN'
    for o in s['buffer']+s['placed_objects']:
        if o['size_mm'] is None:
            unknown=True
        else:
            require(all(number(x)>0 for x in o['size_mm']),'NONPOSITIVE_SIZE')
    def check_pose(o):
        nonlocal unknown
        if o['pose'] is not None:
            p=o['pose']; yaw=number(p['yaw_deg'])
            require(yaw in (0,90),'INVALID_YAW')
            require(number(p['z_base_mm'])>=0,'NEGATIVE_BASE')
        if o['oriented_size_mm'] is not None:
            size=list(map(number,o['oriented_size_mm']))
            require(all(x>0 for x in size),'NONPOSITIVE_SIZE')
        if o['pose'] is None or o['oriented_size_mm'] is None:
            unknown=True
            return None
        if o['size_mm'] is not None:
            orig=list(map(number,o['size_mm']))
            require(size == (orig if yaw==0 else [orig[1],orig[0],orig[2]]),'ORIENTATION_SIZE_MISMATCH')
        b=bounds(o)
        require(domain[0]<=b[0]<b[1]<=domain[1] and domain[2]<=b[2]<b[3]<=domain[3]
                and b[5]<=H,'OUT_OF_CONTAINER')
        return b
    occupied=[]
    for o in s['placed_objects']:
        b=check_pose(o)
        if b is not None:
            require(not any(volume_overlap(b,x) for x in occupied),'PLACED_OVERLAP')
            occupied.append(b)
    boxes={o['item_id']:o for o in s['buffer']}
    actions={}
    for a in v['pool']:
        require(a['candidate_id'] not in actions,'DUPLICATE_CANDIDATE_ID')
        require(a['pick_item_id'] in boxes,'ACTION_NOT_IN_BUFFER')
        b=check_pose(dict(a,size_mm=boxes[a['pick_item_id']]['size_mm']))
        if b is not None:
            require(not any(volume_overlap(b,x) for x in occupied),'ACTION_OVERLAP')
        actions[a['candidate_id']]=(a,b)
    return domain,H,boxes,occupied,actions,unknown


def evaluate(raw, *, expected_sha256):
    """Evaluate a sealed closed request. No IO except static package Schema reads.

    Descriptor cache is local to one complete input/scope, so partial results or
    stale cross-version cache entries cannot escape. All deterministic output is
    under semantic; observations contain wall time only (caller may add memory).
    """
    start=time.perf_counter()
    counters=dict(enumerated_rectangles=0,emptiness_tests=0,intersection_tests=0,
                  output_rectangles=0,sort_items=0,cache_reuses=0)
    semantic=dict(version=JM_FS_RESULT, scope=SCOPE, algorithm=JM_FS_ALGORITHM,
                  budget=BUDGET.copy(), budget_digest=digest(BUDGET),
                  input_sha256=sha(raw) if type(raw) is bytes else None,
                  input_semantic_digest=None, scope_digest=None, descriptor_scope=None,
                  status='INVALID_INPUT', reason='INVALID_INPUT', descriptors=[], actions=[],
                  contrast=dict(status='UNKNOWN',reason='NO_CONTRAST',A=None,B=None,direction='UNKNOWN'),
                  preflight=dict(descriptors=0,sum_q=0,intersection_bound=0),
                  cost=counters, online_injection='NOT_IMPLEMENTED', execution_eligible=False)
    try:
        v=parse_saved(raw,expected_sha256)
        # Numeric JSON tokens and explicitly allowed decimal strings converge
        # without ever passing through binary float.
        v=normalize(v)
        validate_schema(v,JM_FS_SCHEMAS[JM_FS_INPUT])
        # Canonicalize explicitly permitted decimal strings as well as tokens.
        # No identifiers or arbitrary strings are interpreted as numbers.
        c=v['state']['container']
        for k in c:c[k]=text(number(c[k]))
        for o in v['state']['buffer']+v['state']['placed_objects']+v['pool']:
            for k in ('size_mm','oriented_size_mm'):
                if o.get(k) is not None:o[k]=[text(number(x)) for x in o[k]]
            if o.get('pose') is not None:
                o['pose']={k:text(number(x)) for k,x in o['pose'].items()}
        # Validate all numeric fields even when another observation is unknown.
        domain,H,boxes,occupied,actions,unknown=_prepare(v)
        canonical=json.loads(json.dumps(v))
        canonical.pop('provenance')
        canonical['pool'].sort(key=lambda a:a['candidate_id'])
        canonical['state']['buffer'].sort(key=lambda a:a['item_id'])
        canonical['state']['placed_objects'].sort(key=lambda a:a['item_id'])
        semantic['input_semantic_digest']=digest(canonical)
        mode=v['descriptor_scope']['mode']; pair=v['descriptor_scope']['contrast']
        require(pair is None or (pair[0]!=pair[1] and all(k in actions for k in pair)), 'CONTRAST_BINDING')
        require(mode!='HISTORICAL_AB' or pair is not None,'CONTRAST_REQUIRED')
        members=sorted(actions) if mode=='FULL_POOL' else sorted(pair)
        scope=dict(mode=mode,action_ids=members,contrast=pair)
        semantic['descriptor_scope']=scope
        semantic['scope_digest']=digest(dict(input=semantic['input_semantic_digest'],scope=scope,
                                            algorithm=JM_FS_ALGORITHM,budget=BUDGET))
        if unknown:
            semantic.update(status='UNKNOWN',reason='UNKNOWN_OBSERVATION_OR_PRECISION')
        else:
            descriptors={}; action_keys={}
            for cid in members:
                a,b=actions[cid]
                row=dict(candidate_id=cid,status='NOT_APPLICABLE',reason='NONFLOOR_ACTION',fit_ids=None,members=[])
                semantic['actions'].append(row)
                if b[4]!=0:
                    continue
                row.update(status='VALUE',reason='FLOOR_DESCRIPTOR',fit_ids=[])
                remaining=[o for key,o in sorted(boxes.items()) if key!=a['pick_item_id']]
                occ=sorted(occupied+[b])
                keys={}
                for o in remaining:
                    h=number(o['size_mm'][2])
                    if h>H: continue
                    key=digest(dict(scope=semantic['scope_digest'],occupied=[[text(x) for x in z] for z in occ],height=text(h)))
                    keys[h]=key
                    if key not in descriptors:
                        descriptors[key]=_descriptor(domain,occ,h)
                        descriptors[key]['action_ids']=[]
                    else:
                        counters['cache_reuses']+=1
                    if cid not in descriptors[key]['action_ids']:descriptors[key]['action_ids'].append(cid)
                action_keys[cid]=(remaining,keys)
            totalq=sum(d['q'] for d in descriptors.values())
            bound=sum(5*d['q']*max(1,d['m']) for d in descriptors.values())
            semantic['preflight']=dict(descriptors=len(descriptors),sum_q=totalq,intersection_bound=bound)
            if (any(d['q']>BUDGET['per_descriptor_q'] for d in descriptors.values()) or
                    totalq>BUDGET['scope_q'] or bound>BUDGET['intersection_bound']):
                raise GeometryError('COMPUTE_BOUND_EXCEEDED')
            computed={}
            for key,d in _descriptor_items(descriptors):
                rects=_rectangles(d,counters,BUDGET['maximal_rectangles']-counters['output_rectangles'])
                counters['output_rectangles']+=len(rects);counters['sort_items']+=len(rects)
                areas=[(r[1]-r[0])*(r[3]-r[2]) for r in rects]
                maxarea=max(areas,default=Fraction(0))
                encoded=[[text(x) for x in r] for r in rects]
                record=dict(key=key,height_mm=text(d['height']),action_ids=sorted(d['action_ids']),
                            q=d['q'],obstacles=d['m'],maximal_rectangles=encoded,
                            maximum_area_mm2=text(maxarea),
                            maximum_rectangles=[e for e,area in zip(encoded,areas) if area==maxarea])
                semantic['descriptors'].append(record)
                computed[key]=rects
            semantic['descriptors'].sort(key=lambda row:row['key'])
            for row in semantic['actions']:
                cid=row['candidate_id']
                if cid not in action_keys:continue
                remaining,keys=action_keys[cid]
                for o in remaining:
                    l,w,h=map(number,o['size_mm']); variants=[]
                    for yaw,dx,dy in [(0,l,w),(90,w,l)]:
                        key=keys.get(h)
                        witness=next((r for r in computed.get(key,[]) if dx<=r[1]-r[0] and dy<=r[3]-r[2]),None)
                        variants.append(dict(yaw_deg=yaw,fits=witness is not None,
                                             witness=None if witness is None else [text(x) for x in witness],
                                             descriptor_key=key, reason='BOX_ABOVE_CONTAINER' if h>H else 'EXACT_2D_TEST'))
                    row['members'].append(dict(item_id=o['item_id'],orientations=variants))
                    if any(x['fits'] for x in variants):row['fit_ids'].append(o['item_id'])
            semantic.update(status='VALUE',reason='COMPLETE_SCOPE')
            if members and not action_keys:
                semantic.update(status='NOT_APPLICABLE',reason='NO_FLOOR_ACTIONS')
        if pair is not None:
            a,b=(actions[k][0] for k in pair)
            eligible=(a['pick_item_id']==b['pick_item_id'] and a['pose']['yaw_deg']==b['pose']['yaw_deg']
                      and number(a['pose']['z_base_mm'])==number(b['pose']['z_base_mm'])==0
                      and a['pose']!=b['pose'])
            rows={r['candidate_id']:r for r in semantic['actions']}
            if not eligible:
                semantic['contrast']=dict(status='NOT_APPLICABLE',reason='NOT_FS_FLOOR_TRANSLATION',A=pair[0],B=pair[1],direction='UNKNOWN')
            elif semantic['status']=='VALUE':
                semantic['contrast']=dict(status='VALUE',reason='EXACT_IDENTITY_SETS',A=pair[0],B=pair[1],
                                          direction=direction(rows[pair[0]]['fit_ids'],rows[pair[1]]['fit_ids']))
            else:
                semantic['contrast']=dict(status='UNKNOWN',reason=semantic['reason'],A=pair[0],B=pair[1],direction='UNKNOWN')
    except GeometryError as exc:
        reason=str(exc)
        status='UNKNOWN' if reason in ('COMPUTE_BOUND_EXCEEDED','OUTPUT_BOUND_EXCEEDED') else 'INVALID_INPUT'
        semantic.update(status=status,reason=reason,descriptors=[],actions=[])
        semantic['contrast'].update(status=status,reason=reason,direction='UNKNOWN')
    semantic['semantic_digest']=digest({k:v for k,v in semantic.items() if k not in ('input_sha256','cost')})
    result=dict(semantic=semantic,observations=dict(elapsed_s=time.perf_counter()-start))
    validate_schema(result,JM_FS_SCHEMAS[JM_FS_RESULT])
    return result
