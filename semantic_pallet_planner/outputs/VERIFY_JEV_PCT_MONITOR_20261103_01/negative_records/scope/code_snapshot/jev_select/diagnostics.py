"""Saved-state diagnostics; scores never enter the model request."""
from __future__ import annotations

from pathlib import Path
from collections import Counter

from .contracts import CandidateBundle, DecisionContext, JevSelectError, digest
from .ledger import read, write
from .selector import PublicBusinessScorer, baseline_label
from .candidates import PublicBusinessGuard
from .dataset_j4 import verify_seal


def diagnose_episode(episode):
    rows=[];previous=set()
    for event in episode['events']:
        if event['event']!='PLACE':continue
        ctx=event['context'];selection=event['selection'];label=selection['selected_display_id']
        entry=ctx['display_mapping'][label];c=ctx['criteria'][label]
        observation=event['observation'];bundle=CandidateBundle.from_dict(event['bundle'])
        if selection['selected_candidate_id']!=entry['candidate_id'] or event['action']!=event['proposed_action']:
            raise JevSelectError('diagnostic_action_binding_mismatch')
        matches=[o for o in event['after']['placed_items'] if o['item_id']==entry['pick_item_id']]
        if len(matches)!=1 or matches[0]['pose']!=c['pose']:
            raise JevSelectError('diagnostic_committed_pose_mismatch')
        costs=PublicBusinessScorer().score(observation,PublicBusinessGuard().resolve(observation),bundle)
        chosen=costs[entry['candidate_id']]
        same=[costs[v['candidate_id']] for v in ctx['display_mapping'].values() if v['pick_item_id']==entry['pick_item_id']]
        geometry=baseline_label(DecisionContext.from_dict(ctx),'shared_geometry')
        instances=event['business_after']['instances'];current={v['identity'] for v in instances}
        new=[v for v in instances if v['identity'] not in previous];previous=current
        classification='NO_NEW_VIOLATION'
        if new:
            classification=('SAME_BOX_BETTER_POSE' if min(same)<chosen else
                            'OTHER_BOX_BETTER_ACTION' if min(costs.values())<chosen else 'ALL_RETAINED_ACTIONS_ADD_VIOLATIONS')
        rows.append({'decision_id':event['decision_id'],'selected':label,'pick_item_id':entry['pick_item_id'],
                     'selected_pose':c['pose'],'geometry_choice':geometry,
                     'different_box_from_geometry':ctx['criteria'][geometry]['pick_object']!=c['pick_object'],
                     'different_pose_from_geometry':ctx['criteria'][geometry]['pose']!=c['pose'],
                     'chosen_cost':list(chosen),'best_cost':list(min(costs.values())),
                     'same_box_best_cost':list(min(same)),'candidate_count':len(costs),
                     'zero_new_violation_candidates':sum(v[0]==0 for v in costs.values()),
                     'generation_counts':event['bundle']['generation_counts'],
                     'new_instances':new,'classification':classification})
    return {'job_id':episode['job_id'],'summary':episode['summary'],'decisions':rows,
            'interpretation':'Local alternatives only; no counterfactual continuation or global feasibility claim'}


