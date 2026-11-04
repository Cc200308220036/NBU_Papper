"""Validate saved v2 with its own archived analysis, after current code evolves.

Launch by file path through readonly_guard.py, never via a current package -m.
No execution/fork generation routes are exposed. Parent bytes and archived
source identities are rechecked by the unchanged saved-only v2 validator.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--repo',default='.')
a=p.parse_args();repo=Path(a.repo).resolve();root=(repo/a.output).resolve()
plan=json.loads((root/'analysis_plan.json').read_text());archive=root/'analysis_code_snapshot'
assert 'semantic_pallet_planner.jev_select' not in sys.modules, 'launch standalone; do not preload current package'
assert all(hashlib.sha256((archive/n).read_bytes()).hexdigest()==h for n,h in plan['analysis_source_manifest'].items())
with tempfile.TemporaryDirectory(prefix='jev_jn2_v2_readonly_') as tmp:
    package=Path(tmp)/'semantic_pallet_planner';shutil.copytree(archive,package)
    parent=repo/json.loads((repo/plan['parent']['path']/'comparison_plan.json').read_text())['parent_a']['path']
    for n,h in json.loads((parent/'algorithm_snapshot_manifest.json').read_text()).items():
        source=parent/'algorithm_snapshot'/n;assert hashlib.sha256(source.read_bytes()).hexdigest()==h
        target=package/'jev_select/stability'/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    sys.path.insert(0,tmp)
    from semantic_pallet_planner.jev_select import packaging_reanalysis as r
    r.REPO=repo;r.v1.REPO=repo;r.fork.common.REPO=repo
    assert Path(r.__file__).resolve().is_relative_to(package)
    result=r.validate(root)
    result['import_scope']='verified archived analysis only; current production package not imported'
    print(json.dumps(result,ensure_ascii=False))
