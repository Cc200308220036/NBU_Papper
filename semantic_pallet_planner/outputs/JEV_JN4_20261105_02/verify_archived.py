"""Independent archive import; never execute a saved job."""
import argparse,importlib.util,sys,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--repo',default='.');p.add_argument('--engineering',default='engineering_final');p.add_argument('--snapshot',default='code_snapshot');a=p.parse_args()
repo=Path(a.repo).resolve();root=Path(a.output).resolve();snapshot=root/a.snapshot
assert not any(n=='semantic_pallet_planner' or n.startswith('semantic_pallet_planner.') for n in sys.modules)
spec=importlib.util.spec_from_file_location('semantic_pallet_planner',snapshot/'__init__.py',submodule_search_locations=[str(snapshot)])
m=importlib.util.module_from_spec(spec);sys.modules['semantic_pallet_planner']=m;spec.loader.exec_module(m)
from semantic_pallet_planner.jev_select import packaging_evaluation_orders as workflow
from semantic_pallet_planner.jev_select import packaging_experiment as common
from semantic_pallet_planner.jev_select import packaging_comparisons as comparisons
workflow.REPO=repo;common.REPO=repo;comparisons.REPO=repo
print(json.dumps(workflow.validate_run(root/a.engineering/'run')))
