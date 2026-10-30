"""Stable v2 layout/AST validation; frozen v1 runner and evidence remain untouched."""
from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import os
import shutil
import sys
import time
import platform
import importlib.metadata
from dataclasses import asdict
from pathlib import Path

import numpy as np
from jsonschema import Draft202012Validator

from ..config import WORKSPACE, generator_config, load_config
from ..domain import PalletState
from ..evaluation.attribute_metrics_v2 import reconstruct
from ..evaluation.geometry_oracle import check_candidate
from ..evaluation.policy_o1b import resolve
from ..evaluation.policy_v2 import evaluate, violations
from ..evaluation.replay_values_v2 import replay_values_equal
from ..evaluation.state import apply_candidate, state_metrics
from ..planner.generator import ExtremePointGenerator
from ..protocol import canonical_json, state_hash
from ..repository import DatasetRepository
from ..selectors.instruction_parser_o1b import resolved_public_policy
from ..selectors.layout_preserving_v2 import SOFT_BUDGETS, select_layout, RANKING_EPS, VERSION as RANKING_VERSION
from ..vlm.layout_flash_client import LayoutFlashClient
from ..vlm.policy_protocol_o2b import PROMPT_VERSION, model_request, parse_policy_response
from ..vlm.pilot_protocol_v2 import digest
from ..vlm.protocol_o2a import ChoiceProtocolError
from .attribute_o3_online import step_state, task_plan
from .attribute_pilot_v2 import read_json, sha, write_csv, write_json
from .layout_ablation import SOURCE, REFERENCES, inventory, PROTOCOL
from .o3_online_adapter import public_request, screen

VERSION = 'layout_flash_validation_v2'
VARIANTS = ('original', 'relaxed_geometry', 'relaxed_wo_floor')
MODES = ('safe', 'observe_business')
BASELINE = WORKSPACE/'semantic_pallet_planner/outputs/EXP_OPT_O3_LAYOUT_VALIDATION_20261019_01'
GUIDE = WORKSPACE/'docs/04_运行与复核手册/O3布局数值稳定V2运行与API交接_20261020.md'
API_FAILURES = {'api_budget_exhausted', 'provider_error', 'invalid_response'}


def plan(repo, split, scenarios=None, limit_orders=None):
    tasks, audit = task_plan(repo, split, None)
    if scenarios is not None:
        available = {t['scenario_id'] for t in tasks}
        if not scenarios or len(set(scenarios)) != len(scenarios) or not set(scenarios) <= available:
            raise ValueError('scenarios must be unique members of the chosen split')
        tasks = [t for sid in scenarios for t in tasks if t['scenario_id'] == sid]
    else:
        count = 10 if limit_orders is None else limit_orders
        if count < 1:
            raise ValueError('limit-orders must be positive')
        ids = list(dict.fromkeys(t['scenario_id'] for t in tasks))[:count]
        tasks = [t for t in tasks if t['scenario_id'] in ids]
    audit.update(source_keys=list(dict.fromkeys(t['source_order_key'] for t in tasks)))
    audit['independent_source_orders'] = len(audit['source_keys'])
    return tasks, audit


def response_text(raw):
    if raw.get('cache_hit') is not False:
        raise ChoiceProtocolError('cached_response')
    try:
        value = raw['provider_payload']['choices'][0]['message']['content']
        if not isinstance(value, str):
            raise TypeError()
        return value
    except (KeyError, IndexError, TypeError):
        raise ValueError('invalid provider response shape') from None


def prompt_record(req, error=None):
    prompt = model_request(req, repair_error=error)
    return prompt, {'model_request': json.loads(canonical_json(asdict(prompt))), 'http_body': LayoutFlashClient.body(prompt),
                    'public_request_digest': digest(req)}


class Session:
    """Count BEFORE every network attempt; no transport retry or Parser fallback."""
    def __init__(self, client, maximum):
        self.client, self.maximum, self.used = client, maximum, 0

    def parse(self, folder, req):
        folder.mkdir(parents=True, exist_ok=False)
        write_json(folder/'public_request.json', req)
        attempts = []
        error = None
        parsed = None
        status = None
        for index in range(2):
            prompt, recorded = prompt_record(req, error)
            if self.used >= self.maximum:
                status = 'api_budget_exhausted'
                break
            self.used += 1
            name = 'initial' if index == 0 else 'repair'
            write_json(folder/(name+'.prompt.json'), recorded)
            attempt = {'sequence': self.used, 'name': name, 'valid': False}
            started = time.perf_counter()
            try:
                raw = self.client.complete(prompt)
            except Exception as exc:
                # Keep codes, never exception text or request headers.
                attempt.update(category=getattr(exc, 'category', 'provider_error'),
                               exception_type=type(exc).__name__, latency_s=time.perf_counter()-started)
                write_json(folder/(name+'.error.json'), attempt)
                attempts.append(attempt)
                status = 'provider_error'
                break
            attempt['latency_s'] = time.perf_counter()-started
            write_json(folder/(name+'.raw.json'), raw)
            try:
                parsed = parse_policy_response(response_text(raw), req)
            except ChoiceProtocolError as exc:
                attempt['code'] = exc.code
                error = exc.code
                status = 'invalid_response'
            except (ValueError, TypeError):
                attempt['code'] = 'provider_response_shape'
                status = 'provider_error'
            else:
                attempt['valid'] = True
                status = None
            attempts.append(attempt)
            if parsed is not None or status == 'provider_error' or error == 'cached_response':
                break
        trace = {'attempts': attempts, 'status': status, 'parsed': parsed,
                 'public_request_digest': digest(req)}
        write_json(folder/'attempts.json', trace)
        return trace


