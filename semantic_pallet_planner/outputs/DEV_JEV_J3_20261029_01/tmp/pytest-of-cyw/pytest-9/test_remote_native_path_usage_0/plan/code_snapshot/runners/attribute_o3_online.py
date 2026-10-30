"""O3 online attribute episodes. New outputs only; no V1/O2b mutation."""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator

from ..config import WORKSPACE, generator_config, load_config
from ..domain import PalletState
from ..evaluation.attribute_metrics_v2 import raw_metrics, reconstruct, public_relations
from ..evaluation.geometry_oracle import check_candidate
from ..evaluation.policy_o1b import resolve
from ..evaluation.policy_v2 import evaluate, optimal_set, priority_regret, violations
from ..evaluation.replay_values_v2 import replay_values_equal, REPLAY_COMPARISON_VERSION
from ..evaluation.state import apply_candidate, state_metrics
from ..planner.generator import ExtremePointGenerator
from ..protocol import canonical_json, state_hash
from ..repository import DatasetRepository, ALL_SPLITS
from ..selectors.instruction_parser_o1b import canonical_text, parse_o1b_instruction, policy, resolved_public_policy
from ..selectors.policy_executor_v2 import execute_policy, fixed_attribute, geometry
from ..vlm.deepseek_client import DeepSeekClient
from ..vlm.pilot_protocol_v2 import digest, scan_public
from ..vlm.policy_protocol_o2b import PROMPT_VERSION, model_request, parse_policy_response
from .attribute_pilot_v2 import enumerate_physical, read_json, sha, write_csv, write_json
from .o3_online_adapter import candidate_diagnostics, public_request, screen

VERSION = 'attribute_o3_online_pilot_2'
EXECUTION_MODES = ('safe', 'observe_business')
METHODS = ('geometry_greedy', 'fixed_attribute', 'public_parser',
           'flash_policy_parser', 'truth_ast_executor')
OFFLINE = tuple(m for m in METHODS if m != 'flash_policy_parser')
SOURCE = WORKSPACE/'semantic_pallet_planner/src/semantic_pallet_planner'
FROZEN = (
    'runners/attribute_o3_online.py', 'runners/o3_online_adapter.py',
    'planner/generator.py', 'planner/constraints.py', 'planner/scoring.py',
    'evaluation/attribute_metrics_v2.py', 'evaluation/policy_v2.py',
    'evaluation/geometry_oracle.py', 'evaluation/state.py',
    'evaluation/replay_values_v2.py',
    'selectors/instruction_parser_o1b.py', 'selectors/policy_executor_v2.py',
    'vlm/policy_protocol_o2b.py', 'vlm/pilot_protocol_v2.py', 'vlm/deepseek_client.py',
    'visualization/o3_animation.py',
    'schemas/o3_request.schema.json',
)


def source_key(repo, scenario_id):
    record = read_json(repo.root/'annotations/ground_truth_rules'/f'{scenario_id}.json')
    return str(record.get('source_order_key', record.get('source_order_id', scenario_id)))


def task_plan(repo, split, limit_orders):
    if split not in ('train', 'validation'):
        raise ValueError('O3 pilot may use train or validation only')
    ids = repo.list_scenarios(split)
    if split == 'train':
        # O1b used the final thirty sorted train orders; this is an explicitly
        # seen development subset, not fresh validation evidence.
        ids = ids[20:]
    if limit_orders is not None:
        if limit_orders < 1:
            raise ValueError('limit_orders must be positive')
        ids = ids[:limit_orders]
    pairs = (
        policy(1., ('heavy_low', 'heavy_center'), True),
        policy(3., ('heavy_center', 'heavy_low'), True),
    )
    tasks = []
    for sid in ids:
        scenario = repo.get_scenario(sid)
        if scenario['buffer_size'] != 1:
            raise ValueError('buffer_size must be 1')
        for index, ast in enumerate(pairs):
            tasks.append({'episode_id': f'O3_{sid}_P{index}', 'scenario_id': sid,
                          'source_order_key': source_key(repo, sid), 'source_split': split,
                          'policy_id': f'P{index}', 'instruction_text': canonical_text(ast),
                          'truth_policy': ast, 'attribute_source': 'synthetic'})
    keys = [source_key(repo, sid) for sid in ids]
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate source order within O3 split')
    other = {source_key(repo, sid) for s in ALL_SPLITS if s != split
             for sid in repo.list_scenarios(s)}
    if set(keys) & other:
        raise ValueError('source order crosses dataset splits')
    return tasks, {'split': split, 'independent_source_orders': len(keys),
                   'source_keys': keys, 'cross_split_overlap': [], 'policies_per_order': 2,
                   'role': 'seen_train_development' if split == 'train' else 'validation_development',
                   'unseen_test_evidence': False}


def step_state(scenario, task, placed, index):
    available = [] if index == len(scenario['arrival_order']) else [
        next(x for x in scenario['items'] if x['item_id'] == scenario['arrival_order'][index])]
    return {'container': copy.deepcopy(scenario['container']), 'placed_items': copy.deepcopy(placed),
            'available_items': copy.deepcopy(available), 'step_index': index,
            'request_id': f"{task['episode_id']}_STEP_{index:03d}",
            'instruction_text': task['instruction_text']}


