"""GP3_N2_R1_ONLY: real hand-state consumer behavior, no execution or LP."""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import test_geometry_public_n2 as n2
from semantic_pallet_planner.jev_select.candidate_backends import load_geometry_config,preflight_config
from semantic_pallet_planner.jev_select.candidates import PublicBusinessGuard
from semantic_pallet_planner.jev_select.context import ContextBuilder,validate_context
from semantic_pallet_planner.jev_select.contracts import DecisionContext,canonical,digest,JevSelectError
from semantic_pallet_planner.jev_select.packaging_runtime import build_context,public_facts,validate_runtime_context,no_policy


class BindingR1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pairs={};cls.records=[]
        for backend in n2.GEOMETRY_BACKENDS:
            cfg,obs,b=n2.build(n2.t.current_scene(),backend)
            policy=no_policy(obs)
            ctx=ContextBuilder(cfg).build(obs,b,policy)
            cls.pairs[backend]=(cfg,obs,b,policy,ctx)
            if os.environ.get('N2_R1_EVIDENCE'):
                p=Path(os.environ['N2_R1_EVIDENCE'])/'current_pairs'/backend;p.mkdir(parents=True,exist_ok=True)
                for name,value in [('config',cfg),('observation',obs),('bundle',b.data),('audit',b.audit),('telemetry',b.telemetry),('context',ctx.data),('policy',policy.data)]:
                    (p/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

    @classmethod
    def tearDownClass(cls):
        if os.environ.get('N2_R1_EVIDENCE'):
            (Path(os.environ['N2_R1_EVIDENCE'])/'consumer_matrix.json').write_text(json.dumps(cls.records,ensure_ascii=False,indent=2)+'\n')

    def consumers(self,cfg,obs,b,policy,ctx):
        # Match the old independent config/context edge, exposing the missing
        # cross edge instead of relying on a stale-context rejection.
        mixed=copy.deepcopy(ctx.data)
        mixed['local_binding']['config_digest']=digest(cfg)
        mixed['local_binding']['runtime_identity']=copy.deepcopy(cfg.get('runtime_identity'))
        mixed=DecisionContext.from_dict(mixed)
        return {
            'filter':lambda:PublicBusinessGuard().filter(obs,policy,b,cfg),
            'ContextBuilder':lambda:ContextBuilder(cfg).build(obs,b,policy),
            'direct_F0':lambda:build_context(cfg,obs,b,policy),
            'public_facts':lambda:public_facts(cfg,obs,b,policy),
            'full_context':lambda:validate_context(mixed,obs,b,cfg),
            'direct_context':lambda:validate_runtime_context(mixed,obs,b,cfg),
            'context_config_bundle_only':lambda:validate_context(mixed,bundle=b,config=cfg),
        }

    def reject(self,label,cfg,pair,code=None):
        _,obs,b,policy,ctx=pair
        before=canonical({'config':cfg,'bundle':b.data,'audit':b.audit,'context':ctx.data})
        for name,call in self.consumers(cfg,obs,b,policy,ctx).items():
            with self.subTest(case=label,entry=name):
                # Instrumentation only: any regeneration would fail this test.
                with patch.object(n2.CandidateProvider,'build',side_effect=AssertionError('regeneration forbidden')):
                    with self.assertRaises((JevSelectError,ValueError)) as err:call()
                if code:self.assertEqual(err.exception.code,code)
                self.records.append({'case':label,'backend':b.data['candidate_backend'],'entry':name,'result':'REJECTED','error':str(err.exception),'config_digest':digest(cfg),'frozen_config_digest':digest(b.audit['config'])})
        self.assertEqual(before,canonical({'config':cfg,'bundle':b.data,'audit':b.audit,'context':ctx.data}))

    def test_valid_pairs(self):
        for backend,pair in self.pairs.items():
            cfg,obs,b,policy,ctx=pair
            preflight_config(cfg)
            PublicBusinessGuard().filter(obs,policy,b,cfg)
            self.assertEqual(ContextBuilder(cfg).build(obs,b,policy).data,ctx.data)
            self.assertEqual(build_context(cfg,obs,b,policy).data,ctx.data)
            validate_context(ctx,obs,b,cfg)
            validate_runtime_context(ctx,obs,b,cfg)
            self.records.append({'case':'valid_pair','backend':backend,'result':'PASS','config_digest':digest(cfg)})

    def test_both_directions_cross_backend(self):
        keys=list(self.pairs)
        for a,b in (keys,keys[::-1]):
            cfg=self.pairs[a][0];preflight_config(cfg)
            self.reject('cross_backend_'+a,cfg,self.pairs[b],'geometry_config_bundle_mismatch')

    def test_same_backend_legal_identity_variants(self):
        for backend,pair in self.pairs.items():
            for field in ('selector','data_identity','task_identity','monitor_identity'):
                ids=copy.deepcopy(n2.IDENTITIES);method=pair[0]['selector']
                if field=='selector':method='local_first_test_double'
                else:ids[field]=digest('R1_other_'+field)
                cfg=load_geometry_config(backend=backend,method=method,**ids)
                preflight_config(cfg)  # Actual valid standalone config, not a drift double.
                self.reject(field,cfg,pair,'geometry_config_bundle_mismatch')

    def test_invalid_and_drifted_configs(self):
        for pair in self.pairs.values():
            for field,value in [('numerical_profile','unknown'),('construction_only',False),('generator_config_digest','0'*64),('max_request_bytes',95999),('unexpected',True)]:
                cfg=copy.deepcopy(pair[0]);cfg[field]=value
                self.reject('invalid_'+field,cfg,pair)
            cfg=copy.deepcopy(pair[0]);cfg['runtime_identity']['source_identity']='0'*64
            self.reject('source_drift',cfg,pair,'geometry_config_bundle_mismatch')

    def test_matching_but_obsolete_source_rejected(self):
        from semantic_pallet_planner.jev_select.candidate_backends import GeometryCandidateBundle
        from semantic_pallet_planner.jev_select.contracts import validate_schema
        p=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N2_20261117_01/cases/empty')
        for backend in self.pairs:
            def read(name):return json.loads((p/backend/(name+'.json')).read_bytes())
            old=GeometryCandidateBundle.from_artifacts(read('bundle'),read('audit'),read('telemetry'))
            cfg=read('config');validate_schema('config',cfg)
            # Pair matches internally, but frozen source is historical: no resigning.
            self.reject('matching_historical_source',cfg,(cfg,read('observation'),old,no_policy(read('observation')),DecisionContext.from_dict(read('context'))))

if __name__=='__main__':unittest.main(verbosity=2)