def saved_parse(folder, req):
    """No network. Reconstruct parsing and repair decisions from saved provider output."""
    trace = read_json(folder/'attempts.json')
    if read_json(folder/'public_request.json') != req or trace['public_request_digest'] != digest(req):
        raise ValueError('Flash public request binding')
    attempts = trace['attempts']
    if len(attempts) > 2:
        raise ValueError('too many repair attempts')
    parsed = None
    error = None
    status = None
    for i, attempt in enumerate(attempts):
        name = 'initial' if i == 0 else 'repair'
        if attempt['name'] != name or (i and error is None):
            raise ValueError('illegal repair sequence')
        _, expected = prompt_record(req, error)
        if not replay_values_equal(read_json(folder/(name+'.prompt.json')), expected):
            raise ValueError('Flash prompt drift')
        if (folder/(name+'.error.json')).exists():
            if attempt != read_json(folder/(name+'.error.json')) or attempt['valid'] or i != len(attempts)-1:
                raise ValueError('transport error evidence')
            status = 'provider_error'
            break
        raw = read_json(folder/(name+'.raw.json'))
        try:
            parsed = parse_policy_response(response_text(raw), req)
        except ChoiceProtocolError as exc:
            if attempt.get('code') != exc.code or attempt['valid']:
                raise ValueError('protocol error evidence') from exc
            error, status = exc.code, 'invalid_response'
        except (ValueError, TypeError):
            if attempt.get('code') != 'provider_response_shape' or attempt['valid']:
                raise ValueError('provider shape evidence') from None
            status = 'provider_error'
        else:
            if not attempt['valid'] or i != len(attempts)-1:
                raise ValueError('successful parse evidence')
            status = None
    if trace['status'] == 'api_budget_exhausted':
        if parsed is not None or len(attempts) == 2:
            raise ValueError('invalid budget stop')
        status = 'api_budget_exhausted'
    if trace['status'] != status or not replay_values_equal(trace['parsed'], parsed):
        raise ValueError('saved AST or status tampered')
    return trace


def decide(req, mapping, ast, mode, variant, failure=None):
    """Both AST sources enter exactly the same layout executor and submit checks."""
    out = {'policy_ast': ast, 'resolved_policy': None, 'proposed_label': None,
           'committed_label': None, 'trace': {}, 'would_screen_block': False,
           'screen_intervened': False, 'physical_errors': [], 'status': failure}
    if not mapping:
        out['status'] = 'no_physical_candidate'
        return out
    if failure:
        return out
    policy = resolve(ast, req) if ast['schema_version'] == 'pallet_policy_o1b_conditional_1' else ast
    out['resolved_policy'] = policy
    evaluations = [evaluate(req, c, policy, req['container']) for c in req['candidates']]
    if mode == 'safe' and not any(not v['after_violation_instances'] for v in evaluations):
        out['status'] = 'no_business_feasible_candidate'
        return out
    proposal, trace = select_layout(req, policy, variant, allow_business_violation=mode == 'observe_business')
    label, blocked, reason = screen(req, proposal, evaluations)
    out.update(proposed_label=proposal, trace=trace, would_screen_block=blocked)
    if mode == 'safe':
        out.update(committed_label=label, screen_intervened=blocked, status=reason)
    else:
        out.update(committed_label=proposal)
    if out['committed_label']:
        physical = check_candidate(req, {'container': req['container']}, mapping[out['committed_label']])
        out['physical_errors'] = physical
        if physical:
            out.update(committed_label=None, status='physical_rejection')
        else:
            out['status'] = 'select'
    out['status'] = out['status'] or 'selector_abstain'
    return out


