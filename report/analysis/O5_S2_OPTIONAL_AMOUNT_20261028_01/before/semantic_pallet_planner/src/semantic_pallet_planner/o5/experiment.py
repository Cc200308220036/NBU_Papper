"""Offline plan/run/resume/verify CLI backend; no network implementation exists."""
import copy
import importlib.metadata
import platform
import shutil
from pathlib import Path
from .common import ROOT, VERSION, O5Error, atomic, digest, exclusive, new_directory, read, sha
from .config import load
from .data import validate_dataset
from .episode import run_episode, verify_episode
from .schemas import validate
from .testing import OfflineTransport, fixture_task


def source_files():
    package = ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
    files = {str(p.relative_to(ROOT)): sha(p) for p in sorted(package.rglob('*.py'))}
    for name in ('semantic_pallet_dataset_v1/configs/mvd_v0.1.json',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        p = Path(name) if name.startswith('/') else ROOT/name
        files[name] = sha(p)
    return files


def dependencies():
    return {'python': platform.python_version(), **{name: importlib.metadata.version(name) for name in ('Pillow', 'jsonschema', 'numpy')}}


def prepare(dataset, output, config=None, *, count=2, stub_policy='first', fixture=False):
    cfg = load(config)
    manifest = {'scope': 'SYNTHETIC_PROTOCOL_FIXTURES_NOT_RESEARCH_DATA'} if fixture else validate_dataset(dataset)
    if type(count) is not int or not 1 <= count <= 20 or stub_policy not in ('first', 'stop'):
        raise O5Error('INVALID_OFFLINE_PLAN')
    if fixture:
        tasks = [fixture_task(14), fixture_task(20, length=220, width=180, height=80)][:count]
        for index, task in enumerate(tasks):
            task['task_id'] += f'_{index+1}'
            task['source_cluster_id'] += f'_{index+1}'
    else:
        tasks = read(Path(dataset)/'private/development.json')[:count]
    if len(tasks) != count:
        raise O5Error('INSUFFICIENT_DEVELOPMENT_TASKS')
    jobs = [{'job_id': f'J{i+1:03d}_{method}', 'task_id': task['task_id'], 'method': method,
             'attempt_limit': 2*len(task['items']) if method == 'D0' else 0}
            for i, task in enumerate(tasks) for method in cfg['methods']]
    plan = {'schema_version': 'o5_plan_manifest_v1', 'protocol_version': VERSION,
            'mode': 'OFFLINE_ENGINEERING_ONLY', 'dataset_path': 'PROTOCOL_FIXTURE_ONLY' if fixture else str(Path(dataset).resolve()),
            'dataset_digest': digest(manifest), 'config': cfg, 'source_files': source_files(),
            'dependency_versions': dependencies(), 'jobs': jobs, 'stub_policy': stub_policy, 'new_api_attempts': 0}
    validate('PlanManifest', plan)
    dest = new_directory(output)
    atomic(dest/'plan.json', plan)
    atomic(dest/'private/tasks.json', tasks)
    (dest/'private/tasks.json').chmod(0o400)
    for name, checksum in plan['source_files'].items():
        if not name.startswith('/'):
            target = dest/'code_snapshot'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/name, target)
    atomic(dest/'manifest.json', {'schema_version': 'o5_offline_plan_seal_v1', 'plan_digest': digest(plan),
           'tasks_digest': digest(tasks), 'snapshot': {str(p.relative_to(dest)): sha(p) for p in (dest/'code_snapshot').rglob('*') if p.is_file()}})
    return {'status': 'PASS', 'jobs': len(jobs), 'mode': plan['mode'], 'new_api_attempts': 0}


def validate_plan(root):
    root = Path(root)
    plan = validate('PlanManifest', read(root/'plan.json'))
    seal = read(root/'manifest.json')
    tasks = read(root/'private/tasks.json')
    if (digest(plan) != seal['plan_digest'] or digest(tasks) != seal['tasks_digest']
            or source_files() != plan['source_files'] or dependencies() != plan['dependency_versions']):
        raise O5Error('PLAN_OR_SOURCE_DRIFT')
    expected_data = ({'scope': 'SYNTHETIC_PROTOCOL_FIXTURES_NOT_RESEARCH_DATA'} if plan['dataset_path'] == 'PROTOCOL_FIXTURE_ONLY'
                     else validate_dataset(plan['dataset_path']))
    if digest(expected_data) != plan['dataset_digest']:
        raise O5Error('DATASET_CHANGED')
    if any(sha(root/name) != value for name, value in seal['snapshot'].items()):
        raise O5Error('SNAPSHOT_CHANGED')
    return plan, tasks


