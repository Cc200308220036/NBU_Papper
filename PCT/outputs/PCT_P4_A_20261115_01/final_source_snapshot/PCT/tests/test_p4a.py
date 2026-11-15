"""Offline P4-A tests. Forbidden computational modules cannot be imported."""
import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

FORBIDDEN=('torch','numpy','scipy','semantic_pallet_planner')
def guard(event,args):
    if event=='import' and args[0].split('.')[0] in FORBIDDEN:raise AssertionError('FORBIDDEN_IMPORT:'+args[0])
    if event in ('socket.connect','socket.getaddrinfo'):raise AssertionError('FORBIDDEN_NETWORK')
sys.addaudithook(guard)
from pct_baseline import p4a
from pct_baseline.contracts import digest,sha
from pct_baseline.p4a_storage import pack,unpack

class PlanChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog,cls.tasks=p4a.authenticated_catalog('.')
        cls.spec=p4a.build_spec('.');cls.identity=p4a.input_identity('.')
        cls.training=p4a.build_training(cls.catalog,cls.identity,cls.spec)
        cls.evaluation=p4a.build_evaluation(cls.catalog,cls.identity,cls.spec,cls.training)
    def test_full_schedules_and_pairwise_traversal(self):
        p4a.validate_plan('training',self.training,self.catalog,self.identity,self.spec)
        schedules=self.training['schedules']
        for i in range(3):
            a=schedules[i]['attempts'];b=schedules[i+3]['attempts']
            self.assertEqual([(x['epoch'],x['task_id']) for x in a],[(x['epoch'],x['task_id']) for x in b])
            for epoch in range(1,126):self.assertEqual(len({x['task_id'] for x in a if x['epoch']==epoch}),16)
        self.assertEqual(sum(m['action_cap'] for m in self.training['models']),198000)
    def test_complete_evaluation_slots_and_budgets(self):
        p4a.validate_plan('evaluation',self.evaluation,self.catalog,self.identity,self.spec,self.training)
        jobs=self.evaluation['jobs']
        self.assertEqual(len({(j['task_id'],j['method'],j['seed'],j['repeat']) for j in jobs}),220)
        self.assertEqual(sum(j['send_cap'] for j in jobs),1284)
        self.assertEqual(sum(j['network_choice_cap'] for j in jobs),2568)
        self.assertEqual(sum(j['p4c_probe_budget'] for j in jobs),1)
        self.assertEqual(jobs[0]['job_id'],p4a.FIRST+'/jev_none_b1/r0')
        for task in self.catalog['tasks']:
            js=[j for j in jobs if j['task_id']==task['task_id']]
            self.assertEqual(len(js),10);self.assertEqual(sum(j['send_cap'] for j in js),3*task['box_count'])
    def test_reproducible_order_and_source_groups(self):
        self.assertEqual(self.training,p4a.build_training(self.catalog,self.identity,self.spec))
        self.assertEqual(self.evaluation,p4a.build_evaluation(self.catalog,self.identity,self.spec,self.training))
        train=[t for t in self.catalog['tasks'] if t['training_eligible']]
        self.assertEqual(len({t['original_order'] for t in train}),4)
        self.assertEqual(len({t['source_component'] for t in train}),3)
        for task in train:self.assertEqual(len(task['variant_siblings']),4)
        self.assertTrue(all(not t['independent_holdout'] for t in self.catalog['tasks']))
    def test_resigned_mutations_rejected(self):
        mutations=[lambda p:p.update(sending_admitted=True),lambda p:p['jobs'][0].update(send_cap=999),
                   lambda p:p['jobs'][1].update(job_id=p['jobs'][0]['job_id']),
                   lambda p:p['jobs'][1].update(unexpected=True),lambda p:p['jobs'][1].update(source_component='0'*64),
                   lambda p:p['jobs'][1].update(weights_sha256='0'*64),lambda p:p['jobs'].reverse()]
        for mutate in mutations:
            bad=copy.deepcopy(self.evaluation);mutate(bad);bad['plan_digest']=digest({k:v for k,v in bad.items() if k!='plan_digest'})
            with self.assertRaises(Exception):p4a.validate_plan('evaluation',bad,self.catalog,self.identity,self.spec,self.training)
        bad=copy.deepcopy(self.training);bad['rules']['n']=6;bad['plan_digest']=digest({k:v for k,v in bad.items() if k!='plan_digest'})
        with self.assertRaises(Exception):p4a.validate_plan('training',bad,self.catalog,self.identity,self.spec)
    def test_file_drift_and_non_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'source.json';path.write_text('{}');ident={'source.json':sha(path)}
            p4a.check_input_identity(d,ident);path.write_text('{"changed":true}')
            with self.assertRaises(ValueError):p4a.check_input_identity(d,ident)
        for original in (self.training,self.evaluation):
            for flag in (False,True):
                bad=copy.deepcopy(original);bad.update(sending_admitted=flag,execution_admitted=flag)
                with self.assertRaisesRegex(ValueError,'NO_EXECUTOR'):p4a.require_executable(bad)
        self.assertFalse(any(n.split('.')[0] in FORBIDDEN for n in sys.modules))

class StorageChecks(unittest.TestCase):
    def test_bytes_roundtrip_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source';source.mkdir();(source/'a.json').write_bytes('{"中文": 1}\n'.encode())
            archive=root/'batch.gz';index=pack(source,['a.json'],archive)
            unpack(archive,index,root/'restored')
            self.assertEqual((source/'a.json').read_bytes(),(root/'restored/a.json').read_bytes())
            data=bytearray(archive.read_bytes());data[-5]^=1;archive.write_bytes(data)
            with self.assertRaises(ValueError):unpack(archive,index,root/'bad')
    def test_unknown_paths_and_duplicate_rejection(self):
        from pct_baseline.p4a_storage import safe_name
        for name in ('../escape','/absolute','a/../escape','.','a\\b',1):
            with self.assertRaises(ValueError):safe_name(name)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'a').write_text('{}');index=pack(root,['a'],root/'b.gz')
            bad=copy.deepcopy(index);bad['extra']=1
            with self.assertRaises(ValueError):unpack(root/'b.gz',bad,root/'out')
            with self.assertRaises(ValueError):pack(root,['a','a'],root/'dup.gz')

if __name__=='__main__':unittest.main()