def snapshot(root, cfg, tasks, source_audit, methods, repo, execution_mode):
    if root.exists():
        raise FileExistsError('O3 output already exists; choose a new directory')
    root.mkdir(parents=True)
    source_hash = {n: sha(SOURCE/n) for n in FROZEN}
    for name in FROZEN:
        destination = root/'code_snapshot'/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE/name, destination)
    used = {t['scenario_id'] for t in tasks}
    dataset_hash = {str(Path('tasks/scenarios')/f'{sid}.json'):
                    sha(repo.root/'tasks/scenarios'/f'{sid}.json') for sid in sorted(used)}
    manifest = {'version': VERSION, 'git_parent_commit': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=WORKSPACE, text=True).strip(),
        'dirty_source_sha256_is_authoritative': True, 'source_sha256': source_hash,
        'dataset_sha256': dataset_hash, 'dataset_root': str(repo.root),
        'methods': methods, 'planned_episodes': len(tasks)*len(methods),
        'top_k': 16, 'buffer_size': 1, 'seed': cfg['seed'],
        'generator': 'extreme_point_ems_style/diverse_v1',
        'prompt_version': PROMPT_VERSION, 'max_repair_calls': 1,
        'fallback_policy': 'abort', 'cost_tracking': False,
        'remote_status': 'enabled' if 'flash_policy_parser' in methods else 'not_run',
        'execution_mode': execution_mode,
        'replay_comparison': REPLAY_COMPARISON_VERSION,
        'business_infeasible_policy': (
            'executor_min_incremental_then_post_violations_then_soft_then_geometry_then_label'
            if execution_mode == 'observe_business' else 'abort'),
        'fixed_attribute_fallback': 'existing_fixed_policy_min_post_violations_then_soft_then_geometry_then_label'}
    write_json(root/'manifest.json', manifest)
    write_json(root/'config.snapshot.json', cfg)
    write_json(root/'data/tasks.private.json', tasks)
    write_json(root/'data/source_split_audit.json', source_audit)


def load_resume(root, cfg, tasks, methods, repo, execution_mode):
    manifest = read_json(root/'manifest.json')
    if (manifest['version'] != VERSION or manifest['methods'] != methods or
            manifest['seed'] != cfg['seed'] or manifest.get('execution_mode') != execution_mode):
        raise ValueError('O3 resume configuration mismatch')
    if read_json(root/'data/tasks.private.json') != tasks:
        raise ValueError('O3 task plan drift')
    for n, h in manifest['source_sha256'].items():
        if sha(SOURCE/n) != h or sha(root/'code_snapshot'/n) != h:
            raise ValueError('O3 source drift: '+n)
    for n, h in manifest['dataset_sha256'].items():
        if sha(repo.root/n) != h:
            raise ValueError('O3 dataset drift: '+n)
    old = replay_all(root, tasks, methods, repo, cfg, complete=False,
                     execution_mode=execution_mode)
    if old['status'] != 'PASS':
        raise ValueError('Existing O3 records fail replay: '+str(old['failures'][:5]))


def invoke_flash(root, req, mapping, client, *, allow_business_violation=False):
    folder = root/'selector_inputs'/'flash_policy_parser'/req['request_id']
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder/'public_request.json', req)
    private_ids = [c['candidate_id'] for c in mapping.values()]
    attempts, parsed = [], None
    repair_error = None
    for name in ('initial_response', 'repair_response'):
        if name == 'repair_response' and repair_error is None:
            break
        try:
            prompt = model_request(req, repair_error=repair_error, private_strings=private_ids)
            write_json(folder/(name+'.prompt.json'), {'system_prompt': prompt.system_prompt,
                       'user_text': prompt.user_text, 'request_sha256': digest(req)})
            response = client.complete(prompt)
            write_json(folder/(name+'.raw.json'), {k: v for k, v in response.as_dict().items()
                                                   if k != 'estimated_cost'})
            parsed = parse_policy_response(response.raw_text, req)
            write_json(folder/(name+'.parsed.json'), parsed)
            attempts.append({'name': name, 'valid': True, 'input_tokens': response.input_tokens,
                             'output_tokens': response.output_tokens, 'latency_s': response.latency_s})
            break
        except Exception as exc:
            category = getattr(exc, 'category', 'invalid_response')
            code = getattr(exc, 'code', type(exc).__name__)
            attempts.append({'name': name, 'valid': False, 'category': category, 'code': code})
            write_json(folder/(name+'.error.json'), {'category': category, 'code': code,
                                                      'exception_type': type(exc).__name__})
            repair_error = code if category == 'invalid_response' or hasattr(exc, 'code') else None
    trace = {'attempts': attempts, 'initial_api_valid': bool(attempts and attempts[0]['valid']),
             'final_api_valid': parsed is not None, 'repair_count': max(0, len(attempts)-1)}
    write_json(folder/'attempts.json', trace)
    if parsed is None:
        category = attempts[-1].get('category', 'provider_error')
        return None, None, ('invalid_response' if category == 'invalid_response' else 'provider_error'), trace
    ast = parsed['policy_ast']
    resolved = resolve(ast, req) if ast['schema_version'] == 'pallet_policy_o1b_conditional_1' else ast
    return execute_policy(req, resolved,
                          allow_business_violation=allow_business_violation), ast, None, trace


def select(req, method, truth_policy, root, mapping, client,
           *, allow_business_violation=False):
    if method == 'geometry_greedy': return geometry(req), None, None, {}
    if method == 'fixed_attribute': return fixed_attribute(req), None, None, {}
    if method == 'public_parser':
        ast = parse_o1b_instruction(req['instruction_text'])
        return execute_policy(req, resolved_public_policy(req['instruction_text'], req),
                              allow_business_violation=allow_business_violation), ast, None, {}
    if method == 'truth_ast_executor':
        return execute_policy(req, truth_policy,
                              allow_business_violation=allow_business_violation), truth_policy, None, {'privileged_input': True}
    if method == 'flash_policy_parser':
        return invoke_flash(root, req, mapping, client,
                            allow_business_violation=allow_business_violation)
    raise ValueError('unknown method')


