"""N2 hand-state candidate/request construction only; no episode/LP/model calls."""
import ast
import copy
import json
from pathlib import Path
import unittest
import subprocess
import types
from unittest.mock import patch

import test_geometry_runtime_n1 as t
from semantic_pallet_planner.jev_select.candidate_backends import (
    load_geometry_config,capture_common_input,GeometryCandidateBundle,GeometryConstructionError)
from semantic_pallet_planner.jev_select.candidates import CandidateProvider, PublicBusinessGuard, validate_bundle
from semantic_pallet_planner.jev_select.config import generator_config, generator_config_for
from semantic_pallet_planner.jev_select.context import ContextBuilder,validate_context
from semantic_pallet_planner.jev_select.contracts import digest,canonical,validate_schema,schema_validator,JevSelectError,CandidateBundle
from semantic_pallet_planner.jev_select.episode import decision_inputs
from semantic_pallet_planner.jev_select.geometry_runtime_input import capture_current_public_snapshot_v1,runtime_config
from semantic_pallet_planner.jev_select.packaging_versions import GEOMETRY_BACKENDS,reject_geometry_execution

IDENTITIES={k:digest('N2_HAND_CONSTRUCTION_'+k) for k in t.c.IDENTITY_KEYS}


def config(backend):return load_geometry_config(backend=backend,**IDENTITIES)


def build(state,backend,common=None):
    cfg=config(backend);req=t.observation(state,t.INSTRUCTION,[])
    return cfg,req,CandidateProvider().build(state,req,generator_config_for(cfg),config=cfg,common_input=common)


class HeaderOnly(dict):
    def __getitem__(self,key):
        assert key in ('instruction_text','regions'), 'future/private task access: '+str(key)
        return super().__getitem__(key)


def inputs(state,cfg,job='job',did='D0000',timings=None):
    return decision_inputs(state,HeaderOnly(instruction_text=t.INSTRUCTION,regions=[]),cfg,
                           job,did,timings=timings)


