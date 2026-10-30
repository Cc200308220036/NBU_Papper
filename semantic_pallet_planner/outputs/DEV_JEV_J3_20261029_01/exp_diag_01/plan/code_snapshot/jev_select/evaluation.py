"""Independent reference feedback and whole-order metrics, downstream of choice."""
from __future__ import annotations

import math
from collections import Counter

from semantic_pallet_planner.o4.extensions.e2.protocol import observation
from semantic_pallet_planner.o4.extensions.e2.reference import state as reference_state


def feedback(state, task):
    req = observation(state, task["instruction_text"], task["regions"])
    return reference_state(req["placed_objects"], task["reference_policy"], task["regions"],
                           pending_objects=req["available_objects"], end_of_stream=state["end_of_stream"])


def summarize(task, config, method, state, events, reason):
    final = feedback(state, task)
    placed = len(state["placed_items"]); total = len(task["items"])
    volume = sum(math.prod(o["oriented_size_mm"]) for o in state["placed_items"])
    planned_volume = sum(math.prod(o["dimensions_mm"].values()) for o in task["items"])
    decisions = [e for e in events if e["event"] not in ("WAIT_RECEIVE", "EOS")]
    violating = sum(e["event"] == "PLACE" and bool(e["reference_after"]["violations"]) for e in decisions)
    return {"task_id": task["task_id"], "source_order_key": task["source_order_key"],
            "source_kind": task["source_kind"], "negative": task.get("negative", False),
            "selector_backend": method, "candidate_backend": config["candidate_backend"],
            "selectable_pool": config["selectable_pool"], "policy_source": config["policy_source"],
            "feature_version": config["feature_version"], "memory_mode": config["memory_mode"],
            "planned_items": total, "arrived_items": state["arrival_count"], "placed_items": placed,
            "pending_ids": [p["item"]["item_id"] for p in state["pending_items"]],
            "unarrived_ids": [o["item_id"] for o in task["items"] if o["item_id"] not in state["arrived_ids"]],
            "completed": placed == total, "clean_completed": placed == total and not final["violations"] and violating == 0,
            "termination_reason": reason, "final_business_violations": final["violations"],
            "relation_status": final["relation_status"], "violating_steps": violating,
            "placed_item_ratio": placed / total, "placed_volume_ratio": volume / planned_volume,
            "volume_utilization": volume / (state["container"]["length_mm"] * state["container"]["width_mm"] * state["container"]["max_height_mm"]),
            "max_height_mm": max((o["pose"]["z_base_mm"] + o["oriented_size_mm"][2] for o in state["placed_items"]), default=0),
            "decision_records": len(decisions), "singleton_steps": sum(e.get("route") == "SINGLETON_BYPASS" for e in decisions),
            "choice_steps": sum(e.get("route") == "CHOICE_REQUIRED" for e in decisions),
            "physical_check_failures": sum(e.get("reason") == "physical_rejection" for e in decisions)}