def run_episode(root, task, method, repo, gen, cfg, client=None,
                *, execution_mode='safe'):
    if execution_mode not in EXECUTION_MODES:
        raise ValueError('unknown O3 execution mode')
    scenario = repo.get_scenario(task['scenario_id'])
    place, events, reason = [], [], None
    directory = root/'episodes'/method/task['episode_id']
    directory.mkdir(parents=True, exist_ok=False)
    validator = Draft202012Validator(read_json(SOURCE/'schemas/o3_request.schema.json'))
    for index in range(len(scenario['arrival_order'])):
        before = step_state(scenario, task, place, index)
        generated = gen.generate(PalletState.from_dict(before))
        candidates = generated.candidate_set.data['candidates']
        if generated.candidate_set.data['physical_state_hash'] != state_hash(before['container'], before):
            raise ValueError('candidate state binding mismatch')
        req, mapping, scan = public_request(before, candidates, task['instruction_text'], seed=cfg['seed'])
        validator.validate(req)
        if scan['status'] != 'PASS': raise ValueError('public leakage')
        public_evals, truth_evals, optimum = candidate_diagnostics(req, task['truth_policy'])
        public_optimum = optimal_set(public_evals)
        enumeration = None
        if not public_optimum['feasible_indices']:
            full = enumerate_physical(before, generator_config(cfg))
            full_evaluations = [evaluate(before, c, task['truth_policy'], scenario['container']) for c in full]
            enumeration = {'physical_count': len(full),
                           'business_feasible_count': len(optimal_set(full_evaluations)['feasible_indices'])}
        step_folder = directory/'selector_inputs'/req['request_id']
        step_folder.mkdir(parents=True)
        write_json(step_folder/'public_request.json', req)
        write_json(step_folder/'mapping.private.json', {label: candidate['candidate_id'] for label,candidate in mapping.items()})
        proposed = ast = status = None
        trace = {}
        if not candidates:
            status = 'no_physical_candidate'
        elif execution_mode == 'safe' and not public_optimum['feasible_indices']:
            status = 'no_business_feasible_candidate'
        else:
            try:
                proposed, ast, status, trace = select(
                    req, method, task['truth_policy'], root, mapping, client,
                    allow_business_violation=execution_mode == 'observe_business')
            except ValueError:
                status = 'policy_parse_error'
            except Exception:
                status = 'internal_error'
        committed = None; blocked = False; would_block = False
        if status is None:
            screened, would_block, screen_status = screen(req, proposed, public_evals)
            if execution_mode == 'safe':
                committed, blocked, status = screened, would_block, screen_status
            elif proposed is not None and proposed in {c['display_label'] for c in req['candidates']}:
                committed = proposed
            else:
                status = screen_status
        status = status or 'select'
        labels = {c['display_label']: i for i,c in enumerate(req['candidates'])}
        raw = truth_evals[labels[proposed]] if proposed in labels else None
        physical_errors = []
        if committed is not None:
            physical_errors = check_candidate(req, {'container': scenario['container']}, mapping[committed])
            if physical_errors:
                committed = None; status = 'physical_rejection'
            else:
                place = apply_candidate(before, mapping[committed])
        after = step_state(scenario, task, place, index+1)
        if committed is not None and index == len(scenario['arrival_order'])-1:
            status = 'all_items_placed'
        elif committed is not None:
            status = 'select'
        raw_before = raw_metrics(reconstruct(before['placed_items']))
        raw_after = raw_metrics(reconstruct(place))
        rel = public_relations(before, mapping[committed]) if committed else None
        event = {'episode_id': task['episode_id'], 'method': method, 'step_index': index,
                 'request_id': req['request_id'], 'state_hash': req['state_hash'],
                 'policy_digest': req['policy_digest'],
                 'candidate_set_digest': digest(req['candidates']),
                 'mapping_digest': digest({label: c['candidate_id'] for label,c in mapping.items()}),
                 'before_state_hash': state_hash(before['container'], before),
                 'after_state_hash': state_hash(after['container'], after) if committed else req['state_hash'],
                 'current_item_id': before['available_items'][0]['item_id'],
                 'candidate_count': len(candidates), 'topk_feasible_count': len(optimum['feasible_indices']),
                 'public_topk_feasible_count': len(public_optimum['feasible_indices']),
                 'proposed_label': proposed, 'committed_label': committed,
                 'screen_intervened': blocked, 'would_screen_block': would_block,
                 'diagnostic_continuation': bool(execution_mode == 'observe_business'
                                                and committed and not public_optimum['feasible_indices']),
                 'execution_mode': execution_mode, 'status': status,
                 'raw_avoidable_hard_wrong': bool(raw['after_violation_instances']) if raw and raw['business_hard_applicable'] and optimum['feasible_indices'] else None,
                 'raw_optimal_hit': proposed in [req['candidates'][i]['display_label'] for i in optimum['equivalent_indices']] if raw and optimum['feasible_indices'] else None,
                 'raw_priority_regret': priority_regret(raw, optimum) if raw and optimum['feasible_indices'] else None,
                 'raw_new_business_violations': raw['new_business_violation_count'] if raw else None,
                 'raw_worsened_business_violations': raw['worsened_existing_violation_count'] if raw else None,
                 'raw_post_business_violations': raw['post_business_violation_count'] if raw else None,
                 'physical_violations': len(physical_errors), 'attribute_before': raw_before,
                 'attribute_after': raw_after, 'attribute_delta': rel['delta'] if rel else None,
                 'before_placed': before['placed_items'], 'after_placed': copy.deepcopy(place),
                 'parsed_ast': ast, 'trace': trace,
                 'generation_audit': generated.audit.data, 'full_enumeration_diagnostic': enumeration,
                 'coverage_category': ('topk_lost_feasible' if enumeration and enumeration['business_feasible_count'] else
                                       'enumeration_no_feasible' if enumeration else 'topk_feasible')}
        events.append(event)
        if committed is None or status == 'all_items_placed':
            reason = status; break
    if reason is None: reason = 'internal_error'
    final_violations, applicability = violations(reconstruct(place), task['truth_policy'])
    requested = len(scenario['arrival_order'])
    violating_steps = sum(bool(e['committed_label']) and
                          bool((e['raw_new_business_violations'] or 0) +
                               (e['raw_worsened_business_violations'] or 0)) for e in events)
    summary = {'episode_id': task['episode_id'], 'scenario_id': task['scenario_id'],
               'source_order_key': task['source_order_key'], 'policy_id': task['policy_id'],
               'method': method, 'planned_items': requested, 'placed_items': len(place),
               'termination_reason': reason, 'completed': reason == 'all_items_placed',
               'episode_attribute_success': reason == 'all_items_placed' and not final_violations,
               'placed_item_ratio': len(place)/requested,
               'placed_volume_ratio': sum(math.prod(x['oriented_size_mm']) for x in place)/
                   sum(math.prod([x['dimensions_mm'][k] for k in ('length','width','height')]) for x in scenario['items']),
               'final_business_violation_count': len(final_violations),
               'final_business_violation_ids': final_violations,
               'execution_mode': execution_mode,
               'committed_business_violation_steps': violating_steps,
               'business_violation_step_rate': violating_steps/len(place) if place else None,
               'new_business_violation_instances_total': sum(
                   e['raw_new_business_violations'] or 0 for e in events if e['committed_label']),
               'worsened_business_violation_instances_total': sum(
                   e['raw_worsened_business_violations'] or 0 for e in events if e['committed_label']),
               'ever_business_violation': violating_steps > 0,
               'completed_with_business_violation': reason == 'all_items_placed' and bool(final_violations),
               'final_attribute_metrics': raw_metrics(reconstruct(place)),
               'final_geometry_metrics': state_metrics(scenario['container'], place),
               'screen_interventions': sum(e['screen_intervened'] for e in events),
               'committed_physical_violations': sum(e['physical_violations'] for e in events),
               'steps': len(events), 'remote_attempts': sum(len(e['trace'].get('attempts', [])) for e in events),
               'privileged_input': method == 'truth_ast_executor'}
    write_json(directory/'episode.json', {'schema_version': 'pallet_o3_episode_1',
               'task': task, 'method': method, 'summary': summary, 'final_placed': place,
               'core_result_sha256': digest(events)})
    (directory/'steps.jsonl').write_text(''.join(canonical_json(e)+'\n' for e in events))
    return summary, events


