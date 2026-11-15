"""Synthetic process-death batch worker, no public episode/model/optimizer work."""
import argparse
import json
import os
import random
from pathlib import Path
import numpy as np
import torch
from unittest.mock import patch
from pct_baseline.p4b_storage import Store,checked
from pct_baseline.p4b_training import BatchController
from pct_baseline.p4b_state import save_initial,load,tensor_digest
from pct_baseline import p4b_rng as rng


def seed():
    random.seed(11);np.random.seed(11);torch.manual_seed(11)


def draw():return [random.random(),float(np.random.random()),float(torch.rand(()))]


def schedule():return [{'attempt_index':i,'batch_id':i//8,'task_id':str(i),'policy_snapshot_id':'fixture-policy'} for i in range(2000)]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);ap.add_argument('--cut',type=int,default=-1);ap.add_argument('--uniform',action='store_true');args=ap.parse_args()
    with patch.object(torch.nn.Module,'_call_impl',side_effect=AssertionError('REAL_FORWARD_FORBIDDEN')),patch.object(torch.optim.Adam,'step',side_effect=AssertionError('OPTIMIZER_FORBIDDEN')):
        core=torch.nn.Linear(1,1);optimizer=torch.optim.Adam(core.parameters(),lr=1e-4)
        seed()
        class CutStore(Store):
            def append(self,record,*,key):
                value=super().append(record,key=key)
                if (args.cut==0 and key=='batch-binding-0000') or (args.cut>0 and key==f'attempt-{args.cut-1:04d}'):
                    os._exit(77) # exact durable publication boundary, before next collector
                return value
        with CutStore(args.root,{'fixture':'rng-prefix','source':'worker-v3'}) as store:
            if not (args.root/'initial').exists():save_initial(store,core,optimizer,tensor_digest(core))
            pin=checked(args.root/'initial/manifest.json')['seal']
            load(store,core,optimizer,update_id=0,expected_seal=pin)
            controller=BatchController(store,schedule(),'fixed');callbacks=[]
            def collect(slot,policy):
                callbacks.append(slot['attempt_index'])
                draws=[draw() for _ in range(1 if args.uniform else 1+slot['attempt_index']%3)]
                return {'status':'COMPLETED','transitions':[{'draws':draws,'cursor':slot['attempt_index']+1}]}
            def finish(_,trajectories,refs):
                return {'trajectories':trajectories,'refs':refs}
            result=controller.batch(0,collect,finish,lambda:'fixed')
            state=rng.capture();next_draw=draw()
            report={'result':result,'callbacks':callbacks,'rng_counts':controller.rng_counts,
                    'rng_after_batch':state,'next_draw':next_draw,'denominator':controller.denominator(),
                    'attempts':{k:v for k,v in controller.records.items() if k.startswith('attempt-')}}
            (args.root/'worker-result.json').write_text(json.dumps(report,sort_keys=True)+'\n')


if __name__=='__main__':main()