class PublicN2(unittest.TestCase):
    def test_two_backends_share_exact_bytes_common_admission_not_backend_binding(self):
        s=t.current_scene();req=t.observation(s,t.INSTRUCTION,[])
        common=capture_common_input(s,req,config(GEOMETRY_BACKENDS[0]))
        bundles=[]
        for backend in GEOMETRY_BACKENDS:
            cfg,_,b=build(s,backend,common)
            validate_bundle(req,b)
            self.assertEqual(b.data['candidate_backend'],backend)
            self.assertEqual(b.data['generator_config_digest'],digest(generator_config_for(cfg)))
            self.assertEqual(b.data['physical_candidates'],b.data['selectable_candidates'])
            self.assertEqual(b.audit['native_bytes_hex'],common[0].hex())
            self.assertEqual(b.audit['geometry_bytes_hex'],common[1].hex())
            self.assertNotIn('backend',b.audit['common_binding'])
            bundles.append(b)
        self.assertEqual(bundles[0].audit['common_binding'],bundles[1].audit['common_binding'])
        self.assertEqual(bundles[0].audit['common_admission'],bundles[1].audit['common_admission'])
        self.assertNotEqual(bundles[0].data['backend_binding_digest'],bundles[1].data['backend_binding_digest'])

    def test_N1_binding_not_relabelled_and_N1_guard_remains(self):
        s=t.current_scene();req=t.observation(s,t.INSTRUCTION,[])
        n,g,n1=capture_current_public_snapshot_v1(s,req,profile=t.c.PROFILE,identities=IDENTITIES)
        with self.assertRaises(GeometryConstructionError) as error:
            build(s,GEOMETRY_BACKENDS[0],(n,g,n1))
        self.assertEqual(error.exception.scope,'COMMON_INPUT_ERROR')
        bad=runtime_config();bad['generator']['backend']='e2_original_v1'
        with self.assertRaises(ValueError):
            capture_current_public_snapshot_v1(s,req,profile=t.c.PROFILE,identities=IDENTITIES,config=bad)

    def test_both_backends_common_numeric_prefix_ledger_failure_precedes_generation(self):
        ledger=t.rounded_ledger_scene();ledger['placed_items'][0]['supported_load_kg']=7
        prefix=t.current_scene(t.scene([t.placed('a',0,0,0,4,4,2),t.placed('b',0,0,1.9999999999999998,4,4,2)]))
        numeric=t.current_scene();numeric['pending_items'][0]['item']['mass_kg']=2**53+1
        for s in (ledger,prefix,numeric):
            before=t.c.encode(s)
            for backend in GEOMETRY_BACKENDS:
                with patch('semantic_pallet_planner.o4.extensions.e2.candidates.generate',side_effect=AssertionError('generation entered')), \
                     patch('semantic_pallet_planner.planner.space_candidates.generator._generation_core',side_effect=AssertionError('generation entered')):
                    with self.assertRaises(GeometryConstructionError) as error:build(s,backend)
                    self.assertEqual(error.exception.scope,'COMMON_INPUT_ERROR')
                    self.assertFalse(error.exception.telemetry['generation_called'])
            self.assertEqual(t.c.encode(s),before)

    def test_real_internal_error_separate_from_normal_empty(self):
        for backend in GEOMETRY_BACKENDS:
            s=t.current_scene(t.scene(buffer=[t.item(h=2.0004)]))
            with self.assertRaises(GeometryConstructionError) as error:build(s,backend)
            self.assertEqual(error.exception.scope,'BACKEND_INTERNAL_ERROR')
            self.assertEqual(error.exception.code,'PHYSICAL_CHECK_DISAGREEMENT')
            self.assertEqual(error.exception.audit['common_admission']['status'],'PASS')
            self.assertTrue(error.exception.telemetry['generation_called'])
            self.assertGreaterEqual(error.exception.telemetry['generation_s'],0)
            cfg,req,b=build(t.current_scene(t.SCENES['nonstackable']),backend)
            self.assertEqual(b.data['physical_candidates'],[])
            self.assertEqual(ContextBuilder(cfg).build(req,b,PublicBusinessGuard().resolve(req)).data['route'],
                             'STOP_NO_PHYSICAL_CANDIDATE')

    def test_singleton_context_is_constructed_without_selection_or_request(self):
        s=t.current_scene(t.scene(length=2,width=4))
        for backend in GEOMETRY_BACKENDS:
            req,policy,b,ctx=inputs(s,config(backend))
            self.assertEqual(len(b.data['physical_candidates']),1)
            self.assertEqual(ctx.data['route'],'SINGLETON_BYPASS')
            self.assertIsNone(ctx.data['request_body'])

    def test_F0_common_fields_question_alias_seed_and_audit_isolation(self):
        import semantic_pallet_planner.jev_select.packaging_runtime as pr
        factory=pr.random.Random;seeds=[]
        def track(seed):seeds.append(seed);return factory(seed)
        s=t.current_scene();contexts=[]
        with patch.object(pr.random,'Random',side_effect=track):
            for backend in GEOMETRY_BACKENDS:
                cfg=config(backend);req,policy,b,ctx=inputs(s,cfg,job=backend)
                validate_context(ctx,req,b,cfg)
                body=ctx.data['request_body'];text=canonical(body)
                for forbidden in ('e2_original_v1','ems_surface_hybrid_v1','profile','host','compression',
                                   'geometry_audit','monitor','SURFACE_CORNER','EMS_STYLE_3D'):
                    self.assertNotIn(forbidden,text)
                self.assertEqual(body['state']['memories'],[])
                self.assertLessEqual(len(text.encode()),96000)
                contexts.append(ctx.data)
        self.assertTrue(seeds and len(set(seeds))==1)
        a,b=contexts
        self.assertEqual(a['model_state'],b['model_state'])
        self.assertEqual(a['request_body']['questions']['next_action']['instructions'],
                         b['request_body']['questions']['next_action']['instructions'])
        def actions(ctx):
            return {canonical([v['pick_object'],[t.c.numeric_text(v['pose'][k]) for k in
                    ('x_mm','y_mm','z_base_mm','yaw_deg')],list(map(t.c.numeric_text,v['oriented_size_mm']))]):v
                    for v in ctx['criteria'].values()}
        aa,bb=actions(a),actions(b)
        self.assertTrue(set(aa)&set(bb))
        for key in set(aa)&set(bb):self.assertEqual(aa[key],bb[key])
        cfg=config(GEOMETRY_BACKENDS[1])
        first=inputs(s,cfg,'jobA','DA')[3].data
        second=inputs(s,cfg,'jobB','DB')[3].data
        self.assertEqual(first['request_body'],second['request_body'])

    def test_roundtrip_full_artifacts_and_reject_drift(self):
        cfg,req,b=build(t.current_scene(),GEOMETRY_BACKENDS[1])
        restored=GeometryCandidateBundle.from_artifacts(json.loads(canonical(b.data)),json.loads(canonical(b.audit)),b.telemetry)
        self.assertEqual(canonical(validate_bundle(req,restored)),canonical(b.data))
        for key in ('candidate_backend','generator_config_digest','common_input_digest','backend_binding_digest'):
            bad=b.data;bad[key]='drift'
            with self.assertRaises(ValueError):validate_bundle(req,b.with_data(bad))
        bad=b.data;bad['selectable_candidates']=bad['selectable_candidates'][:-1]
        bad['selectable_digest']=digest(bad['selectable_candidates'])
        with self.assertRaises(ValueError):validate_bundle(req,b.with_data(bad))
        with self.assertRaises(ValueError):validate_bundle(req,CandidateBundle.from_dict(b.data))

    def test_old_default_provider_complete_bytes_against_reviewed_implementation(self):
        raw=subprocess.check_output(['git','show','d69d904f09686c323edcf949f7e01022a7d564cb:semantic_pallet_planner/src/semantic_pallet_planner/jev_select/candidates.py'])
        module=types.ModuleType('semantic_pallet_planner.jev_select._n2_reviewed_provider')
        module.__package__='semantic_pallet_planner.jev_select'
        exec(compile(raw,'reviewed_candidates.py','exec'),module.__dict__)
        for source in (t.SCENES['empty'],t.SCENES['platform']):
            s=t.current_scene(source);req=t.observation(s,t.INSTRUCTION,[])
            old=module.CandidateProvider().build(s,req,generator_config())
            current=CandidateProvider().build(s,req,generator_config())
            self.assertEqual(canonical(old.data),canonical(current.data))
        from semantic_pallet_planner.jev_select.packaging_runtime import load_runtime_config
        old_config=load_runtime_config(data_identity=IDENTITIES['data_identity'],task_digest=IDENTITIES['task_identity'])
        s=t.current_scene();req=t.observation(s,t.INSTRUCTION,[])
        old=module.CandidateProvider().build(s,req,generator_config(),config=old_config)
        current=CandidateProvider().build(s,req,generator_config(),config=old_config)
        self.assertEqual(canonical(old.data),canonical(current.data))

    def test_request_cap_with_explicit_facts_test_double_and_memory_rejection(self):
        import semantic_pallet_planner.jev_select.packaging_runtime as pr
        cfg,req,b=build(t.current_scene(),GEOMETRY_BACKENDS[1])
        policy=PublicBusinessGuard().resolve(req)
        value,state,criteria,mapping,buffer=pr.public_facts(cfg,req,b,policy)
        # Schema-valid oversized F0 facts fixture only, not a physical state or
        # a claim that a real buffer has 1000 items. No physical checker stub.
        state=copy.deepcopy(state);state['available_objects']*=1000
        with patch.object(pr,'public_facts',return_value=(value,state,criteria,mapping,buffer)):
            with self.assertRaises(ValueError) as err:ContextBuilder(cfg).build(req,b,policy)
        self.assertEqual(err.exception.code,'packaging_runtime_request_too_large')
        from semantic_pallet_planner.jev_select.contracts import MemorySnapshot
        with self.assertRaises(JevSelectError):
            decision_inputs(t.current_scene(),HeaderOnly(instruction_text=t.INSTRUCTION,regions=[]),cfg,
                            'job','D0000',memory_snapshot=MemorySnapshot.empty())

    def test_actual_backend_stats_no_E2_cache_access_for_new_backend(self):
        class CacheForbidden:
            def cache_info(self):raise AssertionError('new backend accessed E2 cache')
        timings={}
        with patch('semantic_pallet_planner.o4.extensions.e2.candidates._cached_generation',CacheForbidden()):
            inputs(t.current_scene(),config(GEOMETRY_BACKENDS[1]),timings=timings)
        self.assertFalse(timings['generation_cache_supported'])
        self.assertIsNone(timings['generation_cache_hits']);self.assertIsNone(timings['generation_cache_misses'])
        timings={};inputs(t.current_scene(),config(GEOMETRY_BACKENDS[0]),timings=timings)
        self.assertTrue(timings['generation_cache_supported'])
        self.assertEqual(timings['generation_cache_hits']+timings['generation_cache_misses'],1)

    def test_config_unknown_backend_old_closed_schemas_and_unimplemented_execution(self):
        with self.assertRaises(ValueError):config('unknown')
        cfg=config(GEOMETRY_BACKENDS[0]);bad=copy.deepcopy(cfg);bad['feature_profile']='F1_space_facts'
        with self.assertRaises(ValueError):generator_config_for(bad)
        old=json.loads(Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select/configs/packaging_runtime_v4.json').read_bytes())
        old['candidate_backend']='ems_surface_hybrid_v1'
        with self.assertRaises(ValueError):validate_schema('config',old)
        with self.assertRaises(JevSelectError):schema_validator('checkpoint_v14')
        with self.assertRaises(JevSelectError):schema_validator('selection_result_v14')
        with self.assertRaises(JevSelectError):reject_geometry_execution(cfg,'run_episode')
        # Do not call prohibited run_episode/commit. Inspect their fail-closed entry guards.
        pkg=Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select')
        for filename,names in [('episode.py',{'run_episode','_run_episode_v2'}),('execution.py',{'commit_physical'})]:
            for node in ast.parse((pkg/filename).read_text()).body:
                if isinstance(node,ast.FunctionDef) and node.name in names:
                    self.assertEqual(node.body[1].value.func.id,'reject_geometry_execution')


if __name__=='__main__':unittest.main()
