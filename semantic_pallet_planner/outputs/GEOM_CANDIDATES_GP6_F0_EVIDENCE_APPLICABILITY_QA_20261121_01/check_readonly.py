"""Inspect persisted evidence, source bytes and schema definitions without planner imports."""
import hashlib
from importlib.metadata import PackageNotFoundError, version
import io
import json
from pathlib import Path
import platform
import subprocess
import tarfile

from jsonschema import Draft202012Validator

SOURCE = Path('semantic_pallet_planner/src/semantic_pallet_planner')
OUTPUTS = Path('semantic_pallet_planner/outputs')
TARGET = 'd2fe7261aee0ae9673bae0548a1e457557b82fe5'
HISTORICAL = '1c6c85613'
GP5 = OUTPUTS / 'GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01'
GP6 = OUTPUTS / 'GEOM_CANDIDATES_GP6_BRIDGE_01_FIX_20261121_01'
AUDIT = OUTPUTS / 'GEOM_CANDIDATES_GP6_F0_KERNEL_BRIDGE_FIX_20261121_01'
PRIOR = OUTPUTS / 'GEOM_CANDIDATES_GP6_BRIDGE_01_FIX_QA_20261121_01'


def git(*args):
    return subprocess.check_output(['git', *map(str, args)])


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode())


def read(path):
    return json.loads(path.read_bytes())


def archived_sources(commit):
    with tarfile.open(fileobj=io.BytesIO(git('archive', commit, SOURCE))) as archive:
        return {Path(member.name).relative_to(SOURCE).as_posix(): archive.extractfile(member).read()
                for member in archive.getmembers() if member.isfile()}


def manifest(files):
    return {name: sha(raw) for name, raw in files.items()
            if Path(name).suffix in ('.py', '.json')
            and not {'tests', '__pycache__'}.intersection(Path(name).parts)}


def installed(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return 'NOT_INSTALLED'


def main():
    old_files = archived_sources(HISTORICAL)
    new_files = archived_sources(TARGET)
    old, new = manifest(old_files), manifest(new_files)
    local = manifest({p.relative_to(SOURCE).as_posix(): p.read_bytes() for p in SOURCE.rglob('*')
                      if p.is_file() and p.suffix in ('.py', '.json')
                      and not {'tests', '__pycache__'}.intersection(p.relative_to(SOURCE).parts)})
    assert local == new
    for actual, receipt in ((old, read(GP5 / 'source_manifest.json')),
                            (new, read(GP6 / 'source_identity.json'))):
        assert actual == receipt['files'] and digest(actual) == receipt['source_identity']
    delta = [{'path': key, 'before': old.get(key), 'after': new.get(key)}
             for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)]
    previous = read(PRIOR / 'next_stage_admission.json')
    assert len(delta) == previous['current_cross_version_delta_count'] == 28
    assert digest(delta) == previous['current_cross_version_delta_digest']

    audit = read(AUDIT / 'historical_readonly_audit.json')
    receipt_path = Path(audit['receipt_path'])
    refs = {path: row['expected'] for path, row in audit['reference_checks'].items()}
    refs[str(receipt_path)] = audit['receipt_sha256']
    for path, expected in refs.items():
        assert sha(Path(path).read_bytes()) == sha(git('show', f'{TARGET}:{path}')) == expected
    receipt = read(receipt_path)
    plan = read(GP5 / 'acceptance_plan_FROZEN.json')
    monitor = read(GP5 / 'monitor_snapshot.json')
    assert receipt['runtime_version'] == plan['runtime_version'] == 'jev_packaging_geometry_order_v17'
    assert receipt['source_identity'] == plan['source_identity'] == digest(old)
    assert receipt['environment_digest'] == plan['environment_digest']
    assert receipt['publication_policy_digest'] == plan['publication_policy_digest']
    assert receipt['monitor_digest'] == digest(monitor)
    ledger = read(Path(receipt['counter_log']['path']))
    assert receipt['counts'] == ledger['counts']
    assert len(receipt['records']) == 4 and len(receipt['recovery']) == 6
    algorithm_files = monitor['algorithm_identity']['files_sha256']
    assert monitor['algorithm_identity']['source_digest'] == digest(algorithm_files)
    for name, expected in algorithm_files.items():
        key = f'jev_select/stability/{name}'
        assert sha(old_files[key]) == sha(new_files[key]) == expected
        assert sha((SOURCE / key).read_bytes()) == expected

    schemas = []
    for item in delta:
        key = item['path']
        if not key.endswith('.schema.json'):
            continue
        schema = json.loads(new_files[key])
        Draft202012Validator.check_schema(schema)
        assert schema['additionalProperties'] is False
        schemas.append(key)
    unchanged_schemas = {k for k in old if k.endswith('.schema.json')}
    assert all(old[k] == new[k] for k in unchanged_schemas)

    # A field-level check only. No plan creation, authorization or dispatch.
    plan_schema = json.loads(new_files['jev_select/schemas/geometry_jev_plan_v1.schema.json'])
    pair = {'model_calls_max': 1, 'shared_max_sends': 2}
    for name, value in pair.items():
        Draft202012Validator(plan_schema['properties'][name]).validate(value)
    assert 0 < pair['model_calls_max'] <= pair['shared_max_sends'] <= 76

    print(json.dumps({
        'target_commit': TARGET, 'historical_archive_commit': HISTORICAL,
        'source_identity': digest(new), 'historical_source_identity': digest(old),
        'current_source_files': len(new), 'historical_source_files': len(old),
        'source_delta_digest': digest(delta), 'source_delta': delta,
        'checked_receipt_and_references': len(refs),
        'historical_monitor_digest': digest(monitor),
        'historical_environment_digest': receipt['environment_digest'],
        'historical_publication_policy_digest': receipt['publication_policy_digest'],
        'historical_monitor_environment': monitor['execution_environment'],
        'historical_archive': {'main_records': len(receipt['records']), 'recoveries': len(receipt['recovery']),
                               'counts': ledger['counts']},
        'unchanged_algorithm_identity_files': sorted(algorithm_files),
        'unchanged_legacy_schemas_count': len(unchanged_schemas),
        'new_closed_schemas_checked': schemas,
        'allowed_budget_field_values': pair,
        'local_environment': {'python': platform.python_version(), 'platform': platform.system(),
                              'machine': platform.machine(),
                              'dependencies': {n: installed(n) for n in ('jsonschema', 'numpy', 'scipy', 'pytest')}},
        'business_execution': 'NOT_RUN',
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
