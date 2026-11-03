"""O2a text choice protocol: exact bindings, one bounded repair, auditable errors.

The public request remains the V2 schema so old/new prompts see identical facts.
Only the response contract and prompt change in this version.
"""
from __future__ import annotations

import json
from .pilot_protocol_v2 import scan_public
from ..protocol import canonical_json
from .client import ModelRequest

VERSION = 'pallet_choice_v3_protocol_2'
PROMPT_VERSION = 'o2a_concise_json_v2'
SYSTEM_PROMPT = '''你是码垛业务候选选择器。只用公开JSON。先检查易碎箱累计业务限载和禁止面接触；没有业务可行候选则abstain。可行时按指令的第一、第二软优先级比较公开关系事实，最后用geometry_score破同分。不要把整垛质心当重箱自身距离。
仅返回一个JSON对象，恰好7个字段：schema_version,request_id,state_hash,policy_digest,action,display_label,reason。schema_version必须是pallet_choice_v3_protocol_2。原样复制三个绑定值。action只能是select或abstain；select时display_label必须为给出的C编号，abstain时为null。reason简短且不超过3000字。禁止额外字段（包括type）、代码块、坐标、真实候选ID或解释性前后缀。'''
REPAIR_PROMPT = '''上次输出没有通过响应格式校验。错误代码：{error_code}。请重新读取下面的同一公开请求，只返回符合要求的一个JSON对象。只允许7个字段：schema_version,request_id,state_hash,policy_digest,action,display_label,reason。schema_version=pallet_choice_v3_protocol_2；三个绑定值必须原样复制；select须使用给出的C编号，abstain须使display_label为null。不要输出type、坐标、代码块或任何额外字段。不要重复上次响应。\n公开请求：\n{request}'''
FIELDS = {'schema_version', 'request_id', 'state_hash', 'policy_digest', 'action', 'display_label', 'reason'}


class ChoiceProtocolError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def parse_choice(raw: str, request: dict) -> dict:
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise ChoiceProtocolError('malformed_json') from None
    if not isinstance(obj, dict):
        raise ChoiceProtocolError('not_object')
    if set(obj) != FIELDS:
        raise ChoiceProtocolError('unexpected_fields')
    if obj['schema_version'] != VERSION:
        raise ChoiceProtocolError('schema_version')
    for field in ('request_id', 'state_hash', 'policy_digest'):
        if obj[field] != request[field]:
            raise ChoiceProtocolError('binding_'+field)
    if not isinstance(obj['reason'], str) or len(obj['reason']) > 3000:
        raise ChoiceProtocolError('reason')
    if obj['action'] == 'abstain' and obj['display_label'] is None:
        return obj
    if obj['action'] != 'select' or obj['display_label'] not in {c['display_label'] for c in request['candidates']}:
        raise ChoiceProtocolError('action_or_label')
    return obj


def public_input(request: dict, private_strings=()) -> str:
    scan = scan_public(request, private_strings)
    if scan['status'] != 'PASS':
        raise ChoiceProtocolError('public_input_leakage')
    return canonical_json(request)


def repair_user_text(request: dict, error_code: str, private_strings=()) -> str:
    # Never echo the raw model response: it can contain a real ID or other private text.
    if error_code not in {'malformed_json', 'not_object', 'unexpected_fields', 'schema_version',
                          'binding_request_id', 'binding_state_hash', 'binding_policy_digest',
                          'reason', 'action_or_label'}:
        raise ChoiceProtocolError('unrecognized_repair_error')
    return REPAIR_PROMPT.format(error_code=error_code, request=public_input(request, private_strings))


def model_request(request: dict, *, repair_error: str | None = None, private_strings=()) -> ModelRequest:
    user = (repair_user_text(request, repair_error, private_strings) if repair_error else
            public_input(request, private_strings))
    return ModelRequest(model='deepseek-flash', system_prompt=SYSTEM_PROMPT,
                        user_text=user, max_output_tokens=512, timeout_s=60.)
