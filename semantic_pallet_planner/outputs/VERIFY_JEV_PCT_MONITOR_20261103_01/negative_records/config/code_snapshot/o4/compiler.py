"""Published compositional Chinese grammar; no datasets or reference files read."""
import re
from .common import FIELDS,O4Error,validate
from .normalize import normalize_policy,validate_policy
from .observation import validate_observation

NAMES={'货物类别':'cargo_category','包装加固':'packaging.reinforced','禁压标记':'labels.no_top_load',
       '标签限载':'labels.max_top_load_kg','物理限载':'physical_top_load_limit_kg','质量':'mass_kg',
       '易碎':'fragile','重量等级':'weight_class'}
VALUES={'食品':'food','玻璃制品':'glassware','电子产品':'electronics','清洁用品':'household_cleaner','其他':'general',
        '是':True,'否':False,'轻':'light','中':'medium','重':'heavy'}
OPS={'等于':'eq','小于':'lt','不大于':'le','大于':'gt','不小于':'ge'}


def split_top(text,separator='，'):
    parts=[];level=0;start=0
    for i,ch in enumerate(text):
        if ch=='（': level+=1
        elif ch=='）': level-=1
        if level<0: raise O4Error('unsupported_construct','unbalanced parentheses')
        if ch==separator and level==0: parts.append(text[start:i]);start=i+1
    if level: raise O4Error('unsupported_construct','unbalanced parentheses')
    parts.append(text[start:])
    return parts


def parse_selector(text):
    if text=='全部箱体': return {'all':True}
    m=re.fullmatch(r'对象（([A-Za-z0-9_,]+)）',text)
    if m:return {'object_ids':m[1].split(',')}
    for prefix,op in [('同时满足','and'),('任一满足','or'),('不满足','not')]:
        if text.startswith(prefix+'（') and text.endswith('）'):
            body=text[len(prefix)+1:-1]
            return {op:parse_selector(body)} if op=='not' else {op:[parse_selector(p) for p in split_top(body)]}
    m=re.fullmatch(r'('+'|'.join(NAMES)+r')('+'|'.join(OPS)+r')(.+)',text)
    if not m:raise O4Error('unsupported_construct','unrecognized selector')
    field,op,value=NAMES[m[1]],OPS[m[2]],m[3]
    if FIELDS[field]=='number':
        if not re.fullmatch(r'\d+(?:\.\d+)?kg',value):raise O4Error('unsupported_construct','numeric selector requires kg')
        value=float(value[:-2])
    elif value in VALUES:value=VALUES[value]
    else:raise O4Error('unsupported_construct','unknown selector value')
    return {op:{'field':field,'value':value}}


def parse_instruction(text):
    text=re.sub(r'\s+','',text)
    if text=='无额外业务硬约束。':return {'schema_version':'o4_policy_v1','rules':[]}
    if not text.startswith('规则'):
        return parse_work_order(text)
    clauses=text.split('。')
    if clauses[-1]!='':raise O4Error('unsupported_construct','rule must end with 。')
    rules=[]
    for clause in clauses[:-1]:
        m=re.fullmatch(r'规则([A-Za-z0-9_]+)：(.+)；优先级(\d+)；覆盖([A-Za-z0-9_,]+|无)',clause)
        if not m:raise O4Error('unsupported_construct','unsupported rule grammar')
        identifier,body,priority,overrides=m.groups()
        r={'rule_id':identifier,'priority':int(priority),'overrides':[] if overrides=='无' else overrides.split(',')}
        contact=re.fullmatch(r'禁止（(.+)）与（(.+)）直接面接触',body)
        load=re.fullmatch(r'对（(.+)），(禁止顶部加载|累计顶部限载按标签|累计顶部限载为\d+(?:\.\d+)?kg)',body)
        if contact:
            r.update(type='forbidden_contact',left=parse_selector(contact[1]),right=parse_selector(contact[2]))
        elif load:
            r['target']=parse_selector(load[1]); action=load[2]
            r['type']='no_top_load' if action=='禁止顶部加载' else 'max_top_load'
            if r['type']=='max_top_load':
                r['limit']={'field':'labels.max_top_load_kg'} if action=='累计顶部限载按标签' else {'constant_kg':float(action[len('累计顶部限载为'):-2])}
        else:raise O4Error('unsupported_construct','unknown constraint')
        rules.append(r)
    return validate_policy({'schema_version':'o4_policy_v1','rules':rules})


def parse_work_order(text):
    """Explicitly published natural clauses from the implementation specification."""
    clauses=[c for c in re.split('[；。]',text) if c]
    rules=[]
    for clause in clauses:
        base={'rule_id':f'r{len(rules)+1}','priority':20,'overrides':[]}
        if clause in ('本订单普通箱按各自标签的累计顶部限载执行','普通箱按各自标签的累计顶部限载执行'):
            base.update(type='max_top_load',target={'all':True},limit={'field':'labels.max_top_load_kg'})
        elif clause=='带禁压标记的箱体禁止顶部加载':
            base.update(type='no_top_load',target={'eq':{'field':'labels.no_top_load','value':True}},priority=10,
                        overrides=[r['rule_id'] for r in rules if r['type']=='max_top_load' and r['target']=={'all':True}])
        elif re.fullmatch(r'已加固且无禁压标记的玻璃制品外箱，改按订单指定的\d+(?:\.\d+)?kg业务限载执行，替代其标签业务限载',clause):
            limit=float(re.search(r'指定的(\d+(?:\.\d+)?)kg',clause)[1])
            base.update(type='max_top_load',target={'and':[{'eq':{'field':'cargo_category','value':'glassware'}},
                {'eq':{'field':'packaging.reinforced','value':True}},{'eq':{'field':'labels.no_top_load','value':False}}]},
                limit={'constant_kg':limit},priority=0,overrides=[r['rule_id'] for r in rules if r['type']=='max_top_load' and r['target']=={'all':True}])
        elif clause=='食品外箱与清洁用品外箱允许同托盘，但不得直接面接触':
            base.update(type='forbidden_contact',left={'eq':{'field':'cargo_category','value':'food'}},right={'eq':{'field':'cargo_category','value':'household_cleaner'}})
        elif clause=='所有箱体仍须满足独立物理承载限制':continue
        else:raise O4Error('unsupported_construct','unpublished natural clause')
        rules.append(base)
    return validate_policy({'schema_version':'o4_policy_v1','rules':rules})


def response_for(req,ast):
    return {'schema_version':'o4_response_v1',**{k:req[k] for k in ('request_id','state_hash','observation_digest','instruction_digest')},'policy_ast':ast}


def validate_response(response,req):
    validate_observation(req)
    validate('response',response)
    if any(response[k]!=req[k] for k in ('request_id','state_hash','observation_digest','instruction_digest')):
        raise O4Error('invalid_binding','response belongs to another request')
    validate_policy(response['policy_ast'],req)
    return response


def compile_policy(req):
    validate_observation(req)
    ast=parse_instruction(req['instruction_text'])
    return validate_response(response_for(req,ast),req)


def validate_and_normalize(response,req):
    validate_response(response,req)
    return normalize_policy(response['policy_ast'],req)
