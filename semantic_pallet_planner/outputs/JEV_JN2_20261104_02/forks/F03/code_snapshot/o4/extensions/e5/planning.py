"""Exact public-root memoization of the unchanged E2 planner, no model cache."""
import copy
import json
import time
from functools import lru_cache
from ...common import canonical
from ..e2.planning import choose as _base_choose

PUBLIC_KEYS=('container','buffer_capacity','pending_items','placed_items','arrived_ids','attributes','event_index','arrival_count','placed_count','end_of_stream')
SCOPE='exact_public_state_request_ast_config_method_v1'


@lru_cache(maxsize=64)
def _cached(serialized):return _base_choose(*json.loads(serialized))


def choose(state,req,ast,config,method):
    if 'o4_e5_capacity' in config:
        from .layout_v3.planning import choose as capacity_choose
        return capacity_choose(state,req,ast,config,method)
    if 'o4_e5_layout' in config:
        from .layout_v2.planning import choose as layout_choose
        return layout_choose(state,req,ast,config,method)
    started=time.perf_counter();public={k:state[k] for k in PUBLIC_KEYS}
    key=canonical([public,req,ast,config,method]);before=_cached.cache_info().hits
    selected,groups,trace,reason=copy.deepcopy(_cached(key))
    if _cached.cache_info().hits>before:
        # No new geometry generation on an exact root hit. Logical enumeration
        # and search counters are preserved; measured time is not replayed.
        for group in groups:group['generation']['elapsed_seconds']=0.
    trace['elapsed_seconds']=time.perf_counter()-started;trace['memoization_scope']=SCOPE
    trace['evaluation_count_scope']='logical_search_work_preserved_on_exact_input_hits'
    return selected,groups,trace,reason


def clear_cache():_cached.cache_clear()
