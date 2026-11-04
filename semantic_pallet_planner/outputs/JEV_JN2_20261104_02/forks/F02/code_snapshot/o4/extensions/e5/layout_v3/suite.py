"""Independent B0 protocol: small proof, then a freshly frozen expansion."""
import copy
import json
import shutil
import sys
import time
from pathlib import Path
from ....common import digest, O4Error
from ..backends import LocalCompiler
from ..episode import episode
from ..storage import atomic, exclusive
from .config import DEFAULT
from .experiment import ROOT, OUT, OLD, TARGET, EP, read, sha, write

SMALL_PLAN = OUT/'PLAN_O4_E5_CAPACITY_NEXT_SMALL_20261027_01'
SMALL_RUN = OUT/'EXP_O4_E5_CAPACITY_NEXT_SMALL_20261027_01'
FINAL_PLAN = OUT/'PLAN_O4_E5_CAPACITY_NEXT_F_20261027_01'
FINAL_RUN = OUT/'EXP_O4_E5_CAPACITY_NEXT_EXPANDED_20261027_01'


def configuration(base):
    c = copy.deepcopy(base); c.pop('o4_e5_layout', None); c['o4_e5_capacity'] = copy.deepcopy(DEFAULT)
    return c


def freeze(root, plan):
    root.mkdir(exist_ok=False)
    write(root/'plan.json', plan)
    package = ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
    shutil.copytree(package, root/'code_snapshot/semantic_pallet_planner', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    write(root/'manifest.json', {'plan_digest': digest(plan), 'source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in package.rglob('*.py')},
        'snapshot_sha256': {str(p.relative_to(root/'code_snapshot')): sha(p) for p in (root/'code_snapshot').rglob('*') if p.is_file()},
        'loaded_module_prepare': __file__, 'python': sys.executable, 'new_api_attempts': 0,
        'default_replacement_status': 'ORIGINAL_REMAINS_DEFAULT', 'protected_manifest': str(TARGET/'protected.before.json')})


def prepare_small(test_xml):
    import xml.etree.ElementTree as ET
    evidence = ET.parse(test_xml).getroot()
    suites = [evidence] if evidence.tag == 'testsuite' else evidence.findall('testsuite')
    assert suites and not any(int(s.get(k, 0)) for s in suites for k in ('errors', 'failures', 'skipped'))
    diag = read(TARGET/'local_diagnosis.json'); assert diag['search_calls'] == 12 and all(diag['tree_consistency'].values())
    interpretation = ROOT/'report/analysis/O4_E5_CAPACITY_NEXT_20261027_01/t0_interpretation.json'
    assert all(read(interpretation)['checks'].values())
    old = read(OLD/'plan.json'); tasks = [t for t in old['tasks'] if t['source_order_key'] in old['l2_sources']]
    reuse = []; jobs = []
    for t in tasks:
        for method in ('single', 'buffer_search'):
            jobs.append({'job_id': f'SMALL_{t["task_id"]}_B0_{method}', 'task_id': t['task_id'], 'group': 'B0', 'method': method, 'status': 'NOT_RUN'})
            for group in ('A', 'B'):
                p = EP/f'L2_{t["task_id"]}_{group}_{method}_oracle_ast.json'
                r = read(p); assert r['summary']['execution_status'] == 'PASS'
                reuse.append({'group': group, 'task_id': t['task_id'], 'method': method, 'path': str(p.relative_to(ROOT)), 'sha256': sha(p),
                              'input_digest': digest(t), 'config_digest': digest(old['group_configurations'][group]), 'summary': r['summary'],
                              'role': 'original comparator' if group == 'A' else 'historical B equivalence reference, not an additional trial'})
    plan = {'protocol': 'capacity_next_B0_small_v1', 'tasks': tasks, 'jobs': jobs,
        'configurations': {'A': old['group_configurations']['A'], 'B0': configuration(old['base_config'])},
        'reuse': reuse, 'version': DEFAULT, 'selection': 'T0 supports retaining B candidates with legacy ranking; S/R/E not introduced',
        'posthoc_development_selection': True, 'test_xml_sha256': sha(Path(test_xml)), 't0_interpretation_sha256': sha(interpretation),
        'budget': [16, 48, 3, 8, 256], 'new_api_attempts': 0,
        'gates': {'volume_tolerance': 1e-9, 'minimum_gain': .01, 'count_gain': 1, 'task_loss_hold': 2, 'median_ratio': 2, 'p95_ratio': 3},
        'expansion': 'NEW 18 remaining development tasks A/F x single/search =72; only after small PASS'}
    freeze(SMALL_PLAN, plan)
    return {'plan': str(SMALL_PLAN), 'new_jobs': len(jobs), 'historical_reference_records': len(reuse)}


def validate_plan(root):
    m = read(root/'manifest.json'); plan = read(root/'plan.json')
    assert digest(plan) == m['plan_digest']
    assert Path(__file__).resolve().is_relative_to(root/'code_snapshot'), 'use frozen import path with python -P'
    assert all(sha(root/'code_snapshot'/p) == h for p,h in m['snapshot_sha256'].items())
    for row in plan.get('reuse', []): assert sha(ROOT/row['path']) == row['sha256']
    return plan


def run(expanded=False, resume=False, max_jobs=None):
    plan_root, dest = (FINAL_PLAN, FINAL_RUN) if expanded else (SMALL_PLAN, SMALL_RUN)
    plan = validate_plan(plan_root)
    if not resume:
        dest.mkdir(exist_ok=False); atomic(dest/'jobs.json', copy.deepcopy(plan['jobs']))
        atomic(dest/'run.json', {'plan_digest': digest(plan), 'loaded_module': __file__, 'new_api_attempts': 0})
    assert read(dest/'run.json')['plan_digest'] == digest(plan)
    tasks = {t['task_id']: t for t in plan['tasks']}
    with exclusive(dest/'run.lock'):
        jobs = read(dest/'jobs.json'); remaining = [j for j in jobs if j['status'] in ('NOT_RUN', 'IN_PROGRESS')]
        for j in remaining[:max_jobs] if max_jobs else remaining:
            print(j['job_id'], flush=True); j['status'] = 'IN_PROGRESS'; atomic(dest/'jobs.json', jobs)
            cp = dest/'checkpoints'/f'{j["job_id"]}.json'; t = tasks[j['task_id']]
            def save(checkpoint, phase):
                if phase in ('after_decision', 'after_failure'): atomic(cp, checkpoint)
            started = time.perf_counter()
            try:
                r = episode(t, 'oracle_ast', j['method'], plan['configurations'][j['group']], LocalCompiler('oracle_ast', t['reference_policy']),
                            j['job_id'], resume=read(cp) if cp.exists() else None, on_checkpoint=save)
                for e in r['events']:
                    if 'search_trace' not in e: continue
                    assert e['search_trace']['evaluations'] <= 256 and sum(len(g['candidates']) for g in e['groups']) <= 48
                    assert all(len(g['candidates']) <= 16 for g in e['groups'])
                    assert e['search_trace'].get('max_depth', 0) <= 3 and e['search_trace'].get('max_beam', 0) <= 8
                assert not r['summary']['final_business_violations'] and not r['summary']['violating_steps']
                atomic(dest/'episodes'/f'{j["job_id"]}.json', r)
                j.update(status='PASS', elapsed_seconds=time.perf_counter()-started)
            except Exception as exc:
                j.update(status='FAIL', error=repr(exc)); atomic(dest/'errors'/f'{j["job_id"]}.json', {'error': repr(exc)})
            atomic(dest/'jobs.json', jobs)
            atomic(dest/'progress.json', {s: sum(j['status'] == s for j in jobs) for s in ('PASS', 'FAIL', 'IN_PROGRESS', 'NOT_RUN')})
            if j['status'] == 'FAIL': break
    return {'output': str(dest), 'statuses': read(dest/'progress.json')}


def small_gate():
    plan = read(SMALL_PLAN/'plan.json'); jobs = read(SMALL_RUN/'jobs.json')
    assert len(jobs) == 12 and all(j['status'] == 'PASS' for j in jobs)
    pairs = []; equivalent = True
    for j in jobs:
        r = read(SMALL_RUN/'episodes'/f'{j["job_id"]}.json')
        a, b = [next(v for v in plan['reuse'] if v['task_id'] == j['task_id'] and v['method'] == j['method'] and v['group'] == g) for g in ('A', 'B')]
        old_b = read(ROOT/b['path'])
        def trajectory(result):
            return [(e['before'], next(({'pick': c['pick_item_id'], 'pose': c['pose'], 'size': c['oriented_size_mm']} for c in e['candidates'] if e.get('action') and c['candidate_id'] == e['action']['candidate_id']), None), e['after']) for e in result['events'] if 'search_trace' in e]
        equal = trajectory(r) == trajectory(old_b); equivalent &= equal
        s, sa = r['summary'], a['summary']
        pairs.append({'task_id': j['task_id'], 'method': j['method'], 'A': sa, 'B0': s,
                      'F': s, 'F_is_B0': True, 'historical_B_trajectory_equal': equal,
                      'count_delta': s['placed_items']-sa['placed_items'], 'volume_delta': s['placed_volume_ratio']-sa['placed_volume_ratio'],
                      'hold': s['placed_items'] < sa['placed_items']-1 or (sa['clean_completed'] and not s['clean_completed']),
                      'episode_sha256': sha(SMALL_RUN/'episodes'/f'{j["job_id"]}.json')})
    aggregates = []
    for method in ('single', 'buffer_search'):
        subset = [p for p in pairs if p['method'] == method]
        aggregates.append({'method': method, 'count_delta': sum(p['count_delta'] for p in subset),
                           'mean_volume_delta': sum(p['volume_delta'] for p in subset)/6,
                           'clean_delta': sum(int(p['B0']['clean_completed'])-int(p['A']['clean_completed']) for p in subset)})
    noninferior = all(a['count_delta'] >= 0 and a['mean_volume_delta'] >= -1e-9 and a['clean_delta'] >= 0 for a in aggregates)
    gain = any(a['count_delta'] >= 1 and a['mean_volume_delta'] >= .01 for a in aggregates)
    passed = equivalent and noninferior and gain and not any(p['hold'] for p in pairs)
    result = {'engineering_status': 'SMALL_EXECUTION_PASS' if equivalent else 'EQUIVALENCE_FAILED',
              'performance_status': 'SMALL_PASS' if passed else 'SMALL_HOLD', 'default_replacement_status': 'ORIGINAL_REMAINS_DEFAULT',
              'aggregates': aggregates, 'pairs': pairs, 'new_api_attempts': 0, 'F': 'B0', 'S_R_E': 'NOT_IMPLEMENTED_NOT_REQUIRED_BY_T0'}
    write(SMALL_RUN/'small_gate.json', result)
    return {k:v for k,v in result.items() if k != 'pairs'}


def prepare_final():
    gate = read(SMALL_RUN/'small_gate.json'); assert gate['performance_status'] == 'SMALL_PASS'
    old = read(OLD/'plan.json'); small = read(SMALL_PLAN/'plan.json')
    # No production algorithm changes after small proof are allowed into F.
    m = read(SMALL_PLAN/'manifest.json')
    assert all(sha(ROOT/p) == h for p,h in m['source_sha256'].items())
    tasks = [t for t in old['tasks'] if t['source_order_key'] not in old['l2_sources']]
    assert len(tasks) == 18
    jobs = [{'job_id': f'EXPAND_{t["task_id"]}_{g}_{method}', 'task_id': t['task_id'], 'group': g, 'method': method, 'status': 'NOT_RUN'}
            for t in tasks for g in ('A', 'F') for method in ('single', 'buffer_search')]
    plan = {**small, 'protocol': 'capacity_next_B0_final_expansion_v1', 'tasks': tasks, 'jobs': jobs,
            'configurations': {'A': small['configurations']['A'], 'F': small['configurations']['B0']},
            'small_gate_sha256': sha(SMALL_RUN/'small_gate.json'), 'F': 'B0', 'old_D_L3': 'NOT_RUN_NOT_RESUMED',
            'major_denominator': 'small 24 A/F records plus expanded 72 =96 records; 24 tasks, 12 historical development sources',
            'small_F_records_sha256': {j['job_id']: sha(SMALL_RUN/'episodes'/f'{j["job_id"]}.json') for j in read(SMALL_RUN/'jobs.json')},
            'independent_generalization': 'NOT_MEASURED'}
    freeze(FINAL_PLAN, plan)
    return {'F': 'B0', 'new_expansion_jobs': len(jobs), 'plan': str(FINAL_PLAN)}
