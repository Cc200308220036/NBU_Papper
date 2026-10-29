"""Complete-order denominators and source-clustered pairing, not semantic scores."""
import math
import random
from collections import defaultdict
from .common import O5Error


def summarize(task, placed, reason, journals):
    total = len(task['items'])
    total_volume = sum(math.prod(i['dimensions_mm'].values()) for i in task['items'])
    loaded_volume = sum(math.prod(i['oriented_size_mm']) for i in placed)
    container = task['container']
    return {'planned_items': total, 'placed_items': len(placed), 'planned_volume_mm3': total_volume,
            'placed_volume_mm3': loaded_volume, 'placed_item_ratio': len(placed)/total,
            'placed_volume_ratio': loaded_volume/total_volume,
            'pallet_volume_utilization': loaded_volume/(container['length_mm']*container['width_mm']*container['max_height_mm']),
            'completed': len(placed) == total, 'termination_reason': reason,
            'proposal_physical_rejections': sum(bool(j['physical_errors']) for j in journals),
            'actual_physical_violations': 0, 'decision_count': len(journals),
            'result_scope': 'OFFLINE_ENGINEERING_NOT_MODEL_PERFORMANCE'}


def paired_sources(results, left='G0', right='D0', bootstrap_samples=10000, seed=20261028):
    groups = defaultdict(lambda: defaultdict(list))
    for row in results:
        groups[row['source_cluster_id']][row['method']].append(row['summary']['placed_volume_ratio'])
    if not groups or any(set(g) != {left, right} for g in groups.values()):
        raise O5Error('INCOMPLETE_PAIRED_DENOMINATOR')
    pairs = [{'source_cluster_id': s, 'left_mean': sum(g[left])/len(g[left]),
              'right_mean': sum(g[right])/len(g[right]), 'left_repeats': len(g[left]), 'right_repeats': len(g[right])}
             for s, g in sorted(groups.items())]
    differences = [p['right_mean']-p['left_mean'] for p in pairs]
    rng = random.Random(seed)
    samples = sorted(sum(rng.choice(differences) for _ in differences)/len(differences) for _ in range(bootstrap_samples))
    return {'pairs': pairs, 'independent_sources': len(pairs), 'mean_difference': sum(differences)/len(differences),
            'bootstrap_samples': bootstrap_samples, 'seed': seed,
            'interval95': [samples[int(.025*(len(samples)-1))], samples[int(.975*(len(samples)-1))]],
            'power_certified': False, 'result_scope': 'OFFLINE_ENGINEERING_NOT_MODEL_PERFORMANCE'}
