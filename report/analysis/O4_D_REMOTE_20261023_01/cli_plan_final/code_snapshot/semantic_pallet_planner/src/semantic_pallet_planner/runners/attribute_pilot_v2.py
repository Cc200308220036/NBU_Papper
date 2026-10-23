"""O0/O1/O2 pilot: immutable V1, validation-only pairing, resumable real API."""
from __future__ import annotations
import argparse
import copy
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import time
from collections import Counter, defaultdict

import numpy as np
from jsonschema import Draft202012Validator

from ..config import load_config, generator_config, WORKSPACE
from ..repository import DatasetRepository, ALL_SPLITS
from ..domain import PalletState, restore_placed
from ..protocol import canonical_json, state_hash
from ..planner.generator import ExtremePointGenerator
from ..planner.constraints import candidate_points, evaluate_pose
from ..planner.scoring import geometry_score
from ..evaluation.semantic import semantic_evaluation, touching
from ..evaluation.state import apply_candidate
from ..evaluation.geometry_oracle import check_candidate
from ..evaluation.replay_values_v2 import replay_values_equal, REPLAY_ABS_TOL, REPLAY_COMPARISON_VERSION
from ..evaluation.attribute_metrics_v2 import public_relations, transition, reconstruct
from ..evaluation.policy_v2 import evaluate, optimal_set, priority_regret, validate_policy
from ..selectors.instruction_parser_v2 import instruction_from_policy, parse_instruction
from ..selectors.policy_executor_v2 import geometry, fixed_attribute, public_parser, execute_policy
from ..vlm.pilot_protocol_v2 import digest, scan_public, parse_choice, SYSTEM_PROMPT
from ..vlm.deepseek_client import DeepSeekClient
from ..vlm.client import ModelRequest