def aggregate(rows, attempts, *, mode="offline", pricing=None):
    groups = []
    for method in sorted({r["selector_backend"] for r in rows}):
        for negative in (False, True):
            selected = [r for r in rows if r["selector_backend"] == method and r["negative"] == negative]
            if selected:
                groups.append({"selector_backend": method, "stratum": "contradictory_constructed" if negative else "positive_or_development",
                               "planned_orders": len(selected), "clean_completed": sum(r["clean_completed"] for r in selected),
                               "termination_reasons": dict(Counter(r["termination_reason"] for r in selected))})
    real = [r for r in attempts if r["origin"] == "jev"]
    measured = [r for r in real if r["transport"] and r["transport"]["network_attempted"] is True]
    unknown_send = sum(r["transport"]["network_attempted"] is None for r in real)
    from .transport import strict_json, validate_transport
    usages = []; served = []; latencies = []
    for row in measured:
        saved = row["transport"]; latencies.append(saved["latency_s"])
        try:
            payload = strict_json(validate_transport(saved))
            usage = payload.get("usage")
            if isinstance(payload.get("model"), str): served.append(payload["model"])
            if isinstance(usage, dict) and set(usage) == {"input_tokens", "output_tokens"} and all(type(v) is int and v >= 0 for v in usage.values()):
                usages.append(usage)
        except (ValueError, TypeError, UnicodeError, AttributeError):
            pass
    usage_complete = bool(measured) and len(usages) == len(measured) and unknown_send == 0
    known_input = sum(u["input_tokens"] for u in usages); known_output = sum(u["output_tokens"] for u in usages)
    pricing = pricing or {"input_per_million": 0.042, "output_per_million": 0.}
    known_cost = (known_input * pricing["input_per_million"] + known_output * pricing["output_per_million"]) / 1_000_000
    def percentile(values, fraction):
        if not values: return None
        values = sorted(values); position = (len(values)-1) * fraction
        lo = int(position); hi = min(lo+1, len(values)-1)
        return values[lo] + (values[hi]-values[lo]) * (position-lo)
    return {"version": "jev_metrics_v1", "mode": mode, "planned_jobs": len(rows),
            "source_orders": len({r["source_order_key"] for r in rows}), "groups": groups,
            "model_api_calls": len(measured), "unknown_send_attempts": unknown_send, "remote_reserved_attempts": len(real),
            "offline_attempts": len(attempts) - len(real),
            "estimated_model_cost_usd": 0. if mode == "offline" else known_cost if usage_complete else None,
            "known_usage_cost_usd": known_cost if mode == "remote" else 0., "usage_complete": usage_complete,
            "known_input_tokens": known_input if mode == "remote" else None,
            "known_output_tokens": known_output if mode == "remote" else None,
            "model_usage": {"input_tokens": known_input, "output_tokens": known_output} if usage_complete else None,
            "served_models": sorted(set(served)),
            "model_latency_p50_s": percentile(latencies, .5), "model_latency_p95_s": percentile(latencies, .95),
            "model_quality": "NOT_MEASURED" if mode == "offline" else "SMOKE_ONLY_NOT_BENCHMARKED",
            "memory_maintenance_cost_usd": 0.}



def evaluate_committed_state(state, reference_spec, regions):
    """Independent downstream audit, with rule/object identities and coverage."""
    from itertools import combinations
    from semantic_pallet_planner.o4.observation import public_object
    from semantic_pallet_planner.o4.evaluator import _accept
    from .contracts import canonical, digest, validate_schema
    placed = [public_object(o, state['attributes'][o['item_id']], True) for o in state['placed_items']]
    pending = [public_object(o['item'], state['attributes'][o['item']['item_id']]) for o in state['pending_items']]
    raw = reference_state(placed, reference_spec, regions, pending_objects=pending, end_of_stream=state['end_of_stream'])
    by_id = {o['object_id']: o for o in placed}
    rules = {r['rule_id']: r for r in reference_spec['rules']}
    instances = []
    def add(kind, rule_id, objects, severity=None):
        instances.append({'identity': canonical([kind, rule_id, objects]), 'kind': kind,
                          'rule_id': rule_id, 'object_ids': objects, 'severity': severity})
    for oid, limit in raw['limits_kg'].items():
        load = raw['loads_kg'][oid]
        if load <= limit + 1e-6:
            continue
        for rid in raw['active_rules'].get(oid, []):
            rule = rules[rid]
            threshold = 0. if rule['type'] == 'no_top_load' else rule['limit'].get('constant_kg', by_id[oid]['labels']['max_top_load_kg'])
            if load > threshold + 1e-6:
                add(rule['type'], rid, [oid], {'value': load-threshold, 'unit': 'kg'})
    for pair in raw['contact_pairs']:
        a, b = [by_id[i] for i in pair]
        for rule in rules.values():
            if rule['type'] == 'forbidden_contact' and ((_accept(a, rule['left']) and _accept(b, rule['right'])) or (_accept(b, rule['left']) and _accept(a, rule['right']))):
                add('forbidden_contact', rule['rule_id'], sorted(pair))
    for row in raw['region_instances']:
        if not row['inside']:
            add('inside_region', row['rule_id'], [row['object_id']])
    for row in raw['relation_instances']:
        if not row['satisfied']:
            add('relative_position', row['rule_id'], [row['subject_id'], row['reference_id']],
                {'value': max(0., row['min_gap_mm']-row['clearance_mm']), 'unit': 'mm'})
    coverage = []
    for rid, rule in rules.items():
        kind = rule['type']
        if kind in ('no_top_load', 'max_top_load', 'inside_region'):
            checked = sum(_accept(o, rule['target']) for o in placed)
            deferred = sum(_accept(o, rule['target']) for o in pending)
            active = sum(rid in raw['active_rules'].get(o['object_id'], []) for o in placed) if kind != 'inside_region' else checked
        elif kind == 'forbidden_contact':
            def pairs(objects):
                return {tuple(sorted((a['object_id'], b['object_id']))) for a,b in combinations(objects,2)
                        if (_accept(a,rule['left']) and _accept(b,rule['right'])) or (_accept(b,rule['left']) and _accept(a,rule['right']))}
            known = pairs([*placed,*pending]); decided = pairs(placed)
            checked, deferred, active = len(decided), len(known-decided), len(decided)
        else:
            status = raw['relation_status'][rid]
            checked, deferred, active = status['checked_pairs'], status['deferred_pairs'], status['checked_pairs']
        coverage.append({'rule_id': rid, 'kind': kind, 'checked': checked, 'deferred': deferred,
                         'active': active, 'status': 'deferred' if deferred else 'checked' if checked else 'not_applicable'})
    value = {'version': 'jev_business_state_v1', 'reference_spec_digest': digest(reference_spec),
             'observed_state_digest': digest([placed,pending,regions,state['end_of_stream']]),
             'instances': sorted(instances,key=lambda r:r['identity']), 'coverage': sorted(coverage,key=lambda r:r['rule_id']), 'raw': raw}
    validate_schema('business_state', value)
    return value


