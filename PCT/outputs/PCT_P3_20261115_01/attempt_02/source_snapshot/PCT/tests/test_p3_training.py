"""Preflight only: no physical run, no candidate generation, no optimizer update."""
import copy
from pathlib import Path
import random
import tempfile
import unittest
import numpy as np
import torch
from pct_baseline.p3_training import (segmented_targets, a2c_loss, committed_reward,
                                      save_snapshot, load_snapshot)
from pct_baseline.contracts import ContractError

class TrainingPreflight(unittest.TestCase):
    def test_actual_chunk_length_and_truncation(self):
        r=torch.ones(7,requires_grad=True)
        v=torch.arange(7,dtype=torch.float32,requires_grad=True)
        target,segments=segmented_targets(r,v,terminal=True)
        self.assertEqual(target.tolist(),[10,9,8,7,6,2,1])
        self.assertEqual([x['actual_length'] for x in segments],[5,2])
        self.assertFalse(target.requires_grad)
        b=torch.tensor(8.,requires_grad=True)
        target,_=segmented_targets(r[:2],v[:2],terminal=False,truncated=True,
                                   final_bootstrap=b,gamma=.5)
        self.assertEqual(target.tolist(),[3.5,5.])
        self.assertFalse(target.requires_grad)
        with self.assertRaises(ContractError):
            segmented_targets(r,v,terminal=False,truncated=True)

    def test_detach_and_singleton_critic(self):
        v=torch.tensor([1.,2.],requires_grad=True)
        logp=torch.tensor([-.4,-.8],requires_grad=True)
        targets=torch.tensor([3.,5.],requires_grad=True)
        loss,actor,critic=a2c_loss(v,logp,targets,torch.tensor([True,False]))
        loss.backward()
        self.assertEqual(v.grad.tolist(),[-2.,-3.])
        self.assertEqual(logp.grad.tolist(),[-2.,0.])
        self.assertIsNone(targets.grad)
        self.assertAlmostEqual(float(critic.detach()),6.5)
        v2=torch.tensor([1.],requires_grad=True)
        loss,actor,_=a2c_loss(v2,torch.tensor([0.]),torch.tensor([3.]),torch.tensor([False]))
        self.assertEqual(float(actor),0.)
        loss.backward();self.assertEqual(v2.grad.tolist(),[-4.])

    def test_reward_empty_and_nonfinite(self):
        self.assertEqual(committed_reward(10,30,100),2.)
        self.assertEqual(committed_reward(30,30,100),0.)
        with self.assertRaises(ContractError):
            segmented_targets(torch.empty(0),torch.empty(0),terminal=True)
        with self.assertRaises(ContractError):
            a2c_loss(torch.tensor([float('nan')]),torch.zeros(1),torch.ones(1),torch.ones(1,dtype=torch.bool))

    def test_initial_optimizer_rng_roundtrip_and_drift(self):
        # Deliberately no optimizer.step: post-update recovery is a separate B31 test.
        model=torch.nn.Linear(2,1);optimizer=torch.optim.Adam(model.parameters(),lr=1e-4)
        identity={'plan':'preflight','source':'synthetic_math_only'}
        position={'update_id':0,'attempt_cursor':0,'batch_shards':[], 'policy_snapshot_id':'preflight'}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'snapshot'
            record=save_snapshot(p,model,optimizer,identity=identity,position=position)
            expected=(random.random(),float(np.random.random()),float(torch.rand(())))
            with torch.no_grad():
                model.weight.add_(1)
            load_snapshot(p,model,optimizer,expected_identity=identity,
                          expected_record_digest=record['record_digest'])
            actual=(random.random(),float(np.random.random()),float(torch.rand(())))
            self.assertEqual(expected,actual)
            with self.assertRaises(ContractError):
                load_snapshot(p,model,optimizer,expected_identity={'plan':'drift'},
                              expected_record_digest=record['record_digest'])
            with self.assertRaises(ContractError):
                save_snapshot(p,model,optimizer,identity=identity,position=position)

if __name__=='__main__': unittest.main()
