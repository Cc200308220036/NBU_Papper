"""P2-A explicit padding-safe extension, separate from the compatibility core.

Consumes packed network tensors only; has no public candidate or order adapter.
The pointer remains upstream's context/key dot product (no glimpse aggregation).
"""
import torch
from .vendor.pct.attention_model import AttentionModel
from .vendor.pct.model import DRL_GAT
from .vendor.pct.distributions import FixedCategorical


class PaddingSafeAttention(AttentionModel):
    def forward(self, input, deterministic=False, evaluate_action=False,
                normFactor=1, evaluate=False):
        expected = self.internal_node_holder + self.leaf_node_holder + 1
        if input.ndim != 3 or input.shape[1:] != (expected, 9) or input.shape[0] < 1:
            raise ValueError('PCT_NETWORK_SHAPE')
        if input.dtype != torch.float32 or input.device.type != 'cpu':
            raise ValueError('PCT_NETWORK_DTYPE_DEVICE')
        if not torch.isfinite(input).all() or normFactor != 1:
            raise ValueError('PCT_NETWORK_NONFINITE_OR_NORMALIZATION')
        flags = input[:, :, 8]
        if not ((flags == 0) | (flags == 1)).all() or not (flags[:, -1] == 1).all():
            raise ValueError('PCT_NETWORK_VALID_FLAGS')
        leaves = flags[:, self.internal_node_holder:-1]
        if not (leaves.sum(-1) > 0).all():
            raise ValueError('PCT_NETWORK_EMPTY_LEAVES')
        # The strict branch is always -inf key masking, independent of sampling.
        return super().forward(input, deterministic, evaluate_action, normFactor, True)

    def _inner(self, embeddings, mask=None, deterministic=False,
               evaluate_action=False, shape=None, full_mask=None, valid_length=None):
        fixed = self._precompute(embeddings, shape=shape, full_mask=full_mask,
                                 valid_length=valid_length)
        # No new glimpse operation: use the original dot-product pointer.
        query = fixed.context_node_projected[:, None, :]
        logits, _ = self._one_to_many_logits(
            query, fixed.glimpse_key, fixed.glimpse_val, fixed.logit_key, mask)
        logits = logits.masked_fill(mask.bool(), -torch.inf)
        probabilities = torch.softmax(logits / self.temp, dim=-1)
        if not torch.isfinite(probabilities).all():
            raise ValueError('PCT_NETWORK_NONFINITE_OUTPUT')
        dist = FixedCategorical(probs=probabilities)
        selected = dist.mode() if deterministic else dist.sample()
        logprob = None if evaluate_action else dist.log_probs(selected)
        return probabilities, logprob, selected, dist.entropy(), dist, fixed.context_node_projected


class PaddingSafeDRLGAT(DRL_GAT):
    def __init__(self, args):
        super().__init__(args)
        # Same parameter keys/shapes; strict loading required by the harness.
        self.actor = PaddingSafeAttention(
            args.embedding_size, args.hidden_size, n_encode_layers=args.gat_layer_num,
            n_heads=1, internal_node_holder=args.internal_node_holder,
            internal_node_length=args.internal_node_length,
            leaf_node_holder=args.leaf_node_holder)