def replay_all(root, tasks, methods, repo, cfg, *, complete=True,
               execution_mode=None):
    """Regenerate physical candidates and recompute every committed transition."""
    manifest_path = root/'manifest.json'
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    legacy = manifest.get('version') == 'attribute_o3_online_pilot_1'
    if execution_mode is None:
        execution_mode = manifest.get('execution_mode', 'safe')
    gen = ExtremePointGenerator(generator_config(cfg))
    failures = []; count = 0
    for task in tasks:
        scenario = repo.get_scenario(task['scenario_id'])
        for method in methods:
            directory = root/'episodes'/method/task['episode_id']
            if not directory.exists():
                if complete: failures.append(f"{method}/{task['episode_id']}:missing")
                continue
            count += 1
            result = read_json(directory/'episode.json')
            events = [json.loads(x) for x in (directory/'steps.jsonl').read_text().splitlines() if x]
            if result['core_result_sha256'] != digest(events) or not events:
                failures.append(f"{method}/{task['episode_id']}:event_digest"); continue
            placed = []
            for index, event in enumerate(events):
                prefix = f"{method}/{task['episode_id']}/step{index}"
                if event['step_index'] != index or event['before_placed'] != placed:
                    failures.append(prefix+':before'); break
                before = step_state(scenario, task, placed, index)
                generated = gen.generate(PalletState.from_dict(before))
                cset = generated.candidate_set.data['candidates']
                req, mapping, scan = public_request(before, cset, task['instruction_text'], seed=cfg['seed'])
                stored = read_json(directory/'selector_inputs'/req['request_id']/'public_request.json')
                if not replay_values_equal(stored, req) or scan['status'] != 'PASS':
                    failures.append(prefix+':public_request')
                if any(event[k] != value for k,value in {
                        'state_hash': req['state_hash'], 'policy_digest': req['policy_digest'],
                        # The exact digest binds the actual recorded input;
                        # regenerated numeric facts may differ by <1e-9 across
                        # Python math implementations, checked above separately.
                        'candidate_set_digest': digest(stored['candidates']),
                        'mapping_digest': digest({label:c['candidate_id'] for label,c in mapping.items()})}.items()):
                    failures.append(prefix+':binding')
                public_eval, truth_eval, opt = candidate_diagnostics(req, task['truth_policy'])
                if not optimal_set(public_eval)['feasible_indices']:
                    full = enumerate_physical(before, generator_config(cfg))
                    all_eval = [evaluate(before, c, task['truth_policy'], scenario['container']) for c in full]
                    enumeration = {'physical_count': len(full),
                                   'business_feasible_count': len(optimal_set(all_eval)['feasible_indices'])}
                    category = 'topk_lost_feasible' if enumeration['business_feasible_count'] else 'enumeration_no_feasible'
                else:
                    enumeration = None; category = 'topk_feasible'
                if event['coverage_category'] != category or event['full_enumeration_diagnostic'] != enumeration:
                    failures.append(prefix+':coverage')
                labels = {c['display_label']: i for i,c in enumerate(req['candidates'])}
                proposal = event['proposed_label']; committed = event['committed_label']
                if proposal is not None and proposal not in labels: failures.append(prefix+':invalid_proposal')
                if method in OFFLINE and proposal is not None:
                    expected, _, _, _ = select(
                        req, method, task['truth_policy'], root, mapping, None,
                        allow_business_violation=execution_mode == 'observe_business')
                    if proposal != expected: failures.append(prefix+':selector')
                if method == 'flash_policy_parser' and proposal is not None:
                    remote_folder = root/'selector_inputs'/method/req['request_id']
                    trace = read_json(remote_folder/'attempts.json')
                    name = 'repair_response' if trace['repair_count'] else 'initial_response'
                    raw = read_json(remote_folder/(name+'.raw.json'))['raw_text']
                    parsed = parse_policy_response(raw, req)
                    ast = parsed['policy_ast']
                    resolved = resolve(ast, req) if ast['schema_version']=='pallet_policy_o1b_conditional_1' else ast
                    if (event['parsed_ast'] != ast or proposal != execute_policy(
                            req, resolved,
                            allow_business_violation=execution_mode == 'observe_business')):
                        failures.append(prefix+':remote_choice')
                screen_label, blocked, screen_reason = screen(req, proposal, public_eval)
                if event.get('execution_mode', 'safe') != execution_mode or event.get('would_screen_block', blocked) != blocked:
                    failures.append(prefix+':mode_or_screen_diagnostic')
                if execution_mode == 'safe':
                    if committed and (committed != screen_label or blocked): failures.append(prefix+':screen')
                    if event['screen_intervened'] != blocked: failures.append(prefix+':screen_flag')
                    if blocked and event['status'] != 'screen_abstain': failures.append(prefix+':screen_status')
                    if cset and not optimal_set(public_eval)['feasible_indices'] and event['status'] != 'no_business_feasible_candidate':
                        failures.append(prefix+':empty_business')
                else:
                    if event['screen_intervened'] or event['status'] in ('screen_abstain','no_business_feasible_candidate'):
                        failures.append(prefix+':business_screen_active')
                    if proposal is not None and proposal in labels and committed != proposal:
                        failures.append(prefix+':proposal_not_committed')
                if (not committed and proposal is not None and not blocked and
                        event['status'] not in ('physical_rejection','provider_error','invalid_response')):
                    failures.append(prefix+':uncommitted_valid_proposal')
                if not cset and event['status'] != 'no_physical_candidate': failures.append(prefix+':empty_candidates')
                if committed:
                    physical = check_candidate(req, {'container': scenario['container']}, mapping[committed])
                    if physical: failures.append(prefix+':physical')
                    placed = apply_candidate(before, mapping[committed])
                if event['after_placed'] != placed: failures.append(prefix+':after')
                raw = truth_eval[labels[proposal]] if proposal in labels else None
                for field, value in {'topk_feasible_count': len(opt['feasible_indices']),
                                     'candidate_count': len(cset),
                                     'raw_new_business_violations': raw['new_business_violation_count'] if raw else None,
                                     'raw_worsened_business_violations': raw['worsened_existing_violation_count'] if raw else None,
                                     'raw_post_business_violations': raw['post_business_violation_count'] if raw else None,
                                     'raw_avoidable_hard_wrong': bool(raw['after_violation_instances']) if raw and raw['business_hard_applicable'] and opt['feasible_indices'] else None,
                                     'raw_optimal_hit': proposal in [req['candidates'][i]['display_label'] for i in opt['equivalent_indices']] if raw and opt['feasible_indices'] else None,
                                     'raw_priority_regret': priority_regret(raw, opt) if raw and opt['feasible_indices'] else None,
                                     'attribute_before': raw_metrics(reconstruct(before['placed_items'])),
                                     'attribute_after': raw_metrics(reconstruct(placed))}.items():
                    if legacy and field == 'raw_worsened_business_violations' and field not in event:
                        continue
                    if not replay_values_equal(event[field], value): failures.append(prefix+':'+field)
                if not legacy and event.get('diagnostic_continuation') != bool(
                        execution_mode == 'observe_business' and committed and
                        not optimal_set(public_eval)['feasible_indices']):
                    failures.append(prefix+':diagnostic_continuation')
                expected_delta = public_relations(before, mapping[committed])['delta'] if committed else None
                if not replay_values_equal(event['attribute_delta'], expected_delta): failures.append(prefix+':attribute_delta')
                after_hash = state_hash(before['container'], step_state(scenario, task, placed,
                                       index+1)) if committed else req['state_hash']
                if event['after_state_hash'] != after_hash: failures.append(prefix+':after_hash')
                if committed is None and index != len(events)-1: failures.append(prefix+':continued_after_stop')
            summary = result['summary']
            if result['final_placed'] != placed or summary['placed_items'] != len(placed) or summary['steps'] != len(events):
                failures.append(f"{method}/{task['episode_id']}:final_state")
            final_violations, _ = violations(reconstruct(placed), task['truth_policy'])
            expected_success = summary['termination_reason']=='all_items_placed' and not final_violations
            violating_steps = sum(bool(e['committed_label']) and
                                  bool((e['raw_new_business_violations'] or 0) +
                                       (e.get('raw_worsened_business_violations') or 0)) for e in events)
            if (summary['episode_attribute_success'] != expected_success or summary['termination_reason'] != events[-1]['status']
                    or summary['completed'] != (len(placed)==len(scenario['arrival_order']))
                    or summary.get('execution_mode', 'safe') != execution_mode
                    or summary.get('final_business_violation_count') != len(final_violations)):
                failures.append(f"{method}/{task['episode_id']}:final_metrics")
            if not legacy and (summary.get('committed_business_violation_steps') != violating_steps
                    or summary.get('business_violation_step_rate') != (violating_steps/len(placed) if placed else None)
                    or summary.get('ever_business_violation') != (violating_steps > 0)
                    or summary.get('final_business_violation_ids') != final_violations
                    or summary.get('new_business_violation_instances_total') != sum(
                        e['raw_new_business_violations'] or 0 for e in events if e['committed_label'])
                    or summary.get('worsened_business_violation_instances_total') != sum(
                        e['raw_worsened_business_violations'] or 0 for e in events if e['committed_label'])
                    or summary.get('completed_with_business_violation') !=
                       (summary['completed'] and bool(final_violations))):
                failures.append(f"{method}/{task['episode_id']}:business_violation_metrics")
    report = {'status': 'PASS' if not failures else 'FAIL', 'episodes_replayed': count,
              'expected_episodes': len(tasks)*len(methods), 'failures': failures}
    if complete: write_json(root/'replay_report.json', report)
    return report


