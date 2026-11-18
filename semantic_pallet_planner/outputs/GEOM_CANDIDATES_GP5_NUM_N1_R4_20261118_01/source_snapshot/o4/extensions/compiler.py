"""Public compositional E1 grammar; never reads private reference policies."""
import re
from ..compiler import parse_instruction as parse_old, parse_selector
from ..fixtures import render_policy as render_old, render_selector
from ..common import O4Error
from .protocol import POLICY, validate_policy, validate_observation, response_for


def parse_instruction(text):
    compact = re.sub(r'\s+', '', text)
    if compact == '无额外业务硬约束。':
        return {'schema_version': POLICY, 'rules': []}
    # Keep old clauses together so their override graph is validated as a whole.
    old, spatial = [], []
    for clause in compact.split('。')[:-1]:
        m = re.fullmatch(r'规则([A-Za-z0-9_]+)：对（(.+)），(?:底面完全位于区域|整个底面放入区域)([A-Za-z0-9_]+)；优先级(\d+)；覆盖(无)', clause)
        if m:
            spatial.append({'rule_id': m[1], 'type': 'inside_region', 'target': parse_selector(m[2]),
                            'region_id': m[3], 'priority': int(m[4]), 'overrides': []})
        else:
            old.append(clause + '。')
    if not compact.endswith('。') or not compact:
        raise O4Error('unsupported_construct', '$.instruction_text: complete clauses ending in 。 required')
    rules = parse_old(''.join(old))['rules'] if old else []
    return validate_policy({'schema_version': POLICY, 'rules': rules + spatial})


def compile_policy(req):
    validate_observation(req)
    return response_for(req, parse_instruction(req['instruction_text']))


def render_policy(ast, paraphrase=False):
    """Fixture text serializer only; not called by the parser."""
    if not ast['rules']:
        return '无额外业务硬约束。'
    lines = []
    for r in reversed(ast['rules']) if paraphrase else ast['rules']:
        if r['type'] == 'inside_region':
            verb = '整个底面放入区域' if paraphrase else '底面完全位于区域'
            lines.append(f"规则{r['rule_id']}：对（{render_selector(r['target'], paraphrase)}），{verb}{r['region_id']}；优先级{r['priority']}；覆盖无。")
        else:
            lines.append(render_old({'schema_version': 'o4_policy_v1', 'rules': [r]}, paraphrase))
    return '\n'.join(lines)
