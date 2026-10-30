"""Published O1b A/B/C grammar, operating only on a public instruction string."""
from __future__ import annotations

import re
from ..evaluation.policy_v2 import validate_policy
from ..evaluation.policy_o1b import validate_envelope, resolve
from .instruction_parser_v2 import parse_instruction, instruction_from_policy

LOW = ('heavy_low', 'heavy_center')
CENTER = ('heavy_center', 'heavy_low')


def policy(threshold: float, order: tuple[str, str], contact: bool = True):
    hard = [{'type': 'fragile_load_limit', 'selector': {'fragile': True}, 'threshold_kg': threshold}]
    if contact:
        hard.append({'type': 'forbidden_contact', 'left': {'product_category': 'electronics'},
                     'right': {'weight_class': 'heavy'}})
    return validate_policy({'schema_version': 'pallet_policy_v2_pilot',
        'hard_constraints': hard,
        'soft_priorities': [{'priority': i + 1, 'metric': metric} for i,metric in enumerate(order)]})


def canonical_text(p):
    return instruction_from_policy(p)


def paraphrase_text(p):
    threshold = next(r['threshold_kg'] for r in p['hard_constraints'] if r['type']=='fragile_load_limit')
    contact = any(r['type']=='forbidden_contact' for r in p['hard_constraints'])
    contact_part = '电子产品箱与重箱不得直接面接触；' if contact else ''
    names = {'heavy_low':'重箱尽量处于低位','heavy_center':'重箱尽量靠近托盘中心'}
    order = [x['metric'] for x in p['soft_priorities']]
    return (f'易碎物料箱的累计承载上限是{threshold:g}千克；{contact_part}'
            f'先确保上述强制要求，再优先{names[order[0]]}，其次{names[order[1]]}。')


def conditional_envelope(p0, p1, reverse=False):
    return validate_envelope({'schema_version': 'pallet_policy_o1b_conditional_1',
        'condition': {'field': 'weight_class', 'equals': 'heavy'},
        'then_policy': p1 if reverse else p0, 'else_policy': p0 if reverse else p1})


def conditional_text(p0, p1, reverse=False):
    first, second = (p1,p0) if reverse else (p0,p1)
    return (f'若本次箱为重箱，执行政策「{canonical_text(first)}」；'
            f'否则执行政策「{canonical_text(second)}」。')


def parse_o1b_instruction(text):
    """Parse published development templates; unrecognized text fails explicitly."""
    try:
        return parse_instruction(text)
    except ValueError:
        pass
    t = re.sub(r'\s+', '', text)
    m = re.fullmatch(r'易碎物料箱的累计承载上限是(\d+(?:\.\d+)?)千克；'
                     r'(电子产品箱与重箱不得直接面接触；)?先确保上述强制要求，再优先'
                     r'(重箱尽量处于低位|重箱尽量靠近托盘中心)，其次'
                     r'(重箱尽量处于低位|重箱尽量靠近托盘中心)。', t)
    if m:
        names={'重箱尽量处于低位':'heavy_low','重箱尽量靠近托盘中心':'heavy_center'}
        order=(names[m[3]],names[m[4]])
        if order[0]==order[1]: raise ValueError('duplicate soft priority')
        return policy(float(m[1]),order,bool(m[2]))
    m = re.fullmatch(r'若本次箱为重箱，执行政策「(.+?)」；否则执行政策「(.+?)」。',t)
    if m:
        return conditional_envelope(parse_instruction(m[1]),parse_instruction(m[2]))
    raise ValueError('unsupported O1b instruction')


def resolved_public_policy(text, request):
    parsed=parse_o1b_instruction(text)
    return resolve(parsed,request) if parsed['schema_version']=='pallet_policy_o1b_conditional_1' else parsed
