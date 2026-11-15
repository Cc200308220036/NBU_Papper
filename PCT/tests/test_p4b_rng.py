"""Production resume helpers + synthetic draws/process death; no business run."""
import copy
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import torch
from pct_baseline.contracts import read,digest
from pct_baseline.p4b_storage import Store
from pct_baseline.p4b_runtime import StageJournal
from pct_baseline.p4b_formal import Session,Selector
from pct_baseline.p4b_training import BatchController
from pct_baseline import p4b_rng as rng
from test_p4b_remediation import checkpoint
from p4b_rng_worker import seed,draw,schedule


def network_guard(event,args):
    if event in ('socket.connect','socket.getaddrinfo'):raise AssertionError('NETWORK_FORBIDDEN')
sys.addaudithook(network_guard)
ID={'source':'rng-test-v3','policy':'fixed'}
WORKER=Path('PCT/tests/p4b_rng_worker.py')


class RngResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.guards=[patch.object(torch.nn.Module,'_call_impl',side_effect=AssertionError('REAL_FORWARD_FORBIDDEN')),
                     patch.object(torch.optim.Adam,'step',side_effect=AssertionError('OPTIMIZER_FORBIDDEN'))]
        for guard in self.guards:guard.start()
    def tearDown(self):
        for guard in reversed(self.guards):guard.stop()
        self.temp.cleanup()
    def worker(self,path,cut=-1,uniform=False):
        result=subprocess.run([sys.executable,str(WORKER),str(path),'--cut',str(cut)]+(['--uniform'] if uniform else []),capture_output=True,text=True)
        self.assertEqual(result.returncode,0 if cut<0 else 77,result.stderr)
        if cut<0:return read(path/'worker-result.json')
    def test_prefix_two_and_variable_lengths_process_restart(self):
        baseline=self.worker(self.root/'baseline')
        evidence=[]
        for length in (0,1,2,3,5,7,8):
            root=self.root/f'prefix-{length}';self.worker(root,length);resumed=self.worker(root)
            for key in ('result','rng_after_batch','next_draw','denominator','attempts'):
                self.assertEqual(resumed[key],baseline[key],(length,key))
            self.assertEqual(resumed['callbacks'],list(range(length,8)))
            self.assertEqual(resumed['rng_counts'],{'actual_attempts':8-length,'saved_attempt_reuses':length,'rng_post_consumptions':length})
            evidence.append({'saved_prefix':length,'new_synthetic_callbacks':8-length,'next_draw':resumed['next_draw'],
                             'all_three_rng_and_results_equal':True,'cursor':8,'actual_reused_counts':resumed['rng_counts']})
        # Result next to the tests is never written. An explicit output directory
        # can archive evidence, while ordinary unittest stays in temp directories.
        target=os.environ.get('PCT_RNG_EVIDENCE_DIR')
        if target:
            Path(target,'batch_prefix_comparison.json').write_text(json.dumps({'scope':'synthetic collector/process termination, not production order crash',
                'baseline_next_draw':baseline['next_draw'],'cases':evidence,'business_counts':0},ensure_ascii=False,indent=2)+'\n')
    def test_original_two_attempt_counterexample_same_python_draw(self):
        continuous=self.worker(self.root/'uniform-baseline',uniform=True)
        self.worker(self.root/'uniform-resumed',2,uniform=True)
        resumed=self.worker(self.root/'uniform-resumed',uniform=True)
        archived=read('PCT/outputs/PCT_P4_B_0_FIX_QA_20261115_01/batch_rng_probe.json')
        third=resumed['result']['trajectories'][2][0]['draws'][0][0]
        self.assertEqual(third,archived['next_uninterrupted_draw'])
        self.assertNotEqual(third,archived['next_resumed_draw'])
        self.assertEqual(resumed['result'],continuous['result'])
        self.assertEqual(resumed['rng_after_batch'],continuous['rng_after_batch'])
        target=os.environ.get('PCT_RNG_EVIDENCE_DIR')
        if target:Path(target,'original_counterexample_recheck.json').write_text(json.dumps({
            'scope':'synthetic production-controller resume, no production order crash',
            'saved_attempts':2,'new_callbacks':len(resumed['callbacks']),
            'archived_wrong_python_third_draw':archived['next_resumed_draw'],
            'expected_python_third_draw':archived['next_uninterrupted_draw'],
            'fixed_python_third_draw':third,'python_numpy_torch_post_equal':True},indent=2)+'\n')
    def phase_run(self,path,cut=None):
        phases=['READY','DECISION_READY','SELECTED','MONITORED','COMMITTED']
        seed();start=rng.capture();results=[]
        with Store(path,ID) as store:
            session=Session(store,StageJournal(store))
            for phase in phases:
                if phase=='SELECTED':
                    value=session.call('synthetic_selection',draw,owner={'decision':'d1'});results.append(value)
                else:results.append(draw())
                if phase=='COMMITTED':session.before_commit(checkpoint(phase)['pending_event'])
                session.observe(checkpoint(phase))
                if phase==cut:break
            session.finish('FIXTURE_CUT' if cut else 'FIXTURE_FINISHED')
            final_state=copy.deepcopy(session.journal.checkpoint['state'])
        if cut:
            rng.restore(start)
            with Store(path,ID) as store:
                session=Session(store,StageJournal(store));session.recover_commits()
                for phase in phases[phases.index(cut)+1:]:
                    if phase=='SELECTED':results.append(session.call('synthetic_selection',draw,owner={'decision':'d1'}))
                    else:results.append(draw())
                    if phase=='COMMITTED':session.before_commit(checkpoint(phase)['pending_event'])
                    session.observe(checkpoint(phase))
                if cut=='COMMITTED':
                    final=checkpoint('READY');final['state']=checkpoint('COMMITTED')['state'];final['events']=[checkpoint('COMMITTED')['pending_event']];session.observe(final)
                session.finish('FIXTURE_RESUMED')
                self.assertEqual(session.counts['saved_monitor_reuses'],int(cut=='MONITORED'))
                self.assertEqual(sum(k.startswith('op-start-') for k in session.values),1)
                final_state=copy.deepcopy(session.journal.checkpoint['state'])
        return results,rng.capture(),draw(),final_state
    def test_ready_decision_selected_monitored_committed_continuation(self):
        baseline=self.phase_run(self.root/'continuous')
        cases=[]
        for phase in ('READY','DECISION_READY','SELECTED','MONITORED','COMMITTED'):
            resumed=self.phase_run(self.root/phase,phase)
            self.assertEqual(resumed,baseline,phase)
            cases.append({'resume_phase':phase,'post_rng_digest':digest(resumed[1]),
                'results_digest':digest(resumed[0]),'next_three_draws':resumed[2],'final_state':resumed[3],
                'actual_selection_operations_total':1,'saved_monitor_reuses':int(phase=='MONITORED')})
        target=os.environ.get('PCT_RNG_EVIDENCE_DIR')
        if target:Path(target,'five_stage_rng_comparison.json').write_text(json.dumps({'scope':'synthetic Session/StageJournal control flow, no public episode','cases':cases},indent=2)+'\n')
    def test_completed_operation_before_selection_publication(self):
        seed();entry=rng.capture()
        with Store(self.root/'operation',ID) as store:
            session=Session(store,StageJournal(store));session.observe(checkpoint('READY'));session.observe(checkpoint('DECISION_READY'))
            output=session.call('synthetic_selection',draw,owner={'decision':'d1'});post=rng.capture()
        rng.restore(entry)
        with Store(self.root/'operation',ID) as store:
            session=Session(store,StageJournal(store))
            result=session.call('synthetic_selection',lambda:self.fail('must reuse operation output'),owner={'decision':'d1'})
            self.assertEqual(result,output);self.assertEqual(rng.capture(),post)
            self.assertEqual(session.counts['operation_result_reuses'],1)
            self.assertEqual(session.counts['synthetic_selection_calls'],0)
            draw()
            with self.assertRaisesRegex(ValueError,'DUPLICATE_CONSUMPTION'):
                session.call('synthetic_selection',lambda:0,owner={'decision':'d1'})
    def test_whole_job_result_post_rng_reuse(self):
        seed();entry=rng.capture()
        with Store(self.root/'job',ID) as store:
            session=Session(store,StageJournal(store));session.observe(checkpoint('READY'))
            draw() # synthetic summary/finish consumption after the durable WAL
            session.save_job_result(session.journal.checkpoint,{'fixture':draw()});post=rng.capture()
            expected=draw()
        rng.restore(entry)
        with Store(self.root/'job',ID) as store:
            session=Session(store,StageJournal(store));session.saved_job_result(session.journal.checkpoint,'fixture-job')
            self.assertEqual(rng.capture(),post);self.assertEqual(draw(),expected)
            self.assertEqual(session.counts['saved_episode_result_reuses'],1)
    def test_real_selector_saved_choice_post_rng_no_new_forward(self):
        from types import SimpleNamespace
        from semantic_pallet_planner.jev_select.contracts import DecisionContext
        from pct_baseline import geo_encoding
        from pct_baseline.p4b_state import tensor_digest
        path=Path('PCT/outputs/PCT_P3_20261115_01/attempt_02/jobs/diagnostic_pct_geo_b1_0/episode.json')
        event=next(e for e in read(path)['events'] if e.get('selection'))
        ctx=DecisionContext.from_dict(event['context']);encoding=geo_encoding.encode_geometry(ctx);n=encoding.data['candidate_count']
        calls=[]
        def synthetic_actor(*_,**__):
            calls.append(draw());p=torch.zeros((1,16));p[0,:n]=1/n
            return None,torch.tensor([0]),torch.tensor(0.),None,SimpleNamespace(probs=p)
        core=SimpleNamespace(state_dict=lambda:{'fake':torch.tensor([1.])},actor=synthetic_actor,critic=lambda _:torch.tensor(1.))
        cfg={'selector':'pct_geo_b1','policy_snapshot':tensor_digest(core)}
        seed();entry=rng.capture()
        def selector(session):
            obj=Selector(cfg,core,session);obj.bound=(ctx,encoding,geo_encoding.verify_candidates(encoding,event['bundle']['selectable_candidates']));return obj
        with Store(self.root/'choice',ID) as store:
            session=Session(store,StageJournal(store));selection=selector(session).select(ctx,decision_id='fixture-d1')
            post=rng.capture();expected=draw()
        rng.restore(entry)
        with Store(self.root/'choice',ID) as store:
            session=Session(store,StageJournal(store));again=selector(session).select(ctx,decision_id='fixture-d1')
            self.assertEqual(again.data,selection.data);self.assertEqual(rng.capture(),post)
            self.assertEqual(draw(),expected);self.assertEqual(len(calls),1)
            self.assertEqual(session.counts['selection_record_reuses'],1)
    def clone_records(self,source,target,transform,identity=ID):
        with Store(source,ID) as store:records=list(store.records())
        with Store(target,identity) as store:
            for value in records:
                record=transform(value['key'],copy.deepcopy(value['record']))
                if record is not None:store.append(record,key=value['key'])
    def test_missing_digest_policy_and_legacy_refused(self):
        # Produce one valid batch with the real controller, no optimizer.
        seed();entry=rng.capture()
        with Store(self.root/'original',ID) as store:
            c=BatchController(store,schedule(),'fixed')
            c.batch(0,lambda s,p:{'status':'COMPLETED','transitions':[{'draw':draw()}]},lambda *_:None,lambda:'fixed')
        transforms={
            'missing':lambda k,v:({x:y for x,y in v.items() if x!='rng'} if k=='attempt-0000' else v),
            'digest':lambda k,v:(dict(v,rng=dict(v['rng'],post=v['rng']['pre'])) if k=='attempt-0000' else v),
            'gap':lambda k,v:None if k=='attempt-0001' else v,
            'result':lambda k,v:dict(v,transitions=[{'tampered':True}]) if k=='attempt-0000' else v,
        }
        for name,transform in transforms.items():
            target=self.root/name;self.clone_records(self.root/'original',target,transform);rng.restore(entry)
            with Store(target,ID) as store:
                c=BatchController(store,schedule(),'fixed')
                with self.assertRaises(ValueError):c.batch(0,lambda *_:self.fail('collector forbidden'),lambda *_:None,lambda:'fixed')
        changed={'source':'other-source','policy':'fixed'}
        self.clone_records(self.root/'original',self.root/'source-drift',lambda k,v:v,identity=changed)
        rng.restore(entry)
        with Store(self.root/'source-drift',changed) as store:
            with self.assertRaisesRegex(ValueError,'BINDING_DRIFT'):
                BatchController(store,schedule(),'fixed').batch(0,lambda *_:self.fail('source drift'),lambda *_:None,lambda:'fixed')
        rng.restore(entry)
        with Store(self.root/'legacy',ID) as store:
            store.append({'status':'COMPLETED','slot_digest':digest(schedule()[0]),'policy':'fixed','transitions':[]},key='attempt-0000')
            with self.assertRaisesRegex(ValueError,'LEGACY_ATTEMPT'):
                BatchController(store,schedule(),'fixed').batch(0,lambda *_:self.fail('legacy must stop'),lambda *_:None,lambda:'fixed')
        rng.restore(entry)
        with Store(self.root/'original',ID) as store:
            with self.assertRaisesRegex(ValueError,'BINDING_DRIFT'):
                BatchController(store,schedule(),'changed').batch(0,lambda *_:None,lambda *_:None,lambda:'changed')
    def test_wal_rng_missing_and_result_binding_drift_stop(self):
        from pct_baseline.p4b_storage import seal
        for mode in ('missing','checkpoint-drift'):
            root=self.root/mode;seed()
            with Store(root,ID) as store:
                session=Session(store,StageJournal(store));session.observe(checkpoint('READY'))
                entry=copy.deepcopy(session.values['rng-entry']['pre'])
            path=root/'wal/00000000.json';row=read(path);row.pop('seal')
            if mode=='missing':row.pop('rng')
            else:row['checkpoint']['state']={'tampered':True}
            path.write_text(json.dumps(seal(row))+'\n');rng.restore(entry)
            with Store(root,ID) as store:
                with self.assertRaises(ValueError):Session(store,StageJournal(store))
    def test_native_snapshot_without_rng_contract_is_not_upgraded(self):
        from pct_baseline import p4b_state as state
        from pct_baseline.p4b_storage import checked,seal
        from pct_baseline.contracts import sha
        seed();core=torch.nn.Linear(1,1);opt=torch.optim.Adam(core.parameters(),lr=1e-4)
        with Store(self.root/'native',ID) as store:
            state.save_initial(store,core,opt,state.tensor_digest(core))
            path=store.root/'initial';(path/'rng').write_bytes(state.dump(state.rng_state()))
            row=checked(path/'manifest.json');row.pop('seal');row['files']['rng']=sha(path/'rng');row=seal(row)
            (path/'manifest.json').write_text(json.dumps(row)+'\n')
            with self.assertRaisesRegex(ValueError,'LEGACY_SNAPSHOT'):
                state.load(store,core,opt,update_id=0,expected_seal=row['seal'])
    def test_rng_direct_missing_drift_duplicate_and_ambiguous(self):
        seed();s=rng.capture();binding={'source':'s','policy':'p'};owner={'cursor':1};result={'result':1}
        row=rng.envelope(s,s,binding=binding,owner=owner,result=result);consumer=rng.Consumer()
        consumer.advance(row,binding=binding,owner=owner,result=result)
        with self.assertRaisesRegex(ValueError,'DUPLICATE_CONSUMPTION'):consumer.advance(row,binding=binding,owner=owner,result=result)
        bad=copy.deepcopy(row);bad['post'].pop('numpy')
        with self.assertRaises(ValueError):rng.validate(bad,binding=binding,owner=owner,result=result)
        draw()
        with self.assertRaisesRegex(ValueError,'CURRENT_DRIFT'):rng.Consumer().advance(row,binding=binding,owner=owner,result=result)
        seed()
        with Store(self.root/'ambiguous',ID) as store:
            session=Session(store,StageJournal(store));session.call('synthetic',draw,owner={'decision':'x'})
            start=copy.deepcopy(session.values['op-start-00000000']);end=copy.deepcopy(session.values['op-end-00000000'])
            session.save('op-start-00000001',start)
            end.pop('rng');end=session.pack_result(end,{'operation':1,'kind':'synthetic','request':{'decision':'x'}},start['rng_pre'])
            session.save('op-end-00000001',end)
        seed()
        with Store(self.root/'ambiguous',ID) as store:
            session=Session(store,StageJournal(store))
            with self.assertRaisesRegex(ValueError,'AMBIGUOUS_OPERATION'):session.call('synthetic',lambda:0,owner={'decision':'x'})
