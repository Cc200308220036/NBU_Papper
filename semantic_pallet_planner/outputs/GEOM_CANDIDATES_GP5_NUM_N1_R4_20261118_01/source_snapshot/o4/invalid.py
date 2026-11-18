"""24 declared rejection recipes; serializable without non-JSON NaN values."""
import copy
from .common import O4Error
from .observation import validate_observation,rebind
from .normalize import validate_policy
from .compiler import compile_policy,response_for,validate_response
from .fixtures import policy,rule,eq

RECIPES=[
 ('unknown_observation_field','invalid_observation'),('duplicate_object','invalid_observation'),('negative_mass','invalid_observation'),
 ('invalid_units','invalid_observation'),('future_objects_field','invalid_observation'),('nonfinite_mass','invalid_observation'),
 ('duplicate_rule','invalid_ast'),('unknown_rule_field','invalid_ast'),('negative_limit','invalid_ast'),
 ('unknown_constraint','invalid_ast'),('unknown_limit_field','invalid_ast'),('missing_priority','invalid_ast'),
 ('wrong_request_id','invalid_binding'),('wrong_state_hash','invalid_binding'),('wrong_observation_digest','invalid_binding'),('wrong_instruction_digest','invalid_binding'),
 ('unknown_object_id','invalid_ast'),('unknown_selector_field','invalid_ast'),('deep_selector','invalid_ast'),('too_many_rules','invalid_ast'),
 ('override_cycle','invalid_ast'),('override_unknown','invalid_ast'),('contact_override','invalid_ast'),('unknown_language','unsupported_construct')]


def invalid_cases():
    return [{'case_id':f'invalid_{i:02d}','recipe':name,'expected_code':code} for i,(name,code) in enumerate(RECIPES,1)]


def execute_invalid_case(case,req):
    name=case['recipe'];req=copy.deepcopy(req);ast=policy([rule()])
    if name in {n for n,_ in RECIPES[:6]}:
        if name=='unknown_observation_field':req['confidence']=.5
        if name=='duplicate_object':req['available_objects']=[copy.deepcopy(req['placed_objects'][0])];req['available_objects'][0].pop('pose');req['available_objects'][0].pop('oriented_size_mm')
        if name=='negative_mass':req['available_objects'][0]['mass_kg']=-1
        if name=='invalid_units':req['units']['mass']='g'
        if name=='future_objects_field':req['future_objects']=[]
        if name=='nonfinite_mass':req['available_objects'][0]['mass_kg']=float('nan')
        return validate_observation(req)
    if name.startswith('wrong_'):
        response=response_for(req,ast);key=name[len('wrong_'):];response[key]='wrong' if key=='request_id' else '0'*64
        return validate_response(response,req)
    if name=='duplicate_rule':ast['rules']*=2
    if name=='unknown_rule_field':ast['rules'][0]['confidence']=1
    if name=='negative_limit':ast['rules'][0]['limit']['constant_kg']=-1
    if name=='unknown_constraint':ast['rules'][0]['type']='inside_region'
    if name=='unknown_limit_field':ast['rules'][0]['limit']={'field':'physical_top_load_limit_kg'}
    if name=='missing_priority':del ast['rules'][0]['priority']
    if name=='unknown_object_id':ast['rules'][0]['target']={'object_ids':['not_arrived']}
    if name=='unknown_selector_field':ast['rules'][0]['target']=eq('source_order_id','answer')
    if name=='deep_selector':
        for _ in range(5):ast['rules'][0]['target']={'not':ast['rules'][0]['target']}
    if name=='too_many_rules':ast['rules']=[rule(f'r{i}') for i in range(33)]
    if name=='override_cycle':ast=policy([rule('a',priority=1,overrides=['b']),rule('b',priority=2,overrides=['a'])])
    if name=='override_unknown':ast['rules'][0]['overrides']=['absent']
    if name=='contact_override':ast=policy([rule('a','forbidden_contact',overrides=['b']),rule('b')])
    if name=='unknown_language':
        req['instruction_text']='请自行猜测合适的业务规则。';return compile_policy(rebind(req))
    return validate_policy(ast,req)
