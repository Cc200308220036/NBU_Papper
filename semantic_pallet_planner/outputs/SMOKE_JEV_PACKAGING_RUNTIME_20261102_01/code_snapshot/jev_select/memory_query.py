"""Public-only offline query v1. No task, provenance, scores or credential inputs.

Numbers use six decimal places at most; lengths mm, mass kg, angles deg.
ASCII English tokens only; Chinese is retained in bodies but is not segmented.
"""
from __future__ import annotations

import math
import re
from .contracts import JevSelectError, canonical, digest, validate_schema

TOKENIZER_VERSION = 'english_ascii_numeric_6dp_v1'
QUERY_VERSION = 'jev_memory_query_v1'
GATE_FIELDS = {
    'placed_count': 'number', 'available_count': 'number', 'candidate_count': 'number',
    'layout_height_mm': 'number', 'max_available_mass_kg': 'number',
    'min_support_ratio': 'number', 'buffer_capacity': 'number',
    'container_length_mm': 'number', 'container_width_mm': 'number',
    'container_max_height_mm': 'number', 'container_max_payload_kg': 'number',
    'available_categories': 'set', 'policy_terms': 'set',
}
OPERATORS = ('eq', 'ne', 'lt', 'le', 'gt', 'ge', 'contains')
OBJECT_FIELDS = {'object_id', 'mass_kg', 'dimensions_mm', 'stackable', 'fragile',
    'weight_class', 'cargo_category', 'packaging', 'labels', 'physical_top_load_limit_kg',
    'pose', 'oriented_size_mm', 'current_top_load_kg'}
FEATURE_FIELDS = {'geometry_score', 'geometry_components', 'support_ratio', 'com_margin_mm',
    'supported_by', 'resulting_max_height_mm', 'resulting_volume_utilization',
    'heavy_low_quality', 'heavy_center_quality'}


def tokenize(text):
    text = re.sub(r'\b(?:[bcrh]\d+|scn_\d+|item_\d+)\b', ' ', text.lower())
    tokens = re.findall(r'[a-z]+(?:_[a-z]+)*|[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?', text)
    result=[]
    for token in tokens:
        if re.fullmatch(r'[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?',token):
            number=float(token)
            if not math.isfinite(number): raise JevSelectError('invalid_query_number')
            token = format(number,'.6f').rstrip('0').rstrip('.') if number else '0'
        result.append('0' if token == '-0' else token)
    return result


def _closed(value, fields):
    if not isinstance(value, dict) or set(value) - set(fields):
        raise JevSelectError('nonpublic_memory_query_field')


def _number(value):
    if type(value) not in (int,float): raise JevSelectError('invalid_public_fact_type')
    canonical(value)


def _object(obj):
    _closed(obj, OBJECT_FIELDS)
    for key, fields in [('dimensions_mm', {'length','width','height'}),
                        ('pose', {'x_mm','y_mm','z_base_mm','yaw_deg'}),
                        ('packaging', {'reinforced'}), ('labels', {'max_top_load_kg','no_top_load'})]:
        if key in obj: _closed(obj[key], fields)
    numeric = {'mass_kg','physical_top_load_limit_kg','current_top_load_kg'}
    for k,v in obj.items():
        if k in numeric: _number(v)
        elif k in ('stackable','fragile') and type(v) is not bool: raise JevSelectError('invalid_public_fact_type')
        elif k in ('object_id','cargo_category','weight_class') and not isinstance(v,str): raise JevSelectError('invalid_public_fact_type')
        elif k in ('dimensions_mm','pose'):
            for x in v.values(): _number(x)
        elif k == 'oriented_size_mm':
            if not isinstance(v,list) or len(v)!=3: raise JevSelectError('invalid_public_fact_type')
            for x in v: _number(x)
        elif k in ('labels','packaging'):
            for field,x in v.items():
                if field == 'max_top_load_kg': _number(x)
                elif type(x) is not bool: raise JevSelectError('invalid_public_fact_type')
    return {k:v for k,v in obj.items() if k != 'object_id'}