def report_metrics(root, tasks, methods):
    summaries, steps = [], []
    for task in tasks:
        for method in methods:
            folder = root/'episodes'/method/task['episode_id']
            if not folder.exists(): continue
            summaries.append(read_json(folder/'episode.json')['summary'])
            steps.extend(json.loads(x) for x in (folder/'steps.jsonl').read_text().splitlines() if x)
    write_csv(root/'metrics/per_episode.csv', summaries)
    write_csv(root/'metrics/per_step.csv', steps)
    by = defaultdict(list)
    for row in summaries: by[row['method']].append(row)
    aggregate = {m: {'episodes': len(rows), 'attribute_success': sum(x['episode_attribute_success'] for x in rows),
                     'completed': sum(x['completed'] for x in rows),
                     'episode_completion_rate': sum(x['completed'] for x in rows)/len(rows),
                     'clean_completion_rate': sum(x['episode_attribute_success'] for x in rows)/len(rows),
                     'mean_placed_item_ratio': sum(x['placed_item_ratio'] for x in rows)/len(rows),
                     'mean_placed_volume_ratio': sum(x['placed_volume_ratio'] for x in rows)/len(rows),
                     'mean_episode_business_violation_step_rate': (
                         sum(x['business_violation_step_rate'] for x in rows if x['business_violation_step_rate'] is not None)/
                         sum(x['business_violation_step_rate'] is not None for x in rows)
                         if any(x['business_violation_step_rate'] is not None for x in rows) else None),
                     'orders_with_any_business_violation': sum(x['ever_business_violation'] for x in rows),
                     'completed_with_business_violation': sum(x['completed_with_business_violation'] for x in rows),
                     'completed_order_business_violation_rate': (
                         sum(x['completed_with_business_violation'] for x in rows)/
                         sum(x['completed'] for x in rows)) if any(x['completed'] for x in rows) else None,
                     'all_attempt_business_violation_rate': sum(x['ever_business_violation'] for x in rows)/len(rows),
                     'committed_business_violation_step_rate': (
                         sum(x['committed_business_violation_steps'] for x in rows)/
                         sum(x['placed_items'] for x in rows)) if any(x['placed_items'] for x in rows) else None,
                     'final_business_violation_instances': sum(x['final_business_violation_count'] for x in rows),
                     'screen_interventions': sum(x['screen_interventions'] for x in rows),
                     'termination_reasons': dict(Counter(x['termination_reason'] for x in rows))}
                 for m,rows in by.items()}
    write_json(root/'metrics/summary.json', aggregate)
    write_json(root/'metrics/coverage.json', {'steps': len(steps),
               'with_business_feasible_topk': sum(bool(x['topk_feasible_count']) for x in steps),
               'without_business_feasible_topk': sum(not x['topk_feasible_count'] for x in steps),
               'no_physical_candidate': sum(x['status']=='no_physical_candidate' for x in steps),
               'topk_lost_feasible': sum(x['coverage_category']=='topk_lost_feasible' for x in steps),
               'enumeration_no_feasible': sum(x['coverage_category']=='enumeration_no_feasible' for x in steps)})
    pairs = []
    rows = {(r['source_order_key'],r['method'],r['policy_id']): r for r in summaries}
    sources = sorted({t['source_order_key'] for t in tasks})
    for source in sources:
        for method in methods:
            a, b = (rows[(source,method,p)] for p in ('P0','P1'))
            pairs.append({'source_order_key': source, 'method': method,
                          'both_attribute_success': a['episode_attribute_success'] and b['episode_attribute_success'],
                          'both_completed': a['completed'] and b['completed'],
                          'p0_attribute_success': a['episode_attribute_success'],
                          'p1_attribute_success': b['episode_attribute_success'],
                          'p0_placed_item_ratio': a['placed_item_ratio'],
                          'p1_placed_item_ratio': b['placed_item_ratio']})
    write_csv(root/'metrics/policy_pairs.csv', pairs)
    ci = {}
    baseline = 'public_parser'
    if baseline in methods:
        for method in methods:
            if method == baseline: continue
            grouped = []
            for source in sources:
                deltas = [float(rows[(source,method,p)]['episode_attribute_success']) -
                          float(rows[(source,baseline,p)]['episode_attribute_success']) for p in ('P0','P1')]
                grouped.append(sum(deltas)/2)
            rng = random.Random(20261015)
            samples = sorted(sum(rng.choice(grouped) for _ in grouped)/len(grouped) for _ in range(1000))
            ci[method] = {'reference': baseline, 'metric': 'episode_attribute_success',
                          'source_order_clusters': len(grouped), 'paired_difference': sum(grouped)/len(grouped),
                          'ci95_percentile': [samples[24], samples[975]],
                          'bootstrap_draws': 1000, 'exploratory_development_only': True}
    write_json(root/'metrics/paired_cluster_ci.json', ci)
    if summaries and summaries[0]['execution_mode'] == 'observe_business':
        comparisons = {}
        for method in methods:
            if method == baseline: continue
            for field in ('ever_business_violation', 'business_violation_step_rate',
                          'episode_attribute_success', 'placed_item_ratio'):
                grouped = []
                for source in sources:
                    deltas = []
                    for policy_id in ('P0', 'P1'):
                        left = rows[(source,method,policy_id)][field]
                        right = rows[(source,baseline,policy_id)][field]
                        if left is not None and right is not None:
                            deltas.append(float(left)-float(right))
                    if deltas: grouped.append(sum(deltas)/len(deltas))
                if not grouped: continue
                rng = random.Random(20261015)
                samples = sorted(sum(rng.choice(grouped) for _ in grouped)/len(grouped)
                                 for _ in range(1000))
                comparisons[f'{method}__{field}'] = {
                    'reference': baseline, 'metric': field,
                    'source_order_clusters': len(grouped),
                    'paired_difference': sum(grouped)/len(grouped),
                    'ci95_percentile': [samples[24], samples[975]],
                    'bootstrap_draws': 1000, 'exploratory_development_only': True}
        write_json(root/'metrics/business_violation_comparison.json', comparisons)
    return summaries, steps