def summarize(scenario, task, mode, variant, parser, events):
    placed = events[-1]['after_placed']
    final, _ = violations(reconstruct(placed), task['truth_policy'])
    planned = len(scenario['arrival_order'])
    violating = sum(bool(e['committed_label']) and bool(e['raw_evaluation']['new_business_violation_count']+
        e['raw_evaluation']['worsened_existing_violation_count']) for e in events)
    return {'episode_id': task['episode_id'], 'scenario_id': task['scenario_id'],
        'source_order_key': task['source_order_key'], 'policy_id': task['policy_id'],
        'mode': mode, 'variant': variant, 'parser': parser,
        'planned_items': planned, 'placed_items': len(placed), 'completed': len(placed) == planned,
        'clean_completed': len(placed) == planned and not final, 'placed_item_ratio': len(placed)/planned,
        'placed_volume_ratio': sum(math.prod(p['oriented_size_mm']) for p in placed)/
            sum(math.prod(list(p['dimensions_mm'].values())) for p in scenario['items']),
        'final_business_violation_count': len(final), 'final_violation_ids': final,
        'violating_steps': violating, 'business_violation_step_rate': violating/len(placed) if placed else None,
        'physical_violations': sum(bool(e['physical_errors']) for e in events),
        'termination_reason': events[-1]['status'], 'final_geometry': state_metrics(scenario['container'], placed)}


def episode(root, scenario, task, variant, mode, cfg, parser, session=None, replay_events=None):
    folder = root/'episodes'/mode/variant/parser/task['episode_id']
    if replay_events is None:
        folder.mkdir(parents=True, exist_ok=False)
    gen = ExtremePointGenerator(generator_config(cfg))
    validator = Draft202012Validator(read_json(SOURCE/'schemas/o3_request.schema.json'))
    placed, events = [], []
    for index in range(len(scenario['arrival_order'])):
        state = step_state(scenario, task, placed, index)
        generated = gen.generate(PalletState.from_dict(state))
        req, mapping, scan = public_request(state, generated.candidate_set.data['candidates'],
                                          task['instruction_text'], seed=cfg['seed'])
        validator.validate(req)
        if scan['status'] != 'PASS':
            raise ValueError('public leakage')
        ast, api, failure = None, None, None
        if parser == 'public_parser':
            ast = resolved_public_policy(req['instruction_text'], req)
        elif mapping:
            path = Path('selector_inputs')/mode/variant/parser/task['episode_id']/f'{index:03d}'
            if replay_events is None:
                api = session.parse(root/path, req)
            else:
                api = saved_parse(root/path, req)
            ast = api['parsed']['policy_ast'] if api['parsed'] else None
            failure = api['status']
        result = decide(req, mapping, ast, mode, variant, failure)
        raw = evaluate(req, mapping[result['proposed_label']], task['truth_policy'], req['container']) if result['proposed_label'] else None
        if result['committed_label']:
            placed = apply_candidate(state, mapping[result['committed_label']])
            if index == len(scenario['arrival_order'])-1:
                result['status'] = 'all_items_placed'
        after = step_state(scenario, task, placed, index+1)
        event = dict(result, step_index=index, request=req, candidate_set_digest=digest(req['candidates']),
            before_state_hash=req['state_hash'], after_state_hash=state_hash(req['container'], after)
                if result['committed_label'] else req['state_hash'], after_placed=copy.deepcopy(placed),
            generation_audit=generated.audit.data, raw_evaluation=raw, api=api, schema_leakage_status=scan['status'])
        events.append(event)
        if replay_events is not None:
            if index >= len(replay_events) or not replay_values_equal(event, replay_events[index]):
                raise ValueError(f'event/AST/action/transition mismatch at step {index}')
        if not result['committed_label'] or result['status'] == 'all_items_placed':
            break
    summary = summarize(scenario, task, mode, variant, parser, events)
    if replay_events is not None:
        if len(events) != len(replay_events):
            raise ValueError('event count mismatch')
    else:
        (folder/'steps.jsonl').write_text(''.join(canonical_json(e)+'\n' for e in events))
        write_json(folder/'episode.json', {'task': task, 'summary': summary, 'events_digest': digest(events)})
    return summary, events


def events_at(root, mode, variant, parser, task):
    folder = root/'episodes'/mode/variant/parser/task['episode_id']
    return folder, [json.loads(s) for s in (folder/'steps.jsonl').read_text().splitlines()]


