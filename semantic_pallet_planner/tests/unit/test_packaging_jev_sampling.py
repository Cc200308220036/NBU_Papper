"""CONSTRUCTED_ONLY. stdlib tests; no model, engine, candidate build or solver."""
import base64
import copy
from decimal import localcontext
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from semantic_pallet_planner.jev_select import packaging_jev_sampling as s

OUT=Path(os.environ['JM_B1_EVIDENCE']) if 'JM_B1_EVIDENCE' in os.environ else None


def archive(p):
    if OUT:
        folder=OUT/'constructed_saved'
        folder.mkdir(exist_ok=True)
        for field,value in [('pool_ref',[c['frozen_candidate'] for c in p['pool']]),('prefix_ref',p['public_state'])]:
            raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
            path=folder/(field+'_'+s.sha(raw)+'.json')
            path.write_bytes(raw)
            p[field]={'path':path.as_posix(),'sha256':s.sha(raw),'pointer':''}
    return p


def make(*, scores=('0.5','0.5','0.49'), items=('a','a','b'), task='T0', ordinal=0, placed=False, original=0):
    pool=[]
    for i,item in enumerate(items):
        c={'candidate_id':f'A{i}', 'pick_item_id':item,
           'pose':{'x_mm':i*10,'y_mm':0,'z_base_mm':0,'yaw_deg':0},'oriented_size_mm':[10,20,30]}
        c['frozen_candidate']=copy.deepcopy(c)
        c['candidate_digest']=s.digest(c['frozen_candidate'])
        pool.append(c)
    def attr(item):
        return {'item_id':item,'size_mm':[10,20,30],'mass_kg':1,'max_top_load_kg':5,'stackable':True}
    state={'container':{'length_mm':100,'width_mm':100,'max_height_mm':100,'max_payload_kg':100},
           'buffer':[attr(x) for x in sorted(set(items))],'placed_objects':[]}
    if placed:
        state['placed_objects']=[attr('placed')|{'pose':{'x_mm':0,'y_mm':0,'z_base_mm':0,'yaw_deg':0},
                                             'oriented_size_mm':[10,20,30],
                                             'area_current_top_load_kg':0,'area_remaining_top_load_kg':5}]
    mapping=[{'label':f'C{i:02}', 'candidate_id':c['candidate_id'],'candidate_digest':c['candidate_digest']} for i,c in enumerate(pool)]
    ref={'path':'CONSTRUCTED_ONLY.json','sha256':'0'*64,'pointer':''}
    p={'version':s.JM_SAMPLING_VERSION,'evidence_scope':'CONSTRUCTED_ONLY','task_id':task,'source_group':'CONSTRUCTED_GROUP',
       'decision_id':f'D{ordinal}','decision_ordinal':ordinal,'prefix_ref':copy.deepcopy(ref),'pool_ref':copy.deepcopy(ref),
       'public_state':state,'pool':pool,'display_mapping':mapping,
       'original':{'label':mapping[original]['label'],'candidate_id':pool[original]['candidate_id'],
                   'exact_action_digest':s.exact_digest(pool[original])},'probability_evidence':None}
    raw=('{"model":"CONSTRUCTED_ONLY","answers":{"next_action":{"type":"choice","choice":"'+mapping[original]['label']+
         '","probabilities":{'+','.join('"'+r['label']+'":'+v for r,v in zip(mapping,scores))+'},"confidence":0.5}}}').encode()
    set_raw(p,raw)
    return archive(p)


def set_raw(p,raw):
    p['probability_evidence']={'protocol':'jev_systemone_choice_native_v1','origin':'CONSTRUCTED_ONLY',
                             'raw_base64':base64.b64encode(raw).decode(),'raw_sha256':s.sha(raw)}


def run(*ps,order=None):
    return s.sample(list(ps),task_order=order or list(dict.fromkeys(p['task_id'] for p in ps)))