def inspect_experiment(experiment,output,*,job_ids=None,build_viewer=True):
    from .experiment import _new_output
    root=Path(experiment).resolve();seal=verify_seal(root)
    if seal['status']!='PASS':raise JevSelectError('experiment_seal_not_verified')
    jobs=read(root/'audit/jobs.json');selected=[j for j in jobs if not job_ids or j['job_id'] in job_ids]
    if job_ids and set(job_ids)!={j['job_id'] for j in selected}:raise JevSelectError('unknown_diagnostic_job')
    out=_new_output(output);out.mkdir(parents=True)
    episodes=[read(root/'episodes'/f"{j['job_id']}.json") for j in selected]
    attempts=read(root/'audit/attempts.json')['attempts']
    by_id={a['attempt_id']:a for a in attempts}
    from .context import validate_context
    from .selector import parse_response
    cfg=read(root/'plan/config.snapshot.json')
    verified_choices=0
    for episode in episodes:
        job=next(j for j in selected if j['job_id']==episode['job_id'])
        if cfg['version']=='jev_direct_choice_v3' and read(root/'plan/plan.json').get('memory_bindings'):
            from .batch_j4 import validate_plan_j4
            from .config import config_for_memory
            snapshots=validate_plan_j4(root/'plan')[3]
            config=config_for_memory(cfg,job['method'],snapshots[job['method']])
        else:config=dict(cfg,selector=job['method'])
        for event in episode['events']:
            if not event.get('context'):continue
            ctx=DecisionContext.from_dict(event['context']);did=event['decision_id']
            validate_context(ctx,event['observation'],CandidateBundle.from_dict(event['bundle']),config)
            if read(root/'requests'/job['job_id']/f'{did}.json')!=ctx.data['request_body'] or read(root/'mappings'/job['job_id']/f'{did}.json')!=ctx.data:
                raise JevSelectError('diagnostic_saved_context_mismatch')
            selection=event.get('selection')
            if not selection or not selection['attempt_ids']:continue
            attempt=by_id[selection['attempt_ids'][0]]
            if attempt['job_id']!=job['job_id'] or attempt['decision_id']!=did or attempt['body_digest']!=digest(ctx.data['request_body']) or attempt['binding_digest']!=digest(ctx.data['local_binding']):
                raise JevSelectError('diagnostic_attempt_binding_mismatch')
            if parse_response(ctx,attempt,config).data!=selection:
                raise JevSelectError('diagnostic_response_mismatch')
            verified_choices+=1
    rows=[diagnose_episode(e) for e in episodes]
    report={'status':'PASS','scope':'SAVED_STATE_PUBLIC_SCORING_NO_TRAJECTORY_REPLAY','seal':seal,
            'planned_jobs':len(jobs),'inspected_jobs':len(rows),'model_api_calls':0,'new_environment_steps':0,
            'verified_saved_responses':verified_choices,
            'http_counts':dict(Counter(str((a.get('transport') or {}).get('http_status')) for a in attempts)),
            'jobs':rows}
    write(out/'diagnostics.json',report)
    if build_viewer:
        from .viewer import build_process_viewer
        build_process_viewer(episodes,out/'process',source_root=root)
    return report


def violation_measure(business):
    """Keep heterogeneous severities separate; kg and mm are never summed."""
    groups = {}
    for instance in business['instances']:
        severity = instance.get('severity')
        key = instance['rule_id'] + ':' + instance['kind']
        row = groups.setdefault(key, {'count':0, 'severity_by_unit':{}})
        row['count'] += 1
        if severity is not None:
            unit = severity['unit']
            row['severity_by_unit'][unit] = row['severity_by_unit'].get(unit, 0.) + severity['value']
    return {'instance_count':len(business['instances']), 'by_rule':groups}


def outcome_dominates(candidate, baseline):
    """A shorter partial packing cannot qualify as a lower-violation solution."""
    if candidate['placed_items'] < baseline['placed_items']:
        return False
    for metric in ('trajectory_violation_instance_steps', 'ever_unique_violation_instances'):
        if metric in candidate and metric in baseline and candidate[metric] > baseline[metric]:
            return False
    left, right = candidate['final_violations'], baseline['final_violations']
    better = candidate['placed_items'] > baseline['placed_items']
    for key in set(left['by_rule']) | set(right['by_rule']):
        a = left['by_rule'].get(key, {'count':0, 'severity_by_unit':{}})
        b = right['by_rule'].get(key, {'count':0, 'severity_by_unit':{}})
        if a['count'] > b['count']:
            return False
        better |= a['count'] < b['count']
        for unit in set(a['severity_by_unit']) | set(b['severity_by_unit']):
            x, y = a['severity_by_unit'].get(unit, 0.), b['severity_by_unit'].get(unit, 0.)
            if x > y + 1e-6:
                return False
            better |= x + 1e-6 < y
    return better


