"""QA-JM1B2-01: saved-byte semantics only; no sampler/engine/network/solver."""
import base64
import copy
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from semantic_pallet_planner.jev_select import packaging_jev_training_template as b2
from semantic_pallet_planner.jev_select import packaging_jev_sampling as b1

REPO=Path(__file__).resolve().parents[3]
OLD=REPO/'semantic_pallet_planner/outputs/JEV_JM1_B2_20261111_01'
QA=REPO/'semantic_pallet_planner/outputs/JEV_JM_JM1_B2_QA_20261111_01'
EVIDENCE=Path(os.environ['JM_B2_FIX_EVIDENCE']) if 'JM_B2_FIX_EVIDENCE' in os.environ else None
if EVIDENCE:
    assert EVIDENCE.resolve()==(REPO/'semantic_pallet_planner/outputs/JEV_JM1_B2_FIX_20261111_01').resolve()


def load(p):return json.loads(p.read_text())
def write(root,name,value):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return b2.saved_ref(name,root=root)

def mapping(root):
    return {str(p.relative_to(root)):b1.sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}

def forbidden(*args,**kwargs):raise AssertionError('forbidden sampler/network dispatch')


class SavedPointSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        shutil.copytree(OLD/'constructed_evidence',self.root,dirs_exist_ok=True)
        self.template=load(OLD/'constructed_template.json')
        self.binding=self.template['points'][0]
        self.point=b2.read_saved(self.binding['selected_point_ref'],root=self.root)
        self.public=b2.read_saved(self.binding['projection_ref'],root=self.root)
    def tearDown(self):self.tmp.cleanup()

    def check_readonly(self,template):
        before=mapping(self.root)
        with patch.object(b1,'sample',forbidden),patch.object(socket,'socket',forbidden):
            try:return b2.validate_template(template,root=self.root)
            finally:self.assertEqual(mapping(self.root),before)

    def test_original_qa_cases_and_additional_value_negatives(self):
        cases=[]
        archived=load(QA/'semantic_probe.json')
        expected={'invalid_native_lexeme':'B2_NATIVE_LEXEME_CHANGED',
                  'contradictory_gap':'B2_RELATIVE_GAP_CHANGED',
                  'false_orientation':'B2_ORIENTATION_FLAG_CHANGED','invalid_stratum':'B2_STRATUM_CHANGED'}
        for row in archived['cases']:
            cases.append((row['case'],row['mutated_selected_point'],expected[row['case']]))
        mutations=[
            ('member_token',lambda p:p['branches'][1]['members'][0].update(native_lexeme='0.5000'),'B2_GROUP_MEMBERS_CHANGED'),
            ('missing_member',lambda p:p['branches'][1].update(members=[]),'B2_GROUP_MEMBERS_CHANGED'),
            ('duplicate_member',lambda p:p['branches'][1]['members'].append(copy.deepcopy(p['branches'][1]['members'][0])),'B2_GROUP_MEMBERS_CHANGED'),
            ('wrong_member_map',lambda p:p['branches'][1]['members'][0].update(candidate_id='A0'),'B2_GROUP_MEMBERS_CHANGED'),
            ('group_score',lambda p:p['branches'][1].update(group_score={'numerator':1,'denominator':1}),'B2_GROUP_SCORE_CHANGED'),
            ('group_score_type',lambda p:p['branches'][1].update(group_score={'numerator':True,'denominator':2}),'B2_GROUP_SCORE_CHANGED'),
            ('layer',lambda p:p['branches'][1].update(layer='RELATIVE_NEAR_TOP'),'B2_BRANCH_LAYER_CHANGED'),
            ('cross_attribute',lambda p:p['branches'][2]['public_attribute_contrast']['alternative'].update(mass_kg=999),'B2_PUBLIC_ATTRIBUTE_CONTRAST_CHANGED'),
            ('cross_attribute_extra',lambda p:p['branches'][2]['public_attribute_contrast'].update(future_gain=1),'B2_PUBLIC_ATTRIBUTE_CONTRAST_CHANGED'),
            ('position_flag',lambda p:p['branches'][1].update(position_changed=False),'B2_POSITION_FLAG_CHANGED'),
            ('flag_integer',lambda p:p['branches'][1].update(orientation_changed=0),'B2_ORIENTATION_FLAG_CHANGED'),
            ('legal_but_wrong_stratum',lambda p:p.update(stratum='RELATIVE_NEAR_TOP'),'B2_STRATUM_CHANGED'),
            ('same_value_wrong_lexeme',lambda p:p['branches'][1].update(native_lexeme='0.5000'),'B2_NATIVE_LEXEME_CHANGED'),
        ]
        for name,mutate,code in mutations:
            p=copy.deepcopy(self.point);mutate(p);cases.append((name,p,code))
        observations=[]
        for name,point,code in cases:
            with self.subTest(name=name):
                t=copy.deepcopy(self.template)
                t['points'][0]['selected_point_ref']=write(self.root,f'negative/{name}.json',point)
                with self.assertRaisesRegex(b1.SamplingError,code) as error:self.check_readonly(t)
                observations.append({'case':name,'expected':code,'actual':str(error.exception),
                    'selected_point_ref':t['points'][0]['selected_point_ref'],'dispatches':0,'saved_bytes_unchanged':True})
        if EVIDENCE:
            shutil.copytree(self.root,EVIDENCE/'targeted_saved_evidence',dirs_exist_ok=True)
            write(EVIDENCE,'negative_semantic_receipts.json',{'scope':'CONSTRUCTED_ONLY','cases':observations,
                'archived_QA_cases_used_verbatim':True,'source_QA_probe_sha256':b1.sha((QA/'semantic_probe.json').read_bytes())})

    def test_diagnostic_binding_epsilon_and_local_row_negatives(self):
        ref=self.binding['selected_point_ref']
        diag=b2.read_saved({**ref,'pointer':''},root=self.root)
        mutations=[
            ('epsilon_missing',lambda d:d.pop('diagnostic_epsilon'),'B2_INVALID_DIAGNOSTIC_EPSILON'),
            ('epsilon_changed',lambda d:d.update(diagnostic_epsilon={'numerator':1,'denominator':10}),'B2_DIAGNOSTIC_EPSILON_PROCEDURE_CHANGED'),
            ('epsilon_illegal',lambda d:d.update(diagnostic_epsilon={'numerator':1,'denominator':0}),'B2_INVALID_DIAGNOSTIC_EPSILON'),
            ('policy_identity',lambda d:d.update(policy_sha256='0'*64),'B2_DIAGNOSTIC_IDENTITY_CHANGED'),
            ('point_row_missing',lambda d:d.update(rows=d['rows'][1:]),'B2_DIAGNOSTIC_EPSILON_PROCEDURE_CHANGED'),
            ('local_groups',lambda d:d['rows'][0]['groups'][0].update(score={'numerator':1,'denominator':1}),'B2_DIAGNOSTIC_GROUPS_CHANGED'),
            ('local_min_gap',lambda d:d['rows'][0].update(min_positive_gap={'numerator':3,'denominator':100}),'B2_DIAGNOSTIC_MIN_GAP_CHANGED'),
        ]
        observations=[]
        for name,mutate,code in mutations:
            with self.subTest(name=name):
                changed=copy.deepcopy(diag);mutate(changed)
                t=copy.deepcopy(self.template)
                t['points'][0]['selected_point_ref']=write(self.root,f'diagnostic/{name}.json',changed)|{'pointer':ref['pointer']}
                with self.assertRaisesRegex(b1.SamplingError,code) as error:self.check_readonly(t)
                observations.append({'case':name,'expected':code,'actual':str(error.exception),'dispatches':0,'saved_bytes_unchanged':True})
        # A valid point alone has no epsilon identity; refuse instead of guessing.
        t=copy.deepcopy(self.template);t['points'][0]['selected_point_ref']=write(self.root,'standalone.json',self.point)
        with self.assertRaisesRegex(b1.SamplingError,'B2_MISSING_SAMPLING_DIAGNOSTIC'):self.check_readonly(t)
        observations.append({'case':'standalone_valid_point_missing_diagnostic','actual':'B2_MISSING_SAMPLING_DIAGNOSTIC','dispatches':0})
        if EVIDENCE:
            shutil.copytree(self.root,EVIDENCE/'diagnostic_saved_evidence',dirs_exist_ok=True)
            write(EVIDENCE,'diagnostic_negative_receipts.json',{'scope':'CONSTRUCTED_ONLY','cases':observations})

    def test_raw_bytes_mapping_and_token_validation(self):
        originals=[('raw_identity',lambda p:p['probability_evidence'].update(raw_base64=base64.b64encode(b'{}').decode()),'RAW_IDENTITY_CHANGED'),
            ('mapping',lambda p:p['display_mapping'].pop(),'INCOMPLETE_MAP'),
            ('missing_probability',lambda p:p.update(probability_evidence=None),'MISSING_NATIVE_PROBABILITIES')]
        outcomes=[]
        for name,mutate,code in originals:
            with self.subTest(name=name):
                p=copy.deepcopy(self.public);mutate(p)
                with self.assertRaisesRegex(b1.SamplingError,code):b2._probability_facts(p)
                outcomes.append({'case':name,'reason':code})
        p=copy.deepcopy(self.public)
        raw=base64.b64decode(p['probability_evidence']['raw_base64']).replace(b'"C01":0.5',b'"C01":"0.5"')
        p['probability_evidence'].update(raw_base64=base64.b64encode(raw).decode(),raw_sha256=b1.sha(raw))
        with self.assertRaisesRegex(b1.SamplingError,'NONFINITE_OR_OUT_OF_RANGE'):b2._probability_facts(p)
        if EVIDENCE:write(EVIDENCE,'raw_negative_receipts.json',{'scope':'CONSTRUCTED_ONLY','cases':outcomes+[{'case':'quoted_numeric_token','reason':'NONFINITE_OR_OUT_OF_RANGE'}]})

    def test_archived_positive_budget_and_always_refused_gate(self):
        original=mapping(OLD);qa=mapping(QA)
        result=self.check_readonly(self.template);old=load(OLD/'constructed_budget.json')
        self.assertEqual(result['version'],'jev_jm_training_template_check_v2')
        self.assertEqual({k:v for k,v in result.items() if k!='version'},{k:v for k,v in old.items() if k!='version'})
        self.assertEqual(result['global_send_upper'],579)
        with patch.object(b1,'sample',forbidden):gate=b2.formal_freeze_readiness(self.template,root=self.root)
        self.assertEqual(gate['status'],'REFUSED');self.assertFalse(gate['formal_frozen'])
        self.assertEqual(original,mapping(OLD));self.assertEqual(qa,mapping(QA))
        if EVIDENCE:write(EVIDENCE,'legal_original_receipt.json',{'scope':'CONSTRUCTED_ONLY','current_result':result,
            'only_result_version_changed':True,'formal_gate':gate,'original_B2_unchanged':True,'original_QA_unchanged':True,'dispatches':0})

    def test_near_stratum_positive_and_outside_epsilon_refusal(self):
        # New raw-number fixture only; reuse exact saved pool/actions. Never sample.
        from fractions import Fraction
        p=copy.deepcopy(self.public)
        raw=base64.b64decode(p['probability_evidence']['raw_base64'])
        raw=raw.replace(b'"C00":0.5',b'"C00":0.500041').replace(b'"C01":0.5',b'"C01":0.500040')
        p['probability_evidence'].update(raw_base64=base64.b64encode(raw).decode(),raw_sha256=b1.sha(raw))
        row=b1.inspect_decision(p)
        self.assertEqual(row['min_positive_gap'],{'numerator':1,'denominator':500041})
        row.update(status='ELIGIBLE',selected=True,stratum='RELATIVE_NEAR_TOP')
        point=copy.deepcopy(self.point)
        point.update(projection_digest=b1.digest(p),raw_sha256=b1.sha(raw),stratum='RELATIVE_NEAR_TOP')
        scores={'C00':Fraction(500041,1000000),'C01':Fraction(500040,1000000),'C02':Fraction(49,100)}
        native={'C00':'0.500041','C01':'0.500040','C02':'0.49'}
        for branch in point['branches']:
            label=branch['label'];score=scores[label];gap=(scores['C00']-score)/scores['C00']
            branch.update(native_lexeme=native[label],group_score=b1._ratio(score),relative_gap=b1._ratio(gap),
                          layer='EXACT_TOP' if label=='C00' else 'RELATIVE_NEAR_TOP')
            branch['members'][0]['native_lexeme']=native[label]
        cross=point['branches'].pop()
        row['registered_layer']=sorted(b['exact_action_digest'] for b in point['branches'])
        diagnostic=b2.read_saved({**self.binding['selected_point_ref'],'pointer':''},root=self.root)
        diagnostic.update(rows=[row],selected_points=[point],positive_gap_denominator=1,
                          diagnostic_epsilon={'numerator':1,'denominator':500041})
        t=copy.deepcopy(self.template);t['slots']=t['slots'][:1];t['points']=t['points'][:1]
        t['points'][0].update(point_id=b1.digest({'projection':b1.digest(p),'decision_id':p['decision_id']}),
            projection_ref=write(self.root,'near_public.json',p),
            selected_point_ref=write(self.root,'near_diagnostic.json',diagnostic)|{'pointer':'/selected_points/0'})
        t['repeat_point_ids']=[t['points'][0]['point_id']]
        result=self.check_readonly(t)
        self.assertEqual(result['initial_suffixes'],2)
        diagnostic['selected_points'][0]['branches'].append(cross)
        t['points'][0]['selected_point_ref']=write(self.root,'near_outside.json',diagnostic)|{'pointer':'/selected_points/0'}
        with self.assertRaisesRegex(b1.SamplingError,'B2_BRANCH_OUTSIDE_SAVED_LAYER'):self.check_readonly(t)
        if EVIDENCE:write(EVIDENCE,'legal_near_and_outside_receipt.json',{'scope':'CONSTRUCTED_ONLY',
            'epsilon':{'numerator':1,'denominator':500041},'legal_result':result,
            'outside_cross_refused':'B2_BRANCH_OUTSIDE_SAVED_LAYER','dispatches':0})

    def test_archived_duplicate_action_original_member_identity(self):
        saved=load(REPO/'semantic_pallet_planner/outputs/JEV_JM1_B1_20261111_01/duplicate_actions.json')
        p=saved['input'];diag=saved['result'];point=diag['selected_points'][0]
        for ref in [p['pool_ref'],p['prefix_ref']]:
            target=self.root/ref['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((REPO/ref['path']).read_bytes())
        t=copy.deepcopy(self.template);t['slots']=t['slots'][:1];t['points']=t['points'][:1]
        t['points'][0].update(projection_ref=write(self.root,'duplicate_public.json',p),
            selected_point_ref=write(self.root,'duplicate_diagnostic.json',diag)|{'pointer':'/selected_points/0'},
            point_id=b1.digest({'projection':b1.digest(p),'decision_id':p['decision_id']}))
        t['repeat_point_ids']=[t['points'][0]['point_id']]
        result=self.check_readonly(t)
        self.assertEqual(len(point['branches'][0]['members']),2)
        self.assertEqual(point['branches'][0]['label'],'C00')
        self.assertEqual(point['branches'][0]['native_lexeme'],'0.1')
        self.assertEqual(point['branches'][0]['group_score'],{'numerator':1,'denominator':2})
        self.assertEqual((result['initial_suffixes'],result['repeat_suffixes']),(2,2))
        if EVIDENCE:write(EVIDENCE,'legal_duplicate_receipt.json',{'scope':'CONSTRUCTED_ONLY','original_branch':point['branches'][0],'result':result})


if __name__=='__main__':unittest.main(verbosity=2)
