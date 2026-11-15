"""No orders/LP/real forward/optimizer.step. Synthetic control + object roundtrip."""
import copy
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import torch
from pct_baseline.contracts import read,digest
from pct_baseline.p4b_storage import Store,checked,FALLBACK
from pct_baseline.p4b_runtime import StageJournal
from pct_baseline.p4b_formal import Session,Selector,admission,public_compatibility
from pct_baseline import p4b_state as state
from pct_baseline.p4b_training import BatchController,check_update_intents,formal_descriptor


def network_guard(event,args):
    if event in ('socket.connect','socket.getaddrinfo'):raise AssertionError('NETWORK_FORBIDDEN')
sys.addaudithook(network_guard)

IDENTITY={'source':'fixture','data':'fixture','policy':'fixture','environment':'fixture'}


def checkpoint(phase):
    pending={'decision_id':'d1','before':{'placed':0},'bundle':{'physical_candidates':[{'id':'c1'}]},
             'context':{'public':True},'observation':{},'selection':None,'monitor':None,'proposed_action':None}
    if phase in ('SELECTED','MONITORED','COMMITTED'):
        pending.update(selection={'status':'selected','id':'c1'},proposed_action={'id':'c1'})
    if phase in ('MONITORED','COMMITTED'):pending['monitor']={'status':'STABLE'}
    return {'phase':phase,'state':{'placed':int(phase=='COMMITTED')},'events':[],
            'pending_event':None if phase=='READY' else pending}


class RemediationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'store'
        self.forward=patch.object(torch.nn.Module,'_call_impl',side_effect=AssertionError('REAL_FORWARD_FORBIDDEN'))
        self.step=patch.object(torch.optim.Adam,'step',side_effect=AssertionError('OPTIMIZER_STEP_FORBIDDEN'))
        self.forward.start();self.step.start()
    def tearDown(self):self.step.stop();self.forward.stop();self.temp.cleanup()
    def test_closed_configuration_and_route(self):
        from semantic_pallet_planner.jev_select.packaging_versions import resolve_extension
        from semantic_pallet_planner.jev_select.contracts import validate_schema
        p=Path('PCT/outputs/PCT_P3_20261115_01/attempt_02/jobs/diagnostic_pct_geo_b1_0/header.json')
        c=read(p)['config'];c.pop('p3_plan_digest');c.pop('p3_mode')
        c.update(version='pct_p4b_config_v2',formal_descriptor='a'*64,policy_snapshot='b'*64,
                 admission_digest='c'*64,formal_mode='training',model_identity='b'*64,attempt_slot_digest='d'*64)
        validate_schema('config',c)
        self.assertEqual(resolve_extension(c['version']).__name__,'pct_baseline.p4b_protocol')
        self.assertEqual(resolve_extension('pct_p3_config_v1').__name__,'pct_baseline.p3_protocol')
        self.assertEqual(resolve_extension('pct_b1_config_v1').__name__,'pct_baseline.protocol')
        for key,value in [('extra',True),('buffer_capacity',3),('version','pct_p3_config_v1')]:
            bad=copy.deepcopy(c);bad[key]=value
            with self.assertRaises(ValueError):validate_schema('config',bad)
        public_compatibility(c)
    def test_actual_extension_admission_without_episode(self):
        from pct_baseline.p4b_formal import build_config,preflight,current_identity,JobSink,admit_execution
        torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
        root=Path('PCT/outputs/PCT_P4_A_20261115_01/build_01');plan=read(root/'training_plan.json')
        identity=current_identity();formal=formal_descriptor(plan,read(root/'data_catalog.json'),identity)
        spec=formal['models'][0];slot=formal['schedules'][0]['attempts'][0]
        task=read(root/'data/tasks'/(slot['task_id']+'.json'))
        receipt={'accepted_identity':{'status':'ACCEPTED','identity':identity},
                 'resources':{'status':'ACCEPTED','identity':identity,'required_free_bytes':FALLBACK},
                 'authorization':{'status':'AUTHORIZED','identity':identity,'scope':'FORMAL_TRAINING','authorization_id':'FIXTURE_ONLY_NOT_LAUNCH_AUTHORIZATION'}}
        from pct_baseline.geo_model import new_core
        core=new_core();policy=state.tensor_digest(core)
        cfg=build_config(task,spec['method'],formal,policy,receipt,slot=slot,model_spec=spec)
        preflight(cfg);public_compatibility(cfg)
        header={'identity':identity,'task':task,'config':cfg,'job_id':'fixture-admit'}
        with Store(self.root,{'header':digest(header)},free=lambda:FALLBACK*2) as store:
            sink=JobSink(store,header,receipt,formal=formal,slot=slot,model_spec=spec)
            selector=Selector(cfg,core,sink.session)
            args=dict(execution={'version':'pct_p4b_execution_v2','header_digest':digest(header)},job_id=header['job_id'],
                      method=cfg['selector'],resume=None,on_checkpoint=sink,expected_events=None,training_fork=None,
                      memory_snapshot=None,memory_view=None,memory_driver=None)
            admit_execution(task,selector,cfg,**args)
            with self.assertRaisesRegex(ValueError,'BINDING'):
                admit_execution(task,selector,dict(cfg,attempt_slot_digest='0'*64),**args)
            sink.session.finish('ADMISSION_ONLY_NO_EPISODE')
    def test_missing_admission_and_binding(self):
        receipt={'accepted_identity':{'status':'ACCEPTED','identity':IDENTITY},
                 'resources':{'status':'ACCEPTED','identity':IDENTITY,'required_free_bytes':FALLBACK},
                 'authorization':{'status':'AUTHORIZED','identity':IDENTITY,'scope':'FORMAL_TRAINING','authorization_id':'FIXTURE_ONLY'}}
        self.assertEqual(admission(receipt,IDENTITY,FALLBACK),digest(receipt))
        for field in receipt:
            bad=copy.deepcopy(receipt);bad[field]=None
            with self.assertRaises(ValueError):admission(bad,IDENTITY,FALLBACK)
        with self.assertRaisesRegex(ValueError,'RESOURCE_GATE'):admission(receipt,IDENTITY,FALLBACK-1)
        with self.assertRaisesRegex(ValueError,'IDENTITY'):admission(receipt,dict(IDENTITY,source='changed'),FALLBACK)
    def test_five_phase_constructed_consumption(self):
        phases=['READY','DECISION_READY','SELECTED','MONITORED','COMMITTED']
        for start in phases:
            root=self.root/start
            with Store(root,IDENTITY) as store:
                journal=StageJournal(store);session=Session(store,journal)
                for phase in phases[:phases.index(start)+1]:
                    if phase=='COMMITTED':session.before_commit(checkpoint(phase)['pending_event'])
                    session.observe(checkpoint(phase))
                session.finish('CONSTRUCTED_CUT')
            with Store(root,IDENTITY) as store:
                journal=StageJournal(store);session=Session(store,journal);session.recover_commits()
                calls={'select':0,'monitor':0,'commit':0}
                # Pure control harness drives the same Session observer; it does
                # not call run_episode, generate a candidate or solve anything.
                for phase in phases[phases.index(start)+1:]:
                    if phase=='SELECTED':calls['select']+=1
                    if phase=='MONITORED':calls['monitor']+=1
                    if phase=='COMMITTED':calls['commit']+=1;session.before_commit(checkpoint(phase)['pending_event'])
                    session.observe(checkpoint(phase))
                if start=='COMMITTED':
                    final=checkpoint('READY');event=checkpoint('COMMITTED')['pending_event'];final['events']=[event];session.observe(final)
                session.finish('FINISHED_FIXTURE')
                self.assertEqual(calls['select'],int(start in ('READY','DECISION_READY')))
                self.assertEqual(calls['monitor'],int(start in ('READY','DECISION_READY','SELECTED')))
                self.assertEqual(calls['commit'],int(start!='COMMITTED'))
                self.assertEqual(session.counts['saved_monitor_reuses'],int(start=='MONITORED'))
                ends=[r['record'] for r in store.records() if r['key'].startswith('session-end-')]
                self.assertEqual(len(ends),2)
    def test_actual_call_vs_persist_and_unknown(self):
        with Store(self.root,IDENTITY) as store:
            session=Session(store,StageJournal(store));self.assertEqual(session.call('synthetic_forward',lambda:7),7)
            session.save('selection-fixture',{'selection':'persisted'})
            session.finish('FIXTURE');self.assertEqual(session.counts['synthetic_forward_calls'],1)
            self.assertEqual(session.counts['synthetic_forward_returns'],1)
            session.save('op-start-00000001',{'kind':'synthetic','state':'INTENT'})
        with Store(self.root,IDENTITY) as store:
            with self.assertRaisesRegex(ValueError,'OUTCOME_UNKNOWN'):Session(store,StageJournal(store))
    def test_commit_unknown_and_published_reconcile(self):
        with Store(self.root,IDENTITY) as store:
            journal=StageJournal(store);session=Session(store,journal)
            for phase in ['READY','DECISION_READY','SELECTED','MONITORED']:session.observe(checkpoint(phase))
            session.before_commit(checkpoint('COMMITTED')['pending_event'])
        with Store(self.root,IDENTITY) as store:
            session=Session(store,StageJournal(store))
            with self.assertRaisesRegex(ValueError,'COMMIT_OUTCOME_UNKNOWN'):session.recover_commits()
    def test_real_objects_rng_and_populated_adam_roundtrip(self):
        # Objects and populated Adam state are constructed without forward/step.
        from pct_baseline.geo_model import new_core as geo
        from pct_baseline.load_model import new_core as load_core
        for name,factory in [('geo',geo),('load',load_core)]:
            core=factory();optimizer=torch.optim.Adam(core.parameters(),lr=1e-4)
            for p in core.parameters():optimizer.state[p]={'step':torch.tensor(3.),'exp_avg':torch.ones_like(p)*.2,'exp_avg_sq':torch.ones_like(p)*.3}
            expected=copy.deepcopy(optimizer.state_dict());weights=copy.deepcopy(core.state_dict())
            random.seed(11);np.random.seed(11);torch.manual_seed(11)
            rng=copy.deepcopy(state.rng_state())
            with Store(self.root/name,IDENTITY) as store:
                row=state.save_initial(store,core,optimizer,state.tensor_digest(core))
                fresh=factory();opt=torch.optim.Adam(fresh.parameters(),lr=1e-4)
                state.load(store,fresh,opt,update_id=0,expected_seal=row['seal'])
                self.assertTrue(all(torch.equal(v,fresh.state_dict()[k]) for k,v in weights.items()))
                actual=opt.state_dict()
                for k,v in expected['state'].items():
                    for field,t in v.items():self.assertTrue(torch.equal(t,actual['state'][k][field]))
                self.assertEqual(expected['param_groups'],actual['param_groups'])
                restored=state.rng_state();self.assertEqual(rng['python'],restored['python'])
                self.assertTrue(np.array_equal(rng['numpy'][1],restored['numpy'][1]))
                self.assertEqual((rng['numpy'][0],*rng['numpy'][2:]),(restored['numpy'][0],*restored['numpy'][2:]))
                self.assertTrue(torch.equal(rng['torch_cpu'],restored['torch_cpu']))
                ref=store.append({'fixture':'batch'},key='batch')
                cursor={'epoch':1,'attempt':8,'segment':0}
                row=state.save_update(store,core,optimizer,update_id=1,policy=state.tensor_digest(core),cursor=cursor,batch_refs=[{'key':'batch','seal':ref['seal']}])
                out=state.load(store,fresh,opt,update_id=1,expected_seal=row['seal']);self.assertEqual(out['cursor'],cursor)
                with self.assertRaises(ValueError):state.load(store,fresh,opt,update_id=1,expected_seal='bad')
    def test_real_selector_record_path_with_synthetic_forward(self):
        from types import SimpleNamespace
        from semantic_pallet_planner.jev_select.contracts import DecisionContext
        from pct_baseline import geo_encoding
        root=Path('PCT/outputs/PCT_P3_20261115_01/attempt_02/jobs/diagnostic_pct_geo_b1_0')
        ev=next(e for e in read(root/'episode.json')['events'] if e.get('selection'))
        ctx=DecisionContext.from_dict(ev['context']);encoding=geo_encoding.encode_geometry(ctx)
        n=encoding.data['candidate_count'];calls=[]
        def fake_actor(*args,**kwargs):
            calls.append('actor_stub')
            probs=torch.zeros((1,16));probs[0,:n]=1/n
            return None,torch.tensor([0]),torch.tensor(0.),None,SimpleNamespace(probs=probs)
        core=SimpleNamespace(state_dict=lambda:{'synthetic':torch.tensor([1.])},actor=fake_actor,critic=lambda _:torch.tensor(1.))
        config={'selector':'pct_geo_b1','policy_snapshot':state.tensor_digest(core)}
        with Store(self.root,IDENTITY) as store:
            session=Session(store,StageJournal(store));selector=Selector(config,core,session)
            selector.bound=(ctx,encoding,geo_encoding.verify_candidates(encoding,ev['bundle']['selectable_candidates']))
            first=selector.select(ctx,decision_id='fixture-d1');second=selector.select(ctx,decision_id='fixture-d1')
            self.assertEqual(first.data,second.data);self.assertEqual(calls,['actor_stub'])
            self.assertEqual(session.counts['policy_choice_calls'],1)
            self.assertEqual(session.counts['selection_results_persisted'],1)
            self.assertEqual(session.counts['selection_record_reuses'],1)
            singleton_data=ctx.data;singleton_data['route']='SINGLETON_BYPASS'
            singleton_context=DecisionContext.from_dict(singleton_data);n=1
            row=encoding.resolve(0)
            singleton_encoding=SimpleNamespace(data={'candidate_count':1,'mapping':[row],'feature_digest':'f'*64},
                    tensor=lambda:None,resolve=lambda i:row)
            selector.bound=(singleton_context,singleton_encoding,{row['candidate_id']:ev['bundle']['selectable_candidates'][0]})
            selector.select(singleton_context,decision_id='fixture-singleton')
            self.assertEqual(session.counts['singleton_critic_calls'],1)
            self.assertEqual(session.counts['policy_choice_calls'],1)
            session.finish('SYNTHETIC_SELECTOR_PATH')
    def test_batch_policy_drift_and_empty_stop(self):
        schedule=[{'attempt_index':i,'batch_id':i//8,'task_id':str(i)} for i in range(2000)]
        for kind in ('drift','empty'):
            with Store(self.root/kind,IDENTITY) as store:
                controller=BatchController(store,schedule,'frozen');policy=['frozen']
                def collect(s,p):
                    if kind=='drift':policy[0]='changed'
                    return {'status':'NATURAL_EMPTY_POOL','transitions':[]}
                with self.assertRaises(ValueError):controller.batch(0,collect,lambda *_:self.fail('update forbidden'),lambda:policy[0])
                self.assertTrue(controller.stopped)
                self.assertEqual(len(controller.update_denominator()),250)
                if kind=='empty':self.assertEqual(controller.update_denominator()[0]['status'],'NO_UPDATE')
    def test_p3_hard_guards_unchanged(self):
        from pct_baseline.p3_training import save_snapshot
        from pct_baseline.p3_runtime import TASKS
        self.assertEqual(len(TASKS),2)
        core=torch.nn.Linear(1,1);optimizer=torch.optim.Adam(core.parameters(),lr=1e-4)
        for update,cursor in [(3,0),(0,17)]:
            with self.assertRaisesRegex(ValueError,'P3_POSITION_BUDGET'):
                save_snapshot(self.root/f'{update}-{cursor}',core,optimizer,identity={'fixture':True},
                    position={'update_id':update,'attempt_cursor':cursor,'batch_shards':[],'policy_snapshot_id':'fixture'})
    def test_commit_published_before_receipt_reconciles(self):
        with Store(self.root,IDENTITY) as store:
            journal=StageJournal(store);session=Session(store,journal)
            for phase in ['READY','DECISION_READY','SELECTED','MONITORED']:session.observe(checkpoint(phase))
            session.before_commit(checkpoint('COMMITTED')['pending_event'])
            journal(checkpoint('COMMITTED')) # crash between durable CP and observer receipt
        with Store(self.root,IDENTITY) as store:
            session=Session(store,StageJournal(store));session.recover_commits()
            self.assertIn('commit-done-d1',session.values)
            session.finish('RECONCILED_FIXTURE_NO_COMMIT_CALL')
    def test_optimizer_intent_stops_before_reapply(self):
        with Store(self.root,IDENTITY) as store:
            store.append({'update_id':1,'batch_refs':[]},key='optimizer-intent-0001')
            with self.assertRaisesRegex(ValueError,'OPTIMIZER_OUTCOME_UNKNOWN'):check_update_intents(store)
    def test_batch_fixed_policy_failure_and_denominator(self):
        schedule=[{'attempt_index':i,'batch_id':i//8,'task_id':str(i)} for i in range(2000)]
        with Store(self.root,IDENTITY) as store:
            controller=BatchController(store,schedule,'frozen');calls=[]
            def collect(slot,policy):
                calls.append((slot['attempt_index'],policy))
                if slot['attempt_index']==2:raise RuntimeError('fixture failure')
                return {'status':'COMPLETED','transitions':[{'fixture':True}]}
            def update(*_):raise AssertionError('update must not run')
            with self.assertRaisesRegex(RuntimeError,'fixture failure'):controller.batch(0,collect,update,lambda:'frozen')
            self.assertEqual(calls,[(0,'frozen'),(1,'frozen'),(2,'frozen')])
            denominator=controller.denominator();self.assertEqual(len(denominator),2000)
            self.assertEqual(sum(v['status']=='NOT_RUN' for v in denominator),1997)
        with Store(self.root,IDENTITY) as store:self.assertTrue(BatchController(store,schedule,'frozen').stopped)
    def test_successful_constructed_batch_and_frozen_descriptor(self):
        root=Path('PCT/outputs/PCT_P4_A_20261115_01/build_01')
        plan=read(root/'training_plan.json');formal=formal_descriptor(plan,read(root/'data_catalog.json'),IDENTITY)
        self.assertEqual(formal['schedules'],plan['schedules']);self.assertEqual(formal['rules'],plan['rules'])
        schedule=formal['schedules'][0]['attempts']
        with Store(self.root,IDENTITY) as store:
            controller=BatchController(store,schedule,'frozen');called=[]
            def update(b,ts,refs):called.append((b,len(ts),len(refs)));return 'SYNTHETIC_UPDATE_CALLBACK_ONLY'
            out=controller.batch(0,lambda s,p:{'status':'NATURAL_EMPTY_POOL','transitions':[{'fixture':True}]},update,lambda:'frozen')
            self.assertEqual(out,'SYNTHETIC_UPDATE_CALLBACK_ONLY');self.assertEqual(called,[(0,8,8)])
            self.assertEqual(sum(v['status']=='NOT_RUN' for v in controller.denominator()),1992)
