"""Read-only standard validation of this run, with live operations forbidden."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
import os
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.experiment import file_manifest
from semantic_pallet_planner.jev_select import packaging_orders as orders
OUT=Path(__file__).resolve().parent
RUN=OUT/'run'
counts={'network':0,'credential_file':0,'run_writes':0}
blocked={}
def audit(event,args):
    if event in ('socket.connect','socket.getaddrinfo','socket.gethostbyname','socket.sendto','socket.bind'):
        counts['network']+=1;raise AssertionError('network forbidden')
    if event=='open' and isinstance(args[0],(str,bytes)):
        name=os.fsdecode(args[0])
        if any(s in name.lower() for s in ('typesafe_api_key','deepseek_api.md','.env','credentials')):
            counts['credential_file']+=1;raise AssertionError('credential forbidden')
        mode,flags=args[1:3]
        writing=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if writing and Path(name).resolve().is_relative_to(RUN):
            counts['run_writes']+=1;raise AssertionError('run write forbidden')
sys.addaudithook(audit)
def forbid(name):
    blocked[name]=0
    def fn(*a,**kw):blocked[name]+=1;raise AssertionError('live entry forbidden: '+name)
    return fn
entries=[
 'semantic_pallet_planner.jev_select.packaging_orders.run',
 'semantic_pallet_planner.jev_select.packaging_experiment._run_job',
 'semantic_pallet_planner.jev_select.episode.run_episode',
 'semantic_pallet_planner.jev_select.episode.decision_inputs',
 'semantic_pallet_planner.jev_select.candidates.CandidateProvider.build',
 'semantic_pallet_planner.jev_select.candidates.generate',
 'semantic_pallet_planner.jev_select.packaging_remote.PackagingRemoteSelector.select',
 'semantic_pallet_planner.jev_select.packaging_runtime.LocalPackagingDouble.select',
 'semantic_pallet_planner.jev_select.execution.commit_physical',
 'semantic_pallet_planner.jev_select.stability.monitor.monitor_selected_action',
 'semantic_pallet_planner.jev_select.stability.balance_adapter.assess_candidate',
 'semantic_pallet_planner.jev_select.stability.balance_network.solve_network',
 'semantic_pallet_planner.jev_select.transport.JevTransport.complete',
 'semantic_pallet_planner.jev_select.transport.credential',
 'scipy.optimize.linprog']
prior=file_manifest(RUN)
with ExitStack() as stack:
    for name in entries:stack.enter_context(patch(name,forbid(name)))
    first=orders.validate_run(RUN);second=orders.validate_run(RUN)
assert first==second and prior==file_manifest(RUN)
assert not any(counts.values()) and not any(blocked.values())
summary=read(RUN/'summary.json')
name='final_record_validation.json' if not summary['categories']['NOT_RUN'] else 'pilot_record_validation.json'
write(OUT/name,{'version':'jev_jn1_b_saved_audit_v1','status':'PASS','validator':first,'repeated_validator_identical':True,
 'guards':counts,'blocked_entry_calls':blocked,'run_manifest_unchanged':True,
 'new_model_requests':0,'new_selections':0,'new_monitor_evaluations':0,'new_commits':0,
 'saved_model_calls':summary['model_calls'],'saved_categories':summary['categories']})
print({'status':'PASS','receipt':name,'saved_model_calls':summary['model_calls'],'categories':summary['categories']})