def replay(root, repo=None):
    root = Path(root)
    manifest = read_json(root/'manifest.json')
    if manifest['version'] != VERSION or manifest['ranking_version'] != RANKING_VERSION:
        raise ValueError('v2 version mismatch; use the frozen v1 runner for old experiments')
    cfg = read_json(root/'config.snapshot.json')
    repo = repo or DatasetRepository(cfg['dataset'])
    tasks = read_json(root/'data/tasks.private.json')
    failures, rows, steps, baseline_steps = [], [], 0, 0
    for name, expected in manifest['source_sha256'].items():
        if sha(SOURCE/name) != expected or sha(root/'snapshots/source'/name) != expected:
            failures.append('source:'+name)
    for name, expected in manifest['dataset_sha256'].items():
        if sha(repo.root/name) != expected or sha(root/'snapshots/dataset'/name) != expected:
            failures.append('dataset:'+name)
    if digest(tasks) != manifest['task_digest'] or digest(cfg) != manifest['config_digest']:
        failures.append('task/config binding')
    for doc, key in ((PROTOCOL, 'protocol_sha256'), (GUIDE, 'guide_sha256')):
        if sha(root/'snapshots'/doc.name) != manifest[key] or sha(doc) != manifest[key]:
            failures.append('protocol:'+doc.name)
    reference_root = Path(manifest['baseline_root']) if manifest['baseline_root'] else None
    for name, expected in manifest['baseline_sha256'].items():
        if not (reference_root/name).exists() or sha(reference_root/name) != expected:
            failures.append('baseline changed:'+name)
    for mode in manifest['modes']:
        for variant in manifest['variants']:
            for parser in manifest['parsers']:
                for task in tasks:
                    prefix = '/'.join((mode, variant, parser, task['episode_id']))
                    try:
                        folder, events = events_at(root, mode, variant, parser, task)
                        record = read_json(folder/'episode.json')
                        if record['task'] != task or record['events_digest'] != digest(events):
                            raise ValueError('task/event digest')
                        summary, _ = episode(root, repo.get_scenario(task['scenario_id']), task,
                            variant, mode, cfg, parser, replay_events=events)
                        if not replay_values_equal(summary, record['summary']):
                            raise ValueError('summary mismatch')
                        rows.append(summary)
                        steps += len(events)
                        if parser == 'public_parser' and (reference_root or (
                                variant == 'original' and task['source_split'] == 'validation')):
                            reference = (reference_root/'episodes'/mode/variant/'public_parser'/task['episode_id']/'steps.jsonl'
                                if reference_root else BASELINE/'episodes'/mode/variant/task['episode_id']/'steps.jsonl')
                            old = [json.loads(s) for s in reference.read_text().splitlines()]
                            fields = ('before_state_hash', 'after_state_hash', 'proposed_label', 'committed_label', 'after_placed', 'status')
                            if reference_root:
                                fields += ('request', 'trace', 'generation_audit', 'raw_evaluation')
                            if len(old) != len(events) or any(not replay_values_equal(
                                {k: a[k] for k in fields}, {k: b[k] for k in fields}) for a, b in zip(old, events)):
                                raise ValueError('v2 reference mismatch' if reference_root else 'frozen original control mismatch')
                            baseline_steps += len(old)
                    except (ValueError, KeyError, TypeError, IndexError, OSError) as exc:
                        failures.append(prefix+':'+str(exc))
    if len(rows) != manifest['planned_episodes']:
        failures.append('incomplete episode matrix')
    try:
        with (root/'metrics/per_episode.csv').open(encoding='utf-8-sig', newline='') as handle:
            actual_csv = list(csv.DictReader(handle))
        expected_csv = [{k: canonical_json(v) if isinstance(v, (dict, list)) else '' if v is None else str(v)
                         for k, v in row.items()} for row in rows]
        if actual_csv != expected_csv:
            failures.append('per-episode CSV mismatch')
        if not replay_values_equal(read_json(root/'metrics/summary.json'), aggregate(rows)):
            failures.append('aggregate summary mismatch')
        if not replay_values_equal(read_json(root/'metrics/paired_cluster_comparisons.json'), comparisons(rows)):
            failures.append('paired comparisons mismatch')
    except (OSError, ValueError) as exc:
        failures.append('metrics artifact:'+str(exc))
    try:
        api = usage(root, manifest['max_api_attempts'])
        if not api['sequence_valid'] or api['actual_attempts'] > manifest['max_api_attempts']:
            failures.append('API sequence/budget')
        if not manifest['remote'] and api['actual_attempts']:
            failures.append('offline network calls')
        if not replay_values_equal(read_json(root/'api_usage.json'), api):
            failures.append('API usage summary mismatch')
        for path in (root/'selector_inputs').rglob('attempts.json'):
            record = read_json(path)
            if record['status'] == 'api_budget_exhausted':
                prior = record['attempts'][-1]['sequence'] if record['attempts'] else api['actual_attempts']
                if prior != manifest['max_api_attempts'] or api['actual_attempts'] != prior:
                    failures.append('premature budget stop')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        failures.append('API audit:'+str(exc))
    return {'status': 'PASS' if not failures else 'FAIL', 'episodes': len(rows), 'steps': steps,
            'reference_steps_compared': baseline_steps,
            'reference_kind': 'stable_v2_baseline' if reference_root else 'frozen_original_control_only',
            'failures': failures, 'rows': rows}


