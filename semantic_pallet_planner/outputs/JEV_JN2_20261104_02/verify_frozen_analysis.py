"""Read B using B's archived analysis identity after the working tree evolves.

Only the artifact path anchor is relocated. Default is full saved-record
validation; --plan-only verifies relocation, frozen source and canonical inputs.
Neither path permits suffix execution, model calls, selection or physical commit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--repo',default='.');p.add_argument('--plan-only',action='store_true');a=p.parse_args()
repo=Path(a.repo).resolve();root=(repo/a.output).resolve()
plan=json.loads((root/'comparison_plan.json').read_text());archive=root/'analysis_code_snapshot'
assert all(hashlib.sha256((archive/n).read_bytes()).hexdigest()==h for n,h in plan['analysis_source_manifest'].items())
with tempfile.TemporaryDirectory(prefix='jev_jn2_b_readonly_analysis_') as tmp:
 package=Path(tmp)/'semantic_pallet_planner';shutil.copytree(archive,package)
 parent=repo/plan['parent_a']['path']
 for n,h in json.loads((parent/'algorithm_snapshot_manifest.json').read_text()).items():
  source=parent/'algorithm_snapshot'/n;assert hashlib.sha256(source.read_bytes()).hexdigest()==h
  target=package/'jev_select/stability'/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
 sys.path.insert(0,tmp)
 from semantic_pallet_planner.jev_select import packaging_comparisons as c
 from semantic_pallet_planner.jev_select import packaging_counterfactual as f
 c.REPO=repo;f.common.REPO=repo
 assert c.source_manifest()==plan['analysis_source_manifest']
 real=c.worker
 def readonly_worker(root,command,**kw):
  assert command!='run','readonly verifier cannot execute a suffix'
  return real(root,command,**kw)
 c.worker=readonly_worker
 if a.plan_only:
  value=c.validate_plan(root)
  result={'status':'PASS','scope':'frozen analysis relocation + canonical frozen inputs; no suffix dispatch','analysis_files':len(value['analysis_source_manifest']),'execution_files':len(value['execution_source_manifest'])}
 else:result=c.validate(root)
 print(json.dumps(result,ensure_ascii=False))