def summarize_business_trajectory(events, *, planned_items, rule_registry):
    """Count onsets separately from persistence; transient recovery is retained."""
    previous = set(); unique = set(); new_events = violating_steps = 0
    by_rule = {r['rule_id']: {'kind': r['type'], 'new_events': 0, 'unique_instances': [], 'violating_steps': 0} for r in rule_registry}
    for event in events:
        if event['event'] != 'PLACE' or event.get('business_after') is None:
            continue
        rows = event['business_after']['instances']; current = {r['identity'] for r in rows}
        new = current - previous
        new_events += len(new); unique.update(current); violating_steps += bool(current)
        for rid, metrics in by_rule.items():
            selected = {r['identity'] for r in rows if r['rule_id'] == rid}
            metrics['new_events'] += len(selected & new)
            metrics['unique_instances'] = sorted(set(metrics['unique_instances']) | selected)
            metrics['violating_steps'] += bool(selected)
        previous = current
    return {'final_violation_instances': len(previous), 'new_violation_events': new_events,
            'unique_violation_instances': len(unique), 'violating_steps': violating_steps,
            'new_violations_per_100_planned_items': 100.*new_events/planned_items,
            'by_rule': by_rule}


def summarize_v2(task, config, method, state, events, reason):
    from .contracts import digest
    # Legacy order/space fields stay available, with independent reference recomputation.
    row = summarize(task, config, method, state, events, reason)
    trajectory = summarize_business_trajectory(events, planned_items=len(task['items']), rule_registry=task['reference_policy']['rules'])
    final = evaluate_committed_state(state, task['reference_policy'], task['regions'])
    row.update(trajectory)
    row.update(version='jev_order_metrics_v2', business_mode=config['business_mode'],
               experiment_protocol=config['experiment_protocol'], execution_version=config['execution_version'],
               evaluation_version=config['evaluation_version'], public_spec_digest=digest(task.get('public_spec',task['instruction_text'])),
               partition=task.get('partition','diagnostic'), business_configuration=task.get('business_configuration','diagnostic'),
               clean_completed=row['completed'] and trajectory['unique_violation_instances']==0,
               final_clean_completed=row['completed'] and not final['instances'],
               final_rule_coverage=final['coverage'], unobserved_rule_objects=len(row['unarrived_ids']),
               feasibility_status=task.get('feasibility_status','unknown'),
               synthetic_business_attributes=task.get('business_spec_source')=='public_generated_v1')
    placed = state['placed_items']
    if placed:
        mins = [min(o['pose'][axis]-o['oriented_size_mm'][i]/2 for o in placed) for i,axis in enumerate(('x_mm','y_mm'))]
        maxs = [max(o['pose'][axis]+o['oriented_size_mm'][i]/2 for o in placed) for i,axis in enumerate(('x_mm','y_mm'))]
        envelope = (maxs[0]-mins[0])*(maxs[1]-mins[1])*row['max_height_mm']
        volume = sum(math.prod(o['oriented_size_mm']) for o in placed)
        row['envelope_utilization'] = volume/envelope if envelope else None
    else:
        row['envelope_utilization'] = None
    return row