def audit_outputs(root, tasks, methods, repo):
    validator = Draft202012Validator(read_json(SOURCE/'schemas/o3_request.schema.json'))
    failures = []; checked = 0
    for task in tasks:
        scenario = repo.get_scenario(task['scenario_id'])
        for method in methods:
            folder = root/'episodes'/method/task['episode_id']
            if not folder.exists(): continue
            events = [json.loads(x) for x in (folder/'steps.jsonl').read_text().splitlines() if x]
            for event in events:
                request_id = event['request_id']
                req = read_json(folder/'selector_inputs'/request_id/'public_request.json')
                private = read_json(folder/'selector_inputs'/request_id/'mapping.private.json')
                checked += 1
                try: validator.validate(req)
                except Exception: failures.append(request_id+':schema')
                if scan_public(req, private.values())['status'] != 'PASS':
                    failures.append(request_id+':leakage')
                expected_item = scenario['arrival_order'][event['step_index']]
                visible = {p['item_id'] for p in req['placed_items']}
                if (req['available_items'][0]['item_id'] != expected_item or
                        visible != set(scenario['arrival_order'][:event['step_index']])):
                    failures.append(request_id+':future_or_state')
                if method == 'flash_policy_parser' and (root/'selector_inputs'/method/request_id).exists():
                    remote = root/'selector_inputs'/method/request_id
                    for prompt in remote.glob('*.prompt.json'):
                        value = read_json(prompt)
                        if any(x in value['user_text'] for x in private.values()):
                            failures.append(request_id+':prompt_private_id')
                        if digest(req) != value['request_sha256']:
                            failures.append(request_id+':prompt_binding')
    result = {'status': 'PASS' if not failures else 'FAIL', 'public_requests_checked': checked,
              'failures': failures, 'human_review_required': False}
    write_json(root/'audit/schema_leakage_report.json', result)
    return result


