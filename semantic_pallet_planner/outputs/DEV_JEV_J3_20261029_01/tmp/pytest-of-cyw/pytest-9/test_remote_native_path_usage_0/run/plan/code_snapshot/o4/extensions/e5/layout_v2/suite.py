"""Frozen, resumable local ablations with explicit denominators and no API."""
import copy
import json
import platform
import shutil
import sys
import time
import traceback
from pathlib import Path
from ....common import read, write, digest, O4Error
from ..episode import episode, stable
from ..backends import LocalCompiler
from ..storage import atomic, exclusive
from ..planning import choose as dispatch
from .config import DEFAULT, validate
from .experiment import WORKSPACE, PACKAGE, OUTPUTS, BASE_PLAN, new_output, sha, source_manifest, check_protection
from .planning import clear_cache

P0 = OUTPUTS/'EXP_O4_E5_LAYOUT_V2_P0_20261027_01'
GROUPS = {'A': (False, False), 'B': (True, False), 'C': (False, True), 'D': (True, True)}


def variant(base, group):
    config = copy.deepcopy(base)
    if group != 'A':
        config['o4_e5_layout'] = copy.deepcopy(DEFAULT)
        config['o4_e5_layout'].update(zip(('candidate_retention', 'ranking'), GROUPS[group]))
        validate(config['o4_e5_layout'])
    return config


def local_checks(output):
    root = new_output(output); base = read(WORKSPACE/BASE_PLAN/'config.snapshot.json')
    comparisons = []
    for name in ('original_second', 'withdrawn_v1_second'):
        c = read(WORKSPACE/P0/'cases'/f'{name}.json'); results = {}
        for group in GROUPS:
            selected, groups, trace, reason = dispatch(c['public_state'], c['request'], c['ast'], variant(base, group), 'single')
            results[group] = {'selected': selected, 'groups': groups, 'trace': trace, 'reason': reason}
        comparisons.append({'case': name, 'event_index': c['event_index'], 'episode_sha256': c['episode_sha256'],
                            'request': c['request'], 'state': c['public_state'], 'ast': c['ast'], 'results': results})
    write(root/'fixed_decisions.json', comparisons)
    write(root/'manifest.json', {'stage': 'EX-L0', 'input_sha256': {str(P0/'cases'/f'{n}.json'): sha(WORKSPACE/P0/'cases'/f'{n}.json') for n in ('original_second', 'withdrawn_v1_second')},
                                'source_sha256': source_manifest(), 'loaded_module': __file__, 'new_api_attempts': 0})
    # Behavioral assertions are independently checked in the focused L1 suite.
    write(root/'acceptance_report.json', {'stage': 'EX-L0', 'status': 'RECORDED', 'new_api_attempts': 0,
                                         'default_replacement_status': 'ORIGINAL_REMAINS_DEFAULT'})
    return {'status': 'RECORDED', 'output': str(root)}


