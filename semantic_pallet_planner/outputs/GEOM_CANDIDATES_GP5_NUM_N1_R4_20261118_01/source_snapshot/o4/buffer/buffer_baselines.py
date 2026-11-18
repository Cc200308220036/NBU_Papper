"""Frozen FIFO and public-attribute heuristic; neither accepts reference answers."""
from .buffer_candidates import blocked_reason


def choose(groups,method):
    if method in ('single_greedy','buffer_fifo'):
        ordered=groups[:1]
    elif method=='buffer_heuristic':
        ordered=sorted((g for g in groups if g['eligible']),
                       key=lambda g:(g['business_count'],-g['mass_kg'],g['arrival_index']))
    else:raise ValueError(method)
    for g in ordered:
        for c in g['eligible']:
            if c['local_label']==g['selected']:return c,None
    return None,blocked_reason(groups,fifo=method=='buffer_fifo')
