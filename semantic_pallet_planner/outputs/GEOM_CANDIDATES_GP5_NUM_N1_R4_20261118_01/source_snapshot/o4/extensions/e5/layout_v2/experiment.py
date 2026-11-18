"""Local evidence collection. No transport, remote CLI, or legacy batch replay."""
import hashlib
import shutil
import sys
from pathlib import Path
from ....common import read, write, digest, O4Error
from ...e2.candidates import key
from .diagnostics import inspect_group

WORKSPACE = next(p for p in Path(__file__).resolve().parents if (p/'semantic_pallet_dataset_v1').is_dir() and (p/'docs').is_dir())
PACKAGE = Path(__file__).resolve().parents[4]
OUTPUTS = Path('semantic_pallet_planner/outputs')
BASE_PLAN = OUTPUTS/'PLAN_O4_E5_090_OFFLINE_READY_20261026_06'
SPATIAL = OUTPUTS/'EXP_O4_E5_SPATIAL_LOCAL_20261027_01'
ROLLBACK = OUTPUTS/'EXP_O4_E5_ROLLBACK_SMOKE_20261027_01'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def source_manifest():
    return {str(p.relative_to(WORKSPACE)): sha(p) for p in sorted(PACKAGE.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def protect(root):
    roots = [WORKSPACE/OUTPUTS, WORKSPACE/'report', WORKSPACE/'semantic_pallet_dataset_v1',
             PACKAGE/'o4/extensions/e2', PACKAGE/'o4/extensions', PACKAGE/'planner', PACKAGE/'schemas']
    result = {}
    for base in roots:
        for path in base.rglob('*'):
            if path.is_file() and not path.is_relative_to(root) and '__pycache__' not in path.parts:
                # E5 is the authorized edit area; preserve other extension families.
                if path.is_relative_to(PACKAGE/'o4/extensions/e5'): continue
                name = str(path.relative_to(WORKSPACE))
                if name not in result: result[name] = sha(path)
    return result


def check_protection(before):
    changed = [name for name, checksum in before.items()
               if not (WORKSPACE/name).is_file() or sha(WORKSPACE/name) != checksum]
    return {'status': 'FAIL' if changed else 'PASS', 'checked': len(before), 'changed': changed}


def new_output(output):
    root = Path(output).resolve()
    if not root.is_relative_to(WORKSPACE/OUTPUTS): raise O4Error('output_outside_experiments')
    root.mkdir(parents=True, exist_ok=False)
    return root


def event_report(path, event_index, config):
    result = read(path); event = result['events'][event_index]
    req = event['request']; ast = event['response']['policy_ast']
    groups = [inspect_group(event['before'], req, ast, g['pick_item_id'], config) for g in event['groups']]
    saved = []
    for g in event['groups']:
        saved.append({'pick_item_id': g['pick_item_id'], 'selected': g['selected'],
                      'candidate_snapshot': g['candidates'], 'trace': g['trace']})
    return {'episode_path': str(path.relative_to(WORKSPACE)), 'episode_sha256': sha(path),
            'job_id': result['job_id'], 'event_index': event_index, 'event': event['event'],
            'state_digest': digest(event['before']), 'request_digest': digest(req), 'ast_digest': digest(ast),
            'public_state': event['before'], 'request': req, 'ast': ast,
            'groups': groups, 'saved_groups': saved, 'saved_search_trace': event['search_trace'],
            'saved_action': event['action'], 'scope': 'fixed_public_state_diagnostic_not_full_order',
            'global_infeasibility': 'NOT_PROVEN'}


def p0(output):
    root = new_output(output)
    print('P0: hashing protected historical files', flush=True)
    before = protect(root); write(root/'protected.before.json', before)
    sources = source_manifest()
    snapshot = WORKSPACE/BASE_PLAN/'private/input_snapshot.json'
    config_path = WORKSPACE/BASE_PLAN/'config.snapshot.json'; config = read(config_path)
    write(root/'manifest.json', {'stage': 'P0', 'new_api_attempts': 0,
          'python': sys.executable, 'loaded_module': __file__, 'source_sha256': sources,
          'input_sha256': {str(p.relative_to(WORKSPACE)): sha(p) for p in (snapshot, config_path)},
          'planned_cases': ['original_second', 'withdrawn_v1_second', 'rollback_four_methods'],
          'engineering_status': 'IN_PROGRESS', 'performance_status': 'NOT_RUN',
          'default_replacement_status': 'ORIGINAL_REMAINS_DEFAULT'})
    shutil.copytree(PACKAGE, root/'code_snapshot/semantic_pallet_planner', ignore=shutil.ignore_patterns('__pycache__'))
    write(root/'config.snapshot.json', config)
    data = read(snapshot); write(root/'input.snapshot.json', {'tasks': data['tasks'], 'constructs': data['constructs']})
    reports = []
    for name, filename in [('original_second', 'SP000_E5_SRC02_C0_baseline_single_oracle_ast.json'),
                           ('withdrawn_v1_second', 'SP003_E5_SRC02_C0_combined_single_oracle_ast.json')]:
        path = WORKSPACE/SPATIAL/'episodes'/filename
        record = read(path); index = [i for i, e in enumerate(record['events']) if e.get('groups')][1]
        print('P0:', name, 'event', index, flush=True)
        report = event_report(path, index, config); write(root/'cases'/f'{name}.json', report); reports.append((name, report))
    for path in sorted((WORKSPACE/ROLLBACK/'episodes').glob('*.json')):
        record = read(path); method = record['summary']['planner']; timeline = []
        for index, e in enumerate(record['events']):
            if not e.get('groups'): continue
            print('P0:', method, 'event', index, flush=True)
            report = event_report(path, index, config)
            write(root/'cases'/f'rollback_{method}_{index:03d}.json', report)
            timeline.append({'event_index': index, 'arrived_ids': e['before']['arrived_ids'],
                             'placed_ids': [o['item_id'] for o in e['before']['placed_items']],
                             'action': e['action'], 'counts': [g['counts'] for g in report['groups']],
                             'business_rejections': sorted({v for g in report['groups'] for r in g['rows'] for v in r['business_rejection_codes']}),
                             'search_evaluations': e['search_trace']['evaluations'],
                             'search_truncated': e['search_trace']['search_truncated']})
        write(root/'timelines'/f'{method}.json', {'summary': record['summary'], 'events': timeline})
    original = reports[0][1]; old_rows = original['groups'][0]['rows']
    aligned = [r for r in old_rows if key(r['candidate'])[:4] == (-105, -240, 0, 0)]
    if len(aligned) != 1 or aligned[0]['retained']: raise O4Error('original_case_not_confirmed')
    historical = reports[1][1]['saved_groups'][0]
    selected = historical['selected']; qualities = historical['trace']['spatial_qualities']
    alternative = [c for c in historical['candidate_snapshot'] if key(c)[:4] in ((-50, 295, 0, 90), (50, 295, 0, 90))]
    selected_quality = qualities[selected['candidate_id']]
    comparison = [{'pose': c['pose'], 'quality': qualities[c['candidate_id']]} for c in alternative]
    if key(selected)[:4] != (0, 305, 0, 90) or len(alternative) != 2: raise O4Error('v1_case_not_confirmed')
    write(root/'p0_findings.json', {
        'original_second': {'classification': 'compression', 'aligned_candidate': aligned[0],
                            'correction': 'original boxes touch at y=-95; x edges are not aligned'},
        'withdrawn_v1_second': {'classification': 'position_ranking', 'saved_selected': selected,
                                'saved_quality': selected_quality, 'saved_alternatives': comparison,
                                'correction': '10mm gap follows pallet boundary and box size, not an explicit gap10 sample',
                                'note': 'historical quality read from saved trace; no withdrawn code imported'},
        'rollback_four_methods': {'classification': 'terminal_sampled_business_filter',
                                  'early_layout_causal_effect': 'NOT_PROVEN_WITHOUT_BRANCH_CONTINUATION',
                                  'scope': 'each method follows its own arrival prefix; full per-event timeline retained'},
        'decision': 'P1 ranking and P2 retention are both needed; no new coordinate backend justified',
        'business_support_quality': 'NOT_IMPLEMENTED', 'new_api_attempts': 0})
    print('P0: checking protected historical files', flush=True)
    protected = check_protection(before); write(root/'protected.after.json', protected)
    if protected['status'] != 'PASS': raise O4Error('historical_files_changed')
    acceptance = {'stage': 'P0', 'diagnostic_status': 'PASS', 'engineering_status': 'P0_ONLY',
                  'performance_status': 'NOT_RUN', 'default_replacement_status': 'ORIGINAL_REMAINS_DEFAULT',
                  'new_api_attempts': 0, 'protected_files': protected['checked'],
                  'not_run': ['L1', 'L2', 'L3', 'branch_interventions', 'P3_business_support_prediction']}
    write(root/'acceptance_report.json', acceptance)
    return acceptance