def prepare(output, l0, l1_xml):
    root = new_output(output)
    import xml.etree.ElementTree as ET
    evidence = ET.parse(l1_xml).getroot()
    suites = [evidence] if evidence.tag == 'testsuite' else list(evidence.findall('testsuite'))
    if not suites or any(int(s.get(k, 0)) for s in suites for k in ('errors', 'failures', 'skipped')):
        raise O4Error('l1_not_passed')
    fixed = read(Path(l0)/'fixed_decisions.json')
    if len(fixed) != 2: raise O4Error('l0_missing')
    p0_status = read(WORKSPACE/P0/'acceptance_report.json')
    if p0_status['diagnostic_status'] != 'PASS': raise O4Error('p0_not_passed')
    data = read(WORKSPACE/BASE_PLAN/'private/input_snapshot.json'); tasks = data['tasks']
    sources = sorted({t['source_order_key'] for t in tasks})
    if len(sources) != 12: raise O4Error('source_registry_changed')
    l2_sources = [sources[i] for i in (0, 2, 4)]
    jobs = []
    def add(stage, task, group, method, backend='oracle_ast'):
        jobs.append({'job_id': f'{stage}_{task["task_id"]}_{group}_{method}_{backend}',
                     'stage': stage, 'task_id': task['task_id'], 'group': group,
                     'method': method, 'backend': backend, 'status': 'NOT_RUN'})
    for task in tasks:
        if task['source_order_key'] in l2_sources:
            for group in GROUPS:
                for method in ('single', 'buffer_search'): add('L2', task, group, method)
    source0 = next(t for t in tasks if t['source_order_key'] == '00101152' and t['configuration'] == 0)
    source2 = next(t for t in tasks if t['source_order_key'] == '00102047' and t['configuration'] == 0)
    for group in ('A', 'D'):
        for method in ('buffer_fifo', 'buffer_heuristic'): add('compat', source0, group, method, 'public_parser')
    for task in (source0, source2):
        for method in ('single', 'buffer_search'): add('compat', task, 'D', method, 'public_parser')
    if len(jobs) != 56: raise O4Error('wrong_l2_denominator')
    l3 = []
    for task in tasks:
        if task['source_order_key'] not in l2_sources:
            for group in ('A', 'D'):
                for method in ('single', 'buffer_search'):
                    l3.append({'job_id': f'L3_{task["task_id"]}_{group}_{method}_oracle_ast', 'stage': 'L3',
                               'task_id': task['task_id'], 'group': group, 'method': method,
                               'backend': 'oracle_ast', 'status': 'NOT_RUN'})
    base = read(WORKSPACE/BASE_PLAN/'config.snapshot.json')
    plan = {'version': DEFAULT['version'], 'tasks': tasks, 'constructs': data['constructs'], 'base_config': base,
            'group_configurations': {g: variant(base, g) for g in GROUPS}, 'l2_sources': l2_sources,
            'l2_jobs': jobs, 'l3_jobs': l3, 'l3_policy': 'only after L0/L1 pass and L2 safe, interpretable and beneficial',
            'tuning_policy': 'no parameter changes based on L3', 'new_api_attempts': 0,
            'engineering_checks': [f'C{i:02d}' for i in range(1,15)],
            'performance_gates': {'volume_noninferiority': 1e-9, 'minimum_improvement': .01,
                                  'count_gain': 1, 'task_count_loss_hold': 2, 'median_ratio': 2., 'p95_ratio': 3.},
            'business_support_quality': 'NOT_IMPLEMENTED', 'probe_quality': 'NOT_IMPLEMENTED',
            'independent_generalization': 'NOT_MEASURED'}
    write(root/'plan.json', plan)
    shutil.copytree(PACKAGE, root/'code_snapshot/semantic_pallet_planner', ignore=shutil.ignore_patterns('__pycache__'))
    evidence_dir = root/'prerequisites'; evidence_dir.mkdir()
    shutil.copy2(l1_xml, evidence_dir/'behavior_tests.xml')
    shutil.copy2(Path(l0)/'fixed_decisions.json', evidence_dir/'fixed_decisions.json')
    shutil.copy2(WORKSPACE/P0/'p0_findings.json', evidence_dir/'p0_findings.json')
    shutil.copy2(WORKSPACE/'semantic_pallet_planner/tests/unit/test_o4_e5_layout_v2.py', evidence_dir/'test_o4_e5_layout_v2.py')
    source_files = source_manifest()
    frozen = {str(p.relative_to(root/'code_snapshot')): sha(p) for p in (root/'code_snapshot').rglob('*') if p.is_file()}
    write(root/'manifest.json', {'plan_digest': digest(plan), 'source_sha256': source_files,
          'snapshot_sha256': frozen, 'python': sys.executable, 'platform': platform.platform(), 'loaded_module': __file__,
          'prerequisites_sha256': {str(p.relative_to(root)): sha(p) for p in evidence_dir.iterdir()},
          'input_sha256': {str(BASE_PLAN/'private/input_snapshot.json'): sha(WORKSPACE/BASE_PLAN/'private/input_snapshot.json')},
          'protected_manifest': str(P0/'protected.before.json'), 'new_api_attempts': 0,
          'parameter_status': 'FROZEN_BEFORE_L2', 'default_replacement_status': 'ORIGINAL_REMAINS_DEFAULT'})
    return {'status': 'READY', 'l2': 48, 'compatibility': 8, 'l3': 72, 'plan': str(root), 'new_api_attempts': 0}


