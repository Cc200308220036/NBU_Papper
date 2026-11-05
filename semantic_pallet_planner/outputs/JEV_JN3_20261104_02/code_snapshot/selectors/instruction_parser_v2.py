"""Non-LLM public grammar parser. No annotation/repository access."""
import re
from ..evaluation.policy_v2 import validate_policy

SOFT = {'重箱尽量放低': 'heavy_low', '重箱尽量靠中心': 'heavy_center'}


def parse_object(text):
    names = {'易碎箱': {'fragile': True}, '重箱': {'weight_class': 'heavy'},
             '中等重量箱': {'weight_class': 'medium'}, '轻箱': {'weight_class': 'light'}}
    if text in names:
        return names[text]
    m = re.fullmatch(r'类别\[([A-Za-z0-9_]{1,64})\]', text)
    if m:
        return {'product_category': m[1]}
    raise ValueError('unsupported object')


def parse_instruction(text):
    """Complete published pilot grammar; reject unconsumed text, never guess."""
    text = re.sub(r'\s+', '', text).replace(';', '；').rstrip('。')
    clauses = text.split('；')
    policy = {'schema_version': 'pallet_policy_v2_pilot', 'hard_constraints': [], 'soft_priorities': []}
    phase = False
    for clause in clauses:
        if clause in ('在满足硬约束后', '在物理合法范围内'):
            if phase:
                raise ValueError('duplicate phase separator')
            phase = True
            continue
        m = re.fullmatch(r'易碎箱累计承载不得超过(\d+(?:\.\d+)?)kg', clause)
        if m and not phase:
            policy['hard_constraints'].append({'type': 'fragile_load_limit', 'selector': {'fragile': True}, 'threshold_kg': float(m[1])})
            continue
        m = re.fullmatch(r'(.+)与(.+)禁止直接面接触', clause)
        if m and not phase:
            policy['hard_constraints'].append({'type': 'forbidden_contact', 'left': parse_object(m[1]), 'right': parse_object(m[2])})
            continue
        m = re.fullmatch(r'(第一|第二)优先级[：:](.+)', clause)
        if m and phase and m[2] in SOFT:
            policy['soft_priorities'].append({'priority': {'第一': 1, '第二': 2}[m[1]], 'metric': SOFT[m[2]]})
            continue
        raise ValueError(f'unsupported clause: {clause}')
    if not phase:
        raise ValueError('missing phase separator')
    return validate_policy(policy)


def instruction_from_policy(policy):
    names = {'heavy': '重箱', 'medium': '中等重量箱', 'light': '轻箱'}
    def obj(s):
        if 'fragile' in s and s['fragile'] is True:
            return '易碎箱'
        if 'weight_class' in s:
            return names[s['weight_class']]
        if 'product_category' in s:
            return f"类别[{s['product_category']}]"
        raise ValueError('unsupported object spelling')
    clauses = []
    for r in policy['hard_constraints']:
        if r['type'] == 'fragile_load_limit':
            clauses.append(f"易碎箱累计承载不得超过{r['threshold_kg']:g} kg")
        else:
            clauses.append(f"{obj(r['left'])}与{obj(r['right'])}禁止直接面接触")
    clauses.append('在满足硬约束后' if clauses else '在物理合法范围内')
    rev = {v: k for k, v in SOFT.items()}
    for s in policy['soft_priorities']:
        clauses.append(f"{'第一' if s['priority']==1 else '第二'}优先级：{rev[s['metric']]}")
    return '；'.join(clauses)+'。'