def aggregate_v2(rows, attempts, *, plan, experiment_root):
    """Source-group paired statistics and measured, explicitly bounded timing scopes."""
    import random
    from collections import defaultdict
    from pathlib import Path
    from .contracts import JevSelectError,digest
    from .ledger import read
    root=Path(experiment_root)
    if len(rows)!=len(plan['jobs']) or {r['job_id'] for r in rows}!={j['job_id'] for j in plan['jobs']}:
        raise JevSelectError('metrics_job_denominator_changed')
    summary=aggregate(rows,attempts,mode=plan['mode'],pricing=plan['pricing'])
    summary.update(version='jev_metrics_v2',experiment_protocol=plan['experiment_protocol'],role=plan['role'],
                   business_mode='evaluate_only',model_quality='NOT_MEASURED' if plan['mode']=='offline' else 'EMPIRICAL_ORDER_COMPARISON',
                   planned_tasks=len(plan['task_registry']),workers=1,cache_policy=plan['cache_policy'],
                   complete_jobs=sum(r['completed'] for r in rows),clean_completed_jobs=sum(r['clean_completed'] for r in rows),
                   execution_failures=sum(r['execution_status']=='FAILED' for r in rows))
    metrics=('completed','clean_completed','placed_item_ratio','placed_volume_ratio','new_violation_events',
             'unique_violation_instances','final_violation_instances','new_violations_per_100_planned_items','max_height_mm')
    by_source=defaultdict(list)
    for row in rows:
        key=(row['source_order_key'],row['partition'],row['business_configuration'],row['selector_backend'])
        by_source[key].append(row)
    source_rows=[]
    for (source,partition,configuration,method),selected in sorted(by_source.items()):
        source_rows.append({'source_group_id':source,'partition':partition,'business_configuration':configuration,
                            'selector_backend':method,'underlying_task_ids':sorted(r['task_id'] for r in selected),
                            'job_count':len(selected),
                            **{m:sum(float(r[m]) for r in selected)/len(selected) for m in metrics}})
    groups=[]
    for method,partition,configuration in sorted({(r['selector_backend'],r['partition'],r['business_configuration']) for r in rows}):
        selected=[r for r in rows if (r['selector_backend'],r['partition'],r['business_configuration'])==(method,partition,configuration)]
        sources=[r for r in source_rows if (r['selector_backend'],r['partition'],r['business_configuration'])==(method,partition,configuration)]
        groups.append({'selector_backend':method,'partition':partition,'business_configuration':configuration,
                       'planned_jobs':len(selected),'independent_source_groups':len(sources),
                       'completed_jobs':sum(r['completed'] for r in selected),'clean_completed_jobs':sum(r['clean_completed'] for r in selected),
                       'termination_reasons':dict(Counter(r['termination_reason'] for r in selected)),
                       'execution_failures':sum(r['execution_status']=='FAILED' for r in selected),
                       'source_weighted_means':{m:sum(r[m] for r in sources)/len(sources) for m in metrics},
                       'mean_height_of_completed_jobs_mm':sum(r['max_height_mm'] for r in selected if r['completed'])/sum(r['completed'] for r in selected) if any(r['completed'] for r in selected) else None})
    summary['groups']=groups
    # Pair each task/configuration first, then average within the independent source unit.
    lookup={(r['task_id'],r['selector_backend']):r for r in rows};pairs=[]
    for baseline in ('shared_geometry','shared_business_lexicographic'):
        if baseline not in plan['methods'] or 'jev_choice' not in plan['methods']:continue
        for partition,configuration in sorted({(r['partition'],r['business_configuration']) for r in rows}):
            selected=[r for r in rows if r['selector_backend']=='jev_choice' and (r['partition'],r['business_configuration'])==(partition,configuration)]
            for metric in metrics:
                differences=defaultdict(list)
                for jev in selected:
                    baseline_row=lookup.get((jev['task_id'],baseline))
                    if baseline_row is not None:differences[jev['source_order_key']].append(float(jev[metric])-float(baseline_row[metric]))
                values=[sum(v)/len(v) for key,v in sorted(differences.items())]
                if not values:continue
                interval=None
                if len(values)>=10:
                    rng=random.Random(int(digest(['paired_source_bootstrap',20261029,partition,configuration,baseline,metric])[:16],16))
                    resamples=sorted(sum(rng.choice(values) for _ in values)/len(values) for _ in range(2000))
                    interval=[resamples[49],resamples[1949]]
                common=[(r,lookup[r['task_id'],baseline]) for r in selected if (r['task_id'],baseline) in lookup and r['completed'] and lookup[r['task_id'],baseline]['completed']]
                pairs.append({'baseline':baseline,'partition':partition,'business_configuration':configuration,'metric':metric,
                              'direction':'jev_minus_baseline','independent_source_groups':len(values),
                              'source_mean_difference':sum(values)/len(values),'bootstrap_95_percentile_interval':interval,
                              'bootstrap_repetitions':2000 if interval is not None else 0,'source_differences':values,
                              'common_completed_jobs':len(common),
                              'common_completed_height_difference_mm':sum(a['max_height_mm']-b['max_height_mm'] for a,b in common)/len(common) if common else None})
    per_rule=[]
    for row in rows:
        for rid,counts in row['by_rule'].items():
            coverage=next((x for x in row['final_rule_coverage'] if x['rule_id']==rid),None)
            per_rule.append({'job_id':row['job_id'],'task_id':row['task_id'],'source_group_id':row['source_order_key'],
                             'selector_backend':row['selector_backend'],'partition':row['partition'],
                             'business_configuration':row['business_configuration'],'rule_id':rid,
                             **counts,'coverage':coverage,'unarrived_items':len(row['unarrived_ids'])})
    phase_keys=('public_parse_s','physical_generation_s','facts_context_s','public_business_s','selection_s','physical_commit_s','independent_evaluation_s','checkpoint_io_s')
    timing_rows=[]
    for row in rows:
        episode=read(root/'episodes'/f"{row['job_id']}.json")
        phases={key:0. for key in phase_keys};walls=[];incomplete=0;hits=misses=0
        for event in episode['events']:
            if event['event'] in ('WAIT_RECEIVE','EOS'):
                if event['timings']!={}:raise JevSelectError('invalid_wait_telemetry')
                continue
            times=event['timings']
            if set(times)-set((*phase_keys,'decision_wall_s','decision_segments_s','generation_cache_hits','generation_cache_misses')):
                raise JevSelectError('unknown_telemetry_fields')
            for key,value in times.items():
                if value is None and key=='decision_wall_s':continue
                if type(value) not in (int,float) or not math.isfinite(value) or value<0:raise JevSelectError('invalid_telemetry_value')
            segments=sum(times.get(k,0.) for k in phase_keys)
            if abs(times['decision_segments_s']-segments)>1e-7:raise JevSelectError('telemetry_sum_changed')
            wall=times['decision_wall_s']
            if wall is None:incomplete+=1
            elif wall+1e-7<segments:raise JevSelectError('telemetry_wall_less_than_segments')
            else:walls.append(wall)
            for key in phases:phases[key]+=times.get(key,0.)
            hits+=times.get('generation_cache_hits',0);misses+=times.get('generation_cache_misses',0)
        sessions=read(root/'timings'/f"{row['job_id']}.json")
        for index,session in enumerate(sessions):
            if set(session)!={'session_index','started_at','finished_at','wall_s','resume_validation_included','status','persistence_s'} or session['session_index']!=index:raise JevSelectError('session_telemetry_changed')
            if session['finished_at'] is not None and (session['finished_at']<session['started_at'] or session['wall_s'] is None or session['wall_s']<0):raise JevSelectError('invalid_session_clock')
            if type(session['persistence_s']) not in (int,float) or not math.isfinite(session['persistence_s']) or session['persistence_s']<0:raise JevSelectError('invalid_persistence_clock')
        complete=all(s['wall_s'] is not None for s in sessions)
        timing_rows.append({'job_id':row['job_id'],'selector_backend':row['selector_backend'],
                            'phase_totals_s':phases,'continuous_decision_wall_samples_s':walls,'incomplete_decision_wall_samples':incomplete,
                            'driver_sessions_wall_s':sum(s['wall_s'] for s in sessions) if complete else None,
                            'known_driver_sessions_wall_s':sum(s['wall_s'] for s in sessions if s['wall_s'] is not None),
                            'checkpoint_persistence_s':sum(s['persistence_s'] for s in sessions),
                            'generation_cache_hits':hits,'generation_cache_misses':misses,'resume_sessions':sum(s['resume_validation_included'] for s in sessions)})
    timings={'version':'jev_timings_v1','cache_policy':plan['cache_policy'],
             'decision_wall_boundary':'before public-observation preparation through independent evaluation completion; excludes final measurement/checkpoint record write',
             'resumed_committed_wall_is_unknown':True,'job_sessions_include_resume_validation':True,'rows':timing_rows}
    return {'rows':rows,'summary':summary,'by_source':source_rows,'by_rule':per_rule,'paired':pairs,'timings':timings}