def build_query(public_observation, public_policy, candidate_facts):
    """Accept only the public model-state projection and English public descriptions.

    Candidate keys are local handles and never become query tokens. The public
    policy is {english_descriptions: [str]}, never PublicPolicyContext/private AST.
    Missing facts remain absent (unknown), never substituted with guessed zeros.
    """
    _closed(public_observation, {'units','container','placed_objects','available_objects',
        'regions','buffer','business_requirements','objective','coordinate_convention',
        'business_attribute_source','memories'})
    _closed(public_policy, {'english_descriptions'})
    if public_observation.get('memories'):
        raise JevSelectError('memory_query_recursive_input')
    obs = public_observation
    if 'units' in obs and obs['units'] != {'length':'mm','mass':'kg'}:
        raise JevSelectError('memory_query_units')
    if 'business_requirements' in obs:
        _closed(obs['business_requirements'], {'original_text','english_descriptions'})
    descriptions = public_policy.get('english_descriptions', [])
    if not isinstance(descriptions, list) or any(not isinstance(x,str) for x in descriptions):
        raise JevSelectError('invalid_public_policy_text')
    facts = {}; projection = {'policy': descriptions}
    for key in ('placed_objects','available_objects'):
        if key in obs:
            projection[key] = [_object(o) for o in obs[key]]
            facts['placed_count' if key == 'placed_objects' else 'available_count'] = len(obs[key])
    available = obs.get('available_objects')
    if available is not None:
        if all('cargo_category' in o for o in available):
            facts['available_categories'] = sorted({o['cargo_category'].lower() for o in available})
        if available and all('mass_kg' in o for o in available):
            facts['max_available_mass_kg'] = max(o['mass_kg'] for o in available)
    if 'placed_objects' in obs:
        placed = obs['placed_objects']
        if all('pose' in o and 'oriented_size_mm' in o for o in placed):
            facts['layout_height_mm'] = max((o['pose']['z_base_mm']+o['oriented_size_mm'][2] for o in placed), default=0)
    if 'container' in obs:
        _closed(obs['container'], {'length_mm','width_mm','max_height_mm','max_payload_kg'})
        projection['container'] = obs['container']
        for v in obs['container'].values(): _number(v)
        facts.update({'container_'+k:v for k,v in obs['container'].items()})
    if 'buffer' in obs:
        _closed(obs['buffer'], {'capacity','pending','end_of_stream'})
        if 'capacity' in obs['buffer']:
            _number(obs['buffer']['capacity'])
            facts['buffer_capacity'] = obs['buffer']['capacity']
    if 'regions' in obs:
        for r in obs['regions']:
            _closed(r, {'region_id','x_min_mm','x_max_mm','y_min_mm','y_max_mm'})
            for k,v in r.items():
                if k != 'region_id': _number(v)
        projection['regions'] = [{k:v for k,v in r.items() if k != 'region_id'} for r in obs['regions']]
    rows = []
    if not isinstance(candidate_facts, dict): raise JevSelectError('invalid_candidate_facts')
    for c in candidate_facts.values():
        _closed(c, {'pick_object','pose','oriented_size_mm','features','load_changes'})
        _closed(c.get('features', {}), FEATURE_FIELDS)
        if 'pose' in c:
            _closed(c['pose'], {'x_mm','y_mm','z_base_mm','yaw_deg'})
            for v in c['pose'].values(): _number(v)
        if 'oriented_size_mm' in c:
            if not isinstance(c['oriented_size_mm'],list) or len(c['oriented_size_mm'])!=3: raise JevSelectError('invalid_public_fact_type')
            for v in c['oriented_size_mm']: _number(v)
        f = c.get('features', {})
        for key,v in f.items():
            if key not in ('supported_by','geometry_components') and not (key in ('heavy_low_quality','heavy_center_quality') and v is None): _number(v)
        if 'geometry_components' in f:
            _closed(f['geometry_components'], {'balance','compactness','height','stability'})
            for v in f['geometry_components'].values(): _number(v)
        changes=[]
        for change in c.get('load_changes', []):
            _closed(change, {'object_id','before_top_load_kg','after_top_load_kg'})
            for k,v in change.items():
                if k != 'object_id': _number(v)
            changes.append({k:v for k,v in change.items() if k != 'object_id'})
        rows.append({**{k:v for k,v in c.items() if k in ('pose','oriented_size_mm')},
                     'features':{k:v for k,v in f.items() if k != 'supported_by' and v is not None}, 'load_changes':changes})
    projection['candidates'] = sorted(rows, key=canonical)
    facts['candidate_count'] = len(rows)
    if rows and all('support_ratio' in r['features'] for r in rows):
        facts['min_support_ratio'] = min(r['features']['support_ratio'] for r in rows)
    facts['policy_terms'] = sorted(set(tokenize(' '.join(descriptions))))
    tokens = sorted(set(tokenize(canonical(projection))))
    value = {'version':QUERY_VERSION, 'tokenizer_version':TOKENIZER_VERSION,
             'units':{'length':'mm','mass':'kg','angle':'deg'}, 'facts':facts,
             'tokens':tokens, 'text':' '.join(tokens)}
    value['query_digest'] = digest(value)
    validate_query(value)
    return value


def validate_query(query):
    validate_schema('memory_query', query)
    if query['query_digest'] != digest({k:v for k,v in query.items() if k != 'query_digest'}):
        raise JevSelectError('memory_query_changed')
    if query['tokens'] != sorted(set(tokenize(query['text']))) or query['text'] != ' '.join(query['tokens']):
        raise JevSelectError('memory_query_tokens_changed')
    return query


def validate_gates(gates):
    for g in gates:
        _closed(g, {'field','op','value'})
        if set(g) != {'field','op','value'} or g['field'] not in GATE_FIELDS or g['op'] not in OPERATORS:
            raise JevSelectError('invalid_memory_gate')
        kind = GATE_FIELDS[g['field']]
        if kind == 'number' and (g['op'] == 'contains' or type(g['value']) not in (int,float)):
            raise JevSelectError('invalid_memory_gate_type')
        if kind == 'set' and (g['op'] != 'contains' or not isinstance(g['value'],str)):
            raise JevSelectError('invalid_memory_gate_type')
    canonical(gates)


def evaluate_gates(gates, facts):
    validate_gates(gates)
    rows=[]
    for g in gates:
        actual = facts.get(g['field'])
        if actual is None: status='APPLICABILITY_UNKNOWN'
        else:
            op=g['op']; expected=g['value']
            passed = {'eq':lambda:actual==expected, 'ne':lambda:actual!=expected,
                'lt':lambda:actual<expected, 'le':lambda:actual<=expected,
                'gt':lambda:actual>expected, 'ge':lambda:actual>=expected,
                'contains':lambda:expected in actual}[op]()
            status='APPLICABLE' if passed else 'NOT_APPLICABLE'
        rows.append({**g,'actual':actual,'status':status})
    # Any unknown condition is explicitly unknown, even if another is false.
    status = 'APPLICABILITY_UNKNOWN' if any(r['status']=='APPLICABILITY_UNKNOWN' for r in rows) else 'NOT_APPLICABLE' if any(r['status']=='NOT_APPLICABLE' for r in rows) else 'APPLICABLE'
    return status, rows
