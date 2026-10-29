"""Versioned, strict visual-probe contract. No normalization of incorrect response shapes."""
import copy
import json

CONTRACT = {'version':'o5_visual_probe_response_v2','keys':['workspace','candidates'],
            'colors':['red','blue','green','yellow'],'shapes':['circle','square'],
            'value_format':'color_shape','additional_fields':False}
PROMPT = ('First image is workspace; second image is candidates. '
          'Return one JSON object with exactly two keys: workspace and candidates. '
          'Each value MUST be a string in lowercase color_shape format, joined by one underscore. '
          'Allowed colors: red, blue, green, yellow. Allowed shapes: circle, square. '
          'Infer the values independently from the two images. '
          'Do not use nested objects, arrays, spaces, additional keys or explanations. No packing action.')


def contract():
    return copy.deepcopy(CONTRACT)


def evaluate(task,text):
    expected={a['asset_id']:a['expected_fact'] for a in task['images']}
    if 'response_contract' not in task:
        # Preserve historical unversioned equality semantics, including its generic error category.
        try:return json.loads(text)==expected,None
        except (ValueError,TypeError):return False,None
    if task['response_contract']!=CONTRACT:
        from .common import O5Error
        raise O5Error('UNSUPPORTED_VISUAL_PROBE_CONTRACT')
    def unique_pairs(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate key')
            result[key]=value
        return result
    try:
        value=json.loads(text,object_pairs_hook=unique_pairs)
    except (ValueError,TypeError):
        return False,'PREFLIGHT_RESPONSE_FORMAT_INVALID'
    allowed={color+'_'+shape for color in CONTRACT['colors'] for shape in CONTRACT['shapes']}
    if (not isinstance(value,dict) or set(value)!=set(CONTRACT['keys'])
            or any(not isinstance(v,str) or v not in allowed for v in value.values())):
        return False,'PREFLIGHT_RESPONSE_FORMAT_INVALID'
    if value!=expected:return False,'PREFLIGHT_VISUAL_FACT_MISMATCH'
    return True,None
