"""Standalone JN3-C archive verifier; independent file entry under read-only guard."""
import argparse,importlib.util,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--repo',default='.')
a=p.parse_args();repo=Path(a.repo).resolve();root=Path(a.output).resolve();plan=root/'plan';run=root/'run'
assert not any(n=='semantic_pallet_planner' or n.startswith('semantic_pallet_planner.') for n in sys.modules),'launch standalone before current package import'
spec=importlib.util.spec_from_file_location('semantic_pallet_planner',plan/'code_snapshot/__init__.py',submodule_search_locations=[str(plan/'code_snapshot')])
m=importlib.util.module_from_spec(spec);sys.modules['semantic_pallet_planner']=m;spec.loader.exec_module(m)
from semantic_pallet_planner.jev_select import packaging_memory_pilot as workflow
from semantic_pallet_planner.jev_select import packaging_experiment as common
from semantic_pallet_planner.jev_select import packaging_comparisons as comparisons
workflow.REPO=repo;common.REPO=repo;comparisons.REPO=repo
from semantic_pallet_planner.jev_select.contracts import canonical
print(canonical(workflow.validate_run(run)))
