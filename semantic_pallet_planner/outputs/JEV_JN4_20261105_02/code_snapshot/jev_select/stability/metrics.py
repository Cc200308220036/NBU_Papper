"""Counters over saved selected actions; failed attempts never add loading."""
from collections import Counter
from math import prod


def statistics(config,events,loading):
    rows=[e['monitor'] for e in events if e.get('monitor') is not None]
    statuses=Counter(r['status'] for r in rows)
    reasons=Counter(r['result']['reason_code'] for r in rows if r['result'] is not None)
    enabled=config['stability_monitor']['enabled']
    reason=loading['termination_reason']
    category=({'ALL_ITEMS_PLACED':'COMPLETE','PREDICTED_STATIC_INSTABILITY':'PREDICTED_STATIC_INSTABILITY',
        'STABILITY_UNASSESSABLE':'MONITOR_UNASSESSABLE','STABILITY_MONITOR_ERROR':'MONITOR_ERROR',
        'STOP_NO_PHYSICAL_CANDIDATE':'EMPTY_POOL','SMOKE_EVENT_LIMIT_NOT_ORDER_TERMINATION':'SMOKE_EVENT_LIMIT'}).get(reason)
    if category is None:
        category='COMMIT_ERROR' if any(e['event']=='COMMIT_FAILURE' for e in events) else 'SELECTION_ERROR'
    return {'planned_orders':1,'termination_category':category,
        'selected_actions':sum(e.get('selection',{}).get('status') in ('selected','singleton') for e in events if e.get('selection')),
        'actual_assessments':sum(r['status']!='DISABLED' for r in rows),
        'saved_result_reuses':sum(e.get('monitor_result_reuses',0) for e in events),
        'successful_commits':sum(e['event']=='PLACE' for e in events),
        'statuses':{s:statuses[s] for s in ('DISABLED','STABLE','UNSTABLE','UNASSESSABLE','ERROR')},
        'reason_coverage':dict(reasons),'termination':loading['termination_reason'],
        'stable_complete_rate':(int(loading['completed'] and statuses['STABLE']==loading['planned_items']) if enabled else 'NOT_APPLICABLE'),
        'first_predicted_instability_progress':next(({'committed_items':len(e['before']['placed_items']),
            'committed_mass_kg':sum(o['mass_kg'] for o in e['before']['placed_items']),
            'committed_volume_mm3':sum(prod(o['oriented_size_mm']) for o in e['before']['placed_items'])}
            for e in events if (e.get('monitor') or {}).get('status')=='UNSTABLE'),None),
        'selection_wall_s':sum(e.get('timings',{}).get('selection_s',0) for e in events),
        'monitor_wall_s':sum(r['result'].get('duration_s',0) for r in rows if r['result']),
        'kernel_geometry_calls':sum(r['result'].get('kernel_calls',0) for r in rows if r['result']),
        'interpretation':'predicted static instability only; technical stops and empty pools are not evidence of zero risk'}
