"""Standalone archived E saved-record verifier; launch by path under readonly guard."""
import argparse,importlib.util,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--repo',default='.')
a=p.parse_args();repo=Path(a.repo).resolve();root=Path(a.output).resolve()
assert not any(n=='semantic_pallet_planner' or n.startswith('semantic_pallet_planner.') for n in sys.modules),'launch standalone before current package import'
spec=importlib.util.spec_from_file_location('semantic_pallet_planner',root/'code_snapshot/__init__.py',submodule_search_locations=[str(root/'code_snapshot')])
m=importlib.util.module_from_spec(spec);sys.modules['semantic_pallet_planner']=m;spec.loader.exec_module(m)
from semantic_pallet_planner.jev_select import packaging_contrast_generation as g
from semantic_pallet_planner.jev_select import packaging_contrast_validation as w
from semantic_pallet_planner.jev_select import packaging_comparisons as c
g.REPO=repo;g.A=repo/'semantic_pallet_planner/outputs/JEV_JN3_20261104_01';g.PARENT=repo/'semantic_pallet_planner/outputs/JEV_JN2_20261104_03';w.REPO=repo;w.A=g.A;c.REPO=repo
from semantic_pallet_planner.jev_select.contracts import canonical
print(canonical(w.validate_saved(root)))
