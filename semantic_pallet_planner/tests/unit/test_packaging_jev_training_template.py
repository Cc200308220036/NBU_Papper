"""B2 CONSTRUCTED_ONLY metadata; reuse B1 saved pools, no new tasks or engines."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from semantic_pallet_planner.jev_select import packaging_jev_training_template as b2
from semantic_pallet_planner.jev_select import packaging_jev_sampling as b1

ROOT=Path(__file__).resolve().parents[3]
B1='semantic_pallet_planner/outputs/JEV_JM1_B1_20261111_01/'
POLICY='semantic_pallet_planner/outputs/JEV_JM0_B_20261111_01/sampling_policy.json'
EVIDENCE=Path(os.environ['JM_B2_EVIDENCE']) if 'JM_B2_EVIDENCE' in os.environ else None


def write(root,name,value):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return b2.saved_ref(name,root=root)


def fixture(root):
    # Only saved B1 fixtures are copied. No candidate generation/engine execution.
    for name in ['cap_batch.json','cap_coverage.json']:
        value=json.loads((ROOT/(B1+name)).read_text());write(root,B1+name,value)
    batch=json.loads((root/(B1+'cap_batch.json')).read_text())
    for p in batch['decisions']:
        for name in ['pool_ref','prefix_ref']:
            source=ROOT/p[name]['path'];target=root/p[name]['path'];target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(source.read_bytes())
    policy=json.loads((ROOT/POLICY).read_text());write(root,POLICY,policy)
    # Preserve exact original policy bytes required by pinned B1 contract digest.
    (root/POLICY).write_bytes((ROOT/POLICY).read_bytes())
    source_ref=write(root,'constructed_source_candidates.json',{'scope':'CONSTRUCTED_ONLY','formal_tasks':[]})
    t=b2.make_template(policy_ref=b2.saved_ref(POLICY,root=root),source_candidates_ref=source_ref)
    t['evidence_kind']='CONSTRUCTED_ONLY'
    for i,slot in enumerate(t['slots']):
        metadata={'version':'jev_jm_constructed_budget_metadata_v1','evidence_kind':'CONSTRUCTED_ONLY',
                  'task_id':f'T{i}','full_item_count':10+i,'source_group':'CONSTRUCTED_GROUP',
                  'relation_tokens':['SOURCE:CONSTRUCTED_GROUP',f'VARIANT:T{i}'],
                  'relation_completeness':'CONSTRUCTED_COMPLETE'}
        slot['assignment']={'task_id':metadata['task_id'],'metadata_ref':write(root,f'metadata/T{i}.json',metadata)}
    diagnostic=json.loads((root/(B1+'cap_coverage.json')).read_text());repeat=[]
    for i,point in enumerate(diagnostic['selected_points']):
        di=next(j for j,p in enumerate(batch['decisions']) if (p['task_id'],p['decision_id'])==(point['task_id'],point['decision_id']))
        p=batch['decisions'][di];pid=b1.digest({'projection':b1.digest(p),'decision_id':p['decision_id']})
        t['points'].append({'point_id':pid,'task_id':p['task_id'],'stage':point['stage'],
            'projection_ref':b2.saved_ref(B1+'cap_batch.json',root=root,pointer=f'/decisions/{di}'),
            'selected_point_ref':b2.saved_ref(B1+'cap_coverage.json',root=root,pointer=f'/selected_points/{i}')})
        repeat.append({'point_id':pid,'task_id':p['task_id'],'stage':point['stage'],
                       'source_component':'all_same','decision_digest':b1.digest(p['decision_id'])})
    t['repeat_point_ids']=b2.repeat_priority(repeat,task_order=[f'T{i}' for i in range(6)])
    return t


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.t=fixture(self.root)
    def tearDown(self):self.temp.cleanup()
    def reject(self,t,code):
        with self.assertRaisesRegex(b1.SamplingError,code):b2.validate_template(t,root=self.root)

    def test_max_matrix_and_budget_sums(self):
        result=b2.validate_template(self.t,root=self.root)
        self.assertEqual((result['points'],result['initial_suffixes'],result['repeat_suffixes'],result['total_suffixes']),(12,36,12,48))
        self.assertEqual(result['baseline_send_upper'],sum(range(10,16)))
        self.assertEqual(result['global_send_upper'],sum(j['send_upper'] for j in result['jobs']))
        for j in result['jobs']:
            self.assertEqual(j['send_upper'],max(0,j['full_items']-j['placed_before']-j['forced_first']))
        self.assertEqual(result['source_components']['component_count'],1)
        self.assertEqual(result['source_components']['independent_real_sources'],'UNKNOWN_NOT_CERTIFIED')
        self.assertEqual(len(result['jobs']),54)
        if EVIDENCE:
            target=EVIDENCE/'constructed_evidence'
            import shutil
            shutil.copytree(self.root,target,dirs_exist_ok=True)
            write(EVIDENCE,'constructed_template.json',self.t)
            write(EVIDENCE,'constructed_budget.json',result)
            write(EVIDENCE,'constructed_formal_refusal.json',b2.formal_freeze_readiness(self.t,root=self.root))

    def test_unbound_template_and_formal_refusal(self):
        t=b2.make_template(policy_ref=self.t['policy_ref'],source_candidates_ref=self.t['source_candidates_ref'])
        result=b2.validate_template(t,root=self.root)
        self.assertEqual([s['wave'] for s in t['slots']],[1,1,1,2,2,2])
        self.assertEqual(result['budget_status'],'NOT_MATERIALIZED');self.assertIsNone(result['global_send_upper'])
        gate=b2.formal_freeze_readiness(t,root=self.root)
        self.assertEqual(gate['status'],'REFUSED');self.assertFalse(gate['formal_frozen'])
        self.assertIn('UNBOUND_TASK_SLOTS',gate['reasons'])
        for key in t['real_identities']:
            bad=copy.deepcopy(t);bad['real_identities'][key]='0'*64;self.reject(bad,'PUBLIC_SCHEMA')
        for field,value in [('state','FROZEN'),('execution_state','EXECUTABLE'),('execution_authorized',True),('evidence_kind','REAL')]:
            bad=copy.deepcopy(t);bad[field]=value;self.reject(bad,'PUBLIC_SCHEMA')

    def test_wave_cap_duplicate_task_and_unbound_point_rejections(self):
        bad=copy.deepcopy(self.t);bad['slots'].append(copy.deepcopy(bad['slots'][-1]));self.reject(bad,'PUBLIC_SCHEMA')
        bad=copy.deepcopy(self.t);bad['slots'][3]['wave']=1;self.reject(bad,'B2_WAVES')
        bad=copy.deepcopy(self.t);bad['slots'][1]['ordinal']=1;self.reject(bad,'B2_SLOT_ORDER')
        bad=copy.deepcopy(self.t);bad['slots'][1]['assignment']=copy.deepcopy(bad['slots'][0]['assignment']);self.reject(bad,'B2_DUPLICATE_TASK')
        bad=copy.deepcopy(self.t);bad['slots'][0]['assignment']=None;self.reject(bad,'B2_POINTS_WITH_UNBOUND')

    def test_repeat_round_robin_diversity_and_no_outcomes(self):
        pts=[]
        for task,group in [('a','G1'),('b','G1'),('c','G2')]:
            for stage in ['OPENING','NONEMPTY']:
                pts.append({'point_id':b1.digest([task,stage]),'task_id':task,'stage':stage,
                            'source_component':group,'decision_digest':b1.digest(stage)})
        order=['a','b','c'];picked=b2.repeat_priority(pts,task_order=order)
        lookup={p['point_id']:p for p in pts}
        self.assertEqual([lookup[k]['stage'] for k in picked],['OPENING','NONEMPTY','OPENING','NONEMPTY'])
        self.assertEqual(lookup[picked[1]]['task_id'],'c')
        self.assertEqual(picked,b2.repeat_priority(list(reversed(pts)),task_order=order))
        pts[0]['suffix_gain']=100
        with self.assertRaisesRegex(b1.SamplingError,'PUBLIC_FIELDS_ONLY'):b2.repeat_priority(pts,task_order=order)
        bad=copy.deepcopy(self.t);bad['repeat_point_ids']=list(reversed(bad['repeat_point_ids']));self.reject(bad,'PREREGISTRATION')
        bad=copy.deepcopy(self.t);bad['repeat_point_ids']+=bad['repeat_point_ids'][:1];self.reject(bad,'PUBLIC_SCHEMA')

    def test_saved_point_stage_pool_exact_action_and_branch_rejections(self):
        # Mutate copies and bind new saved hashes, so failures exercise semantic checks.
        bad=copy.deepcopy(self.t);bad['points'][1]=copy.deepcopy(bad['points'][0]);self.reject(bad,'DUPLICATE_STAGE')
        baseline=json.loads((self.root/(B1+'cap_coverage.json')).read_text())
        cases=[('reference',lambda p:p['branches'].pop(0),'B2_BRANCH_CLASSES'),
               ('duplicate',lambda p:p['branches'].append(copy.deepcopy(p['branches'][0])),'B2_BRANCH_CLASSES'),
               ('action',lambda p:p['branches'][1].update(exact_action_digest='0'*64),'B2_EXACT_ACTION_CHANGED'),
               ('pool',lambda p:p['pool_ref'].update(sha256='0'*64),'B2_POINT_SAVED_REFS_CHANGED'),
               ('stage',lambda p:p.update(stage='NONEMPTY'),'B2_STAGE_CHANGED'),
               ('outcome',lambda p:p['branches'][0].update(suffix_gain=1),'B2_BRANCH_CLOSED_FIELDS')]
        receipts=[]
        for name,mutate,code in cases:
            bad=copy.deepcopy(self.t);diag=copy.deepcopy(baseline);mutate(diag['selected_points'][0])
            ref=write(self.root,f'negative/{name}.json',diag)
            bad['points'][0]['selected_point_ref']=ref|{'pointer':'/selected_points/0'}
            self.reject(bad,code);receipts.append({'case':name,'refusal':code,'dispatches':0})
        if EVIDENCE:write(EVIDENCE,'negative_semantic_receipts.json',{'scope':'CONSTRUCTED_ONLY','cases':receipts})

    def test_missing_category_keeps_smaller_denominator(self):
        t=copy.deepcopy(self.t)
        diagnostic=json.loads((self.root/(B1+'cap_coverage.json')).read_text())
        for point in diagnostic['selected_points']:
            point['branches']=[b for b in point['branches'] if b['kind']!='CROSS_BOX_SELECTION']
        ref=write(self.root,'same_box_only.json',diagnostic)
        for i,point in enumerate(t['points']):
            point['selected_point_ref']=ref|{'pointer':f'/selected_points/{i}'}
        result=b2.validate_template(t,root=self.root)
        self.assertEqual((result['initial_suffixes'],result['repeat_suffixes'],result['total_suffixes']),(24,8,32))
        self.assertEqual(len(result['repeat_points']),4)
        if EVIDENCE:write(EVIDENCE,'missing_category_budget.json',result)

    def test_source_transitive_variants_shared_prototypes_unknown(self):
        rows=[{'task_id':'a','source_group':'S1','relation_tokens':['VARIANT:base','PROTO:x'],'relation_completeness':'CONSTRUCTED_COMPLETE'},
              {'task_id':'b','source_group':'S2','relation_tokens':['PROTO:y'],'relation_completeness':'CONSTRUCTED_COMPLETE'},
              {'task_id':'c','source_group':'S3','relation_tokens':['PROTO:x','PROTO:y'],'relation_completeness':'UNKNOWN'}]
        result=b2.relation_components(rows)
        self.assertEqual(result['component_count'],1);self.assertEqual(result['membership_status'],'UNKNOWN')
        self.assertEqual(result['material_components'][0]['tasks'],['a','b','c'])

    def test_small_matrix_and_remaining_count_edges(self):
        t=copy.deepcopy(self.t);t['slots']=t['slots'][:1];t['points']=t['points'][:2]
        # Four public items are visible in nonempty state, so task count 4 is the minimum.
        write(self.root,'metadata/T0.json',{'version':'jev_jm_constructed_budget_metadata_v1','evidence_kind':'CONSTRUCTED_ONLY',
           'task_id':'T0','full_item_count':4,'source_group':'CONSTRUCTED_GROUP','relation_tokens':['G'],'relation_completeness':'UNKNOWN'})
        t['slots'][0]['assignment']['metadata_ref']=b2.saved_ref('metadata/T0.json',root=self.root)
        t['repeat_point_ids']=[p['point_id'] for p in t['points']]
        result=b2.validate_template(t,root=self.root)
        self.assertEqual(result['initial_suffixes'],6);self.assertEqual(result['repeat_suffixes'],6)
        self.assertEqual(result['global_send_upper'],4+6*3+6*2)
        m=b2.read_saved(t['slots'][0]['assignment']['metadata_ref'],root=self.root);m['full_item_count']=1
        t['slots'][0]['assignment']['metadata_ref']=write(self.root,'metadata/T0.json',m)
        self.reject(t,'B2_IMPOSSIBLE_ITEM_DENOMINATOR')

    def test_saved_audit_head_independence_source_drift_and_prefix(self):
        path='source.py';(self.root/path).write_text('# delivery source\n')
        raw=(self.root/path).read_bytes()
        capsule={'version':'jev_jm_saved_bytes_audit_v1','entry_head':'11790ca4e7af9d2affe0a2980dc1158a774d9900',
                 'scope':'B2_TEMPLATE_DELIVERY','files':[{'path':path,'sha256':b1.sha(raw),'bytes':len(raw),'comparison':'EXACT','extension_sha256':None}]}
        (self.root/'.git').mkdir();(self.root/'.git/HEAD').write_text('ref: refs/heads/after-delivery\n')
        a=b2.validate_saved_audit(capsule,root=self.root)
        (self.root/'.git/HEAD').write_text('different later HEAD\n')
        self.assertEqual(a,b2.validate_saved_audit(capsule,root=self.root))
        (self.root/path).write_text('# drift\n')
        with self.assertRaisesRegex(b1.SamplingError,'SOURCE_DRIFT'):b2.validate_saved_audit(capsule,root=self.root)
        capsule['files'][0]['comparison']='ENTRY_PREFIX'
        with self.assertRaisesRegex(b1.SamplingError,'PREFIX_SCOPE'):b2.validate_saved_audit(capsule,root=self.root)
        if EVIDENCE:write(EVIDENCE,'head_independence.json',{'scope':'CONSTRUCTED_ONLY','receipt':a,
            'mutable_git_head_changed_without_affecting_verification':True,'source_drift_refused':True,
            'actual_git_commit_performed':False,'note':'No Git operations; proves checker ignores .git/HEAD, not a real commit execution.'})

    def test_zero_dispatch_readonly_guard_and_cli(self):
        template=write(self.root,'template.json',self.t)
        code='''
import importlib.abc,sys,socket,json
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(x in fullname for x in ('packaging_remote','selector','transport','episode','stability','planning','numpy','scipy')):
   raise AssertionError('business import forbidden: '+fullname)
sys.meta_path.insert(0,Guard())
def fail(*a,**k):raise AssertionError('dispatch forbidden')
socket.socket=fail
from semantic_pallet_planner.jev_select import packaging_jev_sampling as b1
from semantic_pallet_planner.jev_select import packaging_jev_training_template as b2
b1.sample=fail
from pathlib import Path
root=Path(sys.argv[1]);before={str(p):b1.sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
t=json.loads((root/'template.json').read_text());r=b2.validate_template(t,root=root)
assert b2.formal_freeze_readiness(t,root=root)['status']=='REFUSED'
assert before=={str(p):b1.sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
print(json.dumps({'status':'PASS','dispatches':r['dispatches'],'unchanged_saved_bytes':True,'sampling_dispatch':0}))
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.root)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        if EVIDENCE:(EVIDENCE/'zero_dispatch.json').write_text(result.stdout)
        result=subprocess.run([sys.executable,'-m','semantic_pallet_planner.jev_select.packaging_jev_training_template','formal-gate',str(self.root/'template.json'),'--root',str(self.root)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['status'],'REFUSED')


if __name__=='__main__':unittest.main(verbosity=2)
