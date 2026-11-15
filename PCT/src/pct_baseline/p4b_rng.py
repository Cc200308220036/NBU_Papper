"""Versioned CPU RNG ownership and result-bound continuation (no random draws).

Outer snapshot -> batch -> attempt -> job/WAL -> decision/operation. A saved
result transports its post-state; consuming it never simulates its randomness.
"""
import copy
import random
import numpy as np
import torch
from .contracts import digest, require
from .p4b_storage import seal

VERSION='pct_p4b_rng_resume_v3'
WAL='pct_p4b_rng_wal_v3'


def capture():
    require(not torch.cuda.is_initialized(),'P4B_RNG_CPU_ONLY')
    n=np.random.get_state()
    return {'python':_lists(random.getstate()),
            'numpy':[n[0],n[1].tolist(),int(n[2]),int(n[3]),float(n[4])],
            'torch_cpu':torch.get_rng_state().tolist()}


def _lists(x):
    return [_lists(v) for v in x] if isinstance(x,(list,tuple)) else x


def _tuples(x):
    return tuple(_tuples(v) for v in x) if isinstance(x,list) else x


def validate_state(s):
    require(type(s) is dict and set(s)=={'python','numpy','torch_cpu'},'P4B_RNG_FIELDS')
    try:
        random.Random(0).setstate(_tuples(s['python']))
        n=s['numpy']
        require(type(n) is list and len(n)==5 and n[0]=='MT19937' and len(n[1])==624 and
                all(type(v) is int and 0<=v<2**32 for v in n[1]) and
                type(n[2]) is int and 0<=n[2]<=624 and type(n[3]) is int and n[3] in (0,1) and
                type(n[4]) in (float,int) and np.isfinite(n[4]),'P4B_RNG_NUMPY')
        np.random.RandomState(0).set_state((n[0],np.array(n[1],dtype=np.uint32),*n[2:]))
        require(type(s['torch_cpu']) is list and all(type(v) is int and 0<=v<=255 for v in s['torch_cpu']),'P4B_RNG_TORCH')
        torch.Generator(device='cpu').set_state(torch.tensor(s['torch_cpu'],dtype=torch.uint8))
    except (TypeError,ValueError,RuntimeError,IndexError,OverflowError) as exc:
        raise ValueError('P4B_RNG_INVALID_STATE') from exc


def restore(s):
    validate_state(s);require(not torch.cuda.is_initialized(),'P4B_RNG_CPU_ONLY')
    random.setstate(_tuples(s['python']))
    n=s['numpy'];np.random.set_state((n[0],np.array(n[1],dtype=np.uint32),*n[2:]))
    torch.set_rng_state(torch.tensor(s['torch_cpu'],dtype=torch.uint8))


def envelope(pre,post,*,binding,owner,result):
    validate_state(pre);validate_state(post)
    return seal({'version':VERSION,'binding':digest(binding),'owner':copy.deepcopy(owner),
                 'result_digest':digest(result),'pre':copy.deepcopy(pre),'post':copy.deepcopy(post)})


def validate(row,*,binding,owner,result):
    require(type(row) is dict and set(row)=={'version','binding','owner','result_digest','pre','post','seal'},'P4B_RNG_MISSING_OR_FIELDS')
    require(row['version']==VERSION and row['seal']==digest({k:v for k,v in row.items() if k!='seal'}),'P4B_RNG_DIGEST')
    require(row['binding']==digest(binding) and row['owner']==owner and row['result_digest']==digest(result),'P4B_RNG_BINDING_DRIFT')
    validate_state(row['pre']);validate_state(row['post']);return row


class Consumer:
    def __init__(self):self.consumed=set()
    def advance(self,row,*,binding,owner,result):
        validate(row,binding=binding,owner=owner,result=result)
        token=row['seal'];require(token not in self.consumed,'P4B_RNG_DUPLICATE_CONSUMPTION')
        current=digest(capture())
        require(current in (digest(row['pre']),digest(row['post'])),'P4B_RNG_CURRENT_DRIFT')
        restore(row['post']);self.consumed.add(token)
