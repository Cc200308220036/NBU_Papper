"""Pinned local CPU model/Adam/all applicable RNG serialization; no forward/step.

Binary loading is only for locally produced hash-pinned snapshots, never imports
untrusted checkpoints. CPU-only contract rejects CUDA/MPS rather than omit RNG.
"""
import copy
import io
import os
from pathlib import Path
import torch
import numpy as np
from .contracts import require, sha, digest
from .p3_training import rng_state, restore_rng
from .p4b_storage import seal, checked, publish, encoded
from .persistence import fsync_dir

VERSION='pct_p4b_state_v3'


def finite(value):
    if isinstance(value,torch.Tensor):return bool(torch.isfinite(value).all())
    if isinstance(value,dict):return all(finite(v) for v in value.values())
    if isinstance(value,(tuple,list)):return all(finite(v) for v in value)
    if isinstance(value,(float,np.floating)):return bool(np.isfinite(value))
    return True


def dump(value):
    stream=io.BytesIO();torch.save(value,stream);return stream.getvalue()


def payload(model,optimizer):
    require(all(p.device.type=='cpu' for p in model.parameters()),'P4B_CPU_ONLY')
    require(isinstance(optimizer,torch.optim.Adam),'P4B_ADAM_REQUIRED')
    require(all(g['lr']==1e-4 for g in optimizer.param_groups),'P4B_LR_DRIFT')
    m=copy.deepcopy(model.state_dict());a=copy.deepcopy(optimizer.state_dict())
    require(finite(m) and finite(a),'P4B_STATE_NONFINITE')
    return {'model':dump(m),'adam':dump(a),'rng':dump({'version':'pct_p4b_rng_resume_v3','state':rng_state()})}


def tensor_digest(model):
    import hashlib
    return digest({k:{'shape':list(v.shape),'dtype':str(v.dtype),
                      'bytes':hashlib.sha256(v.detach().cpu().contiguous().numpy().tobytes()).hexdigest()}
                   for k,v in model.state_dict().items()})


def save_initial(store,model,optimizer,policy):
    store.guard(0);require(not (store.root/'initial').exists(),'P4B_INITIAL_EXISTS')
    require(policy==tensor_digest(model),'P4B_POLICY_STATE_DRIFT')
    blobs=payload(model,optimizer);store.guard(sum(map(len,blobs.values()))+16384)
    tmp=store.root/'initial.pending';tmp.mkdir()
    for name,data in blobs.items():publish(tmp/name,data)
    row=seal({'version':VERSION,'identity':store.identity,'update_id':0,'policy_snapshot':policy,
              'tensor_digest':tensor_digest(model),'cursor':{'epoch':1,'attempt':0,'segment':0},
              'batch_refs':[],'files':{n:sha(tmp/n) for n in blobs}})
    publish(tmp/'manifest.json',encoded(row));fsync_dir(tmp)
    os.rename(tmp,store.root/'initial');fsync_dir(store.root);return row


def save_update(store,model,optimizer,*,update_id,policy,cursor,batch_refs):
    require(policy==tensor_digest(model),'P4B_POLICY_STATE_DRIFT')
    blobs=payload(model,optimizer)
    return store.publish_update(update_id=update_id,policy_snapshot=policy,cursor=cursor,
                                batch_refs=batch_refs,**blobs)


def load(store,model,optimizer,*,update_id,expected_seal):
    store.audit()
    root=store.root/('initial' if update_id==0 else f'updates/u{update_id:06d}')
    require({p.name for p in root.iterdir()}=={'model','adam','rng','manifest.json'},'P4B_ORPHAN_STATE_FILE')
    row=checked(root/'manifest.json')
    from .p4b_storage import UPDATE
    require(row['version']==(VERSION if update_id==0 else UPDATE),'P4B_STATE_VERSION')
    require(type(update_id) is int and 0<=update_id<=250 and row['cursor']['attempt']==update_id*8,'P4B_STATE_CURSOR')
    require(row['seal']==expected_seal and row['identity']==store.identity and row['update_id']==update_id,'P4B_STATE_PIN')
    require(set(row['files'])=={'model','adam','rng'},'P4B_STATE_COMPONENTS')
    for n,h in row['files'].items():require(sha(root/n)==h,'P4B_STATE_BYTES')
    state={n:torch.load(root/n,map_location='cpu',weights_only=False) for n in row['files']}
    require(type(state['rng']) is dict and set(state['rng'])=={'version','state'} and
            state['rng']['version']=='pct_p4b_rng_resume_v3','P4B_RNG_LEGACY_SNAPSHOT')
    require(finite(state['model']) and finite(state['adam']),'P4B_STATE_NONFINITE')
    require(all(p.device.type=='cpu' for p in model.parameters()) and isinstance(optimizer,torch.optim.Adam),'P4B_CPU_ADAM_REQUIRED')
    # Load into a disposable validation copy first; on any error caller discards objects.
    trial=copy.deepcopy(model);trial.load_state_dict(state['model'],strict=True)
    require(tensor_digest(trial)==row['policy_snapshot'],'P4B_POLICY_STATE_DRIFT')
    test_opt=torch.optim.Adam(trial.parameters(),lr=1e-4);test_opt.load_state_dict(state['adam'])
    require(all(g['lr']==1e-4 for g in test_opt.param_groups),'P4B_LR_DRIFT')
    for parameter,moments in test_opt.state.items():
        require(set(moments) in (set(),{'step','exp_avg','exp_avg_sq'}),'P4B_ADAM_FIELDS')
        if moments:
            require(moments['exp_avg'].shape==parameter.shape and moments['exp_avg_sq'].shape==parameter.shape
                    and moments['step'].numel()==1,'P4B_ADAM_SHAPE')
    model.load_state_dict(state['model'],strict=True);optimizer.load_state_dict(state['adam'])
    restore_rng(state['rng']['state']);return copy.deepcopy(row)