def comparison_prototype(cases, branches, source_group):
    """Structured comparison evidence, deliberately outside old generated-card admission."""
    loaded = [(c,s) for c in cases for s in c['affected_supports']
              if (s['excess_above_effective_limit_kg'] or 0.) > 1e-6]
    case, support = loaded[0] if loaded else (cases[0], None)
    better = next((b for b in branches if b['dominates_control']), None)
    item = {'version':'state_action_comparison_prototype_v1',
        'status':'offline_comparison_not_active_memory', 'source_group_id':source_group,
        'actual_decision':case['decision_id'], 'new_box':case['new_box'],
        'affected_support':support, 'actual_after_violations':case['actual_after_violations'],
        'historical_final_violations':cases[-1]['actual_after_violations'],
        'historical_placed_items':len(cases),
        'early_decision_case':next((c for c in cases if c['decision_id']==branches[0]['fork_decision']), None),
        'actual_one_step_alternatives':case['alternatives'],
        'controlled_branch':branches[0], 'better_early_branch':better,
        'evidence_kinds':['actual_executed_state_action_feedback','offline_simulated_alternative'],
        'independent_source_count':1, 'activation_eligible':False,
        'limitations':'Bounded local simulation under one fixed continuation policy; no alternative Jev execution, no global optimum, no benefit generalization, no new independent source or generation attempt.'}
    parts = []
    if support:
        box = support['support_box']
        parts.append(f"state: support category={box['cargo_category']}, mass={box['mass_kg']:g}kg, "
            f"label={box['labels']['max_top_load_kg']:g}kg, effective limit={support['effective_business_limit_kg']:g}kg, "
            f"physical capacity={box['physical_top_load_limit_kg']:g}kg, existing top load={support['before_top_load_kg']:g}kg; "
            f"new box mass={case['new_box']['mass_kg']:g}kg.")
        parts.append(f"actual_result: top load {support['before_top_load_kg']:g}+{support['load_increment_kg']:g}="
            f"{support['after_top_load_kg']:g}kg; excess above active business limit="
            f"{support['excess_above_effective_limit_kg']:g}kg.")
        parts.append('why: the new load propagates through the support chain; compare cumulative load with the effective business limit after overrides, and enforce physical capacity separately.')
    else:
        parts.append(f"actual_result: this observed placement has {case['actual_after_violations']['instance_count']} evaluated violation instances; no positive top-load excess is evidenced.")
    if better:
        control = branches[0]
        parts.append(f"earlier_option: after the same {better['saved_prefix_length']} observed actions, "
            f"compare a {better['fork_new_box']['cargo_category']} box at pose {better['fork_candidate']['pose']} "
            f"with the recorded action. Under the same local continuation, placed count "
            f"{control['placed_items']} vs {better['placed_items']}; final violations "
            f"{control['final_violations']['instance_count']} vs {better['final_violations']['instance_count']}. "
            'This alternative is no worse on every reported final rule count/severity.')
        rule_changes = []
        for key in sorted(set(control['final_violations']['by_rule']) | set(better['final_violations']['by_rule'])):
            left = control['final_violations']['by_rule'].get(key, {'count':0,'severity_by_unit':{}})
            right = better['final_violations']['by_rule'].get(key, {'count':0,'severity_by_unit':{}})
            value = f"{key} count {left['count']}->{right['count']}"
            for unit in sorted(set(left['severity_by_unit']) | set(right['severity_by_unit'])):
                value += f" {unit} {left['severity_by_unit'].get(unit,0.):g}->{right['severity_by_unit'].get(unit,0.):g}"
            rule_changes.append(value)
        parts.append('rule_changes: ' + '; '.join(rule_changes) + '.')
    else:
        parts.append('earlier_option: no tested early branch dominates the controlled continuation; do not claim a globally better box choice.')
    parts.append('limits: earlier alternatives are offline simulations, not Jev outcomes. Fewer placements do not count as improvement. One source only; use as a case comparison, not a verified general strategy.')
    return item, '\n'.join(parts)


def decision_case(event, task):
    """Actual state/action/outcome plus one-step evaluations of the saved pool."""
    from copy import deepcopy
    from semantic_pallet_planner.o4.buffer.buffer_state import physical, place
    from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate
    from .evaluation import evaluate_committed_state
    req = event['observation']
    policy = PublicBusinessGuard().resolve(req).data['response']['policy_ast']
    before = evaluate_committed_state(event['before'], policy, task['regions'])
    chosen_id = event['selection']['selected_candidate_id']
    chosen = next(c for c in event['bundle']['physical_candidates'] if c['candidate_id']==chosen_id)
    available = {o['object_id']:o for o in req['available_objects']}
    placed = {o['object_id']:o for o in req['placed_objects']}
    changed = []
    for oid, after in event['business_after']['raw']['loads_kg'].items():
        prior = before['raw']['loads_kg'].get(oid, 0.)
        if oid in placed and after > prior + 1e-6:
            limit = event['business_after']['raw']['limits_kg'].get(oid)
            changed.append({'support_box':placed[oid], 'before_top_load_kg':prior,
                'load_increment_kg':after-prior, 'after_top_load_kg':after,
                'effective_business_limit_kg':limit,
                'active_rule_ids':event['business_after']['raw']['active_rules'].get(oid, []),
                'excess_above_effective_limit_kg':None if limit is None else max(0., after-limit)})
    previous = {i['identity'] for i in before['instances']}
    options = []
    for c in event['bundle']['physical_candidates']:
        errors = check_candidate(physical(event['before'], c['pick_item_id']),
                                 {'container':event['before']['container']}, c)
        if errors:
            raise JevSelectError('case_saved_candidate_not_physical', str(errors))
        after = evaluate_committed_state(place(deepcopy(event['before']), c), policy, task['regions'])
        options.append({'candidate_id':c['candidate_id'], 'new_box':available[c['pick_item_id']],
            'pose':c['pose'], 'supported_by':c['support']['support_item_ids'],
            'actual_choice':c['candidate_id']==chosen_id,
            'new_violation_count':sum(i['identity'] not in previous for i in after['instances']),
            'after_violations':violation_measure(after)})
    actual_option = next(o for o in options if o['actual_choice'])
    if actual_option['after_violations'] != violation_measure(event['business_after']):
        raise JevSelectError('case_actual_outcome_mismatch')
    options.sort(key=lambda o:(o['new_violation_count'], o['after_violations']['instance_count'], o['candidate_id']))
    return {'version':'decision_case_evidence_v1', 'decision_id':event['decision_id'],
        'evidence_kind':'actual_history_with_simulated_one_step_alternatives',
        'public_rules':req['instruction_text'], 'current_placed_boxes':req['placed_objects'],
        'currently_available_boxes':req['available_objects'], 'new_box':available[chosen['pick_item_id']],
        'actual_pose':chosen['pose'], 'affected_supports':changed,
        'before_violations':violation_measure(before),
        'actual_after_violations':violation_measure(event['business_after']),
        'actual_new_instances':[i for i in event['business_after']['instances'] if i['identity'] not in previous],
        'alternatives':options,
        'limitations':'Alternative outcomes are independent one-step simulation on the saved physical pool, not executed Jev actions. Local improvement does not prove a better full-order trajectory.'}


