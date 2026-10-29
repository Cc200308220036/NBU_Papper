"""Versioned image/text projection, deterministic display permutation and response binding."""
import base64
import copy
import json
import random
from PIL import Image
from .common import O5Error, canonical, digest, sha
from .config import validate as validate_config
from .schemas import validate, TEXT_CONVENTIONS
from .visual import render

GOAL = 'Maximize the loaded fraction of the complete order within the stated physical limits. Only the current item and already placed items are visible.'
TEXT_VERSION = 'o5_direct_text_request_v1'
IMAGE_VERSION = 'o5_decision_request_v1'

CONTRACT = 'Return only JSON with request_id,state_hash,action,candidate_id. PLACE selects one listed Cxx. STOP uses candidate_id=null. Do not output coordinates or change item properties.'


def item_projection(item, placed=False):
    out = {k: copy.deepcopy(item[k]) for k in ('item_id', 'dimensions_mm', 'mass_kg', 'stackable')}
    out['physical_top_load_limit_kg'] = item['top_load_limit_kg_synthetic']
    if placed:
        out.update({k: copy.deepcopy(item[k]) for k in ('pose', 'oriented_size_mm', 'supported_load_kg')})
    return out


def request_hash(req):
    return digest({k: v for k, v in req.items() if k not in ('request_id', 'state_hash')})


def validate_request(req):
    text = req.get('schema_version') == TEXT_VERSION
    validate('DirectTextRequest' if text else 'DecisionRequest', req)
    if req['state_hash'] != request_hash(req) or req['task_goal'] != GOAL or req['output_contract'] != CONTRACT:
        raise O5Error('INVALID_REQUEST_BINDING')
    labels = [c['candidate_id'] for c in req['candidates']]
    if labels != [f'C{i+1:02d}' for i in range(len(labels))] or (not text and [i['asset_id'] for i in req['images']] != ['workspace', 'candidates']):
        raise O5Error('INVALID_DISPLAY_MAPPING')
    ids = [i['item_id'] for i in req['placed_items']] + [req['current_item']['item_id']]
    if len(set(ids)) != len(ids):
        raise O5Error('DUPLICATE_ITEM')
    return req


def build(container, placed, current, pool, config, nonce, directory, *, request_version=IMAGE_VERSION):
    validate_config(config)
    if request_version not in (IMAGE_VERSION, TEXT_VERSION):
        raise O5Error('UNKNOWN_REQUEST_PROTOCOL')
    public = {'schema_version': request_version, 'request_id': 'REQ_'+digest(nonce)[:24],
              'container': copy.deepcopy(container), 'placed_items': [item_projection(p, True) for p in placed],
              'current_item': item_projection(current), 'candidates': [], 'task_goal': GOAL, 'output_contract': CONTRACT}
    ordered = sorted(pool, key=lambda c: canonical([c['pose'], c['oriented_size_mm']]))
    physical_digest = digest([public['container'], public['placed_items'], public['current_item']])
    random.Random(int(digest([config['seed'], physical_digest]), 16)).shuffle(ordered)
    mapping = {}
    for i, c in enumerate(ordered):
        label = f'C{i+1:02d}'
        mapping[label] = copy.deepcopy(c)
        public['candidates'].append({'candidate_id': label, **{k: copy.deepcopy(c[k]) for k in ('pose', 'oriented_size_mm', 'support')}})
    if request_version == TEXT_VERSION:
        public['units_and_coordinates'] = copy.deepcopy(TEXT_CONVENTIONS)
    else:
        public['images'] = render(public, directory)
    public['state_hash'] = request_hash(public)
    validate_request(public)
    return public, mapping


def parse_response(raw, req):
    validate_request(req)
    if isinstance(raw, str):
        try:
            def pairs(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError('duplicate key')
                    result[key] = value
                return result
            raw = json.loads(raw, object_pairs_hook=pairs)
        except ValueError:
            raise O5Error('INVALID_JSON') from None
    validate('DecisionResponse', raw)
    if raw['request_id'] != req['request_id'] or raw['state_hash'] != req['state_hash']:
        raise O5Error('STALE_BINDING')
    if raw['action'] == 'STOP':
        if raw['candidate_id'] is not None:
            raise O5Error('INVALID_STOP')
    elif raw['candidate_id'] not in {c['candidate_id'] for c in req['candidates']}:
        raise O5Error('UNKNOWN_CANDIDATE')
    return copy.deepcopy(raw)


def image_bytes(req, directory):
    """Check original assets for every method, including a pending G0 decision."""
    validate_request(req)
    if req['schema_version'] == TEXT_VERSION:
        return []
    assets = []
    for asset in req['images']:
        path = directory/(asset['asset_id']+'.png')
        if not path.is_file():
            raise O5Error('IMAGE_CHANGED')
        if sha(path) != asset['sha256']:
            raise O5Error('IMAGE_CHANGED')
        with Image.open(path) as img:
            if img.format != 'PNG' or list(img.size) != [asset['width'], asset['height']]:
                raise O5Error('IMAGE_CHANGED')
        assets.append(path.read_bytes())
    return assets


def envelope(req, directory, config, repair_error=None):
    """Versioned production body; text requests never read or render image assets."""
    validate_config(config)
    content = [{'type': 'text', 'text': canonical({'public_input': req, 'repair_error': repair_error})}]
    validate_request(req)
    for data in ([] if req['schema_version'] == TEXT_VERSION else image_bytes(req, directory)):
        content.append({'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,'+base64.b64encode(data).decode(), 'detail': 'high'}})
    body = {'messages': [{'role': 'system', 'content': GOAL+' '+CONTRACT}, {'role': 'user', 'content': content}],
            'max_tokens': config['selection_max_output_tokens'], 'temperature': 0., 'stream': False}
    if len(canonical(body).encode()) > config['max_request_bytes']:
        raise O5Error('REQUEST_TOO_LARGE')
    # Byte count is a conservative text-token bound, not a provider image-token estimate.
    if len(content[0]['text'].encode()) > config['input_token_limit']:
        raise O5Error('TEXT_TOKEN_UPPER_BOUND_EXCEEDED')
    return body