def validate_plan(path):
    path = Path(path).resolve(); plan = read(path/'plan.json'); manifest = read(path/'manifest.json')
    if digest(plan) != manifest['plan_digest']: raise O4Error('plan_changed')
    for name, checksum in manifest['snapshot_sha256'].items():
        if sha(path/'code_snapshot'/name) != checksum: raise O4Error('snapshot_changed', name)
    if not Path(__file__).resolve().is_relative_to(path/'code_snapshot'):
        raise O4Error('wrong_import_path', 'run with python -P and PYTHONPATH pointing to this plan/code_snapshot')
    return path, plan


def summarize_results(root, jobs):
    rows = []; failures = []; decision_times = []
    for job in jobs:
        p = root/'episodes'/f'{job["job_id"]}.json'
        if not p.exists():
            if job['status'] == 'FAIL': failures.append(job)
            continue
        result = read(p); summary = result['summary']; event_stats = []
        for event in result['events']:
            if 'search_trace' not in event: continue
            trace = event['search_trace']
            decision_times.append({'job_id': job['job_id'], 'task_id': job['task_id'], 'group': job['group'],
                                   'method': job['method'], 'seconds': trace.get('elapsed_seconds'),
                                   'runtime': trace.get('generation_seconds'), 'logical_evaluations': trace['evaluations']})
            event_stats.append({'evaluations': trace['evaluations'], 'truncated': trace['search_truncated'],
                                'candidate_counts': [len(g['candidates']) for g in event['groups']],
                                'coverage_lost': [g['generation'].get('coverage_lost', []) for g in event['groups']]})
        volume = sum(__import__('math').prod(o['oriented_size_mm']) for o in result['final_state']['placed_items'])
        container = result['final_state']['container']
        rows.append({**job, **summary, 'pallet_volume_utilization': volume/(container['length_mm']*container['width_mm']*container['max_height_mm']),
                     'layer_heights_mm': sorted({o['pose']['z_base_mm'] for o in result['final_state']['placed_items']}),
                     'event_stats': event_stats, 'episode_sha256': sha(p)})
    write(root/'metrics/rows.json', rows); write(root/'metrics/decision_times.json', decision_times)
    write(root/'metrics/failures.json', failures)
    aggregates = []
    for stage in sorted({j['stage'] for j in jobs}):
        for method in sorted({j['method'] for j in jobs if j['stage'] == stage}):
            for group in sorted({j['group'] for j in jobs if j['stage'] == stage and j['method'] == method}):
                subset = [r for r in rows if (r['stage'], r['method'], r['group']) == (stage, method, group)]
                n = sum((j['stage'], j['method'], j['group']) == (stage, method, group) for j in jobs)
                aggregates.append({'stage': stage, 'method': method, 'group': group, 'planned': n, 'executed': len(subset),
                                   'placed': sum(r['placed_items'] for r in subset), 'clean_completed': sum(r['clean_completed'] for r in subset),
                                   'mean_volume_ratio': sum(r['placed_volume_ratio'] for r in subset)/len(subset) if subset else None,
                                   'violating_steps': sum(r['violating_steps'] for r in subset),
                                   'max_evaluations': max((s['evaluations'] for r in subset for s in r['event_stats']), default=0)})
    write(root/'metrics/summary.json', aggregates)
    return rows, aggregates


