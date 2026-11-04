"""Read-only JN2-A validation under forbidden execution dispatches."""
from pathlib import Path
import sys
from semantic_pallet_planner.jev_select import packaging_counterfactual as f
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.contracts import JevSelectError
import semantic_pallet_planner.jev_select.episode as ep
import semantic_pallet_planner.jev_select.execution as ex
import semantic_pallet_planner.jev_select.stability.monitor as mon
import semantic_pallet_planner.jev_select.stability.balance_adapter as ba
from semantic_pallet_planner.jev_select.candidates import CandidateProvider
import scipy.optimize
root=Path(sys.argv[1]);receipt=Path(sys.argv[2]);counts={}
def forbidden(name):
    counts[name]=0
    def fail(*a,**kw):counts[name]+=1;raise AssertionError('FORBIDDEN_DISPATCH_'+name)
    return fail
for owner,name,label in [(ep,'run_episode','episode'),(ex,'commit_physical','commit'),
        (mon,'monitor_selected_action','monitor'),(ba,'assess_candidate','PCT'),
        (CandidateProvider,'build','candidate_generation'),(f.LocalPackagingDouble,'select','selection'),
        (scipy.optimize,'linprog','LP')]:setattr(owner,name,forbidden(label))
before=f.file_manifest(root)
validation=f.validate_output(root)
result=f.run(root,resume=True)
assert result==read(root/'mechanism_results.json') and before==f.file_manifest(root)
try:
    f.prepare('semantic_pallet_planner/outputs/JEV_JN1_20261103_03',root.parent/'NEVER_CREATED_DUPLICATE_JN2_A')
except JevSelectError as exc:
    assert exc.code=='fork_existing_A_registration_use_resume';duplicate=exc.code
else:raise AssertionError('A budget reset accepted')
write(receipt,{'status':'PASS','validation':validation,'dispatch_counts':counts,'saved_bytes_unchanged':True,
               'completed_resume_dispatches':0,'duplicate_A_registration_rejected':duplicate})
