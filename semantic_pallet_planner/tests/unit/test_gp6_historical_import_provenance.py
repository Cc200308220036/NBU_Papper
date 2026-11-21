"""Trusted temporary import fixtures; no order, kernel, model or production permit."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

WORKER = Path(__file__).resolve().parents[2] / 'src/semantic_pallet_planner/jev_select/geometry_jev_kernel_evidence_worker.py'


def run_probe(tmp_path, mutation):
    # Deliberately use a nonstandard source directory name. Imports must bind to
    # this exact root rather than assume its parent is a safe sys.path entry.
    root = tmp_path / 'verified_input'
    files = {
        '__init__.py': b'',
        'jev_select/__init__.py': b'',
        'jev_select/probe.py': b'VALUE = "TRUSTED_SYNTHETIC"\n',
    }
    for name, raw in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    manifest = {n: hashlib.sha256(v).hexdigest() for n,v in files.items()}
    wrong = tmp_path / 'wrong' / 'semantic_pallet_planner'
    wrong.mkdir(parents=True)
    marker = tmp_path / 'BUSINESS_DISPATCH_FORBIDDEN'
    (wrong/'__init__.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
    (wrong/'jev_select').mkdir()
    (wrong/'jev_select/__init__.py').write_text('')
    (wrong/'jev_select/probe.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
    if mutation == 'bytes':
        (root/'jev_select/probe.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
    elif mutation == 'symlink':
        (root/'jev_select/probe.py').unlink()
        (root/'jev_select/probe.py').symlink_to(wrong/'jev_select/probe.py')
    elif mutation == 'missing':
        del manifest['jev_select/probe.py']
    elif mutation == 'redirect':
        raw=f'__path__ = [{str(wrong/"jev_select")!r}]\n'.encode()
        (root/'jev_select/__init__.py').write_bytes(raw)
        manifest['jev_select/__init__.py']=hashlib.sha256(raw).hexdigest()
    script = '''
import importlib.util, json, sys, types
from pathlib import Path
worker, root, files, wrong, mutation = sys.argv[1:]
spec = importlib.util.spec_from_file_location('trusted_worker', worker)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
sys.path.insert(0, wrong)
if mutation == 'preloaded':
    sys.modules['semantic_pallet_planner'] = types.ModuleType('semantic_pallet_planner')
finder = m.HistoricalImports(root, json.loads(files))
sys.meta_path.insert(0, finder)
from semantic_pallet_planner.jev_select import probe
assert probe.VALUE == 'TRUSTED_SYNTHETIC'
from importlib.resources import files as resources
assert resources('semantic_pallet_planner.jev_select').joinpath('probe.py').read_bytes() == b'VALUE = \"TRUSTED_SYNTHETIC\"\\n'
assert Path(probe.__file__).resolve() == Path(root)/'jev_select/probe.py'
print('TRUSTED_SOURCE_ONLY')
'''
    result = subprocess.run([sys.executable,'-I','-B','-c',script,str(WORKER),str(root),
                             json.dumps(manifest),str(wrong.parent),mutation],
                            capture_output=True,text=True,env={'PYTHONDONTWRITEBYTECODE':'1'})
    assert not marker.exists()  # zero business dispatch, even from ambient imports
    return result


def test_positive_exact_source_with_ambient_wrong_package(tmp_path):
    result=run_probe(tmp_path,'none')
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='TRUSTED_SOURCE_ONLY'


@pytest.mark.parametrize('mutation',['bytes','symlink','missing','redirect','preloaded'])
def test_mismatched_source_refuses_without_fallback_or_dispatch(tmp_path,mutation):
    result=run_probe(tmp_path,mutation)
    assert result.returncode!=0
    assert 'historical_import_' in result.stderr
    assert 'TRUSTED_SOURCE_ONLY' not in result.stdout
