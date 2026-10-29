"""Read-only S2-C prerequisite inventory. Never imports a remote client or sends requests."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect():
    output = ROOT / 'semantic_pallet_planner/outputs'
    draft_path = output / 'PLAN_O5_DIRECT_MEMORY_S2_DRAFT_20261028_04/pilot_draft.json'
    dataset = output / 'DATA_O5_DIRECT_MEMORY_20261028_03'
    draft = json.loads(draft_path.read_text())
    manifest = json.loads((dataset / 'manifest.json').read_text())
    development_path = dataset / 'private/development.json'
    tasks = json.loads(development_path.read_text())[:8]
    task_ids = [task['task_id'] for task in tasks]
    lengths = [len(task['items']) for task in tasks]
    package = ROOT / 'semantic_pallet_planner/src/semantic_pallet_planner'
    runners = sorted(str(p.relative_to(ROOT)) for p in (package / 'runners').glob('*o5*.py'))
    o5_paths = sorted(p for p in output.glob('*O5*') if p.is_dir())
    plan_paths = [p for p in o5_paths if 'S2' in p.name and 'PILOT' in p.name and 'DRAFT' not in p.name]
    preflight_paths = [p for p in o5_paths if 'PREFLIGHT' in p.name]
    observed = {str(p.relative_to(ROOT)): checksum(p) for p in [
        draft_path, dataset / 'manifest.json', development_path,
        package / 'o5/config.py', package / 'o5/selectors.py', package / 'o5/experiment.py',
        package / 'o5/schemas.py', package / 'runners/o5_direct_memory.py',
        ROOT / 'docs/02_阶段实施方案/O5/O5S2真实VLM接入与D0Pilot开发及验收规范_20261028.md']}
    source = (package / 'o5/selectors.py').read_text()
    blockers = []
    if draft['status'] != 'RUNNABLE':
        blockers.append('ONLY_NON_EXECUTABLE_S2_DRAFT')
    if 'REAL_TRANSPORT_FORBIDDEN_IN_S1' in source:
        blockers.append('CURRENT_SELECTOR_FORBIDS_REAL_TRANSPORT')
    if draft.get('model_multimodal_preflight') != 'PASS':
        blockers.append('REAL_MULTIMODAL_PREFLIGHT_NOT_PASSED')
    for key in ['provider', 'model', 'amount_limit', 'currency']:
        if draft.get(key) is None:
            blockers.append('MISSING_' + key.upper())
    if not plan_paths:
        blockers.append('NO_FROZEN_S2_PILOT_PLAN_IN_OUTPUT_ROOT')
    if not preflight_paths:
        blockers.append('NO_PREFLIGHT_ARTIFACT_IN_OUTPUT_ROOT')
    assert task_ids == draft['tasks']
    assert task_ids == [f'development_{i:03d}' for i in range(1, 9)]
    assert 2 * sum(lengths) == draft['maximum_selection_attempts'] == 290
    assert len(tasks) == 8 and manifest['status'] == 'PASS'
    assert checksum(development_path) == manifest['files']['private/development.json']
    return {
        'schema_version': 'o5_s2_c_readiness_audit_v1',
        'readiness': 'HOLD_ENGINEERING' if blockers else 'MANUAL_VALIDATION_REQUIRED',
        'phase': 'PRE_EXECUTION_READINESS_NOT_PILOT_RESULT',
        'scope': 'current worktree and immediate O5 output directories; external branches/paths not inspected',
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'git_status': subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True),
        'blockers': blockers,
        'draft': str(draft_path.relative_to(ROOT)),
        'draft_status': draft['status'],
        'dataset_status': manifest['status'],
        'split_counts': manifest['split_counts'],
        'development_file_checksum_verified': True,
        'tasks': task_ids, 'complete_order_lengths': lengths,
        'planned_jobs': 16, 'executed_s2_c_jobs_this_audit': 0,
        'pilot_attempt_ceiling': 290, 'g0_model_requests': 0,
        'new_api_attempts': 0, 'new_training_episodes': 0, 'new_test_episodes': 0,
        'protocol_valid_rate': None, 'actual_s2_physical_violations': None,
        'd0_frozen': False, 'performance_claim': 'NOT_MEASURED',
        'observed_runners': runners,
        'observed_o5_outputs': [str(p.relative_to(ROOT)) for p in o5_paths],
        'observed_file_sha256': observed,
        'note': 'No credential values read. Absent prerequisites must not be replaced with stub results or guessed authorization.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(inspect(), ensure_ascii=False, indent=2))