def run(plan_path, output, *, resume=False, max_jobs=None, stage='L2'):
    if max_jobs is not None and (type(max_jobs) is not int or max_jobs < 1): raise O4Error('invalid_job_limit')
    path, plan = validate_plan(plan_path)
    root = Path(output).resolve()
    if not resume:
        root = new_output(output)
        atomic(root/'run.json', {'plan': str(path), 'plan_digest': digest(plan), 'stage': stage, 'new_api_attempts': 0})
        atomic(root/'jobs.json', copy.deepcopy(plan['l2_jobs'] if stage == 'L2' else plan['l3_jobs']))
    else:
        identity = read(root/'run.json')
        if identity['plan'] != str(path) or identity['plan_digest'] != digest(plan) or identity['stage'] != stage: raise O4Error('resume_identity_changed')
    if stage != 'L2': raise O4Error('l3_requires_separate_evidence_gate')
    tasks = {t['task_id']: t for t in plan['tasks']}
    with exclusive(root/'run.lock'):
        jobs = read(root/'jobs.json'); remaining = [j for j in jobs if j['status'] in ('NOT_RUN', 'IN_PROGRESS')]
        for job in remaining[:max_jobs] if max_jobs is not None else remaining:
            identifier = job['job_id']; print(identifier, flush=True); job['status'] = 'IN_PROGRESS'; atomic(root/'jobs.json', jobs)
            config = plan['group_configurations'][job['group']]; task = tasks[job['task_id']]
            compiler = LocalCompiler(job['backend'], task['reference_policy'] if job['backend'] == 'oracle_ast' else None)
            checkpoint_path = root/'checkpoints'/f'{identifier}.json'
            checkpoint = read(checkpoint_path) if checkpoint_path.exists() else None
            def save(cp, phase):
                if phase in ('after_decision', 'after_failure'): atomic(checkpoint_path, cp)
            started = time.perf_counter()
            try:
                result = episode(task, job['backend'], job['method'], config, compiler, identifier, resume=checkpoint, on_checkpoint=save)
                # Initial execution already checks binding/commit and downstream reference.
                # No additional full-order replay is scheduled here.
                for event in result['events']:
                    if 'search_trace' in event and (event['search_trace']['evaluations'] > 256 or any(len(g['candidates']) > 16 for g in event['groups'])):
                        raise O4Error('budget_exceeded')
                if result['summary']['final_business_violations'] or result['summary']['violating_steps']:
                    raise O4Error('actual_business_violation')
                atomic(root/'episodes'/f'{identifier}.json', result)
                job.update(status='PASS', elapsed_seconds=time.perf_counter()-started)
            except Exception as exc:
                job.update(status='FAIL', error=str(exc), elapsed_seconds=time.perf_counter()-started)
                atomic(root/'errors'/f'{identifier}.json', {'error': str(exc), 'traceback': traceback.format_exc()})
            atomic(root/'jobs.json', jobs)
            atomic(root/'progress.json', {s: sum(j['status'] == s for j in jobs) for s in ('PASS', 'FAIL', 'IN_PROGRESS', 'NOT_RUN')})
        rows, summary = summarize_results(root, jobs)
        complete = all(j['status'] in ('PASS', 'FAIL') for j in jobs)
        report = {'stage': stage, 'planned_jobs': len(jobs), 'recorded_episodes': len(rows),
                  'engineering_status': 'L2_EXECUTION_COMPLETE_PENDING_AUDIT' if complete and all(j['status'] == 'PASS' for j in jobs) else 'FAIL' if any(j['status'] == 'FAIL' for j in jobs) else 'PARTIAL',
                  'performance_status': 'NOT_ASSESSED', 'default_replacement_status': 'ORIGINAL_REMAINS_DEFAULT',
                  'new_api_attempts': 0, 'loaded_module': __file__, 'business_support_quality': 'NOT_IMPLEMENTED'}
        atomic(root/'acceptance_report.json', report)
        return report
