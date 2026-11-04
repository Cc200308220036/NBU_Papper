"""JN2-B saved-record audit; no training suffix execution permitted."""
from pathlib import Path
import sys
from semantic_pallet_planner.jev_select import packaging_comparisons as c
from semantic_pallet_planner.jev_select import packaging_counterfactual as f
from semantic_pallet_planner.jev_select.ledger import read,write
import semantic_pallet_planner.jev_select.episode as ep
import semantic_pallet_planner.jev_select.execution as ex
import semantic_pallet_planner.jev_select.stability.monitor as mon
import semantic_pallet_planner.jev_select.stability.balance_adapter as ba
from semantic_pallet_planner.jev_select.candidates import CandidateProvider
from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
import scipy.optimize
root=Path(sys.argv[1]);out=Path(sys.argv[2]);counts={};controls=[]
def forbidden(key):
    counts[key]=0
    def fail(*a,**kw):counts[key]+=1;raise AssertionError('FORBIDDEN_'+key)
    return fail
for owner,name in ((ep,'run_episode'),(ex,'commit_physical'),(mon,'monitor_selected_action'),(ba,'assess_candidate'),(CandidateProvider,'build'),(LocalPackagingDouble,'select'),(scipy.optimize,'linprog')):
    setattr(owner,name,forbidden(name))
real=c.worker
def readonly_worker(root,command,**kw):
    assert command!='run','completed collection attempted branch execution'
    result=real(root,command,**kw)
    controls.append({'command':command,'guards':result['guard_counts']})
    return result
c.worker=readonly_worker
before=f.file_manifest(root)
validation=c.validate(root)
summary=c.run(root,resume=True)
assert summary==read(root/'comparison_summary.json')
assert f.file_manifest(root)==before
try:
    c.prepare(c.A_DEFAULT,root.parent/'NEVER_CREATED_DUPLICATE_JN2_B')
except c.JevSelectError as exc:
    assert exc.code=='comparison_already_registered_use_resume';rejected=exc.code
else:raise AssertionError('duplicate registration accepted')
assert all(v==0 for v in counts.values())
write(out,{'status':'PASS','validation':validation,'controller_dispatch_counts':counts,'frozen_readonly_workers':controls,
           'completed_resume_new_suffixes':0,'saved_bytes_unchanged':True,'duplicate_registration_rejected':rejected})
