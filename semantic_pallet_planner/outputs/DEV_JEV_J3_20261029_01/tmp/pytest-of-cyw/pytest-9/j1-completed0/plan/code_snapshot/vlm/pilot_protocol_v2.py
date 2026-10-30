"""Text-only pilot protocol, input whitelist, strict three-way binding."""
import hashlib
import json
from ..protocol import canonical_json

SYSTEM_PROMPT = '''你是属性感知码垛候选选择器。只能读取公开JSON，使用给出的实际物料属性、接触对、承载变化和重箱位置事实。
物理候选已过滤。先满足指令中的累计业务限载和禁止直接面接触，再按第一、第二优先级依次最优；不要用整垛质心代替重箱自身距离。
若不存在满足所有业务硬约束的候选，返回abstain，不允许用几何回退声称满足要求。无目标属性的软目标不参与排序。
同一优先级质量相同（容差1e-6）再比较后续优先级，再用geometry_score和编号破同分。
只返回JSON，字段必须恰为schema_version、request_id、state_hash、policy_digest、action、display_label、reason。
schema_version固定pallet_choice_v2_pilot，action为select或abstain，选择时display_label为给出的C编号，abstain时为null。
原样复制三个绑定字段，不输出坐标、代码或新候选。reason简要引用指令和公开事实。'''

PUBLIC_KEYS = {'schema_version', 'request_id', 'state_hash', 'policy_digest', 'instruction_text',
               'container', 'placed_items', 'available_items', 'candidates', 'buffer_size'}
FORBIDDEN_KEYS = {'candidate_id', 'candidate_fingerprint', 'oracle', 'oracle_score', 'ground_truth_rules',
                  'hidden_policy', 'policy_ast', 'mapping', 'future_items', 'arrival_order', 'scenario_id'}


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def scan_public(request, private_strings=()):
    hits = []
    def visit(x, path=''):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in FORBIDDEN_KEYS or k.startswith(('oracle_', 'ground_truth', 'hidden_')):
                    hits.append(path+'/'+k)
                visit(v, path+'/'+k)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                visit(v, path+f'/{i}')
    visit(request)
    if set(request) != PUBLIC_KEYS:
        hits.append('public_top_level_keys')
    text = canonical_json(request)
    for s in private_strings:
        if s and s in text:
            hits.append('private_string')
    if len(request.get('available_items', [])) != 1 or request.get('buffer_size') != 1:
        hits.append('buffer_size')
    return {'status': 'PASS' if not hits else 'FAIL', 'hits': hits, 'sha256': digest(request)}


def parse_choice(raw, request):
    result = json.loads(raw)
    keys = {'schema_version', 'request_id', 'state_hash', 'policy_digest', 'action', 'display_label', 'reason'}
    if not isinstance(result, dict) or set(result) != keys:
        raise ValueError('unexpected response fields')
    if result['schema_version'] != 'pallet_choice_v2_pilot':
        raise ValueError('wrong schema_version')
    for k in ('request_id', 'state_hash', 'policy_digest'):
        if result[k] != request[k]:
            raise ValueError('binding mismatch: '+k)
    if not isinstance(result['reason'], str) or len(result['reason']) > 3000:
        raise ValueError('invalid reason')
    if result['action'] == 'abstain' and result['display_label'] is None:
        return result
    if result['action'] != 'select' or result['display_label'] not in {c['display_label'] for c in request['candidates']}:
        raise ValueError('invalid action/label')
    return result