def execute(plan_root, output, *, resume=False, max_jobs=None, stop_after=None):
    if any(v is not None and (type(v) is not int or v < 1) for v in (max_jobs, stop_after)):
        raise O5Error('INVALID_JOB_LIMIT')
    plan_root = Path(plan_root).resolve()
    plan, tasks = validate_plan(plan_root)
    dest = Path(output).resolve() if resume else new_directory(output)
    identity = digest([plan, tasks, str(dest)])
    with exclusive(dest/'run.lock'):
        if resume:
            state = read(dest/'run.json')
            if state['identity'] != identity:
                raise O5Error('RUN_IDENTITY_CHANGED')
        else:
            state = {'schema_version': 'o5_run_state_v1', 'identity': identity, 'plan': str(plan_root),
                     'jobs': [{**copy.deepcopy(j), 'status': 'NOT_RUN'} for j in plan['jobs']], 'new_api_attempts': 0}
            atomic(dest/'run.json', state)
        if len(state['jobs']) != len(plan['jobs']) or [{k: j.get(k) for k in plan['jobs'][i]} for i, j in enumerate(state['jobs'])] != plan['jobs']:
            raise O5Error('JOB_REGISTRY_CHANGED')
        by_id = {t['task_id']: t for t in tasks}
        processed = 0
        for job in state['jobs']:
            if job['status'] == 'COMPLETE':
                verify_episode(by_id[job['task_id']], job['method'], plan['config'], dest/'jobs'/job['job_id'],
                               job['job_id'], identity, job['attempt_limit'])
                continue
            if max_jobs is not None and processed >= max_jobs:
                break
            directory = dest/'jobs'/job['job_id']
            job['status'] = 'IN_PROGRESS'
            atomic(dest/'run.json', state)
            try:
                result = run_episode(by_id[job['task_id']], job['method'], plan['config'], directory,
                                     job['job_id'], identity, transport=OfflineTransport(plan['stub_policy']),
                                     attempt_limit=job['attempt_limit'],
                                     resume=(directory/'checkpoint.json').exists(), stop_after=stop_after)
                job['status'] = 'CHECKPOINTED' if result.get('execution_status') == 'CHECKPOINTED' else 'COMPLETE'
            except O5Error as error:
                job['status'] = 'UNKNOWN_IN_FLIGHT' if error.code == 'UNKNOWN_IN_FLIGHT' else 'ERROR'
                job['error'] = error.code
                atomic(dest/'run.json', state)
                raise
            atomic(dest/'run.json', state)
            processed += 1
        complete = all(j['status'] == 'COMPLETE' for j in state['jobs'])
        report = {'schema_version': 'o5_execution_report_v1', 'status': 'PASS' if complete else 'PARTIAL',
                  'mode': plan['mode'], 'planned_jobs': len(state['jobs']),
                  'completed_jobs': sum(j['status'] == 'COMPLETE' for j in state['jobs']),
                  'new_api_attempts': 0, 'model_performance': 'NOT_MEASURED'}
        atomic(dest/'acceptance_report.json', report)
        return report


def verify(root):
    root = Path(root).resolve()
    state = read(root/'run.json')
    plan, tasks = validate_plan(state['plan'])
    if state['identity'] != digest([plan, tasks, str(root)]):
        raise O5Error('RUN_IDENTITY_CHANGED')
    if len(state['jobs']) != len(plan['jobs']) or any({k: job.get(k) for k in expected} != expected
               for job, expected in zip(state['jobs'], plan['jobs'])):
        raise O5Error('JOB_REGISTRY_CHANGED')
    by_id = {t['task_id']: t for t in tasks}
    checked = []
    for job in state['jobs']:
        if job['status'] == 'COMPLETE':
            checked.append(verify_episode(by_id[job['task_id']], job['method'], plan['config'],
                           root/'jobs'/job['job_id'], job['job_id'], state['identity'], job['attempt_limit']))
    return {'status': 'PASS' if len(checked) == len(plan['jobs']) else 'PARTIAL',
            'checked_jobs': len(checked), 'planned_jobs': len(plan['jobs']), 'checks': checked,
            'new_api_attempts': 0, 'model_performance': 'NOT_MEASURED'}


def pilot_draft(dataset, output):
    manifest = read(Path(dataset)/'manifest.json')
    if manifest['status'] == 'PASS':
        validate_dataset(dataset)
    cfg = load()
    tasks = read(Path(dataset)/'private/development.json')[:8] if manifest['status'] == 'PASS' else []
    draft = {'schema_version': 'o5_s2_pilot_draft_v1', 'status': 'DRAFT_NOT_EXECUTABLE',
             'dataset_digest': digest(manifest), 'source_files': source_files(), 'config': cfg,
             'tasks': [t['task_id'] for t in tasks], 'methods': ['G0', 'D0'],
             'maximum_selection_attempts': 2*sum(len(t['items']) for t in tasks) if tasks else None,
             'data_status': manifest['status'],
             'global_attempt_ceiling': 320, 'model': None, 'provider': None, 'provider_seed_support': 'NOT_VERIFIED',
             'model_snapshot': None, 'model_multimodal_preflight': 'NOT_RUN', 'image_token_billing': None,
             'currency': None, 'amount_limit': None, 'unit_prices': None, 'cost_status': 'COST_NOT_FROZEN',
             'runtime_remote_entry': 'NOT_IMPLEMENTED_IN_S1', 'new_api_attempts': 0,
             'gates': {'final_protocol_valid_min': .98, 'actual_physical_violations_max': 0,
                       'ceiling_risk': 'both methods >=7/8 complete and mean VR>=.98'},
             'before_execution': ['freeze exact model, prices, image accounting, context limit and amount cap',
                                  'verify real PNG transmission and provider response metadata',
                                  'obtain explicit user instruction for this S2 plan',
                                  'freeze D0 after successful pilot before any training collection']}
    dest = new_directory(output)
    atomic(dest/'pilot_draft.json', draft)
    return draft
