"""Independent packed13 adapter; original graph/pointer/critic mechanisms retained.

Only input decoding and placed/leaf first MLP dimensions change from P2-A.
"""
import torch
from torch import nn
from .network_safety import PaddingSafeAttention
from .vendor.pct.model import DRL_GAT
from .vendor.pct.tools import init


class LoadAttention(PaddingSafeAttention):
    def __init__(self,args):
        super().__init__(args.embedding_size,args.hidden_size,n_encode_layers=args.gat_layer_num,
                         n_heads=1,internal_node_holder=40,internal_node_length=11,leaf_node_holder=16)
        self.init_leaf_node_embed[0]=init(nn.Linear(12,32),nn.init.orthogonal_,lambda x:nn.init.constant_(x,0),nn.init.calculate_gain('leaky_relu'))

    def forward(self,input,deterministic=False,evaluate_action=False,normFactor=1,evaluate=False):
        if input.ndim!=3 or input.shape[1:]!=(57,13) or input.shape[0]<1:
            raise ValueError('LOAD_NETWORK_SHAPE')
        if input.dtype!=torch.float32 or input.device.type!='cpu' or not torch.isfinite(input).all() or normFactor!=1:
            raise ValueError('LOAD_NETWORK_NUMERIC')
        flags=input[:,:,12]
        if not ((flags==0)|(flags==1)).all() or not (flags[:,-1]==1).all() or not (flags[:,:40].sum(1)>0).all() or not (flags[:,40:56].sum(1)>0).all():
            raise ValueError('LOAD_NETWORK_FLAGS')
        if (input[:,:40,11]!=0).any() or (input[:,56,6:12]!=0).any() or (input[:,:,:12][flags==0]!=0).any():
            raise ValueError('LOAD_NETWORK_UNUSED_OR_PADDING')
        b=input.shape[0]
        tokens=torch.cat([self.init_internal_node_embed(input[:,:40,:11]),
                          self.init_leaf_node_embed(input[:,40:56,:12]),
                          self.init_next_embed(input[:,56:,:6])],dim=1)
        mask=1-flags
        embeddings,_=self.embedder(tokens.reshape(b*57,64),mask=mask,evaluate=True)
        _,lp,idx,entropy,dist,hidden=self._inner(embeddings,mask=mask[:,40:56],deterministic=deterministic,
            evaluate_action=evaluate_action,shape=(b,57,64),full_mask=mask,valid_length=flags.sum(1))
        return lp,idx,entropy,hidden,dist


class LoadDRLGAT(DRL_GAT):
    def __init__(self,args):
        super().__init__(args)
        self.actor=LoadAttention(args)
