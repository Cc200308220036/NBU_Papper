"""O2b text-only, bound, restricted-policy response protocol."""
from __future__ import annotations

import json
import math

from ..evaluation.policy_o1b import validate_envelope
from ..evaluation.policy_v2 import validate_policy
from ..protocol import canonical_json
from .client import ModelRequest
from .pilot_protocol_v2 import scan_public
from .protocol_o2a import ChoiceProtocolError

VERSION = 'pallet_policy_response_o2b_1'
PROMPT_VERSION = 'o2b_policy_parser_1'
FIELDS = {'schema_version', 'request_id', 'state_hash', 'policy_digest', 'policy_ast'}
SYSTEM_PROMPT = '''你只负责把公开业务指令解析成受限JSON规则，不选择候选，不计算距离、载荷或最优解。只能读取给出的公开请求。\n规则AST只允许两种结构：\n普通政策 {"schema_version":"pallet_policy_v2_pilot","hard_constraints":[{"type":"fragile_load_limit","selector":{"fragile":true},"threshold_kg":数值},可选{"type":"forbidden_contact","left":{"product_category":"electronics"},"right":{"weight_class":"heavy"}}],"soft_priorities":[{"priority":1,"metric":"heavy_low或heavy_center"},{"priority":2,"metric":"另一个指标"}]}。\n条件政策 {"schema_version":"pallet_policy_o1b_conditional_1","condition":{"field":"weight_class","equals":"heavy"},"then_policy":普通政策,"else_policy":普通政策}。\n必须保留指令的限载阈值、禁止接触、两级优先级和条件分支。只返回一个JSON对象，恰有schema_version,request_id,state_hash,policy_digest,policy_ast五个字段。schema_version固定pallet_policy_response_o2b_1，三个绑定值原样复制。禁止代码、额外字段、真实候选ID、未来物料或隐藏真值。'''


def validate_restricted_ast(ast):
    """Enforce the announced O1b grammar, including exact selectors and both priorities."""
    if not isinstance(ast, dict):
        raise ChoiceProtocolError('policy_ast_shape')
    if ast.get('schema_version') == 'pallet_policy_o1b_conditional_1':
        try:
            validate_envelope(ast)
        except Exception as exc:
            raise ChoiceProtocolError('policy_ast_schema') from exc
        if ast['condition'] != {'field': 'weight_class', 'equals': 'heavy'}:
            raise ChoiceProtocolError('policy_ast_domain')
        validate_restricted_ast(ast['then_policy'])
        validate_restricted_ast(ast['else_policy'])
        return ast
    try:
        validate_policy(ast)
    except Exception as exc:
        raise ChoiceProtocolError('policy_ast_schema') from exc
    hard = ast['hard_constraints']
    loads = [x for x in hard if x['type'] == 'fragile_load_limit']
    contacts = [x for x in hard if x['type'] == 'forbidden_contact']
    if len(loads) != 1 or len(contacts) > 1 or len(hard) != len(loads) + len(contacts):
        raise ChoiceProtocolError('policy_ast_domain')
    if (loads[0]['selector'] != {'fragile': True} or isinstance(loads[0]['threshold_kg'], bool)
            or not math.isfinite(loads[0]['threshold_kg'])):
        raise ChoiceProtocolError('policy_ast_domain')
    allowed_contact = {'type': 'forbidden_contact', 'left': {'product_category': 'electronics'},
                       'right': {'weight_class': 'heavy'}}
    if contacts and contacts[0] != allowed_contact:
        raise ChoiceProtocolError('policy_ast_domain')
    if len(ast['soft_priorities']) != 2 or {p['metric'] for p in ast['soft_priorities']} != {'heavy_low', 'heavy_center'}:
        raise ChoiceProtocolError('policy_ast_domain')
    return ast


def parse_policy_response(raw, request):
    try:
        obj = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (TypeError, ValueError):
        raise ChoiceProtocolError('malformed_json') from None
    if not isinstance(obj, dict) or set(obj) != FIELDS:
        raise ChoiceProtocolError('unexpected_fields')
    if obj['schema_version'] != VERSION:
        raise ChoiceProtocolError('schema_version')
    for field in ('request_id', 'state_hash', 'policy_digest'):
        if obj[field] != request[field]:
            raise ChoiceProtocolError('binding_' + field)
    validate_restricted_ast(obj['policy_ast'])
    return obj


def public_input(request, private_strings=()):
    scan = scan_public(request, private_strings)
    if scan['status'] != 'PASS':
        raise ChoiceProtocolError('public_input_leakage')
    return canonical_json(request)


def model_request(request, *, repair_error=None, private_strings=()):
    public = public_input(request, private_strings)
    if repair_error is not None:
        if repair_error not in {'malformed_json', 'unexpected_fields', 'schema_version',
                                'binding_request_id', 'binding_state_hash', 'binding_policy_digest',
                                'policy_ast_shape', 'policy_ast_schema', 'policy_ast_domain'}:
            raise ChoiceProtocolError('unrecognized_repair_error')
        public = '上次输出未通过格式检查，错误代码：' + repair_error + '。请仅根据以下同一公开请求重试一次，不复述之前输出：\n' + public
    return ModelRequest(model='deepseek-flash', system_prompt=SYSTEM_PROMPT,
                        user_text=public, max_output_tokens=1200, timeout_s=60.)
