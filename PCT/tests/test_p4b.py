"""Only synthetic persistence tests: no planner, models, LP or optimizer."""
import builtins
import copy
import tempfile
import unittest
import sys

def network_guard(event,args):
    if event in ('socket.connect','socket.getaddrinfo'):raise AssertionError('network forbidden')
sys.addaudithook(network_guard)
from pathlib import Path
from unittest.mock import patch
from pct_baseline.contracts import read, sha
from pct_baseline.p4b_storage import Store, checked
from pct_baseline.p4b_runtime import StageJournal, admit_business, attempt_denominator

IDENTITY={'source':'s','config':'c','data':'d','policy':'p','dependencies':'e'}


def cp(phase):
    pending={'decision_id':'d1','before':{'placed':0},'bundle':{'physical_candidates':[{'id':'c1'}]},
             'context':{'public':True},'observation':{},'selection':None,'monitor':None,'proposed_action':None}
    if phase in ('SELECTED','MONITORED','COMMITTED'):
        pending.update(selection={'status':'selected','id':'c1'},proposed_action={'id':'c1'})
    if phase in ('MONITORED','COMMITTED'):pending['monitor']={'status':'STABLE'}
    return {'phase':phase,'state':{'placed':int(phase=='COMMITTED')},'events':[],
            'pending_event':None if phase=='READY' else pending}