class SamplingTests(unittest.TestCase):
    def test_determinism_private_isolation_and_saved_refs(self):
        p=make()
        a=s.project_public(p,private_audit={'terminal':0,'future':['x'],'suffix_gain':100})
        b=s.project_public(p,private_audit={'terminal':99,'future':['y'],'suffix_gain':-100})
        self.assertEqual(a,b);self.assertEqual(run(a),run(b));self.assertEqual(run(a),run(a))
        with tempfile.TemporaryDirectory() as tmp:
            for field,value in [('pool_ref',[c['frozen_candidate'] for c in p['pool']]),('prefix_ref',p['public_state'])]:
                path=Path(tmp)/(field+'.json');path.write_text(json.dumps(value))
                p[field]={'path':path.name,'sha256':s.sha(path.read_bytes()),'pointer':''}
            before={f.name:s.sha(f.read_bytes()) for f in Path(tmp).iterdir()}
            self.assertEqual(s.validate_saved_evidence(p,root=tmp)['dispatches'],0)
            self.assertEqual(before,{f.name:s.sha(f.read_bytes()) for f in Path(tmp).iterdir()})
            (Path(tmp)/'pool_ref.json').write_text('[]')
            with self.assertRaisesRegex(s.SamplingError,'SAVED_IDENTITY_CHANGED'):
                s.validate_saved_evidence(p,root=tmp)
        if OUT:
            s.validate_saved_evidence(a,root='.')
            (OUT/'saved_validation.json').write_text(json.dumps(s.validate_saved_evidence(a,root='.'),indent=2)+'\n')
            (OUT/'constructed_public.json').write_text(json.dumps(a,indent=2)+'\n')
            (OUT/'constructed_diagnostic.json').write_text(json.dumps(run(a),indent=2)+'\n')

    def test_exact_ties_versus_display_rounding(self):
        exact=run(make(scores=('0.5','0.5000','0.1')))['rows'][0]
        fake=run(make(scores=('0.500041','0.500040','0.1')))['rows'][0]
        self.assertTrue(exact['exact_top_tie']);self.assertFalse(fake['exact_top_tie'])
        self.assertEqual(fake['stratum'],'RELATIVE_NEAR_TOP')
        self.assertEqual(fake['native_lexemes']['C00'],'0.500041')
        tiny=make(scores=('0.500000000000000000000000000000000001','0.5','0.1'))
        with localcontext() as ctx:
            ctx.prec=2
            self.assertFalse(run(tiny)['rows'][0]['exact_top_tie'])
        if OUT:
            (OUT/'rounding_negative.json').write_text(json.dumps({'scope':'CONSTRUCTED_ONLY','exact':exact,'display_false_tie':fake},indent=2)+'\n')

    def test_probabilities_refuse_without_imputation(self):
        cases=[]
        p=make();p['probability_evidence']=None;cases.append((p,'MISSING_NATIVE_PROBABILITIES'))
        for token in ('-0.1','1.1','NaN','Infinity','true','"0.5"','null'):
            cases.append((make(scores=(token,'0.5','0.1')),'NONFINITE_OR_OUT_OF_RANGE'))
        p=make(scores=('0.5',));cases.append((p,'INCOMPLETE_MAP'))
        p=make();p['display_mapping'][1]['candidate_id']='A0';cases.append((p,'INCOMPLETE_MAP'))
        p=make();p['version']='unknown';cases.append((p,'UNKNOWN_PROTOCOL'))
        p=make();p['probability_evidence']['raw_sha256']='f'*64;cases.append((p,'RAW_IDENTITY_CHANGED'))
        p=make();raw=base64.b64decode(p['probability_evidence']['raw_base64']).replace(b'"C00":0.5',b'"C00":0.5,"C00":0.5');set_raw(p,raw)
        cases.append((p,'DUPLICATE_JSON_KEY'))
        receipts=[]
        for p,code in cases:
            with self.subTest(code=code):
                result=run(p,order=['T0']);row=result['rows'][0]
                self.assertEqual(row['reason'],code);self.assertEqual(result['selected_points'],[])
                self.assertEqual(result['counts']['all_supplied_decisions'],1)
                receipts.append({'scope':'CONSTRUCTED_ONLY','public':p,'diagnostic':result})
        if OUT:
            (OUT/'negative_cases.json').write_text(json.dumps(receipts,indent=2)+'\n')

    def test_duplicate_exact_max_and_original_identity(self):
        p=make(scores=('0.1','0.5','0.5'))
        p['pool'][1]['pose']=copy.deepcopy(p['pool'][0]['pose'])
        p['pool'][1]['pose']['x_mm']=-0.0
        p['pool'][1]['oriented_size_mm']=[10.0,20.0,30.0]
        p['pool'][1]['frozen_candidate'].update(pose=p['pool'][1]['pose'],oriented_size_mm=p['pool'][1]['oriented_size_mm'])
        p['pool'][1]['candidate_digest']=s.digest(p['pool'][1]['frozen_candidate'])
        p['display_mapping'][1]['candidate_digest']=p['pool'][1]['candidate_digest']
        archive(p)
        result=run(p);row=result['rows'][0]
        self.assertEqual(row['duplicate_exact_actions'],1)
        branches=row['branches'];self.assertEqual(len(branches),2)
        self.assertEqual(branches[0]['group_score'],{'numerator':1,'denominator':2})
        self.assertEqual(branches[0]['label'],'C00');self.assertEqual(len(branches[0]['members']),2)
        self.assertIn('SAME_BOX',row['missing_classes'])
        for b in branches:
            c=next(c for c in p['pool'] if c['candidate_id']==b['candidate_id'])
            self.assertEqual(s.exact_digest(c),b['exact_action_digest'])
            self.assertEqual(c['candidate_digest'],b['candidate_digest'])
        if OUT:
            (OUT/'duplicate_actions.json').write_text(json.dumps({'scope':'CONSTRUCTED_ONLY','input':p,'result':result},indent=2)+'\n')

    def test_category_gaps_original_outside_and_no_point(self):
        same=run(make(items=('a','a'),scores=('0.5','0.5')))['rows'][0]
        cross=run(make(items=('a','b'),scores=('0.5','0.5')))['rows'][0]
        self.assertEqual(same['missing_classes'],['CROSS_BOX']);self.assertEqual(cross['missing_classes'],['SAME_BOX'])
        outside=run(make(scores=('0.01','0.5','0.49')))['rows'][0]
        self.assertEqual(outside['reason'],'ORIGINAL_OUTSIDE_LAYER')
        none=run(make(scores=('0.9','0.05','0.05')))
        self.assertEqual(none['rows'][0]['reason'],'NO_ALTERNATIVE_CLASS')
        self.assertEqual(len(none['coverage_gaps']),2)
        self.assertEqual(run(make(scores=('0','0','0')))['rows'][0]['reason'],'NONPOSITIVE_MAX')

    def test_quantile_ceiling_exact_only_and_context_independence(self):
        points=[make(scores=('1',v,'0'),ordinal=i) for i,v in enumerate(('0.8','0.9','0.95','0.98','0.99'))]
        result=run(*points)
        self.assertEqual(result['diagnostic_epsilon'],{'numerator':1,'denominator':50})
        self.assertEqual(run(make(scores=('1','0.2','0')))['diagnostic_epsilon'],{'numerator':1,'denominator':10})
        result=run(make(scores=('0.2','0.2','0.2')))
        self.assertEqual(result['diagnostic_epsilon'],{'numerator':0,'denominator':1})
        self.assertEqual(result['real_epsilon'],'NOT_MATERIALIZED_DEFER_C1')
        self.assertEqual(len(result['selected_points']),1)

    def test_stage_cap_priority_and_full_denominator(self):
        ps=[]
        for t in range(6):
            for i in range(4):
                ps.append(make(task=f'T{t}',ordinal=i,placed=i>1))
        result=run(*ps)
        self.assertEqual(len(result['rows']),24);self.assertEqual(len(result['selected_points']),12)
        self.assertEqual(sum(r['reason']=='STAGE_PRIORITY_NOT_SELECTED' for r in result['rows']),12)
        for point in result['selected_points']:
            self.assertEqual(point['decision_id'],'D0' if point['stage']=='OPENING' else 'D2')
        with self.assertRaisesRegex(s.SamplingError,'TASK_CAP'):
            run(*ps,order=[f'T{i}' for i in range(7)])
        same=make(items=('a','a'),scores=('0.5','0.5'),ordinal=0)
        both=make(ordinal=1)
        self.assertEqual(run(same,both)['selected_points'][0]['decision_id'],'D1')
        with self.assertRaisesRegex(s.SamplingError,'DUPLICATE_DECISION'):
            run(same,same)
        if OUT:
            (OUT/'cap_coverage.json').write_text(json.dumps(result,indent=2)+'\n')
            (OUT/'cap_batch.json').write_text(json.dumps({'version':'jev_jm_sampling_batch_v1','task_order':[f'T{i}' for i in range(6)],'decisions':ps},indent=2)+'\n')

    def test_reject_nested_private_fields_and_unknown_protocols(self):
        for target in ('public_state','candidate','item','envelope'):
            p=make()
            obj={'public_state':p['public_state'],'candidate':p['pool'][0],
                 'item':p['public_state']['buffer'][0],'envelope':p}[target]
            obj['future_terminal_pct']={'gain':1}
            self.assertEqual(run(p,order=['T0'])['rows'][0]['status'],'REJECTED')
        p=make();p['probability_evidence']['protocol']='display_rounded_v1'
        self.assertEqual(run(p)['rows'][0]['status'],'REJECTED')
        p=make();set_raw(p,b'{"model":"x","answers":{},"terminal_outcome":1}')
        self.assertEqual(run(p)['rows'][0]['reason'],'UNKNOWN_RESPONSE_PROTOCOL')

    def test_orientation_digest_order_and_frozen_tamper(self):
        p=make(items=('a','a'),scores=('0.5','0.5'))
        c=p['pool'][1]
        c['pose'].update(x_mm=0,yaw_deg=90)
        c['oriented_size_mm']=[20,10,30]
        c['frozen_candidate'].update(pose=c['pose'],oriented_size_mm=c['oriented_size_mm'])
        c['candidate_digest']=s.digest(c['frozen_candidate'])
        p['display_mapping'][1]['candidate_digest']=c['candidate_digest']
        archive(p)
        branch=run(p)['rows'][0]['branches'][1]
        self.assertTrue(branch['orientation_changed']);self.assertFalse(branch['position_changed'])
        p['pool'][0]['frozen_candidate']['pose']['x_mm']=1
        self.assertEqual(run(p)['rows'][0]['reason'],'FROZEN_CANDIDATE_CHANGED')
        p=make(scores=('0.5','0.5','0.5'),items=('a','b','c'))
        expected=min(s.exact_digest(c) for c in p['pool'][1:])
        self.assertEqual(run(p)['selected_points'][0]['branches'][1]['exact_action_digest'],expected)
        p=make(items=('a',),scores=('1',))
        self.assertFalse(run(p)['rows'][0]['multi_candidate'])
        self.assertEqual(run(p)['selected_points'],[])

    def test_no_business_import_dispatch_and_cli(self):
        # Fresh interpreter: forbid both imports and all network operations while
        # calling the actual sampler and saved validator. No stub engine is loaded.
        code='''
import importlib.abc,sys,json,socket,tempfile
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(x in fullname for x in ('packaging_remote','selector','transport','episode','stability','planning','numpy','scipy','jsonschema')):
   raise AssertionError('forbidden business import: '+fullname)
sys.meta_path.insert(0,Guard())
def forbidden(*a,**k):raise AssertionError('network dispatch')
socket.socket=forbidden
from semantic_pallet_planner.jev_select import packaging_jev_sampling as s
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text())
r=s.sample([p],task_order=['T0'])
with tempfile.TemporaryDirectory() as tmp:
 for field,value in [('pool_ref',[c['frozen_candidate'] for c in p['pool']]),('prefix_ref',p['public_state'])]:
  path=Path(tmp)/(field+'.json');path.write_text(json.dumps(value))
  p[field]={'path':path.name,'sha256':s.sha(path.read_bytes()),'pointer':''}
 assert s.validate_saved_evidence(p,root=tmp)['dispatches']==0
print(json.dumps({'status':'PASS','selected':len(r['selected_points']),'business_imports':0,'network':0,'saved_dispatch':0}))
'''
        with tempfile.TemporaryDirectory() as tmp:
            inp=Path(tmp)/'p.json';inp.write_text(json.dumps(make()))
            result=subprocess.run([sys.executable,'-c',code,str(inp)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            if OUT:(OUT/'zero_dispatch.json').write_text(result.stdout)
            batch=Path(tmp)/'batch.json';batch.write_text(json.dumps({'version':'jev_jm_sampling_batch_v1','task_order':['T0'],'decisions':[make()]}))
            output=Path(tmp)/'out.json'
            cli=[sys.executable,'-m','semantic_pallet_planner.jev_select.packaging_jev_sampling',str(batch),str(output)]
            result=subprocess.run(cli,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(output.read_text()),run(make()))
            self.assertNotEqual(subprocess.run(cli,capture_output=True).returncode,0)


if __name__=='__main__':
    unittest.main(verbosity=2)