def comparison_examples(tasks, summaries):
    """Predefined illustration categories; never filters metric denominators."""
    by = {(r['scenario_id'],r['policy_id'],r['method']): r for r in summaries}
    scenarios = list(dict.fromkeys(t['scenario_id'] for t in tasks))
    selected = []
    categories = (
        lambda g,p: p['episode_attribute_success'] and not g['episode_attribute_success'],
        lambda g,p: p['episode_attribute_success'] and g['episode_attribute_success'],
        lambda g,p: not p['episode_attribute_success'] and not g['episode_attribute_success'],
    )
    for predicate in categories:
        sid = next((s for s in scenarios if s not in selected and
                    predicate(by[(s,'P0','geometry_greedy')],by[(s,'P0','public_parser')])), None)
        if sid: selected.append(sid)
    selected.extend(s for s in scenarios if s not in selected)
    return selected[:3]


def run(root, split='train', limit_orders=3, remote=False, resume=False,
        render_comparisons=False, execution_mode='safe'):
    if execution_mode not in EXECUTION_MODES:
        raise ValueError('unknown O3 execution mode')
    cfg = load_config(seed=20261015, top_k=16, topk_mode='diverse_v1', fallback_policy='abort')
    repo = DatasetRepository(cfg['dataset'])
    tasks, source_audit = task_plan(repo, split, limit_orders)
    methods = list(METHODS if remote else OFFLINE)
    if remote and not os.environ.get('DEEPSEEK_API_KEY'):
        raise ValueError('DEEPSEEK_API_KEY is required for real Flash episodes')
    root = Path(root).resolve()
    if resume: load_resume(root, cfg, tasks, methods, repo, execution_mode)
    else: snapshot(root, cfg, tasks, source_audit, methods, repo, execution_mode)
    gen = ExtremePointGenerator(generator_config(cfg))
    client = DeepSeekClient() if remote else None
    for task in tasks:
        for method in methods:
            if (root/'episodes'/method/task['episode_id']).exists(): continue
            run_episode(root, task, method, repo, gen, cfg, client,
                        execution_mode=execution_mode)
    summaries, steps = report_metrics(root, tasks, methods)
    replay = replay_all(root, tasks, methods, repo, cfg)
    audit = audit_outputs(root, tasks, methods, repo)
    rendered = []
    if render_comparisons:
        from ..visualization.o3_animation import render_comparison
        scenario_ids = comparison_examples(tasks,summaries)
        if len(scenario_ids) < 3:
            raise ValueError('Three source orders required for comparison animation')
        for sid in scenario_ids:
            rendered.append(str(render_comparison(root, sid).relative_to(root)))
    checks = {'planned_episodes_recorded': len(summaries)==len(tasks)*len(methods),
              'replay_pass': replay['status']=='PASS',
              'schema_leakage_pass': audit['status']=='PASS',
              'committed_physical_violations_zero': all(x['committed_physical_violations']==0 for x in summaries),
              'source_split_clean': not source_audit['cross_split_overlap'],
              'step_bindings_present': all(x['state_hash'] and x['policy_digest'] and x['candidate_set_digest'] for x in steps)}
    if execution_mode == 'observe_business':
        checks['business_screen_not_enforced'] = all(not x['screen_intervened'] for x in steps)
        checks['violation_metrics_present'] = all(
            x['business_violation_step_rate'] is not None or x['placed_items'] == 0
            for x in summaries)
    if render_comparisons: checks['three_comparison_animations'] = len(rendered)==3
    if render_comparisons and split == 'validation':
        shown = [r for r in summaries if r['scenario_id'] in scenario_ids and r['policy_id']=='P0'
                 and r['method']=='public_parser']
        outcome = 'episode_attribute_success' if execution_mode == 'observe_business' else 'completed'
        checks['comparison_success_and_failure'] = any(r[outcome] for r in shown) and any(not r[outcome] for r in shown)
    status = 'PASS' if all(checks.values()) else 'FAIL'
    write_json(root/'acceptance_report.json', {'stage': 'O3a' if split=='train' else 'O3b_validation',
               'execution_mode': execution_mode,
               'status': status if remote else ('PARTIAL' if status=='PASS' else 'FAIL'),
               'offline_status': status, 'real_flash_status': 'PASS' if remote and status=='PASS' else 'NOT_RUN',
               'checks': checks, 'planned_episodes': len(tasks)*len(methods), 'recorded_episodes': len(summaries),
               'comparison_animations': rendered,
               'research_claims': {'online_flash_advantage': 'inconclusive' if remote else 'not_tested'},
               'unseen_test_result': False})
    if execution_mode == 'observe_business':
        aggregate = read_json(root/'metrics/summary.json')
        lines = ['# O3 业务违规观察实验', '',
                 f"执行模式：`{execution_mode}`；独立来源订单：{source_audit['independent_source_orders']}；"
                 f"政策数/订单：2；记录 episode：{len(summaries)}。", '',
                 f"离线工程检查：{status}；真实 Flash：{'已运行' if remote else '未运行'}；"
                 '研究结论：证据不足；本轮为开发数据，不是未见 test。', '',
                 '| 方法 | 放完/计划 | 全过程曾违规/计划 | 完成订单中最终违规/放完 | 新增或加重违规的放置比例 | 最终违规实例数 |',
                 '|---|---:|---:|---:|---:|---:|']
        for method in methods:
            value = aggregate[method]
            rate = value['committed_business_violation_step_rate']
            lines.append(f"| {method} | {value['completed']}/{value['episodes']} | "
                         f"{value['orders_with_any_business_violation']}/{value['episodes']} | "
                         f"{value['completed_with_business_violation']}/{value['completed']} | "
                         f"{f'{rate:.2%}' if rate is not None else 'N/A'} | "
                         f"{value['final_business_violation_instances']} |")
        lines.extend(['',
                      '业务屏障只记录、不拦截；候选仍须通过物理检查。没有物理候选、响应非法或 API 失败仍可能终止订单。',
                      '完成订单违规率只描述放完的子集，必须联合完成率、已放件数/体积比例和无违规完成率解释。',
                      '步骤违规率按新增/加重违规计；已有违规不使后续无关动作重复记错。一次放置造成多个违规实例仍只计一个违规步骤。',
                      '汇总步骤率为总违规放置数/总提交数；配对区间使用每 episode 步骤率，再在同来源订单的政策之间平均。',
                      '业务无解时，Parser/Flash/真值参考执行器采用冻结的最少增量违规排序继续；固定属性臂沿用其既有固定策略。',
                      '步骤、政策变体不视为独立订单；按来源订单聚类的配对区间见 metrics/business_violation_comparison.json。',
                      '原始 AST、提议、实际提交、would_screen_block、diagnostic_continuation 与 before/after/delta 均保留。',
                      '真值 AST 臂为特权逐步参考，不代表完整订单全局最优。'])
        (root/'pilot_report.md').write_text('\n'.join(lines)+'\n')
    return status, replay


def main():
    parser = argparse.ArgumentParser(description='O3 online attribute episodes')
    parser.add_argument('--output', required=True)
    parser.add_argument('--split', choices=('train', 'validation'), default='train')
    parser.add_argument('--limit-orders', type=int, default=None)
    parser.add_argument('--remote', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--render-comparisons', action='store_true')
    parser.add_argument('--execution-mode', choices=EXECUTION_MODES, default='safe',
                        help='observe_business commits physical candidates without a business screen')
    args = parser.parse_args()
    limit = args.limit_orders if args.limit_orders is not None else (3 if args.split=='train' else 10)
    status, replay = run(args.output, args.split, limit, args.remote, args.resume,
                         args.render_comparisons, args.execution_mode)
    print(json.dumps({'status': status, 'replay': replay['status'], 'output': args.output}, ensure_ascii=False))
    if status != 'PASS': raise SystemExit(1)


if __name__ == '__main__': main()
