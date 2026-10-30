"""Predeclared twelve-call T0 runner. No order episodes or remote backends."""
import argparse
import copy
import hashlib
import importlib
import json
import shutil
import sys
from pathlib import Path

from ....common import digest
from ..layout_v2.config import DEFAULT
from . import diagnostics

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'semantic_pallet_dataset_v1').is_dir() and (p/'docs').is_dir())
OUT = ROOT/'semantic_pallet_planner/outputs'
TARGET = OUT/'EXP_O4_E5_CAPACITY_NEXT_T0_20261027_01'
OLD = OUT/'PLAN_O4_E5_LAYOUT_V2_20261027_01'
EP = OUT/'EXP_O4_E5_LAYOUT_V2_L2_20261027_01/episodes'
P0 = OUT/'EXP_O4_E5_LAYOUT_V2_P0_20261027_01'


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def read(p): return json.loads(p.read_text())


def write(p, data):
    with p.open('x') as f: json.dump(data, f, ensure_ascii=False, indent=2); f.write('\n')


def prepare():
    TARGET.mkdir(exist_ok=False)
    frozen = read(OLD/'manifest.json')
    checks = {}
    for section, base in [('source_sha256', ROOT), ('snapshot_sha256', OLD/'code_snapshot'), ('input_sha256', ROOT)]:
        bad = [p for p, h in frozen[section].items() if sha(base/p) != h]
        checks[section] = {'files': len(frozen[section]), 'mismatches': bad}
        assert not bad, bad
    plan = read(OLD/'plan.json'); assert digest(plan) == frozen['plan_digest']
    config = copy.deepcopy(plan['group_configurations']['B'])
    assert config['o4_e5_layout'] == {**DEFAULT, 'candidate_retention': True, 'ranking': False}
    inputs = {}; evidence = {}
    for c in (0, 1):
        a = EP/f'L2_E5_SRC04_C{c}_A_buffer_search_oracle_ast.json'
        b = EP/f'L2_E5_SRC04_C{c}_B_buffer_search_oracle_ast.json'
        ar, br = read(a), read(b)
        for event_index, q in [(3, 1+c), (5, 3+c)]:
            e = ar['events'][event_index]
            assert e['before'] == br['events'][event_index]['before']
            inputs[f'Q{q}'] = {'source': str(a.relative_to(ROOT)), 'source_sha256': sha(a),
                'paired_B_source': str(b.relative_to(ROOT)), 'paired_B_sha256': sha(b),
                'event_index': event_index, 'state': e['before'], 'request': e['request'], 'ast': e['response']['policy_ast']}
        for p in (a, b): evidence[str(p.relative_to(ROOT))] = sha(p)
    for q, name in [('Q6', 'original_second'), ('Q7', 'withdrawn_v1_second')]:
        p = P0/'cases'/f'{name}.json'; e = read(p)
        inputs[q] = {'source': str(p.relative_to(ROOT)), 'source_sha256': sha(p), 'event_index': e['event_index'],
                     'state': e['public_state'], 'request': e['request'], 'ast': e['ast'], 'saved_vectors': e['groups']}
    p = EP/'L2_E5_SRC00_C0_D_single_oracle_ast.json'; e = next(e for e in read(p)['events'] if e.get('groups'))
    inputs['Q5'] = {'source': str(p.relative_to(ROOT)), 'source_sha256': sha(p), 'event_index': 1,
                    'state': e['before'], 'request': e['request'], 'ast': e['response']['policy_ast'], 'saved_vectors': e['groups']}
    for v in inputs.values():
        v.update(state_digest=digest(v['state']), request_digest=digest(v['request']), ast_digest=digest(v['ast']))
    jobs = [{'id': f'Q{q}_U{u}', 'q': f'Q{q}', 'candidate': 'B', 'beam': 'v2' if u >= 2 else 'legacy', 'leaf': 'v2' if u % 2 else 'legacy'} for q in (1, 2) for u in range(4)]
    jobs += [{'id': f'Q{q}_{candidate}', 'q': f'Q{q}', 'candidate': candidate, 'beam': 'legacy', 'leaf': 'legacy'} for q in (3, 4) for candidate in ('legacy', 'B')]
    write(TARGET/'inputs.json', inputs); write(TARGET/'config.json', config); write(TARGET/'jobs.json', jobs)
    # Freeze the whole package before any diagnostic calls, then import only it.
    package = ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
    shutil.copytree(package, TARGET/'code_snapshot/semantic_pallet_planner', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    snapshot = {str(p.relative_to(TARGET/'code_snapshot')): sha(p) for p in (TARGET/'code_snapshot').rglob('*') if p.is_file()}
    source = {str(p.relative_to(ROOT)): sha(p) for p in package.rglob('*.py')}
    # Historical inventory, not planning replay. Include newly sealed V2 evidence.
    protected = {}
    for folder in (ROOT/'report', OUT):
        for p in folder.rglob('*'):
            if p.is_file() and TARGET not in p.parents and '__pycache__' not in p.parts:
                protected[str(p.relative_to(ROOT))] = sha(p)
    previous = read(P0/'protected.before.json')
    mismatches = [p for p, h in previous.items() if sha(ROOT/p) != h]
    assert not mismatches, mismatches
    write(TARGET/'protected.before.json', protected)
    write(TARGET/'manifest.json', {'stage': 'T0_FROZEN_BEFORE_CALLS', 'source_sha256': source,
        'snapshot_sha256': snapshot, 'frozen_v2_checks': checks, 'legacy_protection_checked': len(previous),
        'inputs_sha256': sha(TARGET/'inputs.json'), 'config_sha256': sha(TARGET/'config.json'), 'jobs_sha256': sha(TARGET/'jobs.json'),
        'budgets': [16, 48, 3, 8, 256], 'max_search_calls': 12, 'Q5_Q7_search_calls': 0,
        'loaded_module_prepare': __file__, 'python': sys.executable, 'new_api_attempts': 0})
    print(json.dumps({'prepared': str(TARGET), 'jobs': len(jobs), 'protected_files': len(protected)}, ensure_ascii=False), flush=True)


def run():
    m = read(TARGET/'manifest.json')
    assert Path(__file__).resolve().is_relative_to(TARGET/'code_snapshot')
    for section, base in [('source_sha256', ROOT), ('snapshot_sha256', TARGET/'code_snapshot')]:
        assert all(sha(base/p) == h for p, h in m[section].items()), section
    for name in ('inputs', 'config', 'jobs'): assert sha(TARGET/f'{name}.json') == m[f'{name}_sha256']
    inputs, config, jobs = [read(TARGET/f'{name}.json') for name in ('inputs', 'config', 'jobs')]
    (TARGET/'calls').mkdir(exist_ok=True)
    for job in jobs:
        dest = TARGET/'calls'/f'{job["id"]}.json'
        if dest.exists(): continue
        # Reservation persists even if interrupted. An incomplete call must be
        # reviewed, never automatically rerun under the fixed twelve-call limit.
        write(TARGET/'calls'/f'{job["id"]}.started.json', {'job': job, 'loaded_module': diagnostics.__file__})
        case = inputs[job['q']]
        r = diagnostics.search(case['state'], case['request'], case['ast'], config, job['candidate'], job['beam'], job['leaf'])
        r['job'] = job
        write(dest, r)
        print(json.dumps({'job': job['id'], 'selected': r['selected'], 'evaluations': r['evaluations'], 'depths': r['expanded_depth_distribution']}), flush=True)
    results = {j['id']: read(TARGET/'calls'/f'{j["id"]}.json') for j in jobs}
    same = {f'Q{q}_{a}_{b}': results[f'Q{q}_U{a}']['tree_digest'] == results[f'Q{q}_U{b}']['tree_digest'] for q in (1, 2) for a, b in ((0, 1), (2, 3))}
    assert all(same.values()), same
    write(TARGET/'local_diagnosis.json', {'search_calls': len(jobs), 'call_results': {k: f'calls/{k}.json' for k in results},
        'tree_consistency': same, 'Q5_Q7': 'saved vectors in inputs.json; no new searches',
        'loaded_modules': {name: importlib.import_module(name).__file__ for name in ('semantic_pallet_planner.o4.extensions.e2.planning', 'semantic_pallet_planner.o4.extensions.e5.layout_v2.planning', 'semantic_pallet_planner.o4.extensions.e5.layout_v3.diagnostics')},
        'analysis_status': 'RECORDED_PENDING_INTERPRETATION', 'new_api_attempts': 0})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['prepare', 'run'])
    args = parser.parse_args()
    prepare() if args.action == 'prepare' else run()