METHODS = ('geometry_greedy', 'fixed_attribute', 'public_parser', 'flash_direct_text', 'truth_rule', 'candidate_oracle')
VERSION = 'attribute_v2_pilot_1'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def read_json(path):
    return json.loads(path.read_text())


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for r in rows for k in r})
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: canonical_json(v) if isinstance(v, (list, dict)) else v for k, v in row.items()})


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def v1_inventory(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def old_applicable(state, kind):
    if kind == 'fragile_protect':
        return any(p['item']['fragile'] for p in state)
    if kind in ('heavy_low', 'heavy_center'):
        return any(p['item']['weight_class'] == 'heavy' for p in state)
    if kind == 'category_group':
        return sum(p['item']['product_category'] == 'electronics' for p in state) >= 2
    return any((a['item']['product_category']=='electronics' and b['item']['weight_class']=='heavy') or
               (b['item']['product_category']=='electronics' and a['item']['weight_class']=='heavy')
               for i, a in enumerate(state) for b in state[i+1:])


def contact_count(state):
    return sum(touching(a, b) and ((a['item']['product_category']=='electronics' and b['item']['weight_class']=='heavy') or
                (b['item']['product_category']=='electronics' and a['item']['weight_class']=='heavy'))
               for i, a in enumerate(state) for b in state[i+1:])


def diagnose_v1(root, repo):
    old = WORKSPACE/'semantic_pallet_planner/outputs/EXP_1C_DEEPSEEK_FLASH_FINAL_V1'
    names = ['steps.jsonl', 'metrics/per_decision.csv', 'config.snapshot.json', 'manifest.json', 'acceptance_report.json', 'replay_report.json']
    missing = [n for n in names if not (old/n).is_file()]
    evidence = {'requested_directory': str(old), 'missing': missing, 'status': 'INCOMPLETE' if missing else 'PENDING',
                'available_experiments': sorted(p.name for p in old.parent.glob('EXP_1C_*') if p.is_dir())}
    if missing:
        write_json(root/'o0/verification.json', evidence)
        return evidence
    inventory = v1_inventory(old)
    write_json(root/'o0/v1_files.before.json', inventory)
    for name in names[2:]:
        target = root/'o0/v1_evidence'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(old/name, target)
    config = read_json(old/'config.snapshot.json')
    manifest = read_json(old/'manifest.json')
    oldsource = WORKSPACE/'semantic_pallet_planner'
    source_mismatch = [p for p, h in manifest['source_checksums'].items() if not (oldsource/p).is_file() or sha(oldsource/p) != h]
    rows = list(csv.DictReader((old/'metrics/per_decision.csv').open()))
    events = [json.loads(line) for line in (old/'steps.jsonl').open() if line.strip()]
    by_case = {}
    for event in events:
        by_case.setdefault(event['request_id'], event)
    diagnostics, recomputed, failures = [], [], []
    for case_id, event in sorted(by_case.items()):
        case = repo.get_decision_case(case_id)
        oracle = repo.get_oracle(case_id)
        cs = event['candidate_set']['candidates']
        truth = oracle['ground_truth_rule']
        evaluated = {}
        for c in cs:
            state = restore_placed(apply_candidate(event['request'], c))
            scores, records = semantic_evaluation(state, truth, {'container': event['request']['container']})
            utility = round(statistics.fmean(scores.values()), 6)
            expected = next(x for x in oracle['candidate_evaluations'] if x['candidate_id']==c['candidate_id'])
            if abs(utility-expected['soft_utility']) > 1e-6 or records != expected['hard_violations']:
                failures.append({'case': case_id, 'candidate': c['candidate_id'], 'kind': 'candidate_annotation_recompute'})
            evaluated[c['candidate_id']] = {'utility': utility, 'records': records,
                   'instances': contact_count(state) if truth['rule_type']=='category_separate' else 0,
                   'applicable': old_applicable(state, truth['rule_type'])}
        best = evaluated[oracle['oracle_candidate_id']]
        eq = [i for i, a in evaluated.items() if len(a['records'])==len(best['records']) and abs(a['utility']-best['utility'])<=1e-6]
        geo = min(cs, key=lambda c: (-geometry_score(c), c['candidate_id']))['candidate_id']
        applicable = any(a['applicable'] for a in evaluated.values())
        diagnostics.append({'decision_case_id': case_id, 'scenario_id': event['scenario_id'], 'rule_type': truth['rule_type'],
            'split': event['split'], 'v2_rule_applicable': applicable, 'v2_no_target_attribute': not applicable,
            'v2_semantic_equivalent_candidate_count': len(eq), 'v2_candidate_business_violation_instances_sum': sum(a['instances'] for a in evaluated.values()),
            'v2_candidate_violation_record_count_sum': sum(len(a['records']) for a in evaluated.values()),
            'v2_topk_business_feasible': any(not a['records'] for a in evaluated.values()) if truth['rule_type']=='category_separate' and applicable else None,
            'v2_geometry_oracle_utility_gap': best['utility']-evaluated[geo]['utility'],
            'v2_geometry_business_violation_instances': evaluated[geo]['instances'], 'original_oracle_candidate_id': oracle['oracle_candidate_id']})
        for e in [e for e in events if e['request_id']==case_id]:
            selected = evaluated[e['candidate_id']]
            delta = selected['utility']-e['metrics']['soft_utility']
            hit = e['candidate_id']==oracle['oracle_candidate_id']
            if abs(delta)>1e-6 or hit != e['metrics']['oracle_hit']:
                failures.append({'case': case_id, 'method': e['method'], 'kind': 'event_recompute'})
            recomputed.append({'decision_case_id': case_id, 'method': e['method'], 'original_utility': e['metrics']['soft_utility'],
                'recomputed_original_utility': selected['utility'], 'utility_delta': delta, 'recomputed_oracle_hit': hit,
                'v2_semantic_equivalent_hit': e['candidate_id'] in eq, 'v2_selected_business_violation_instances': selected['instances']})
    lookup = {(r['decision_case_id'], r['method']): r for r in rows}
    for e in events:
        row = lookup.get((e['request_id'], e['method']))
        if not row or abs(float(row['soft_utility'])-e['metrics']['soft_utility'])>1e-6 or row['candidate_id']!=e['candidate_id']:
            failures.append({'kind': 'csv_step_mismatch', 'case': e['request_id']})
    rule_summary = []
    for kind in sorted({r['rule_type'] for r in diagnostics}):
        group = [r for r in diagnostics if r['rule_type']==kind]
        hard = [r for r in group if r['v2_topk_business_feasible'] is not None]
        rule_summary.append({'rule_type': kind, 'case_count': len(group),
            'applicable_count': sum(r['v2_rule_applicable'] for r in group), 'no_target_count': sum(r['v2_no_target_attribute'] for r in group),
            'business_coverage': statistics.mean(r['v2_topk_business_feasible'] for r in hard) if hard else None,
            'business_coverage_denominator': len(hard), 'mean_geometry_oracle_gap': statistics.mean(r['v2_geometry_oracle_utility_gap'] for r in group)})
    evidence.update(status='PASS' if not failures and len(events)==2160 and len(by_case)==360 and len(rows)==2160 and not source_mismatch else 'FAIL',
        events=len(events), metric_rows=len(rows), unique_cases=len(by_case), methods=dict(Counter(e['method'] for e in events)),
        source_checksum_mismatches=source_mismatch, recomputation_failures=failures,
        human_signoff='PENDING', original_acceptance=read_json(old/'acceptance_report.json')['status'],
        original_replay=read_json(old/'replay_report.json')['status'],
        case_method_unique_count=len(lookup), rule_summary=rule_summary,
        caveat='V1 only category_separate has a business hard rule; fragile_protect remains the original soft rule. Old test is regression only.')
    write_csv(root/'o0/legacy_diagnostic.csv', diagnostics)
    write_csv(root/'o0/legacy_decision_recompute.csv', recomputed)
    write_json(root/'o0/coverage_report.json', rule_summary)
    write_json(root/'o0/verification.json', evidence)
    return evidence


def enumerate_physical(state, cfg):
    """Audit full enumeration using frozen public generator primitives, no change to Top-K."""
    from ..domain import internal_item
    item = internal_item(state['available_items'][0])
    placed = restore_placed(state['placed_items'])
    settings = copy.deepcopy(cfg)
    settings['container'] = state['container']
    out = []
    for yaw in settings['candidate_generator']['yaw_degrees']:
        l, w = item['dimensions'][:2] if yaw==0 else item['dimensions'][:2][::-1]
        for x, y, z in candidate_points(placed, l, w, settings['container']):
            result, _ = evaluate_pose(item, placed, x, y, z, l, w, yaw, settings)
            if result is not None:
                out.append(result['visible'])
    return out


def policy_for(index, variant):
    hard = []
    family = index % 3
    if family in (0, 2):
        hard.append({'type': 'fragile_load_limit', 'selector': {'fragile': True}, 'threshold_kg': 1. if variant==0 else 3.})
    if family in (1, 2):
        hard.append({'type': 'forbidden_contact', 'left': {'product_category': 'electronics'}, 'right': {'weight_class': 'heavy'}})
    metrics = ['heavy_low', 'heavy_center'] if variant==0 else ['heavy_center', 'heavy_low']
    return {'schema_version': 'pallet_policy_v2_pilot', 'hard_constraints': hard,
            'soft_priorities': [{'priority': i+1, 'metric': m} for i, m in enumerate(metrics)]}


def build_pilot(root, repo, cfg):
    # All validation cases retained in ID order. No model-based selection.
    cases = repo.list_cases('validation')
    generator = ExtremePointGenerator(cfg)
    dataset, coverage, sources = [], [], []
    overlaps = []
    split_orders = defaultdict(set)
    for split in ALL_SPLITS:
        for sid in repo.list_scenarios(split):
            truth = read_json(repo.root/'annotations/ground_truth_rules'/f'{sid}.json')
            split_orders[split].add(str(truth.get('source_order_key', truth.get('source_order_id', sid))))
    for split, orders in split_orders.items():
        if split != 'validation':
            for order in sorted(orders & split_orders['validation']):
                overlaps.append({'other_split': split, 'order': order})
    for gi, case_id in enumerate(cases):
        case = repo.get_decision_case(case_id)
        scenario = repo.get_scenario(case['base_scenario_id'])
        if scenario['buffer_size'] != 1:
            raise ValueError('buffer_size not 1')
        state = {k: copy.deepcopy(case[k]) for k in ('placed_items', 'available_items')}
        state.update(container=scenario['container'], request_id=f'V2_STATE_{gi+1:03d}')
        state['placed_items'] = reconstruct(state['placed_items'])
        generation = generator.generate(PalletState.from_dict(state))
        top = generation.candidate_set.data['candidates']
        random.Random(20260928+gi).shuffle(top)
        full = enumerate_physical(state, cfg)
        ids = [c['candidate_id'] for c in top]
        public_cs = []
        for ci, c in enumerate(top):
            public = {k: copy.deepcopy(c[k]) for k in ('pick_item_id', 'pose', 'oriented_size_mm', 'support', 'load', 'resulting_geometry', 'geometry_score_components')}
            public.update(display_label=f'C{ci+1:02d}', geometry_score=geometry_score(c), public_relations=public_relations(state, c))
            public_cs.append(public)
        annotation = read_json(repo.root/'annotations/ground_truth_rules'/f"{case['base_scenario_id']}.json")
        source = {'physical_group_id': state['request_id'], 'source_case_id': case_id, 'source_scenario_id': case['base_scenario_id'],
            'source_order_id': annotation.get('source_order_id'), 'source_order_key': annotation.get('source_order_key', case['base_scenario_id']),
            'source_article_ids': annotation.get('source_article_ids', []), 'source_split': 'validation', 'pilot_split': 'validation',
            'attribute_sources': {'dimensions_mm': 'BED-BPP derived', 'mass_kg': 'BED-BPP derived',
                                  'fragile': 'synthetic', 'weight_class': 'derived/synthetic', 'product_category': 'synthetic',
                                  'top_load_limit_kg_synthetic': 'synthetic'},
            'source_case_sha256': sha(repo.root/'tasks/decision_cases'/f'{case_id}.json')}
        sources.append(source)
        for variant in (0, 1):
            policy = policy_for(gi, variant)
            text = instruction_from_policy(policy)
            if parse_instruction(text) != policy:
                raise ValueError('public policy grammar mismatch')
            request = {'schema_version': 'pallet_request_v2_pilot', 'request_id': f'V2_PILOT_{gi+1:03d}_{variant}',
                       'state_hash': state_hash(scenario['container'], state), 'policy_digest': digest({'grammar': VERSION, 'instruction_text': text}),
                       'instruction_text': text, 'container': scenario['container'], 'placed_items': state['placed_items'],
                       'available_items': state['available_items'], 'candidates': public_cs, 'buffer_size': 1}
            scan = scan_public(request, ids)
            if scan['status'] != 'PASS':
                raise ValueError('public leakage')
            evaluations = [evaluate(state, c, policy, scenario['container']) for c in top]
            optimum = optimal_set(evaluations)
            all_eval = [evaluate(state, c, policy, scenario['container']) for c in full]
            full_best = optimal_set(all_eval)
            geo_label = geometry(request)
            geo_i = next((i for i, c in enumerate(public_cs) if c['display_label']==geo_label), None)
            kinds = {canonical_json([e['after_violation_instances'], e['soft_quality']]) for e in evaluations}
            hard_applicable = any(e['business_hard_applicable'] for e in evaluations)
            track = 'topk_missing_feasible' if not optimum['feasible_indices'] and full_best['feasible_indices'] else 'enumeration_no_feasible' if not full_best['feasible_indices'] else 'no_semantic_opportunity' if len(kinds)<=1 else 'semantic_opportunity'
            cover = {'request_id': request['request_id'], 'physical_group_id': state['request_id'],
                 'source_order_key': source['source_order_key'], 'candidate_count': len(top), 'enumeration_count': len(full),
                 'hard_applicable': hard_applicable, 'no_target_hard': not hard_applicable,
                 'topk_feasible_count': len(optimum['feasible_indices']), 'enumeration_feasible_count': len(full_best['feasible_indices']),
                 'equivalent_labels': [public_cs[i]['display_label'] for i in optimum['equivalent_indices']],
                 'feasible_labels': [public_cs[i]['display_label'] for i in optimum['feasible_indices']],
                 'track': track, 'semantic_opportunity': len(kinds)>1,
                 'geometry_priority_regret': priority_regret(evaluations[geo_i], optimum) if geo_i is not None else [],
                 'geometry_post_violation_count': evaluations[geo_i]['post_business_violation_count'] if geo_i is not None else None}
            item = {'public_request': request, 'source': source, 'hidden_policy': policy, 'mapping': dict(zip([c['display_label'] for c in public_cs], ids)),
                    'physical_candidates': top, 'evaluations': evaluations, 'optimum': optimum, 'coverage': cover}
            dataset.append(item)
            coverage.append(cover)
            write_json(root/'data/public_requests'/f"{request['request_id']}.json", request)
            write_json(root/'data/private_annotations'/f"{request['request_id']}.json", {k: v for k, v in item.items() if k!='public_request'})
    unique_orders = len({canonical_json(s['source_order_key']) for s in sources})
    physical_count = len({d['public_request']['state_hash'] for d in dataset})
    audit = {'status': 'PASS' if not overlaps and physical_count==len(cases) else 'FAIL', 'cross_split_source_order_overlaps': overlaps,
             'source_scenarios': len({s['source_scenario_id'] for s in sources}), 'unique_source_orders': unique_orders,
             'unique_physical_states': physical_count, 'paired_case_count': len(dataset),
             'all_source_split': 'validation', 'independent_orders_30_requirement_met': unique_orders>=30,
             'primary_ci_cluster': 'source_order_key', 'secondary_ci_cluster': 'physical_group_id',
             'all_cases_retained_before_model_calls': True, 'no_test_used_for_tuning': True,
             'attribute_provenance_caveat': 'Semantic attributes and physical capacities are synthetic; not measured damage/safety.'}
    write_json(root/'data/source_manifest.json', sources)
    write_json(root/'data/split_audit.json', audit)
    write_json(root/'data/pilot_dataset.private.json', dataset)
    write_csv(root/'metrics/candidate_coverage.csv', coverage)
    write_json(root/'metrics/coverage_report.json', {'n': len(coverage), 'track_counts': {k: sum(c['track']==k for c in coverage) for k in ('semantic_opportunity','no_semantic_opportunity','topk_missing_feasible','enumeration_no_feasible')},
               'hard_applicable_n': sum(c['hard_applicable'] for c in coverage),
               'hard_feasible_n': sum(c['hard_applicable'] and c['topk_feasible_count']>0 for c in coverage),
               'topk_business_feasible_coverage': (sum(c['hard_applicable'] and c['topk_feasible_count']>0 for c in coverage)/sum(c['hard_applicable'] for c in coverage)) if any(c['hard_applicable'] for c in coverage) else None,
               'semantic_opportunity_n': sum(c['semantic_opportunity'] for c in coverage), 'cases': coverage})
    return dataset


def response_row(item, method, label, status, trace=None):
    request = item['public_request']
    trace = trace or {}
    idx = next((i for i, c in enumerate(request['candidates']) if c['display_label']==label), None)
    applicable = item['coverage']['hard_applicable']
    any_target = applicable or item['optimum']['soft_applicable']
    e = item['evaluations'][idx] if idx is not None else None
    optimum = item['optimum']
    row = {'schema_version': VERSION, 'request_id': request['request_id'], 'state_hash': request['state_hash'],
           'policy_digest': request['policy_digest'], 'physical_group_id': item['source']['physical_group_id'],
           'policy_hard_types': [p['type'] for p in item['hidden_policy']['hard_constraints']],
           'soft_priority_metrics': [p['metric'] for p in item['hidden_policy']['soft_priorities']],
           'source_order_key': item['source']['source_order_key'], 'method': method, 'privileged': method in ('truth_rule', 'candidate_oracle'),
           'status': status, 'display_label': label, 'hard_applicable': applicable, 'soft_applicable': optimum['soft_applicable'],
           'business_hard_satisfied': bool(e and not e['after_violation_instances']) if applicable else None,
           'all_attempt_success': bool(e and not e['after_violation_instances']) if any_target else None,
           'conditional_hard_satisfaction': bool(e and not e['after_violation_instances']) if applicable and optimum['feasible_indices'] else None,
           'post_business_violation_count': e['post_business_violation_count'] if e else None,
           'new_business_violation_count': e['new_business_violation_count'] if e else None,
           'worsened_existing_violation_count': e['worsened_existing_violation_count'] if e else None,
           'avoidable_new_violation': bool(e['new_business_violation_count']>0) if e is not None and applicable and any(x['new_business_violation_count']==0 for x in item['evaluations']) else None,
           'oracle_equivalent_hit': idx in optimum['equivalent_indices'] if optimum['feasible_indices'] and optimum['soft_applicable'] else None,
           'priority_regret': priority_regret(e, optimum) if e else [None]*len(optimum['stage_best']),
           'priority_1_quality': e['soft_quality'][0] if e and e['soft_quality'] else None,
           'physical_violations': None, 'geometry_score': request['candidates'][idx]['geometry_score'] if idx is not None else None,
           'api_valid': trace.get('api_valid'), 'attempt_count': trace.get('attempt_count', 0), 'fallback': False,
           'input_tokens': trace.get('input_tokens'), 'output_tokens': trace.get('output_tokens'),
           'latency_s': trace.get('latency_s'), 'actual_cost': None, 'estimated_cost': trace.get('estimated_cost'),
           'reason': trace.get('reason'), 'error_category': trace.get('error_category'), 'repair_count': 0,
           'comparison_success': bool(e and not e['after_violation_instances'] and (not optimum['soft_applicable'] or idx in optimum['equivalent_indices'])) if any_target else None}
    if idx is not None:
        candidate = item['physical_candidates'][idx]
        normalized_case = {**request, 'placed_items': reconstruct(request['placed_items'])}
        errors = check_candidate(normalized_case, {'container': request['container']}, candidate)
        row['physical_violations'] = len(errors)
        row['physical_errors'] = errors
        rel = public_relations(request, candidate)
        row['attribute_before_after_delta'] = rel
        for k in ('heavy_mass_weighted_z_mm', 'heavy_center_distance_mm', 'fragile_load_ratio_max'):
            row[k] = rel['after'][k]
        row['fragile_added_load_kg'] = rel['delta']['fragile_added_load_kg']
        row['soft_quality_by_priority'] = e['soft_quality']
        row['before_violation_instances'] = e['before_violation_instances']
        row['after_violation_instances'] = e['after_violation_instances']
        row['load_excess_before_after_kg'] = {'before': e['before_load_excess_by_instance_kg'], 'after': e['after_load_excess_by_instance_kg']}
    return row


def remote_choice(root, item, client):
    request = item['public_request']
    folder = root/'selector_inputs/flash_direct_text'/request['request_id']
    folder.mkdir(parents=True, exist_ok=True)
    # Public input only; hidden policy/mapping never accepted by model client.
    scan = scan_public(request, item['mapping'].values())
    write_json(folder/'leakage_report.json', scan)
    if scan['status'] != 'PASS':
        return None, 'input_leakage_rejected', {'api_valid': False, 'attempt_count': 0}
    write_json(folder/'public_request.json', request)
    user = canonical_json(request)
    write_json(folder/'prompt.json', {'version': VERSION, 'system_prompt': SYSTEM_PROMPT, 'user_text': user,
                                    'input_sha256': digest(request)})
    trace = {'api_valid': False, 'attempt_count': 1, 'input_tokens': None, 'output_tokens': None,
             'latency_s': None, 'estimated_cost': None}
    start = time.perf_counter()
    try:
        result = client.complete(ModelRequest(model='deepseek-flash', system_prompt=SYSTEM_PROMPT, user_text=user,
                                              max_output_tokens=512, timeout_s=60.))
        write_json(folder/'response.raw.json', result.as_dict())
        trace.update(input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                     latency_s=result.latency_s, estimated_cost=result.estimated_cost)
        response = parse_choice(result.raw_text, request)
        write_json(folder/'response.parsed.json', response)
        trace.update(api_valid=True, reason=response['reason'])
        return response['display_label'], response['action'], trace
    except Exception as exc:
        category = getattr(exc, 'category', 'invalid_response')
        # Do not serialize provider exception text: it may contain sensitive details.
        trace.update(error_category=category, latency_s=time.perf_counter()-start)
        write_json(folder/'error.json', {'category': category, 'exception_type': type(exc).__name__})
        return None, category, trace


def run_methods(root, dataset, remote=False, client=None):
    records = []
    rows_path = root/'metrics/per_decision.json'
    existing = {(r['request_id'], r['method']): r for r in read_json(rows_path)} if rows_path.exists() else {}
    key_available = bool(os.environ.get('DEEPSEEK_API_KEY')) or client is not None
    if remote and key_available and client is None:
        client = DeepSeekClient()
    for item in dataset:
        request = item['public_request']
        for method in METHODS:
            key = (request['request_id'], method)
            # Resume remote execution exactly once; explicit retry requires new run.
            if key in existing and existing[key]['status'] not in ('blocked_missing_api_key', 'not_run_remote_disabled'):
                records.append(existing[key])
                continue
            trace, status = {}, 'select'
            if method=='geometry_greedy':
                label = geometry(request)
            elif method=='fixed_attribute':
                label = fixed_attribute(request)
            elif method=='public_parser':
                try:
                    label = public_parser(request)
                except ValueError:
                    label, status = None, 'parser_error'
            elif method=='truth_rule':
                label = execute_policy(request, item['hidden_policy'])
            elif method=='candidate_oracle':
                indices = item['optimum']['equivalent_indices']
                label = min((request['candidates'][i] for i in indices), key=lambda c: (-c['geometry_score'], c['display_label']))['display_label'] if indices else None
            elif remote and key_available:
                label, status, trace = remote_choice(root, item, client)
            else:
                label, status = None, 'blocked_missing_api_key' if not key_available else 'not_run_remote_disabled'
            if label is None and status=='select':
                status = 'abstain' if request['candidates'] else 'no_physical_candidate'
            row = response_row(item, method, label, status, trace)
            records.append(row)
            if method=='flash_direct_text' and remote and key_available:
                write_json(rows_path, records + [v for k, v in existing.items() if k not in {(r['request_id'], r['method']) for r in records}])
                print(f"Flash {request['request_id']}: {status}", flush=True)
    write_json(rows_path, records)
    write_csv(root/'metrics/per_decision.csv', records)
    return records


def cluster_comparison(rows, method, reference, field, cluster):
    # Blocked rows are not evidence; actual API failures remain failures.
    selected = {(r['request_id'], r['method']): r for r in rows if not r['status'].startswith(('blocked_', 'not_run_'))}
    groups = defaultdict(list)
    for (rid, m), a in selected.items():
        b = selected.get((rid, reference))
        if m==method and b and a.get(field) is not None and b.get(field) is not None:
            groups[canonical_json(a[cluster])].append((float(a[field])-float(b[field]), rid))
    if not groups:
        return {'method': method, 'reference': reference, 'field': field, 'cluster': cluster, 'n_clusters': 0, 'mean_difference': None, 'ci95': None}
    values = np.array([statistics.mean(x for x, _ in v) for v in groups.values()])
    rng = np.random.default_rng(20260928)
    samples = rng.choice(values, (5000, len(values)), replace=True).mean(axis=1)
    return {'method': method, 'reference': reference, 'field': field, 'cluster': cluster, 'n_clusters': len(values),
            'n_paired_tasks': sum(len(v) for v in groups.values()), 'mean_difference': float(values.mean()),
            'cluster_sd': float(values.std(ddof=1)) if len(values)>1 else None,
            'ci95': [float(x) for x in np.quantile(samples, [.025, .975])], 'bootstrap_resamples': 5000}


def summarize(root, dataset, rows):
    summary, pairs = [], []
    for method in METHODS:
        group = [r for r in rows if r['method']==method]
        ran = [r for r in group if not r['status'].startswith(('blocked_', 'not_run_'))]
        entry = {'method': method, 'planned_n': len(group), 'evaluated_n': len(ran), 'status_counts': dict(Counter(r['status'] for r in group))}
        for field in ('business_hard_satisfied', 'conditional_hard_satisfaction', 'avoidable_new_violation', 'oracle_equivalent_hit',
                      'comparison_success', 'geometry_score', 'priority_1_quality', 'post_business_violation_count',
                      'new_business_violation_count', 'worsened_existing_violation_count', 'all_attempt_success', 'heavy_mass_weighted_z_mm', 'heavy_center_distance_mm', 'fragile_added_load_kg', 'fragile_load_ratio_max'):
            values = [float(r[field]) for r in ran if r.get(field) is not None]
            entry[field] = {'n': len(values), 'na_n': len(ran)-len(values), 'mean': statistics.mean(values) if values else None}
        pg = defaultdict(list)
        for r in ran:
            pg[r['physical_group_id']].append(r)
        eligible = [v for v in pg.values() if len(v)==2 and all(r['comparison_success'] is not None for r in v)]
        entry['policy_pair_success_rate'] = {'n': len(eligible), 'mean': statistics.mean(all(r['comparison_success'] for r in v) for v in eligible) if eligible else None}
        entry['submitted_n'] = sum(r['display_label'] is not None for r in ran)
        entry['submitted_physical_violations'] = sum(r['physical_violations'] or 0 for r in ran)
        summary.append(entry)
        if method not in ('geometry_greedy', 'truth_rule', 'candidate_oracle'):
            for ref in ('geometry_greedy', 'fixed_attribute', 'public_parser'):
                if ref==method:
                    continue
                for field in ('business_hard_satisfied', 'comparison_success', 'priority_1_quality'):
                    for cluster in ('physical_group_id', 'source_order_key'):
                        pairs.append(cluster_comparison(rows, method, ref, field, cluster))
    remote = [r for r in rows if r['method']=='flash_direct_text' and not r['status'].startswith(('blocked_', 'not_run_'))]
    lat = [r['latency_s'] for r in remote if r['latency_s'] is not None]
    costs = {'planned_calls': 60, 'actual_attempts': sum(r['attempt_count'] for r in remote), 'completed_model_records': len(remote),
             'valid_response_rate': statistics.mean(bool(r['api_valid']) for r in remote) if remote else None,
             'input_tokens': sum(r['input_tokens'] for r in remote) if remote and all(r['input_tokens'] is not None for r in remote) else None,
             'output_tokens': sum(r['output_tokens'] for r in remote) if remote and all(r['output_tokens'] is not None for r in remote) else None,
             'actual_cost': None, 'estimated_cost': sum(r['estimated_cost'] for r in remote) if remote and all(r['estimated_cost'] is not None for r in remote) else None,
             'latency_p50_s': float(np.quantile(lat, .5)) if lat else None, 'latency_p95_s': float(np.quantile(lat, .95)) if lat else None,
             'unknown_price_is_not_zero': True}
    per_policy = []
    for method in METHODS:
        for family in sorted({canonical_json([r['policy_hard_types'], r['soft_priority_metrics']]) for r in rows}):
            group = [r for r in rows if r['method']==method and canonical_json([r['policy_hard_types'], r['soft_priority_metrics']])==family and not r['status'].startswith(('blocked_', 'not_run_'))]
            record = {'method': method, 'policy_family': json.loads(family), 'evaluated_n': len(group)}
            for field in ('business_hard_satisfied', 'comparison_success', 'priority_1_quality'):
                vals = [float(r[field]) for r in group if r.get(field) is not None]
                record[field+'_n'] = len(vals)
                record[field+'_mean'] = statistics.mean(vals) if vals else None
            for priority in (0,1):
                vals = [r['priority_regret'][priority] for r in group if len(r['priority_regret'])>priority and r['priority_regret'][priority] is not None]
                record[f'priority_{priority+1}_regret_n'] = len(vals)
                record[f'priority_{priority+1}_regret_mean'] = statistics.mean(vals) if vals else None
            per_policy.append(record)
    write_csv(root/'metrics/per_policy_summary.csv', per_policy)
    write_json(root/'metrics/summary.json', summary)
    write_json(root/'metrics/paired_cluster_ci.json', pairs)
    write_json(root/'metrics/cost_summary.json', costs)
    audits = []
    for method in METHODS:
        group = [r for r in rows if r['method']==method and r['status'] not in ('blocked_missing_api_key', 'not_run_remote_disabled')]
        for success in (True, False):
            options = [r for r in group if r['comparison_success'] is success]
            for r in options[:3]:
                record = {k: r.get(k) for k in ('request_id', 'method', 'display_label', 'status', 'comparison_success', 'reason',
                      'before_violation_instances', 'after_violation_instances', 'worsened_existing_violation_count', 'priority_regret', 'heavy_center_distance_mm',
                      'fragile_added_load_kg', 'physical_violations')}
                item = next(d for d in dataset if d['public_request']['request_id']==r['request_id'])
                record.update(instruction_text=item['public_request']['instruction_text'], feasible_labels=item['coverage']['feasible_labels'],
                              best_equivalent_labels=item['coverage']['equivalent_labels'], coverage_track=item['coverage']['track'],
                              source_case_id=item['source']['source_case_id'], human_signoff='PENDING')
                audits.append(record)
    write_csv(root/'audits/case_audit.csv', audits)
    write_json(root/'audits/case_audit.json', audits)
    return summary, pairs, costs


def validate_and_replay(root, dataset, rows, *, write_reports=True):
    failures, leakage = [], []
    public_schema = read_json(Path(__file__).resolve().parents[1]/'schemas/pilot_request_v2.schema.json')
    validator = Draft202012Validator(public_schema)
    by_request = {d['public_request']['request_id']: d for d in dataset}
    for d in dataset:
        request = d['public_request']
        try:
            validator.validate(request)
            validate_policy(d['hidden_policy'])
        except Exception as exc:
            failures.append({'request_id': request['request_id'], 'kind': 'schema', 'error': str(exc)[:300]})
        leakage.extend(scan_public(request, d['mapping'].values())['hits'])
        if state_hash(request['container'], request)!=request['state_hash']:
            failures.append({'request_id': request['request_id'], 'kind': 'state_hash'})
        if digest({'grammar': VERSION, 'instruction_text': request['instruction_text']})!=request['policy_digest']:
            failures.append({'request_id': request['request_id'], 'kind': 'policy_digest'})
        recomputed_evaluations = [evaluate(request, c, d['hidden_policy'], request['container']) for c in d['physical_candidates']]
        if not replay_values_equal(recomputed_evaluations, d['evaluations']) or not replay_values_equal(optimal_set(recomputed_evaluations), d['optimum']):
            failures.append({'request_id': request['request_id'], 'kind': 'annotation_recompute'})
        if len(request['candidates'])!=len(d['physical_candidates']) or len(set(c['display_label'] for c in request['candidates']))!=len(request['candidates']):
            failures.append({'request_id': request['request_id'], 'kind': 'candidate_cardinality'})
        for i, c in enumerate(d['physical_candidates']):
            pc = request['candidates'][i]
            if d['mapping'].get(pc['display_label'])!=c['candidate_id'] or any(pc[k]!=c[k] for k in ('pose','pick_item_id','oriented_size_mm','support','load','resulting_geometry','geometry_score_components')):
                failures.append({'request_id': request['request_id'], 'kind': 'candidate_mapping'})
            errors = check_candidate(request, {'container': request['container']}, c)
            if errors:
                failures.append({'request_id': request['request_id'], 'kind': 'physical', 'errors': errors})
            independent_after = restore_placed(apply_candidate(request, c))
            _, actual_after = transition(request, c)
            independent_load = {p['item_id']: p['supported_load_kg'] for p in independent_after}
            if any(abs(p['supported_load_kg']-independent_load[p['item_id']])>1e-6 for p in actual_after):
                failures.append({'request_id': request['request_id'], 'kind': 'independent_load_crosscheck'})
            if not replay_values_equal(public_relations(request, c), request['candidates'][i]['public_relations']):
                failures.append({'request_id': request['request_id'], 'kind': 'relation_replay'})
    pairs = defaultdict(list)
    for d in dataset:
        pairs[d['source']['physical_group_id']].append(d)
    for group, items in pairs.items():
        if len(items)!=2 or items[0]['public_request']['state_hash']!=items[1]['public_request']['state_hash'] or items[0]['mapping']!=items[1]['mapping'] or items[0]['public_request']['candidates']!=items[1]['public_request']['candidates'] or items[0]['public_request']['policy_digest']==items[1]['public_request']['policy_digest']:
            failures.append({'group': group, 'kind': 'policy_pair'})
    keys = [(r['request_id'],r['method']) for r in rows]
    if len(keys)!=len(set(keys)) or len(keys)!=len(dataset)*len(METHODS):
        failures.append({'kind': 'method_matrix_cardinality'})
    for row in rows:
        item = by_request[row['request_id']]
        trace = {k: row[k] for k in ('api_valid', 'attempt_count', 'input_tokens', 'output_tokens', 'latency_s', 'estimated_cost', 'reason', 'error_category')}
        replay = response_row(item, row['method'], row['display_label'], row['status'], trace)
        if row['state_hash']!=item['public_request']['state_hash'] or row['policy_digest']!=item['public_request']['policy_digest']:
            failures.append({'request_id': row['request_id'], 'kind': 'row_binding'})
        if not replay_values_equal(row, replay):
            failures.append({'request_id': row['request_id'], 'method': row['method'], 'kind': 'metric_replay'})
    micro_path = root/'checks/microcases_report.json'
    micro_pass = micro_path.exists() and all(m['status']=='PASS' for m in read_json(micro_path))
    if not micro_pass:
        failures.append({'kind': 'micro_hand_expectations'})
    report = {'status': 'PASS' if not failures and not leakage else 'FAIL', 'microcases_pass': micro_pass, 'schema_cases': len(dataset), 'rows_replayed': len(rows),
              'candidate_physical_checks': sum(len(d['physical_candidates']) for d in dataset), 'policy_pair_checks': len(pairs),
              'failures': failures, 'leakage_hits': leakage, 'independent_geometry_checker': 'evaluation/geometry_oracle.py', 'independent_load_crosscheck': 'legacy apply_candidate + restore_placed vs V2 reverse-topological propagation',
              'load_facts_reconstructed_without_generator_private_results': True,
              'numeric_replay_comparison': REPLAY_COMPARISON_VERSION, 'numeric_replay_abs_tolerance': REPLAY_ABS_TOL,
              'binding_types_counts_and_na_remain_exact': True}
    if write_reports:
        write_json(root/'validation_report.json', report)
        write_json(root/'replay_report.json', report)
    return report


def budget_before_calls(root, dataset):
    chars = [len(SYSTEM_PROMPT)+len(canonical_json(d['public_request'])) for d in dataset]
    budget = {'planned_methods': ['flash_direct_text'], 'planned_requests': len(dataset), 'replicates': 1,
              'format_repairs': 0, 'retry_policy': 'No automatic retries; resume only missing credentials/not-run records',
              'max_output_tokens_per_call': 512, 'total_input_characters': sum(chars),
              'rough_input_tokens_range': [math.ceil(sum(chars)/4), sum(chars)],
              'token_estimate_method': 'Loose characters/4..characters bound, not model tokenizer or hard bound',
              'estimated_cost': None, 'currency': None, 'reason': 'No verified account rate; unknown is not free',
              'pricing_formula': 'input_tokens/1e6*input_rate + output_tokens/1e6*output_rate; cache pricing requires supplier breakdown',
              'llm_policy_parser_enabled': False, 'visual_enabled': False}
    write_json(root/'metrics/pre_call_budget.json', budget)


def report(root, o0, dataset, rows, validation, summary, pairs, costs):
    split = read_json(root/'data/split_audit.json')
    remote_ran = costs['completed_model_records']
    engineering = 'PASS' if validation['status']=='PASS' and split['status']=='PASS' else 'FAIL'
    claims = {h: {'status': 'not_tested', 'reason': 'outside current pilot scope'} for h in ('H1', 'H2', 'H3', 'H4', 'H5')}
    for h in ('H1', 'H2'):
        claims[h] = {'status': 'inconclusive' if remote_ran else 'not_tested', 'reason': 'Pilot development sample; inspect paired CIs and strongest public baseline; no unseen test claim.'}
    write_json(root/'research_claims.json', claims)
    remote_pair = next((p for p in pairs if p['method']=='flash_direct_text' and p['reference']=='public_parser' and p['field']=='business_hard_satisfied' and p['cluster']=='source_order_key'), None)
    sd = remote_pair.get('cluster_sd') if remote_pair else None
    n = math.ceil(((1.96+.84)*sd/.05)**2) if sd is not None else None
    recommendations = {'status': 'PROPOSED_NOT_FROZEN', 'primary_effect_pp': 5, 'power': .8, 'alpha_two_sided': .05,
         'normal_approx_independent_group_estimate': n,
         'formula': 'ceil((1.96+0.84)^2 * pilot_order_cluster_difference_sd^2 / 0.05^2)',
         'limitations': 'Not binary paired exact power; 10 validation source orders are weak. Confirm via paired simulation on new independent development orders before preregistration; account for multiplicity.',
         'recommended_next_development_orders': 30, 'provisional_formal_independent_orders_range': [60, 150],
         'replicates': 1 if not remote_ran else 3, 'replicate_reason': 'Current within-case variance unmeasured at one call. 3 repeats is exploratory budget scenario, not justified power.',
         'calls_formula': 'orders * states_per_order * 2 policies * remote_methods * repeats',
         'budget_scenarios': [{'orders': k, 'states_per_order': 1, 'policies': 2, 'remote_methods': 1, 'repeats': r, 'calls': k*2*r, 'cost': None}
                              for k in (60, 100, 150) for r in (1, 3)],
         'thresholds': {'fragile_business_load_kg': [1, 3], 'numeric_equivalence_epsilon': 1e-6},
         'test_policy': 'Freeze after independent validation and verified pricing, before any new test observations.',
         'additional_llm_parser_decision': 'DEFERRED: no real Direct-Text numeric-error evidence yet' if not remote_ran else 'Review real case audit before enabling an additional 60-call AST arm.'}
    write_json(root/'formal_test_recommendations.json', recommendations)
    acceptance = {'offline_engineering_status': engineering, 'O0_recompute': o0['status'],
                  'O0_human_signoff': 'PENDING', 'O1_paired_states_status': validation['status'],
                  'O1_30_independent_source_orders': split['independent_orders_30_requirement_met'],
                  'O2_offline_records': sum(r['method']!='flash_direct_text' for r in rows),
                  'O2_remote_status': 'COMPLETE' if remote_ran==60 else 'BLOCKED' if not remote_ran else 'PARTIAL',
                  'model_response_98_percent_gate': costs['valid_response_rate']>=.98 if remote_ran==60 else None,
                  'research_success_required_for_engineering': False, 'research_claims': claims,
                  'blocked_items': ([] if remote_ran==60 else ['Real Flash 60 calls not completed']) +
                      ([] if split['independent_orders_30_requirement_met'] else ['Validation has fewer than 30 independent source orders']) + ['Researcher manual signoff pending']}
    write_json(root/'acceptance_report.json', acceptance)
    lines = ['# 属性感知 V2/pilot 实验报告', '', '版本：'+VERSION+'；开发数据：validation；buffer_size=1；冻结生成器；Top-K=16。', '',
       '## 实际完成与阻碍', '',
       f"- O0 原始复算状态：{o0['status']}；steps={o0.get('events')}，题数={o0.get('unique_cases')}，CSV={o0.get('metric_rows')}。人工签认仍待研究者完成。",
       f"- 离线工程检查：{engineering}；Schema/物理/关系/指标回放详情见 validation_report.json。",
       f"- 生成 {len(dataset)} 题、{split['unique_physical_states']} 个不同物理状态，源订单数={split['unique_source_orders']}。30状态不是30独立订单；主CI按来源订单聚类，30状态CI仅补充。",
       f"- 离线5方法完成 {sum(r['method']!='flash_direct_text' for r in rows)} 行；真实Flash记录={remote_ran}/60，调用尝试={costs['actual_attempts']}。未调用行是阻碍占位，不能作模型失败或性能证据。",
       '- V1目录与源码保留；原utility不更改。旧test仅用于O0回归，没有用于V2构造或阈值选择。',
       '- 语义属性与承载上限为synthetic/derived，不宣称真实损伤保护。',
       '- 公开Parser完整支持本轮公开语法；本轮不评价自由语言/未见组合泛化。',
       '- 所有非特权方法使用同一公开请求；真实候选ID映射、隐藏AST与最优集合仅在private_annotations和评价路径。', '',
       '## 方法结果', '', '|方法|已评测题|硬满足率（分母）|最优等价命中（分母）|政策配对成功（分母）|', '|---|---:|---|---|---|']
    def fmt(v):
        return f"{v['mean']:.4f} ({v['n']})" if v['mean'] is not None else f"N/A ({v['n']})"
    for s in summary:
        lines.append(f"|{s['method']}|{s['evaluated_n']}|{fmt(s['business_hard_satisfied'])}|{fmt(s['oracle_equivalent_hit'])}|{fmt(s['policy_pair_success_rate'])}|")
    lines += ['', '## 证据结论', '',
       '- 工程通过与研究支持分开：离线检查通过不代表Flash优于规则系统。H1/H2无足够远程证据时为not_tested/inconclusive；H3/H4/H5本轮未测试。',
       '- 公开Parser和真值规则一致只能说明本轮受限语法可编程执行，不证明VLM无用，也不能拿该受限语法实验主张语言泛化。',
       '- N/A不算成功；新增违规与原有违规分别记录；无业务可行候选时Parser/真值参考abstain，几何仍提交的业务失败如实保留。',
       '- 配对CI见 metrics/paired_cluster_ci.json；成功/失败实例见 audits/case_audit.csv，规则与事实可从逐题公开/私有记录核对。', '',
       '## 费用与正式测试建议', '',
       '- 调用前预算写入 metrics/pre_call_budget.json；单轮Direct 60请求、1重复、无自动修复/重试。实际费率未知，费用=null，不是0元。',
       '- 正式规模不是已冻结决定：先补至少30个独立开发来源订单；候选正式范围60–150独立来源组，1或3调用重复分别预算；同题一次无法估计模型内方差。',
       f'- 基于真实pilot订单聚类差值方差的正态近似样本建议：{n if n is not None else "N/A，API未调用，不能估计VLM差值方差"}；详细公式与限制见 formal_test_recommendations.json。',
       '- 不在新test后追加样本直到显著；5百分点效应、1e-6同分容差及1/3kg限载仅为开发协议，正式前须单独预注册。', '',
       '## 运行与续跑', '', '```bash',
       'cd /home/cyw/NBU_Papper', 'PYTHONPATH=semantic_pallet_planner/src python -m semantic_pallet_planner.runners.attribute_pilot_v2 --output '+str(root),
       '# 在同一进程环境导出 DEEPSEEK_API_KEY 后，仅续跑60次真实Text：',
       'PYTHONPATH=semantic_pallet_planner/src python -m semantic_pallet_planner.runners.attribute_pilot_v2 --output '+str(root)+' --resume --remote',
       '```', '', '命令日志、测试结果、源码快照与哈希见 checks/ 和 manifest.json。未运行Visual、动态记忆、机器人或900题矩阵。']
    (root/'pilot_report.md').write_text('\n'.join(lines)+'\n')



def fork_replay_compatible_pilot(parent, root):
    """Explicit new version; never replace parent manifest or regenerate its data."""
    if parent == root or parent in root.parents or root in parent.parents:
        raise ValueError('Fork must be a separate sibling directory')
    if any(root.iterdir()):
        raise ValueError('Fork destination must be empty')
    original = read_json(parent/'manifest.json')
    if digest(generator_config(load_config(top_k=16, topk_mode='diverse_v1')))!=original['generator_config_sha256']:
        raise ValueError('Generator configuration changed; this is not a replay-only fork')
    allowed = {
        'semantic_pallet_planner/src/semantic_pallet_planner/runners/attribute_pilot_v2.py',
        'docs/metrics_v2_spec.md',
    }
    drift = [p for p,h in original['source_sha256'].items() if not (WORKSPACE/p).is_file() or sha(WORKSPACE/p)!=h]
    if set(drift)-allowed:
        raise ValueError('Non-replay frozen sources changed: '+str(sorted(set(drift)-allowed)))
    for p,h in original['data_sha256'].items():
        if not (parent/p).is_file() or sha(parent/p)!=h:
            raise ValueError('Frozen parent data changed: '+p)
    shutil.copytree(parent, root, dirs_exist_ok=True)
    # Preserve initial failures and manifest as forensic evidence in the new version.
    write_json(root/'compatibility/parent_manifest.json', original)
    for name in ('validation_report.json', 'replay_report.json'):
        if (parent/name).exists():
            shutil.copyfile(parent/name, root/'compatibility'/('parent_'+name))
    dataset = read_json(root/'data/pilot_dataset.private.json')
    rows = read_json(root/'metrics/per_decision.json')
    checked = validate_and_replay(root, dataset, rows, write_reports=False)
    if checked['status']!='PASS':
        write_json(root/'checks/fork_replay_rejection.json', checked)
        raise ValueError('Parent has real replay discrepancies; compatibility fork rejected')
    files = (sorted((WORKSPACE/'semantic_pallet_planner/src').rglob('*.py'))
             + sorted((WORKSPACE/'semantic_pallet_planner/src').rglob('*.json'))
             + sorted((WORKSPACE/'semantic_pallet_planner/tests').rglob('*.py')) + [WORKSPACE/'docs/metrics_v2_spec.md'])
    frozen = {str(p.relative_to(WORKSPACE)):sha(p) for p in files}
    for p in files:
        dest = root/'code_snapshot'/p.relative_to(WORKSPACE)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
    manifest = copy.deepcopy(original)
    manifest.update(source_sha256=frozen, numeric_replay_comparison=REPLAY_COMPARISON_VERSION,
                    numeric_replay_abs_tolerance=REPLAY_ABS_TOL, created_time_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                    parent_pilot_directory=str(parent), parent_manifest_sha256=sha(parent/'manifest.json'),
                    preserved_input_record_sha256=sha(parent/'metrics/per_decision.json'),
                    replay_compatibility_source_changes=drift,
                    data_and_semantic_policy_unchanged=True)
    shutil.copyfile(WORKSPACE/'docs/metrics_v2_spec.md',root/'metrics_v2_spec.md')
    manifest['metrics_spec_sha256']=sha(root/'metrics_v2_spec.md')
    write_json(root/'manifest.json',manifest)
    write_json(root/'compatibility/migration.json',{'parent':str(parent),'destination':str(root),
        'reason':'Python 3.11/3.13 float roundoff, absolute tolerance 1e-9 for finite computed floats only',
        'preserved_data_file_count':len(original['data_sha256']),'initial_decision_records_unchanged':True,
        'new_model_calls_during_migration':0,'prior_replay_checked':checked['status']})
    return dataset, read_json(root/'o0/verification.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--remote', action='store_true')
    parser.add_argument('--fork-from', help='Preserve frozen pilot data/results in a new directory after a replay-only compatibility fix')
    args = parser.parse_args(argv)
    if args.fork_from and args.resume:
        parser.error('--fork-from and --resume cannot be combined')
    root = Path(args.output).resolve()
    if any(part.startswith('EXP_1C_') for part in root.parts):
        raise ValueError('Never write EXP_1C_*')
    if root.exists() and not args.resume:
        raise ValueError('Output exists; explicit --resume required')
    root.mkdir(parents=True, exist_ok=True)
    repo = DatasetRepository(WORKSPACE/'semantic_pallet_dataset_v1')
    cfg = generator_config(load_config(top_k=16, topk_mode='diverse_v1'))
    if args.fork_from:
        dataset, o0 = fork_replay_compatible_pilot(Path(args.fork_from).resolve(), root)
    elif args.resume:
        manifest = read_json(root/'manifest.json')
        if digest(cfg)!=manifest['generator_config_sha256']:
            raise ValueError('Frozen generator configuration changed')
        mismatches = [p for p, h in manifest['source_sha256'].items() if sha(WORKSPACE/p)!=h]
        if mismatches:
            raise ValueError('Frozen source changed: '+str(mismatches))
        data_mismatches = [p for p, h in manifest['data_sha256'].items() if sha(root/p)!=h]
        if data_mismatches:
            raise ValueError('Frozen data changed: '+str(data_mismatches))
        dataset = read_json(root/'data/pilot_dataset.private.json')
        o0 = read_json(root/'o0/verification.json')
    else:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=WORKSPACE, text=True).strip()
        files = (sorted((WORKSPACE/'semantic_pallet_planner/src').rglob('*.py'))+sorted((WORKSPACE/'semantic_pallet_planner/src').rglob('*.json'))
                 + sorted((WORKSPACE/'semantic_pallet_planner/tests').rglob('*.py')) + [WORKSPACE/'docs/metrics_v2_spec.md'])
        checksums = {str(p.relative_to(WORKSPACE)): sha(p) for p in files}
        write_json(root/'manifest.json', {'schema_version': VERSION, 'git_parent_commit': commit, 'dirty_source_sha256_is_authoritative': True,
                   'source_sha256': checksums, 'generator_config_sha256': digest(cfg), 'generator_config': cfg,
                   'remote_model': 'deepseek-flash', 'seed': 20260928, 'data_version': 'V2/pilot', 'created_time_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        for p in files:
            dest = root/'code_snapshot'/p.relative_to(WORKSPACE)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
        o0 = diagnose_v1(root, repo)
        dataset = build_pilot(root, repo, cfg)
        budget_before_calls(root, dataset)
        from .pilot_micro_v2 import microcases, verify_micro
        micro = microcases()
        write_json(root/'data/microcases.hand_expected.json', micro)
        write_json(root/'checks/microcases_report.json', [verify_micro(m) for m in micro])
        shutil.copyfile(WORKSPACE/'docs/metrics_v2_spec.md', root/'metrics_v2_spec.md')
        manifest = read_json(root/'manifest.json')
        manifest['data_sha256'] = {str(p.relative_to(root)): sha(p) for p in sorted((root/'data').rglob('*.json'))}
        manifest['metrics_spec_sha256'] = sha(root/'metrics_v2_spec.md')
        write_json(root/'manifest.json', manifest)
    if (args.resume or args.fork_from) and (root/'metrics/per_decision.json').exists():
        prior = validate_and_replay(root, dataset, read_json(root/'metrics/per_decision.json'), write_reports=False)
        write_json(root/'checks/preflight_replay.json', prior)
        if prior['status']!='PASS':
            raise ValueError('Existing records fail replay; refusing paid continuation; see checks/preflight_replay.json')
    rows = run_methods(root, dataset, remote=args.remote)
    summary, pairs, costs = summarize(root, dataset, rows)
    validation = validate_and_replay(root, dataset, rows)
    old = WORKSPACE/'semantic_pallet_planner/outputs/EXP_1C_DEEPSEEK_FLASH_FINAL_V1'
    before_file = root/'o0/v1_files.before.json'
    if before_file.exists():
        after = v1_inventory(old)
        before = read_json(before_file)
        write_json(root/'o0/v1_preservation.json', {'status': 'PASS' if before==after else 'FAIL', 'file_count': len(before),
                   'changed_files': [p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)]})
    report(root, o0, dataset, rows, validation, summary, pairs, costs)
    print(json.dumps({'output': str(root), 'O0': o0['status'], 'validation': validation['status'], 'real_flash_records': costs['completed_model_records']}, ensure_ascii=False))


if __name__=='__main__':
    main()
