"""P3 A2C mathematics and atomic CPU training snapshots.

No order runner and no optimizer.step here. Collection admission remains separate.
Targets use disjoint actual-length chunks, never sliding fixed-length windows.
"""
import copy
import json
import os
from pathlib import Path
import random
import tempfile

import numpy as np
import torch

from .contracts import digest, require, sha
from .persistence import fsync_dir

VERSION = 'pct_p3_training_snapshot_v1'


def segmented_targets(rewards, frozen_values, *, terminal, truncated=False,
                      final_bootstrap=None, n=5, gamma=1.0):
    """One trajectory; values[i] is frozen V(s_i), no gradients into targets.

    Natural termination (including empty-pool stop) has zero bootstrap. A
    truncated trajectory must supply V(next public state) from collection policy.
    Chunk boundaries bootstrap at the saved state immediately after the chunk.
    """
    require(type(terminal) is bool and type(truncated) is bool and terminal != truncated,
            'P3_END_FLAGS')
    require(type(n) is int and n > 0 and 0 <= gamma <= 1, 'P3_RETURN_PARAMETERS')
    require(rewards.ndim == frozen_values.ndim == 1 and
            rewards.shape == frozen_values.shape and rewards.numel() > 0,
            'P3_ZERO_OR_INVALID_TRANSITIONS')
    require(bool(torch.isfinite(rewards).all() and torch.isfinite(frozen_values).all()),
            'P3_NONFINITE_RETURN_INPUT')
    if truncated:
        require(isinstance(final_bootstrap, torch.Tensor) and final_bootstrap.numel() == 1
                and bool(torch.isfinite(final_bootstrap).all()), 'P3_TRUNCATION_BOOTSTRAP')
    else:
        require(final_bootstrap is None, 'P3_TERMINAL_BOOTSTRAP_FORBIDDEN')
    targets = torch.empty_like(rewards)
    segments = []
    with torch.no_grad():
        for start in range(0, len(rewards), n):
            end = min(start + n, len(rewards))
            bootstrap = (frozen_values[end] if end < len(rewards) else
                         final_bootstrap.reshape(()) if truncated else rewards.new_zeros(()))
            value = bootstrap.detach()
            for i in range(end - 1, start - 1, -1):
                value = rewards[i].detach() + gamma * value
                targets[i] = value
            segments.append({'start': start, 'end_exclusive': end, 'actual_length': end-start,
                             'bootstrap': float(bootstrap.detach())})
    require(bool(torch.isfinite(targets).all()), 'P3_NONFINITE_TARGET')
    return targets.detach(), segments


def a2c_loss(values, log_probabilities, targets, choice_mask):
    require(values.ndim == 1 and values.numel() > 0 and
            values.shape == log_probabilities.shape == targets.shape == choice_mask.shape,
            'P3_LOSS_SHAPE_OR_ZERO_TRANSITIONS')
    require(choice_mask.dtype == torch.bool, 'P3_CHOICE_MASK')
    require(all(bool(torch.isfinite(x).all()) for x in (values, log_probabilities, targets)),
            'P3_NONFINITE_LOSS_INPUT')
    target = targets.detach()
    advantage = (target - values).detach()
    actor = (-(advantage[choice_mask] * log_probabilities[choice_mask]).mean()
             if bool(choice_mask.any()) else values.new_zeros(()))
    critic = ((target - values) ** 2).mean()
    loss = actor + critic
    require(bool(torch.isfinite(loss)), 'P3_NONFINITE_LOSS')
    return loss, actor, critic


def committed_reward(before_volume, after_volume, container_volume):
    require(container_volume > 0 and 0 <= before_volume <= after_volume,
            'P3_INVALID_COMMIT_VOLUME')
    value = 10.0 * (after_volume - before_volume) / container_volume
    require(np.isfinite(value), 'P3_NONFINITE_REWARD')
    return value


