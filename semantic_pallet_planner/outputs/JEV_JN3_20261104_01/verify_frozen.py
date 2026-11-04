"""Standalone archived JN3 verifier. Launch under readonly_guard.py by path."""
import argparse, importlib.util, sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--repo',default='.')
a=p.parse_args();repo=Path(a.repo).resolve();root=Path(a.output).resolve()
assert not any(n=='semantic_pallet_planner' or n.startswith('semantic_pallet_planner.') for n in sys.modules), 'launch standalone, not through preloaded current package'
spec=importlib.util.spec_from_file_location('semantic_pallet_planner',root/'code_snapshot/__init__.py',submodule_search_locations=[str(root/'code_snapshot')])
module=importlib.util.module_from_spec(spec);sys.modules['semantic_pallet_planner']=module;spec.loader.exec_module(module)
from semantic_pallet_planner.jev_select import packaging_trajectory_validation as workflow
from semantic_pallet_planner.jev_select import packaging_comparisons as comparisons
workflow.REPO=repo;workflow.PARENT=repo/'semantic_pallet_planner/outputs/JEV_JN2_20261104_03';comparisons.REPO=repo
from semantic_pallet_planner.jev_select.contracts import canonical
print(canonical(workflow.validate_saved(root)))