def aggregate(rows):
    result = {}
    for r in rows:
        key = '/'.join((r['mode'], r['variant'], r['parser']))
        a = result.setdefault(key, {'episodes': 0, 'completed': 0, 'clean_completed': 0,
            'placed_steps': 0, 'violating_steps': 0, 'final_business_violation_instances': 0,
            'mean_placed_item_ratio': 0., 'mean_placed_volume_ratio': 0.})
        for k in ('episodes', 'completed', 'clean_completed', 'placed_steps', 'violating_steps', 'final_business_violation_instances'):
            a[k] += {'episodes': 1, 'placed_steps': r['placed_items'],
                     'final_business_violation_instances': r['final_business_violation_count']}.get(k, r.get(k, 0))
        for k in ('placed_item_ratio', 'placed_volume_ratio'):
            a['mean_'+k] += r[k]
    for a in result.values():
        for k in ('mean_placed_item_ratio', 'mean_placed_volume_ratio'):
            a[k] /= a['episodes']
        a['micro_violation_step_rate'] = a['violating_steps']/a['placed_steps'] if a['placed_steps'] else None
    return result


def comparisons(rows):
    lookup = {(r['mode'], r['variant'], r['parser'], r['episode_id']): r for r in rows}
    output = []
    for mode in sorted({r['mode'] for r in rows}):
        pairs = [((v, 'flash'), (v, 'public_parser')) for v in VARIANTS]
        pairs += [((a, p), (b, p)) for p in ('public_parser', 'flash') for a, b in
                  (('relaxed_geometry', 'original'), ('relaxed_wo_floor', 'relaxed_geometry'))]
        for (va, pa), (vb, pb) in pairs:
            matches = [(r, lookup.get((mode, vb, pb, r['episode_id']))) for r in rows
                       if (r['mode'], r['variant'], r['parser']) == (mode, va, pa)]
            if not matches or any(b is None for _, b in matches):
                continue
            for metric in ('completed', 'clean_completed', 'placed_item_ratio', 'final_business_violation_count'):
                groups = {}
                for a, b in matches:
                    groups.setdefault(a['source_order_key'], []).append(float(a[metric])-float(b[metric]))
                delta = np.array([np.mean(v) for _, v in sorted(groups.items())])
                boot = np.random.default_rng(20261020).choice(delta, (5000, len(delta))).mean(axis=1)
                output.append({'mode': mode, 'comparison': f'{va}/{pa} - {vb}/{pb}', 'metric': metric,
                    'source_order_clusters': len(delta), 'mean_difference': float(delta.mean()),
                    'exploratory_95_ci': np.quantile(boot, [.025, .975]).tolist(),
                    'multiplicity_adjusted': False, 'new_test': False})
    return output


def agreement(root, tasks, variants, modes, remote):
    rows = []
    if not remote:
        return rows
    for mode in modes:
        for variant in variants:
            for task in tasks:
                _, parser_events = events_at(root, mode, variant, 'public_parser', task)
                _, flash_events = events_at(root, mode, variant, 'flash', task)
                for e in flash_events:
                    if not e['policy_ast']:
                        continue
                    req = e['request']
                    pp = resolved_public_policy(req['instruction_text'], req)
                    # Compare BOTH executors on this saved Flash state; no new API needed.
                    mapping = {c['display_label']: c for c in req['candidates']}
                    public_choice = decide(req, mapping, pp, mode, variant)['proposed_label']
                    i = e['step_index']
                    paired_state = i < len(parser_events) and parser_events[i]['before_state_hash'] == e['before_state_hash']
                    rows.append({'mode': mode, 'variant': variant, 'episode_id': task['episode_id'], 'step_index': i,
                        'comparison_state': 'saved_flash_state', 'ast_equal': normalized_policy(pp) == normalized_policy(e['resolved_policy']),
                        'same_state_action_equal': public_choice == e['proposed_label'],
                        'closed_loop_states_equal': paired_state})
    return rows


def normalized_policy(policy):
    value = copy.deepcopy(policy)
    value['hard_constraints'] = sorted(value['hard_constraints'], key=canonical_json)
    value['soft_priorities'] = sorted(value['soft_priorities'], key=lambda p: p['priority'])
    return value


def usage(root, maximum):
    attempts, raw_responses, sequences = [], [], []
    budget_stops = 0
    for path in sorted((root/'selector_inputs').rglob('attempts.json')):
        record = read_json(path)
        attempts.extend(record['attempts'])
        budget_stops += record['status'] == 'api_budget_exhausted'
        for a in record['attempts']:
            sequences.append(a['sequence'])
            rawfile = path.parent/(a['name']+'.raw.json')
            if rawfile.exists():
                raw_responses.append(read_json(rawfile))
    latency = [a['latency_s'] for a in attempts]
    tokens = [r.get('provider_payload', {}).get('usage') or {} for r in raw_responses]
    missing = sum(t.get('prompt_tokens') is None or t.get('completion_tokens') is None for t in tokens)
    return {'actual_attempts': len(attempts), 'initial_attempts': sum(a['name'] == 'initial' for a in attempts),
        'repair_attempts': sum(a['name'] == 'repair' for a in attempts), 'transport_retries': 0,
        'failed_attempts': sum(not a['valid'] for a in attempts), 'max_api_attempts': maximum,
        'budget_stops': budget_stops, 'sequence_valid': sorted(sequences) == list(range(1, len(attempts)+1)),
        'input_tokens_reported': sum(t.get('prompt_tokens') or 0 for t in tokens),
        'output_tokens_reported': sum(t.get('completion_tokens') or 0 for t in tokens), 'missing_usage_responses': missing,
        'latency_s_percentiles': np.quantile(latency, [.5, .95, 1.]).tolist() if latency else None,
        'returned_models': sorted({r['provider_payload'].get('model', 'NOT_PROVIDED') for r in raw_responses}),
        'estimated_cost': None, 'cost_basis': 'not configured; no price assumption'}