def rng_state():
    require(not torch.cuda.is_initialized(), 'P3_CPU_ONLY_CUDA_RNG_NOT_ADMITTED')
    return {'python': random.getstate(), 'numpy': np.random.get_state(),
            'torch_cpu': torch.get_rng_state().clone()}


def restore_rng(state):
    require(set(state) == {'python','numpy','torch_cpu'}, 'P3_RNG_FIELDS')
    random.setstate(state['python']); np.random.set_state(state['numpy'])
    torch.set_rng_state(state['torch_cpu'])


def save_snapshot(path, model, optimizer, *, identity, position):
    """Publish a new directory containing one binary and its hash-bound metadata.

    Caller holds training writer lock. Never overwrite an earlier update ID.
    Identity includes frozen plan/source/dependency/feature and policy identities;
    position includes update ID, traversal cursor and collected shard references.
    """
    path = Path(path)
    require(not path.exists(), 'P3_SNAPSHOT_EXISTS')
    require(set(position) == {'update_id','attempt_cursor','batch_shards','policy_snapshot_id'},
            'P3_POSITION_FIELDS')
    require(type(position['update_id']) is int and 0 <= position['update_id'] <= 2 and
            type(position['attempt_cursor']) is int and 0 <= position['attempt_cursor'] <= 16,
            'P3_POSITION_BUDGET')
    require(bool(identity) and all(bool(torch.isfinite(t).all()) for t in model.state_dict().values()),
            'P3_SNAPSHOT_IDENTITY_OR_PARAMETERS')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.'+path.name+'.', dir=path.parent))
    payload = {'model':copy.deepcopy(model.state_dict()),
               'optimizer':copy.deepcopy(optimizer.state_dict()), 'rng':rng_state()}
    binary = temporary/'state.pt'
    with binary.open('xb') as stream:
        torch.save(payload, stream); stream.flush(); os.fsync(stream.fileno())
    record = {'version':VERSION,'identity':copy.deepcopy(identity),
              'identity_digest':digest(identity),'position':copy.deepcopy(position),
              'state_sha256':sha(binary)}
    record['record_digest'] = digest(record)
    with (temporary/'snapshot.json').open('x') as stream:
        json.dump(record, stream, allow_nan=False, sort_keys=True)
        stream.flush(); os.fsync(stream.fileno())
    fsync_dir(temporary)
    require(not path.exists(), 'P3_SNAPSHOT_EXISTS')
    os.rename(temporary, path); fsync_dir(path.parent)
    return record


def load_snapshot(path, model, optimizer, *, expected_identity, expected_record_digest):
    """Load a locally produced pinned snapshot, after checking bytes/identity.

    The binary contains Python/NumPy RNG tuples, so this is not an untrusted
    external checkpoint importer. Pin must come from the frozen collection log.
    """
    path = Path(path)
    record = json.loads((path/'snapshot.json').read_text())
    require(set(record) == {'version','identity','identity_digest','position',
                           'state_sha256','record_digest'}, 'P3_SNAPSHOT_FIELDS')
    require(record['version'] == VERSION and record['record_digest'] == expected_record_digest
            == digest({k:v for k,v in record.items() if k != 'record_digest'}), 'P3_SNAPSHOT_PIN')
    require(record['identity'] == expected_identity and
            record['identity_digest'] == digest(expected_identity), 'P3_SNAPSHOT_IDENTITY_DRIFT')
    require(sha(path/'state.pt') == record['state_sha256'], 'P3_SNAPSHOT_BYTES')
    payload = torch.load(path/'state.pt', map_location='cpu', weights_only=False)
    require(set(payload) == {'model','optimizer','rng'} and
            all(bool(torch.isfinite(t).all()) for t in payload['model'].values()),
            'P3_SNAPSHOT_PAYLOAD')
    model.load_state_dict(payload['model'], strict=True)
    optimizer.load_state_dict(payload['optimizer'])
    restore_rng(payload['rng'])
    return copy.deepcopy(record['position'])
