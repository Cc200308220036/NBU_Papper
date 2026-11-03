"""Read saved evidence with every execution/send/solver entry forbidden."""
from pathlib import Path
import hashlib
from unittest.mock import patch
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.packaging_api import execute,parent_check
from semantic_pallet_planner.jev_select.packaging_remote import RequestLedger,remote_selector_factory
from semantic_pallet_planner.jev_select.contracts import DecisionContext,digest
from semantic_pallet_planner.jev_select.packaging_experiment import validate_saved_checkpoint

root=Path(__file__).resolve().parent
tracked=['checkpoint.json','selection.json','monitor.json','event.json','decision_record.json','execution.json',
         'request_ledger/requests.json','response.raw.json','request.json']
def hashes():return {n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in tracked}
prior=hashes();config=read(root/'config.snapshot.json');task=read(root/'task.snapshot.json')
def forbidden(*a,**kw):raise AssertionError('saved-only audit dispatched an operation')
class ForbiddenTransport:
    origin='jev'
    complete=forbidden
with patch('semantic_pallet_planner.jev_select.episode.run_episode',forbidden), \
     patch('semantic_pallet_planner.jev_select.packaging_api.run_episode',forbidden), \
     patch('semantic_pallet_planner.jev_select.execution.commit_physical',forbidden), \
     patch('semantic_pallet_planner.jev_select.candidates.CandidateProvider.build',forbidden), \
     patch('semantic_pallet_planner.jev_select.stability.balance_adapter.assess_candidate',forbidden), \
     patch('semantic_pallet_planner.jev_select.transport.JevTransport.complete',forbidden):
    cp=read(root/'checkpoint.json');validate_saved_checkpoint(cp,task,config,'A_SMOKE')
    selector=remote_selector_factory('jev_no_memory',config=config,ledger=RequestLedger(root/'request_ledger'),
                                     transport=ForbiddenTransport(),job_id='A_SMOKE')
    restored=selector.select(DecisionContext.from_dict(read(root/'frozen/context.json')),decision_id='A_SMOKE_D0000')
    assert restored.data==read(root/'selection.json')
    # Completed invocation reuses saved records; no further order dispatch.
    one=execute(root,transport=ForbiddenTransport());two=execute(root,transport=ForbiddenTransport())
    assert one==two and hashes()==prior
    assert one['request_statistics']['model_calls']==1
assert parent_check()[0]==read(root/'baseline_verification.json')
event=read(root/'event.json');assert event['action']==event['proposed_action']
assert len(event['after']['placed_items'])==len(event['before']['placed_items'])+1
assert read(root/'decision_record.json')['exact_action']==event['action']
write(root/'recovery_validation.json',{'status':'PASS','audit':'saved record validation and two completed-call resumptions',
     'blocked_entries':['network complete','run_episode dispatch','candidate generation','commit_physical','PCT assess_candidate'],
     'selection_reused':True,'protected_files_unchanged':hashes()==prior,'protected_sha256':prior,
     'actual_model_calls_after':1,'new_model_calls':0,'new_commits':0,'new_monitor_evaluations':0})
print('PASS: saved evidence and recovery; no new send, select, monitor or commit')