def run(root, *, split='validation', scenarios=None, limit_orders=None, variants=VARIANTS,
        modes=MODES, remote=False, max_api_attempts=4000, baseline=None):
    root = Path(root).resolve()
    if root.exists():
        raise FileExistsError('use a fresh output directory')
    if scenarios is not None and limit_orders is not None:
        raise ValueError('scenarios and limit-orders are mutually exclusive')
    if not variants or len(set(variants)) != len(variants) or not set(variants) <= set(VARIANTS):
        raise ValueError('invalid variants')
    if not modes or len(set(modes)) != len(modes) or not set(modes) <= set(MODES):
        raise ValueError('invalid execution modes')
    if max_api_attempts < 1:
        raise ValueError('max-api-attempts must be positive')
    if remote and not os.environ.get('DEEPSEEK_API_KEY'):
        raise ValueError('DEEPSEEK_API_KEY required for --remote')
    protected = dict(REFERENCES, layout=BASELINE)
    for name in ('OFFLINE', 'SMOKE', 'VALIDATION'):
        protected['flash_v1_'+name.lower()] = WORKSPACE/f'semantic_pallet_planner/outputs/EXP_OPT_O3_LAYOUT_FLASH_{name}_20261020_01'
    baseline = Path(baseline).resolve() if baseline else None
    if remote and baseline is None:
        raise ValueError('v2 --remote requires an accepted, cross-runtime certified --baseline')
    if baseline:
        protected['stable_v2_baseline'] = baseline
    if any(root == p or root in p.parents or p in root.parents for p in protected.values()):
        raise ValueError('output overlaps protected experiment')
    cfg = load_config(seed=20261015, top_k=16, topk_mode='diverse_v1', fallback_policy='abort')
    repo = DatasetRepository(cfg['dataset'])
    tasks, source_audit = plan(repo, split, scenarios, limit_orders)
    parsers = ['public_parser', 'flash'] if remote else ['public_parser']
    code = {str(p.relative_to(SOURCE)): sha(p) for p in sorted(SOURCE.rglob('*'))
            if p.is_file() and p.suffix in ('.py', '.json')}
    baseline_files = {}
    if baseline:
        ref = read_json(baseline/'manifest.json')
        if (ref['version'] != VERSION or ref['ranking_version'] != RANKING_VERSION or ref['remote']
                or ref['source_sha256'] != code or ref['config_digest'] != digest(cfg)
                or read_json(baseline/'acceptance_report.json')['status'] != 'PASS'):
            raise ValueError('baseline version/source/config/acceptance mismatch')
        reference_tasks = {t['episode_id']: t for t in read_json(baseline/'data/tasks.private.json')}
        if any(reference_tasks.get(t['episode_id']) != t for t in tasks):
            raise ValueError('baseline does not contain selected tasks')
        if any(not (repo.root/n).exists() or sha(repo.root/n) != h for n, h in ref['dataset_sha256'].items()):
            raise ValueError('baseline dataset changed')
        if remote:
            certification = read_json(baseline/'cross_runtime_report.json')
            if certification['status'] != 'PASS' or certification['baseline_manifest_sha256'] != sha(baseline/'manifest.json'):
                raise ValueError('baseline cross-runtime certification mismatch')
            peer = Path(certification['peer_root'])
            if (certification['matched_episodes'] != ref['planned_episodes']
                    or sha(peer/'manifest.json') != certification['peer_manifest_sha256']
                    or read_json(peer/'acceptance_report.json')['status'] != 'PASS'
                    or len(set(certification['python_minor_versions'])) != 2):
                raise ValueError('baseline cross-runtime peer evidence mismatch')
        names = ['manifest.json', 'acceptance_report.json', 'data/tasks.private.json']
        if remote:
            names += ['cross_runtime_report.json']
        for mode in modes:
            for variant in variants:
                for task in tasks:
                    names += [str(Path('episodes')/mode/variant/'public_parser'/task['episode_id']/name)
                              for name in ('steps.jsonl', 'episode.json')]
        baseline_files = {n: sha(baseline/n) for n in names}
    before = {k: inventory(p) for k, p in protected.items()}
    root.mkdir(parents=True)
    data_names = ['configs/mvd_v0.1.json']
    for sid in dict.fromkeys(t['scenario_id'] for t in tasks):
        data_names += [f'tasks/scenarios/{sid}.json', f'annotations/ground_truth_rules/{sid}.json']
    data = {n: sha(repo.root/n) for n in data_names}
    for origin, names, target in ((SOURCE, code, 'source'), (repo.root, data, 'dataset')):
        for name in names:
            dest = root/'snapshots'/target/name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin/name, dest)
    for doc in (PROTOCOL, GUIDE):
        shutil.copyfile(doc, root/'snapshots'/doc.name)
    decisions = sum(len(repo.get_scenario(t['scenario_id'])['arrival_order']) for t in tasks)*len(variants)*len(modes) if remote else 0
    manifest = {'version': VERSION, 'source_sha256': code, 'dataset_sha256': data,
        'task_digest': digest(tasks), 'config_digest': digest(cfg), 'variants': list(variants), 'modes': list(modes),
        'parsers': parsers, 'planned_episodes': len(tasks)*len(variants)*len(modes)*len(parsers),
        'max_flash_decisions': decisions, 'max_attempts_with_one_repair': 2*decisions,
        'max_api_attempts': max_api_attempts, 'remote': remote, 'provider': 'deepseek',
        'base_url': LayoutFlashClient.base_url, 'request_model': 'deepseek-flash', 'prompt_version': PROMPT_VERSION,
        'temperature': 0., 'timeout_s': 60., 'max_repair_calls': 1, 'transport_retries': 0,
        'buffer_size': 1, 'top_k': 16, 'soft_budgets': SOFT_BUDGETS, 'new_test': False,
        'protocol_sha256': sha(PROTOCOL), 'guide_sha256': sha(GUIDE), 'development_only': True}
    manifest.update(ranking_version=RANKING_VERSION, ranking_epsilon=RANKING_EPS,
                    baseline_root=str(baseline) if baseline else None, baseline_sha256=baseline_files,
                    baseline_role='reference_check' if baseline else 'reference_build')
    write_json(root/'environment.json', {'python': sys.version, 'executable': sys.executable,
        'platform': platform.platform(), 'packages': dict(sorted((d.metadata['Name'], d.version)
            for d in importlib.metadata.distributions() if d.metadata['Name']))})
    manifest['invocation'] = [sys.executable, *sys.argv]
    write_json(root/'manifest.json', manifest)
    write_json(root/'config.snapshot.json', cfg)
    write_json(root/'data/tasks.private.json', tasks)
    write_json(root/'audit/source_split.json', source_audit)
    write_json(root/'audit/protected_runs.before.json', before)
    print(json.dumps({k: manifest[k] for k in ('planned_episodes', 'max_flash_decisions', 'max_attempts_with_one_repair', 'max_api_attempts')}), flush=True)
    session = Session(LayoutFlashClient(), max_api_attempts) if remote else None
    rows = []
    for mode in modes:
        for variant in variants:
            for parser in parsers:
                for task in tasks:
                    summary, _ = episode(root, repo.get_scenario(task['scenario_id']), task,
                        variant, mode, cfg, parser, session)
                    rows.append(summary)
                    print(mode, variant, parser, task['episode_id'], summary['placed_items'], summary['termination_reason'], flush=True)
    totals = aggregate(rows)
    write_csv(root/'metrics/per_episode.csv', rows)
    write_json(root/'metrics/summary.json', totals)
    write_json(root/'metrics/paired_cluster_comparisons.json', comparisons(rows))
    agree = agreement(root, tasks, variants, modes, remote)
    if agree:
        write_csv(root/'metrics/parser_flash_agreement.csv', agree)
    else:
        (root/'metrics/parser_flash_agreement.csv').write_text('mode,variant,episode_id,step_index,comparison_state,ast_equal,same_state_action_equal,closed_loop_states_equal\n')
    api = usage(root, max_api_attempts)
    write_json(root/'api_usage.json', api)
    print('Replaying saved AST, layout actions, state transitions and historical layouts', flush=True)
    replayed = replay(root, repo)
    replay_rows = replayed.pop('rows')
    write_json(root/'replay_report.json', replayed)
    after = {k: inventory(p) for k, p in protected.items()}
    write_json(root/'audit/protected_runs.after.json', after)
    audits = {'schema_leakage_failures': 0, 'soft_budget_violations': 0, 'screen_violations': 0,
              'physical_violations': 0, 'checked_events': 0, 'checked_soft_metrics': 0}
    for mode in modes:
        for variant in variants:
            for parser in parsers:
                for task in tasks:
                    _, events = events_at(root, mode, variant, parser, task)
                    for e in events:
                        audits['checked_events'] += 1
                        audits['schema_leakage_failures'] += e['schema_leakage_status'] != 'PASS'
                        audits['physical_violations'] += bool(e['physical_errors'])
                        audits['screen_violations'] += mode == 'observe_business' and e['screen_intervened']
                        for loss, priority in zip(e['trace'].get('soft_loss_from_anchor', []),
                                                  (e['resolved_policy'] or {}).get('soft_priorities', [])):
                            audits['checked_soft_metrics'] += 1
                            audits['soft_budget_violations'] += loss is not None and loss > SOFT_BUDGETS[priority['metric']]+1e-9
    write_json(root/'audit/execution_checks.json', audits)
    checks = {'planned_episodes_recorded': len(rows) == manifest['planned_episodes'],
        'full_replay': replayed['status'] == 'PASS', 'metrics_recomputed': replay_values_equal(rows, replay_rows)
            and replay_values_equal(totals, aggregate(replay_rows)), 'protected_runs_unchanged': before == after,
        'source_split_clean': not source_audit['cross_split_overlap'],
        'schema_leakage_zero': audits['schema_leakage_failures'] == 0,
        'physical_violations_zero': audits['physical_violations'] == 0,
        'soft_budget_violations_zero': audits['soft_budget_violations'] == 0,
        'observe_screen_interventions_zero': audits['screen_violations'] == 0,
        'api_accounting': api['sequence_valid'] and api['actual_attempts'] <= max_api_attempts
            and api['actual_attempts'] == (session.used if session else 0),
        'offline_no_calls': remote or api['actual_attempts'] == 0}
    if remote:
        checks.pop('offline_no_calls')  # This assertion applies only to offline execution.
    incomplete = any(r['termination_reason'] in API_FAILURES for r in rows)
    status = 'FAIL' if not all(checks.values()) else ('PARTIAL' if incomplete else 'PASS')
    acceptance = {'status': status, 'checks': checks, 'episodes': len(rows), 'remote_calls': api['actual_attempts'],
        'real_flash_status': ('NOT_RUN' if not remote else status), 'vlm_advantage': 'NOT_CLAIMED',
        'research_status': 'EXPLORATORY_DEVELOPMENT_ONLY', 'api_incomplete': incomplete,
        'protected_run_files': {k: len(v) for k, v in before.items()}}
    acceptance.update(version=VERSION, ranking_version=RANKING_VERSION,
                      baseline_role=manifest['baseline_role'],
                      cross_runtime_status='NOT_CHECKED' if baseline is None else 'REFERENCE_MATCHED')
    write_json(root/'acceptance_report.json', acceptance)
    lines = ['# Layout Flash validation', '', f'Engineering status: {status}; real Flash: {acceptance["real_flash_status"]}.',
        f'Episodes: {len(rows)}; actual API attempts: {api["actual_attempts"]}.',
        'Seen development sources; no visual or VLM advantage claim. Relaxed variants explicitly change soft objectives.', '',
        '| Mode / variant / parser | Completed | Clean | Mean item ratio | Violation steps / placed |',
        '|---|---:|---:|---:|---:|']
    for key, a in totals.items():
        lines.append(f'| {key} | {a["completed"]}/{a["episodes"]} | {a["clean_completed"]}/{a["episodes"]} | {a["mean_placed_item_ratio"]:.2%} | {a["violating_steps"]}/{a["placed_steps"]} |')
    (root/'results.md').write_text('\n'.join(lines)+'\n')
    (root/'README.md').write_text('\n'.join(lines[:6])+ '\n\nSee results.md, acceptance_report.json, replay_report.json and audit/.\n')
    write_json(root/'delivery_manifest.json', inventory(root))
    return acceptance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--split', choices=('train', 'validation'), default='validation')
    subset = parser.add_mutually_exclusive_group()
    subset.add_argument('--scenarios', nargs='+')
    subset.add_argument('--limit-orders', type=int)
    parser.add_argument('--variants', nargs='+', choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument('--execution-modes', nargs='+', choices=MODES, default=list(MODES))
    method = parser.add_mutually_exclusive_group(required=True)
    method.add_argument('--offline-only', action='store_true')
    method.add_argument('--remote', action='store_true')
    method.add_argument('--replay-only', action='store_true', help='recompute saved evidence without API calls')
    parser.add_argument('--max-api-attempts', type=int, default=4000)
    parser.add_argument('--baseline', type=Path, help='accepted v2 offline baseline; mandatory for --remote')
    args = parser.parse_args()
    if args.replay_only:
        result = replay(args.output)
        result.pop('rows')
    else:
        result = run(args.output, split=args.split, scenarios=args.scenarios, limit_orders=args.limit_orders,
            variants=args.variants, modes=args.execution_modes, remote=args.remote,
            max_api_attempts=args.max_api_attempts, baseline=args.baseline)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
