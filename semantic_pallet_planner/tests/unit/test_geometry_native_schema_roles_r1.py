"""Pure v17 identity-role contracts. No generator, monitor, freezer or episode."""
import copy,json
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator

ROOT=Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select/schemas')
PATTERN='^GP5N3_[0-9a-f]{64}$'
CANDIDATE='GP5N3_'+'a'*64

def load(name):return json.loads((ROOT/(name+'.schema.json')).read_bytes())
def leaves(value,path=''):
    if isinstance(value,dict):
        for key,item in value.items():
            yield from leaves(item,path+'/'+key)
        if value.get('pattern')==PATTERN:yield path,value
    elif isinstance(value,list):
        for i,item in enumerate(value):yield from leaves(item,path+'/'+str(i))

class NativeSchemaRolesR1(unittest.TestCase):
    def test_monitor_result_preserves_original_box_identity(self):
        new=load('checkpoint_v17')['$defs']['monitor_result']
        old=load('checkpoint_v16')['$defs']['monitor_result']
        self.assertEqual(new,old) # All kernel result fields retain their original contract.
        for value in ('synth_1','箱体_02',None):
            self.assertFalse(list(Draft202012Validator(new['properties']['candidate_id']).iter_errors(value)))
        for value in (True,42,{},[]):
            self.assertTrue(list(Draft202012Validator(new['properties']['candidate_id']).iter_errors(value)))
        self.assertFalse(new['additionalProperties'])
        # Item-ID syntax may overlap candidate syntax. Membership is contextual;
        # inventing a reserved-prefix blacklist would change the kernel contract.
        self.assertFalse(list(Draft202012Validator(new['properties']['candidate_id']).iter_errors(CANDIDATE)))

    def test_all_published_candidate_identity_roles_remain_strict(self):
        count=0
        for name in ('candidate_bundle_v17','decision_context_v17','selection_result_v17','checkpoint_v17'):
            for path,spec in leaves(load(name)):
                self.assertNotIn('monitor_result',path)
                count+=1
                # Some selection branches are null-only; preserve those as well.
                if spec.get('type')=='null':continue
                self.assertFalse(list(Draft202012Validator(spec).iter_errors(CANDIDATE)),(name,path))
                for wrong in ('synth_1','GP5N2_'+'a'*64,'GP5N3_short'):
                    self.assertTrue(list(Draft202012Validator(spec).iter_errors(wrong)),(name,path,wrong))
        self.assertEqual(count,13)

    def test_nested_unknown_fields_and_role_misplacement(self):
        cp=load('checkpoint_v17')
        # Minimal closed identity-bearing containers: no full runtime fixture needed.
        for parent,key,good in [(cp['$defs']['action'],'candidate_id',CANDIDATE),
                                (cp['$defs']['selection'],'selected_candidate_id',CANDIDATE),
                                (cp['$defs']['monitor_result'],'candidate_id','synth_1')]:
            schema={'type':'object','properties':{key:parent['properties'][key]},'required':[key],
                    'additionalProperties':parent['additionalProperties']}
            validator=Draft202012Validator(schema)
            self.assertFalse(list(validator.iter_errors({key:good})))
            self.assertTrue(list(validator.iter_errors({key:good,'unknown_role':True})))
            if key=='candidate_id' and parent is not cp['$defs']['monitor_result']:
                self.assertTrue(list(validator.iter_errors({key:'synth_1'})))
        for name in ('candidate_bundle_v17','decision_context_v17','selection_result_v17','checkpoint_v17'):
            Draft202012Validator.check_schema(load(name))

if __name__=='__main__':unittest.main(verbosity=2)