def inspect_decision_cases(experiment, output, *, job_id='J0000', max_branches=4, fork_mode='first_violation'):
    """User-requested local comparison prototype; never imports or activates cards."""
    from copy import deepcopy
    from .dataset_j4 import offline_dataset_guard
    from .experiment import _new_output, file_manifest
    from .config import config_for_memory
    from .memory_store import empty_snapshot
    from .selector import LocalSelector, result
    from .episode import run_episode, semantic_record
    root = Path(experiment).resolve()
    if type(max_branches) is not int or not 1 <= max_branches <= 4:
        raise JevSelectError('case_branch_budget_must_be_1_to_4')
    if fork_mode not in ('first_pick', 'first_violation'):
        raise JevSelectError('unknown_case_fork_mode')
    with offline_dataset_guard() as guards:
        if verify_seal(root)['status'] != 'PASS':
            raise JevSelectError('experiment_seal_not_verified')
        source_before = file_manifest(root)
        account = root.parent/'JEV_J4_GENERATION_ACCOUNTING_V1'
        account_before = file_manifest(account) if account.exists() else {}
        episode = read(root/'episodes'/f'{job_id}.json')
        if episode['summary']['partition'] != 'train':
            raise JevSelectError('case_analysis_training_only')
        task = next(t for t in read(root/'plan/private/input_snapshot.json')['tasks']
                    if t['task_id']==episode['summary']['task_id'])
        events = [e for e in episode['events'] if e['event']=='PLACE']
        if not events:
            raise JevSelectError('case_requires_executed_actions')
        out = _new_output(output); out.mkdir(parents=True)
        write(out/'registration.json', {'version':'decision_case_analysis_v2',
            'source_episode_digest':digest(episode), 'task_digest':digest(task),
            'max_branches':max_branches, 'max_decisions_per_branch':len(task['items']),
            'continuation_policy':'shared_business_lexicographic',
            'fork_mode':fork_mode,
            'branch_selection':'first actual decision adding a violation (or first decision); freeze the earlier actual action prefix; actual action control plus best one-step-cost/geometry saved action per currently visible box; fixed before rollout outcomes',
            'external_calls':0, 'memory_write':False,
            'scope':'local simulated alternatives explicitly requested by user; not historical outcomes or independent support'})
        cases = [decision_case(e, task) for e in events]
        for c in cases:
            write(out/'cases'/f"{c['decision_id']}.json", c)
        fork = (next((i for i,c in enumerate(cases) if c['actual_new_instances']), 0)
                if fork_mode=='first_violation' else 0)
        first = events[fork]; chosen_id = first['selection']['selected_candidate_id']
        pool = first['bundle']['physical_candidates']
        actual = next(c for c in pool if c['candidate_id']==chosen_id)
        aliases = first['context']['display_mapping']
        quality = {v['candidate_id']:first['context']['criteria'][label]['features']['geometry_score']
                   for label,v in aliases.items()}
        prefixes = [actual]
        one_step = {a['candidate_id']:a for a in cases[fork]['alternatives']}
        for pick in sorted({c['pick_item_id'] for c in pool}):
            best = min((c for c in pool if c['pick_item_id']==pick), key=lambda c:(
                one_step[c['candidate_id']]['new_violation_count'],
                one_step[c['candidate_id']]['after_violations']['instance_count'],
                -quality[c['candidate_id']], c['candidate_id']))
            if best['candidate_id'] != chosen_id:
                prefixes.append(best)
        prefixes = prefixes[:max_branches]
        write(out/'branch_registry.json', prefixes)
        memory = empty_snapshot()
        cfg = config_for_memory(read(root/'plan/config.snapshot.json'), 'shared_business_lexicographic', memory)

        class PrefixSelector:
            def __init__(self, candidate_ids):
                self.candidate_ids = candidate_ids
                self.follow = LocalSelector('shared_business_lexicographic')
            def bind_public(self, *args): self.follow.bind_public(*args)
            def select(self, context, *, decision_id):
                index = int(decision_id.rsplit('_D', 1)[1])
                if index >= len(self.candidate_ids):
                    return self.follow.select(context, decision_id=decision_id)
                label = next(k for k,v in context.data['display_mapping'].items()
                             if v['candidate_id']==self.candidate_ids[index])
                return result(context, status='selected', source='local_baseline', label=label)

        branches = []
        for i, prefix in enumerate(prefixes):
            forced = [e['selection']['selected_candidate_id'] for e in events[:fork]] + [prefix['candidate_id']]
            ep = run_episode(deepcopy(task), PrefixSelector(forced), cfg,
                             job_id=f'CASE_BRANCH_{i}', method='shared_business_lexicographic', memory_snapshot=memory)
            if ep['summary'] is None:
                raise JevSelectError('case_branch_incomplete')
            final = next(e['business_after'] for e in reversed(ep['events']) if e.get('business_after'))
            row = {'branch_id':i, 'fork_candidate':prefix, 'fork_decision':first['decision_id'],
                   'fork_new_box':next(o for o in first['observation']['available_objects'] if o['object_id']==prefix['pick_item_id']),
                   'saved_prefix_length':fork, 'control':i==0,
                   'placed_items':ep['summary']['placed_items'], 'planned_items':len(task['items']),
                   'termination_reason':ep['summary']['termination_reason'],
                   'final_violations':violation_measure(final),
                   'evidence_kind':'offline_simulation_not_real_source'}
            feedback_steps = [e['business_after'] for e in ep['events'] if e['event']=='PLACE']
            row['trajectory_violation_instance_steps'] = sum(len(f['instances']) for f in feedback_steps)
            row['ever_unique_violation_instances'] = len({i['identity'] for f in feedback_steps for i in f['instances']})
            if row['termination_reason'] not in ('ALL_ITEMS_PLACED','STOP_NO_PHYSICAL_CANDIDATE'):
                raise JevSelectError('case_branch_execution_failed', row['termination_reason'])
            row['dominates_control'] = False if i==0 else outcome_dominates(row, branches[0])
            branches.append(row)
            write(out/'simulated_branches'/f'{i}.json', semantic_record(ep))
        report = {'version':'decision_case_analysis_v2', 'status':'PASS',
            'source_experiment':root.name, 'source_job':job_id, 'actual_case_count':len(cases),
            'fork_mode':fork_mode, 'fork_decision':first['decision_id'],
            'actual_placed_items':episode['summary']['placed_items'],
            'actual_final_violations':violation_measure(events[-1]['business_after']),
            'branches':branches, 'simulated_branches_run':len(branches),
            'simulated_vs_real_not_same_policy':'Historical Jev outcome is descriptive only. Branches share a fixed local continuation policy, not Jev; only branch-vs-control comparisons isolate the tested early choice under that policy.',
            'limits':'No global optimum, no online reranking, no future sequence exposed to selector, no real two-source support, no active memory card. kg/mm/count remain separate; fewer placements cannot qualify as improvement.',
            'model_api_calls':0, 'offline_guards':dict(guards)}
        prototype, preview = comparison_prototype(cases, branches, task['source_order_key'])
        write(out/'experience_prototype.json', prototype)
        (out/'jev_memory_preview.txt').write_text(preview+'\n', encoding='utf-8')
        report['preview_utf8_bytes'] = len(preview.encode('utf-8'))
        report['preview_fits_existing_item_budget'] = len(preview.encode('utf-8')) <= 1600
        report['preview_not_injected'] = True
        if source_before != file_manifest(root) or account_before != (file_manifest(account) if account.exists() else {}):
            raise JevSelectError('case_analysis_changed_history_or_account')
        write(out/'case_analysis.json', report)
        write(out/'delivery_manifest.json', file_manifest(out))
        return {k:v for k,v in report.items() if k!='branches'}