class P4BTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'store'
        self.guard=patch('builtins.__import__',side_effect=self.no_business_import)
        self.original_import=builtins.__import__;self.guard.start()
    def no_business_import(self,name,*args,**kwargs):
        if name.split('.')[0] in ('torch','numpy','scipy','semantic_pallet_planner'):
            raise AssertionError('business import forbidden: '+name)
        return self.original_import(name,*args,**kwargs)
    def tearDown(self):self.guard.stop();self.temp.cleanup()
    def test_five_stage_recovery_and_counters(self):
        phases=['READY','DECISION_READY','SELECTED','MONITORED','COMMITTED']
        for i,phase in enumerate(phases):
            with Store(self.root,IDENTITY) as store:
                journal=StageJournal(store);journal(cp(phase))
                session=journal.session();self.assertEqual(journal.checkpoint,cp(phase))
                self.assertEqual(session['planned_reuses']['saved_selection_reuses'],int(phase in ('SELECTED','MONITORED')))
                self.assertEqual(session['planned_reuses']['saved_monitor_reuses'],int(phase=='MONITORED'))
                self.assertEqual(session['planned_reuses']['saved_committed_reuses'],int(phase=='COMMITTED'))
                if phase=='MONITORED':
                    journal.record_reuse('saved_selection_reuses','d1');journal.record_reuse('saved_monitor_reuses','d1')
                self.assertEqual(session['counts'],{})
                before=len(journal.rows);journal(cp(phase));self.assertEqual(len(journal.rows),before)
        with Store(self.root,IDENTITY) as store:
            journal=StageJournal(store)
            self.assertEqual(dict(journal.counts),{'candidate_generations':1,'candidate_actions':1,'choice_selections':1,'monitor_results_persisted':1,'commits_persisted':1})
    def test_no_saved_fact_overwrite(self):
        with Store(self.root,IDENTITY) as store:
            journal=StageJournal(store)
            for phase in ['READY','DECISION_READY','SELECTED']:journal(cp(phase))
            changed=cp('MONITORED');changed['pending_event']['selection']['id']='other'
            with self.assertRaisesRegex(ValueError,'SAVED_FACT'):journal(changed)
    def test_all_identity_drifts(self):
        with Store(self.root,IDENTITY):pass
        for key in IDENTITY:
            changed=dict(IDENTITY);changed[key]='changed'
            with self.assertRaisesRegex(ValueError,'IDENTITY_DRIFT'):
                with Store(self.root,changed):pass
    def test_writer_lock(self):
        with Store(self.root,IDENTITY):
            with self.assertRaisesRegex(RuntimeError,'LOCK_CONTENDED'):
                with Store(self.root,IDENTITY):pass
    def test_shards_corruption_and_orphans(self):
        with Store(self.root,IDENTITY) as store:
            store.append({'public':'state'},key='a')
            self.assertEqual(list(store.records())[0]['record'],{'public':'state'})
        shard=next((self.root/'shards').glob('*'));original=shard.read_bytes();shard.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'SHARD_DIGEST'):
            with Store(self.root,IDENTITY):pass
        shard.write_bytes(original);(self.root/'shards'/'orphan.gz').write_bytes(b'orphan')
        with self.assertRaisesRegex(ValueError,'ORPHAN_SHARD'):
            with Store(self.root,IDENTITY):pass
    def test_capacity_and_bound(self):
        with Store(self.root,IDENTITY,shard_limit=1000) as store:
            with self.assertRaisesRegex(ValueError,'TOO_LARGE'):store.append({'data':'x'*1000},key='a')
            store.free=lambda:0
            with self.assertRaisesRegex(ValueError,'CAPACITY_SAFE_STOP'):store.append({},key='b')
            self.assertEqual(store.audit()['records'],0)
    def test_interrupted_write(self):
        with Store(self.root,IDENTITY) as store:
            def fault(point):
                if point=='bytes_fsynced':raise OSError('injected power failure')
            store.fault=fault
            with self.assertRaises(OSError):store.append({'x':1},key='a')
        with self.assertRaisesRegex(ValueError,'PENDING_DIAGNOSIS'):
            with Store(self.root,IDENTITY):pass
    def publish(self,store):
        ref=store.append({'batch':0},key='batch0')
        return store.publish_update(update_id=1,model=b'synthetic model',adam=b'synthetic adam',rng=b'synthetic rng',
            policy_snapshot='frozen0',cursor={'epoch':1,'attempt':8,'segment':0},batch_refs=[{'key':'batch0','seal':ref['seal']}])
    def test_update_success_duplicate_and_corruption(self):
        with Store(self.root,IDENTITY) as store:
            self.publish(store);self.assertEqual(store.audit()['updates'],1)
            with self.assertRaisesRegex(ValueError,'DUPLICATE_OR_GAPPED'):
                store.publish_update(update_id=1,model=b'x',adam=b'y',rng=b'z',policy_snapshot='p',cursor={},batch_refs=[])
        (self.root/'updates/u000001/adam').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'UPDATE_BYTES'):
            with Store(self.root,IDENTITY):pass
    def test_update_all_publication_boundaries(self):
        for boundary in ('intent','model','adam','rng','manifest','directory_published','intent_cleared'):
            root=self.root/boundary
            with Store(root,IDENTITY) as store:
                # Faults injected after setup record, at the named transaction boundary.
                ref=store.append({'batch':0},key='batch0')
                def fault(point):
                    if point==boundary:raise OSError('injected '+point)
                store.fault=fault
                with self.assertRaises(OSError):
                    store.publish_update(update_id=1,model=b'm',adam=b'a',rng=b'r',policy_snapshot='p',
                       cursor={'epoch':1,'attempt':8,'segment':0},batch_refs=[{'key':'batch0','seal':ref['seal']}])
            if boundary=='intent_cleared':
                with Store(root,IDENTITY) as recovered:self.assertEqual(recovered.audit()['updates'],1)
            else:
                with self.assertRaisesRegex(ValueError,'DIAGNOSIS'):
                    with Store(root,IDENTITY):pass
    def test_denominator_and_launch_guard(self):
        slots=[{'attempt_index':i,'status':'NOT_RUN'} for i in range(2000)]
        result=attempt_denominator(slots,{0:'TECHNICAL_FAILURE',1:'CANCELLED'})
        self.assertEqual(len(result),2000);self.assertEqual(sum(r['status']=='NOT_RUN' for r in result),1998)
        with self.assertRaisesRegex(ValueError,'IDENTITY_MISSING'):admit_business()
        with self.assertRaisesRegex(ValueError,'RESOURCE_GATE'):admit_business(accepted_identity={})
        with self.assertRaisesRegex(ValueError,'AUTHORIZATION_MISSING'):
            admit_business(accepted_identity={},resource_receipt={'accepted':True,'free_bytes':601166756537})
        with self.assertRaisesRegex(RuntimeError,'ROUTING_NOT_REGISTERED'):
            admit_business(accepted_identity={},resource_receipt={'accepted':True,'free_bytes':601166756537},authorization={})
    def test_frozen_descriptor_and_campaign(self):
        from pct_baseline.p4b_executor import descriptor,Campaign
        root=Path('PCT/outputs/PCT_P4_A_20261115_01/build_01')
        training=read(root/'training_plan.json');catalog=read(root/'data_catalog.json')
        before={n:sha(root/n) for n in ('training_plan.json','evaluation_template.json')}
        formal=descriptor(training,catalog,source_identity={'test':'synthetic'},environment_identity={'test':'synthetic'})
        self.assertEqual(formal['schedules'],training['schedules'])
        self.assertEqual(formal['rules'],training['rules'])
        identity=dict(IDENTITY,formal_descriptor=formal['seal'])
        with Store(self.root,identity) as store:
            campaign=Campaign(store,formal);model=formal['models'][0]['model_id']
            campaign.save_outcome(model,0,'TECHNICAL_FAILURE',evidence={'fixture':True})
            with self.assertRaisesRegex(ValueError,'CAMPAIGN_STOPPED'):
                campaign.save_outcome(model,1,'COMPLETED',evidence={'fixture':True})
            rows=campaign.denominator()
            self.assertEqual(sum(len(v) for v in rows.values()),12000)
            self.assertEqual(sum(r['status']=='NOT_RUN' for v in rows.values() for r in v),11999)
        with Store(self.root,identity) as store:self.assertTrue(Campaign(store,formal).stopped)
        self.assertEqual(before,{n:sha(root/n) for n in before})
    def test_forward_categories(self):
        with Store(self.root,IDENTITY) as store:
            journal=StageJournal(store)
            for singleton,reuse in [(False,False),(True,False),(False,True)]:
                journal.record_forward('d',singleton=singleton,record_reused=reuse)
            values=[r['record'] for r in store.records()]
            for key in ('policy_choice_forwards','singleton_critic_forwards','selection_record_reuses'):
                self.assertEqual(sum(v[key] for v in values),1)
