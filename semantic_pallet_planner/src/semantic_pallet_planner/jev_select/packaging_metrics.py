"""Derived full-order diagnostics over durable records, never dispatching actions."""
from collections import Counter
from math import prod
from .packaging_runtime import summary, evaluate_state
from .packaging_protocol import CATEGORIES, METRICS_CONTRACT


def distribution(values):
    values = sorted(values)
    def percentile(q):
        if not values:
            return 'NA'
        pos = (len(values)-1)*q
        lo = int(pos); hi = min(lo+1, len(values)-1)
        return values[lo]+(values[hi]-values[lo])*(pos-lo)
    return {'n': len(values), 'sum': sum(values), 'p50': percentile(.5), 'p95': percentile(.95)}


def job_metrics(task, config, cp, status):
    state = cp['state']; events = cp['events']
    # A COMMITTED checkpoint owns a successful physical placement even before
    # downstream evaluation completes. Include it exactly once in diagnostics.
    if cp['phase'] == 'COMMITTED':
        events = [*events, cp['pending_event']]
    reason = cp['reason'] or status['category']
    base = summary(task, config, config['selector'], state, events, reason)
    volume = sum(prod(o['oriented_size_mm']) for o in state['placed_items'])
    container = state['container']; area = container['length_mm']*container['width_mm']
    height = base['max_height_mm']; stats = base['monitor_statistics']
    monitors = [e['monitor'] for e in events if e.get('monitor')]
    selected = stats['selected_actions']
    if cp['pending_event'] and cp['phase'] != 'COMMITTED' and cp['pending_event'].get('selection'):
        selected += 1
        if cp['pending_event'].get('monitor'):
            monitors = [*monitors, cp['pending_event']['monitor']]
    statuses = Counter(m['status'] for m in monitors)
    last = (cp['pending_event'] or (events[-1] if events else {}))
    pending = state['pending_items']
    audit = evaluate_state(state)
    return {'version': METRICS_CONTRACT['version'], 'task_id': task['task_id'],
        'method_id': config['selector'], 'source_group_id': task['source_group_id'], 'layer': task['layer'],
        'origin': 'LOCAL_TEST_DOUBLE_NOT_JEV', 'category': status['category'],
        'termination_reason': reason, 'completed': base['completed'] and status['category']=='COMPLETE',
        'stable_complete': bool(base['completed'] and status['category']=='COMPLETE' and
            config['stability_monitor']['enabled'] and statuses['STABLE']==len(task['items'])),
        'loading': {k: base[k] for k in ('planned_items','arrived_items','placed_items','placed_item_ratio',
            'placed_volume_ratio','placed_mass_kg','planned_mass_kg','placed_mass_ratio')},
        'fixed_container_utilization': volume/(area*container['max_height_mm']),
        'actual_height_mm': height if height else 'NA',
        'envelope_utilization': volume/(area*height) if height else 'NA',
        'selected_actions': selected, 'monitor_statuses': {k: statuses[k] for k in ('STABLE','UNSTABLE','UNASSESSABLE','ERROR','DISABLED')},
        'assessable_coverage': (statuses['STABLE']+statuses['UNSTABLE'])/selected if selected else 'NA',
        'monitor_reasons': dict(Counter(m['result']['reason_code'] for m in monitors if m['result'])),
        'first_predicted_instability_progress': stats['first_predicted_instability_progress'],
        'area_load_ledger': {'maximum_utilization': base['maximum_capacity_utilization'],
            'remaining_capacity_kg': base['remaining_capacity_kg'], 'remaining_distribution': distribution(base['remaining_capacity_kg']),
            'facts': audit['runtime_facts'], 'interpretation': 'area shares; not PCT reactions or future packing capacity'},
        'physical_evaluation': audit,
        'latency_s': {**{name: distribution([e.get('timings',{})[key] for e in events if key in e.get('timings',{})])
            for name,key in [('candidate','physical_generation_s'),('selection','selection_s'),('decision','decision_segments_s')]},
            'monitor': distribution([m['result']['duration_s'] for m in monitors if m['result']]),
            'order': distribution([status['active_wall_s']])},
        'failure_location': {'event_count':len(cp['events']), 'decision':cp['decision'], 'phase':cp['phase'],
            'arrival_cursor':cp['cursor'], 'end_of_stream':state['end_of_stream'],
            'buffer': [p['item'] for p in pending],
            'empty_pool_class': ('SAVED_SAMPLED_POOL_EMPTY_NO_GLOBAL_INFEASIBILITY_CLAIM' if status['category']=='EMPTY_POOL' else 'NA'),
            'generation_counts': (last.get('bundle') or {}).get('generation_counts',[]),
            'monitor_reason': (last.get('monitor') or {}).get('result'),
            'technical_error':status['error'], 'active_wall_s':status['active_wall_s']},
        'cost': {'model_calls':0,'failed_requests':0,'unknown_sends':0,'model_cost_usd':0,'memory_cost_usd':0},
        'feasibility_status':task['feasibility_status'], 'global_infeasibility_proven':False,
        'branch_metrics':'NOT_RUN','memory_metrics':'NOT_RUN','research_benefit':'NOT_ESTABLISHED'}


def aggregate(rows, planned_jobs):
    counts = Counter(r['category'] for r in rows)
    counts['NOT_RUN'] += planned_jobs-len(rows)
    return {'version':'jev_packaging_full_order_summary_v1', 'planned_jobs':planned_jobs,
        'recorded_jobs':len(rows), 'categories':{c:counts[c] for c in CATEGORIES},
        'complete_rate':sum(r['completed'] for r in rows)/planned_jobs,
        'stable_complete_rate':sum(r['stable_complete'] for r in rows)/planned_jobs,
        'predicted_instability_rate':counts['PREDICTED_STATIC_INSTABILITY']/planned_jobs,
        'selected_actions':sum(r['selected_actions'] for r in rows),
        'assessable_coverage': (sum(r['monitor_statuses']['STABLE']+r['monitor_statuses']['UNSTABLE'] for r in rows)/sum(r['selected_actions'] for r in rows)
            if sum(r['selected_actions'] for r in rows) else 'NA'),
        'latency_s': {'order':distribution([r['failure_location']['active_wall_s'] for r in rows])},
        'model_calls':0,'model_cost_usd':0,'memory_cost_usd':0,
        'research_benefit':'NOT_ESTABLISHED'}


def paired(rows):
    by_task = {}
    for row in rows:
        by_task.setdefault(row['task_id'],{})[row['method_id']] = row
    result=[]
    for task, methods in sorted(by_task.items()):
        a=methods.get('local_geometry_test_double'); b=methods.get('local_first_test_double')
        result.append({'task_id':task, 'source_group_id':(a or b)['source_group_id'],
            'direction':'geometry minus fixed order; descriptive only',
            'categories':{m:r['category'] for m,r in methods.items()},
            'delta':({**{k:a['loading'][k]-b['loading'][k] for k in ('placed_items','placed_item_ratio','placed_volume_ratio','placed_mass_ratio')},
                'fixed_container_utilization':a['fixed_container_utilization']-b['fixed_container_utilization'],
                'height_mm':a['actual_height_mm']-b['actual_height_mm'] if 'NA' not in (a['actual_height_mm'],b['actual_height_mm']) else 'NA',
                'envelope_utilization':a['envelope_utilization']-b['envelope_utilization'] if 'NA' not in (a['envelope_utilization'],b['envelope_utilization']) else 'NA'} if a and b else 'NOT_RUN'),
            'interpretation':'No causal branch or global optimality claim; equal full-order fixed utilization cannot rank layouts'})
    return result
