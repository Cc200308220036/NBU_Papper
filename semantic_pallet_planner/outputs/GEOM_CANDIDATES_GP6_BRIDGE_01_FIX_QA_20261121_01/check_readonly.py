"""Validate delivery bytes and a benign historical loader fixture without business imports."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET

PREFIX = 'semantic_pallet_planner/'
SOURCE = PREFIX + 'src/semantic_pallet_planner'
OUTPUT = PREFIX + 'outputs/GEOM_CANDIDATES_'
OLD = OUTPUT + 'GP6_F0_KERNEL_BRIDGE_FIX_20261121_01'
OLD_QA = OUTPUT + 'GP6_F0_KERNEL_BRIDGE_FIX_QA_20261121_01'
NEW = OUTPUT + 'GP6_BRIDGE_01_FIX_20261121_01'
GP5 = OUTPUT + 'GP5_P2_FINAL_RUNTIME_20261120_01'
BASE = '2094bdbaf64949f089203566235bc432d4042899'
FIRST = '16323560e348182fddddd36e4985ee353c70cc5e'
HEAD = '992e64f53d3575fe8c0ee0166fd4a3a67b270b3b'
HIST = '1c6c85613'


def git(*args):
    return subprocess.check_output(['git', *args])


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical_sha(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode())


def blob(commit, path):
    return git('show', f'{commit}:{path}')


def load(path):
    return json.loads(Path(path).read_bytes())


def in_source_set(path):
    return (path.suffix in ('.py', '.json')
            and not {'tests', '__pycache__'}.intersection(path.parts))


def archived_source(commit):
    with tarfile.open(fileobj=io.BytesIO(git('archive', commit, SOURCE))) as archive:
        files = {}
        for member in archive.getmembers():
            if member.isfile():
                path = Path(member.name).relative_to(SOURCE)
                if in_source_set(path):
                    files[path.as_posix()] = sha(archive.extractfile(member).read())
        return files


def check_manifest(folder, commit):
    value = json.loads(blob(commit, f'{folder}/delivery_manifest.json'))
    entries = value['files']
    if isinstance(entries, dict):
        entries = [{'path': path, 'sha256': expected} for path, expected in entries.items()]
    for entry in entries:
        raw = blob(commit, entry['path'])
        assert sha(raw) == entry['sha256'], entry['path']
        if 'bytes' in entry:
            assert len(raw) == entry['bytes'], entry['path']
    return len(entries)


def check_archived_tests():
    command_receipt = load(f'{NEW}/checks_and_commands.json')
    suites = {}
    for run in command_receipt['runs']:
        suite = ET.parse(run['receipt']).find('testsuite')
        assert run['exit_code'] == 0
        for field in ('tests', 'failures', 'errors', 'skipped'):
            assert int(suite.attrib[field]) == run[field], field
        names = [case.attrib['name'] for case in suite.findall('testcase')]
        assert names == run['cases'], names
        assert all(len(case) == 0 for case in suite.findall('testcase'))
        suites[Path(run['receipt']).name] = names
    return suites


def check_loader():
    worker = Path(SOURCE) / 'jev_select/geometry_jev_kernel_evidence_worker.py'
    assert worker.read_bytes() == blob(HEAD, str(worker))
    spec = importlib.util.spec_from_file_location('qa_worker', worker)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='gp6_qa_') as temporary:
        root = Path(temporary).resolve() / 'verified_fixture'
        root.mkdir()
        marker = root / 'fixture_executed'
        files = {
            '__init__.py': b'',
            'example.py': (f'from pathlib import Path\n'
                           f'Path({str(marker)!r}).touch()\nVALUE = 17\n').encode(),
        }
        for name, raw in files.items():
            (root / name).write_bytes(raw)
        manifest = {name: sha(raw) for name, raw in files.items()}
        finder = module.HistoricalImports(root, dict(manifest, **{'example.py': '0' * 64}))
        sys.meta_path.insert(0, finder)
        try:
            try:
                importlib.import_module('semantic_pallet_planner.example')
            except ImportError as exc:
                assert str(exc) == 'historical_import_bytes_mismatch', str(exc)
            else:
                raise AssertionError('expected digest rejection')
            assert not marker.exists()
            finder.files = manifest
            loaded = importlib.import_module('semantic_pallet_planner.example')
            assert Path(loaded.__spec__.origin) == root / 'example.py'
            assert loaded.VALUE == 17 and marker.exists()
        finally:
            sys.meta_path.remove(finder)
            for name in ('semantic_pallet_planner.example', 'semantic_pallet_planner'):
                sys.modules.pop(name, None)
    return {'trusted_module': 'PASS', 'mismatched_digest': 'REJECTED_BEFORE_FIXTURE_EXECUTION'}


def main():
    count = {folder: check_manifest(folder, commit) for folder, commit in
             ((OLD, FIRST), (OLD_QA, BASE), (NEW, HEAD))}
    local = {p.relative_to(SOURCE).as_posix(): sha(p.read_bytes())
             for p in Path(SOURCE).rglob('*')
             if p.is_file() and in_source_set(p.relative_to(SOURCE))}
    new = load(f'{NEW}/source_identity.json')
    old = load(f'{OLD}/new_source_identity.json')
    hist = load(f'{GP5}/source_manifest.json')
    for value, commit in ((new, HEAD), (old, FIRST), (hist, HIST)):
        assert value['files'] == archived_source(commit), commit
        assert canonical_sha(value['files']) == value['source_identity'], commit
    assert new['files'] == local
    patch = git('diff', BASE, HEAD, '--',
                SOURCE + '/jev_select/geometry_jev_kernel_bridge.py',
                SOURCE + '/jev_select/geometry_jev_kernel_evidence_worker.py')
    assert patch == blob(HEAD, f'{NEW}/source_change.patch')
    assert not git('diff', '--name-only', BASE, HEAD, '--', OUTPUT + '*GP5*',
                   SOURCE + '/jev_select/schemas', OLD, OLD_QA)
    audit = load(f'{OLD}/historical_readonly_audit.json')
    refs = {path: row['expected'] for path, row in audit['reference_checks'].items()}
    refs[audit['receipt_path']] = audit['receipt_sha256']
    for path, expected in refs.items():
        assert sha(Path(path).read_bytes()) == expected, path
        assert sha(blob(BASE, path)) == sha(blob(HEAD, path)) == expected, path
    previous = old['files']
    before = hist['files']
    delta = [{'path': path, 'before': before.get(path), 'after': local.get(path)}
             for path in sorted(before.keys() | local.keys())
             if before.get(path) != local.get(path)]
    changes = [path for path in sorted(previous.keys() | local.keys())
               if previous.get(path) != local.get(path)]
    print(json.dumps({
        'reviewed_head': HEAD,
        'manifest_entries_verified_at_delivery': count,
        'source_identity': new['source_identity'], 'current_source_files': len(local),
        'historical_source_identity': hist['source_identity'], 'historical_git_files': len(before),
        'current_cross_version_delta_count': len(delta),
        'current_cross_version_delta_digest': canonical_sha(delta),
        'source_changes_since_previous_qa': changes,
        'historical_receipt_and_reference_bytes': len(refs),
        'patch_matches_two_production_files': True,
        'archived_junit_cases': check_archived_tests(),
        'local_loader_only': check_loader(),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
