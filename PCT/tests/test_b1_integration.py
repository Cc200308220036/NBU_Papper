"""Public integration constructions only. No candidate builder or order execution.

Requires existing jsonschema/numpy; never installs dependencies or substitutes a
validator. Missing dependencies are reported as skipped, not acceptance PASS.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import types
import unittest

READY=all(importlib.util.find_spec(n) is not None for n in ('jsonschema','numpy'))
ROOT=Path(__file__).resolve().parents[2]
PUBLIC=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select'


@unittest.skipUnless(READY,'NOT_RUN: jsonschema and numpy required')
class PublicIntegrationTests(unittest.TestCase):
    def config(self,new=True):
        config=json.loads((PUBLIC/'configs/packaging_runtime_v4.json').read_text())
        config['runtime_identity']={k:'a'*64 for k in ('data_identity','physical_identity','strategy_identity','task_identity')}
        if new:
            config.update(version='pct_b1_config_v1',model=None,selector='geometry_b1',buffer_capacity=1,
                execution_spec_digest='b'*64,model_identity=None,
                stability_monitor={'enabled':False,'algorithm':None,'kernel_config':None,'algorithm_identity':None,'execution_environment':None})
            config['runtime_identity']['monitor_identity']='c'*64
        return config

    def constructed(self,capacity=1,n=2,eos=False):
        from semantic_pallet_planner.o4.extensions.e2.protocol import observation
        from semantic_pallet_planner.jev_select.contracts import CandidateBundle,digest
        from semantic_pallet_planner.jev_select.packaging_runtime import INSTRUCTION
        item={'item_id':'CURRENT_PRIVATE_ID','mass_kg':2,'dimensions_mm':{'length':100,'width':200,'height':50},
              'stackable':True,'top_load_limit_kg_synthetic':10,'fragile':False,'weight_class':'medium','product_category':'general'}
        attrs={'object_id':item['item_id'],'physical_top_load_limit_kg':10,'cargo_category':'general',
               'packaging':{'reinforced':False},'labels':{'no_top_load':False,'max_top_load_kg':10}}
        pending=[] if eos else [{'item':item,'slot':0,'arrival_index':0}]
        state={'container':{'container_id':'CONSTRUCTED','coordinate_frame':'container_bottom_center',
                    'length_mm':1000,'width_mm':1000,'max_height_mm':1000,'max_payload_kg':1000},
               'buffer_capacity':capacity,'pending_items':pending,'placed_items':[],
               'arrived_ids':[] if eos else [item['item_id']], 'attributes':{} if eos else {item['item_id']:attrs},
               'event_index':1,'arrival_count':0 if eos else 1,'placed_count':0,'end_of_stream':eos}
        req=observation(state,INSTRUCTION,[])
        candidates=[]
        for index in range(0 if eos else n):
            candidates.append({'candidate_id':f'EXACT_ORIGINAL_{index}','pick_item_id':item['item_id'],
                'pose':{'x_mm':index*100,'y_mm':0,'z_base_mm':0,'yaw_deg':90 if index else 0},
                'oriented_size_mm':[200,100,50] if index else [100,200,50],
                'support':{'support_ratio':1,'com_margin_mm':50,'support_item_ids':[]},
                'candidate_fingerprint':f'fixture_{index}', 'ems':{'ems_id':'fixture','ems_type':'floor_space'},
                'load':{'downward_load_kg':0,'minimum_remaining_capacity_kg':None},
                'physical_valid':True,'physical_rejection_reasons':[],
                'resulting_geometry':{'max_height_mm':50,'volume_utilization':0.001,'center_of_mass_offset_mm':0},
                'geometry_score_components':{k:0.5 for k in ('compactness','height','stability','balance')}})
        value={'version':'jev_candidate_bundle_b1_v1' if capacity==1 else 'jev_candidate_bundle_v4',
            'observation_digest':req['observation_digest'],'candidate_backend':'e2_original_v1','generator_config_digest':'d'*64,
            'physical_candidates':candidates,'physical_digest':digest(candidates),'generation_counts':[],
            'selectable_pool':'unfiltered','selectable_candidates':[],'selectable_digest':digest([]),'policy_digest':None,
            'experiment_protocol':'jev_packaging_runtime_v1','business_mode':'physical_only'}
        return req,CandidateBundle.from_dict(value)

    def context(self,config=None,n=2,eos=False):
        from semantic_pallet_planner.jev_select.packaging_runtime import no_policy
        from semantic_pallet_planner.jev_select.candidates import PublicBusinessGuard
        from semantic_pallet_planner.jev_select.context import ContextBuilder
        config=config or self.config();req,bundle=self.constructed(config['buffer_capacity'],n,eos)
        policy=no_policy(req);bundle=PublicBusinessGuard().filter(req,policy,bundle,config)
        return config,req,bundle,ContextBuilder(config).build(req,bundle,policy)

    def test_closed_schemas_exact_dispatch_extra_fields_and_forged_versions(self):
        from semantic_pallet_planner.jev_select.contracts import validate_schema,schema_validator
        from semantic_pallet_planner.jev_select.config import protocol_suffix
        from pct_baseline.contracts import validate
        for name in ('config_b1_v1','candidate_bundle_b1_v1','decision_context_b1_v1','task_b1_v1','execution_spec_b1_v1'):
            schema_validator(name)
        config,req,bundle,context=self.context()
        self.assertEqual(protocol_suffix(config),'b1_v1')
        for name,obj in [('config',config),('candidate_bundle',bundle.data),('decision_context',context.data)]:
            validate_schema(name,obj)
            bad=copy.deepcopy(obj);bad['unknown']=0
            with self.subTest(name=name),self.assertRaises(ValueError):validate_schema(name,bad)
            for version in ('unknown_b1_v1',obj['version']+'_v13',obj['version']+'_v1'):
                bad=copy.deepcopy(obj);bad['version']=version
                with self.assertRaises(ValueError):validate_schema(name,bad)
        with self.assertRaises(ValueError):validate_schema('config_b1_v1',context.data)
        from pct_baseline.dataset import authenticate,derive
        from pct_baseline.contracts import read
        _,rows=authenticate(ROOT);execution=read(ROOT/'PCT/configs/data_b1_v1.json')['execution_spec']
        validate('execution_spec_b1_v1',execution)
        for row,parent,identity in rows:
            task=derive(row,parent,identity,execution);validate('task_b1_v1',task)
            bad=copy.deepcopy(task);bad['extra']=True
            with self.assertRaises(ValueError):validate_schema('task_b1_v1',bad)
            # The stdlib projection must exactly equal the existing runtime aliases.
            from semantic_pallet_planner.jev_select.packaging_runtime import runtime_task
            legacy=runtime_task(parent)
            self.assertEqual(task['items'],legacy['items']);self.assertEqual(task['attributes'],legacy['attributes'])

    def test_public_capacity_local_null_request_and_exact_mapping_tampering(self):
        from semantic_pallet_planner.jev_select.context import validate_context,resolve_display_id
        from semantic_pallet_planner.jev_select.contracts import DecisionContext,digest
        config,req,bundle,context=self.context()
        self.assertIsNone(context.data['request_body'])
        public=json.dumps({'state':context.data['model_state'],'criteria':context.data['criteria']})
        for private in ['CURRENT_PRIVATE_ID','future','source_component','parent_data_identity','witness','monitor','task_id','total_count']:
            self.assertNotIn(private,public)
        self.assertEqual(context.data['model_state']['buffer']['capacity'],1)
        self.assertEqual(context.data['route'],'CHOICE_REQUIRED')
        label=next(iter(context.data['display_mapping']))
        exact=resolve_display_id(context,label,req,bundle,config)
        self.assertEqual(exact['candidate_id'],context.data['display_mapping'][label]['candidate_id'])
        self.assertEqual(digest(exact),context.data['display_mapping'][label]['candidate_digest'])
        for kind in ('id','digest','pose','label'):
            bad=context.data
            if kind=='id':bad['display_mapping'][label]['candidate_id']='FORGED'
            elif kind=='digest':bad['display_mapping'][label]['candidate_digest']='e'*64
            elif kind=='pose':bad['criteria'][label]['pose']['x_mm']+=1
            else:bad['display_mapping']['C99']=bad['display_mapping'].pop(label)
            # Even a resealed private mapping must fail deterministic reconstruction.
            bad['local_binding']['mapping_digest']=digest(bad['display_mapping'])
            bad['local_binding']['criteria_digest']=digest(bad['criteria'])
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_context(DecisionContext.from_dict(bad),req,bundle,config)

    def test_empty_pool_singleton_last_and_eos_no_dispatch(self):
        for count,route in [(0,'STOP_NO_PHYSICAL_CANDIDATE'),(1,'SINGLETON_BYPASS'),(2,'CHOICE_REQUIRED')]:
            config,req,bundle,context=self.context(n=count)
            self.assertEqual(context.data['route'],route)
            self.assertFalse(context.data['model_state']['buffer']['end_of_stream'])
        *_,context=self.context(n=0,eos=True)
        self.assertTrue(context.data['model_state']['buffer']['end_of_stream'])
        self.assertEqual(context.data['model_state']['available_objects'],[])

    def test_legacy_capacity3_context_identical_to_head_source(self):
        from semantic_pallet_planner.jev_select.packaging_runtime import no_policy,build_context
        from semantic_pallet_planner.jev_select.config import protocol_suffix
        config,req,bundle,context=self.context(self.config(new=False))
        self.assertEqual(protocol_suffix(config),'v4')
        original=subprocess.run(['git','show','HEAD:semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_runtime.py'],cwd=ROOT,text=True,capture_output=True,check=True).stdout
        baseline=types.ModuleType('baseline_packaging_runtime')
        baseline.__package__='semantic_pallet_planner.jev_select'
        exec(compile(original,'HEAD/packaging_runtime.py','exec'),baseline.__dict__)
        self.assertEqual(context.data,baseline.build_context(config,req,bundle,no_policy(req)).data)
        req1,bundle1=self.constructed(1)
        with self.assertRaises(ValueError):build_context(config,req1,bundle1,no_policy(req1))

    def test_public_contracts_load_without_extension_and_missing_extension_diagnostics(self):
        # Separate interpreters, frozen source paths, no writes/network.
        import os,sys
        env=dict(os.environ,PYTHONPATH=str(ROOT/'semantic_pallet_planner/src'),PYTHONDONTWRITEBYTECODE='1')
        code="from semantic_pallet_planner.jev_select.config import load_config; print(load_config()['version'])"
        old=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,text=True,capture_output=True)
        self.assertEqual(old.returncode,0,old.stderr)
        code="from semantic_pallet_planner.jev_select.packaging_versions import resolve_extension; resolve_extension('pct_b1_config_v1')"
        new=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,text=True,capture_output=True)
        self.assertNotEqual(new.returncode,0);self.assertIn('PCT_B1_EXTENSION_MISSING',new.stderr)
