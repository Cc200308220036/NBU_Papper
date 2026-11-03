"""Saved records only; call from repository root with pilot or final."""
from pathlib import Path
import hashlib
import sys
import copy
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError
from semantic_pallet_planner.jev_select.experiment import file_manifest,source_manifest
import semantic_pallet_planner.jev_select.packaging_experiment as pe

root=Path('semantic_pallet_planner/outputs/JEV_JN0_20261103_02');run=root/'run';label=sys.argv[1]
assert label in ('pilot','final')
plan=read(root/'plan/plan.json');spec=read(root/'supplement_spec.json')
assert digest(spec)==read(root/'supplement_receipt.json')['spec_digest'] and digest(plan)==spec['new_plan_digest']
assert digest(source_manifest())==spec['source_manifest_digest']
before=file_manifest(run)
# All decision/execution routes are blocked, including a completed resume call.
def forbidden(*a,**k):raise AssertionError('unexpected order execution during saved-record audit')
import semantic_pallet_planner.jev_select.episode as episode
import semantic_pallet_planner.jev_select.execution as execution
import semantic_pallet_planner.jev_select.stability.balance_adapter as adapter
from semantic_pallet_planner.jev_select.candidates import CandidateProvider
from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
pe._run_job=episode.run_episode=execution.commit_physical=adapter.assess_candidate=forbidden
CandidateProvider.build=LocalPackagingDouble.select=forbidden
validation=pe.validate_packaging_run(run)
a=pe.summarize_packaging_run(run);b=pe.summarize_packaging_run(run)
assert a==b==read(run/'summary.json')
assert pe.run_packaging_plan(root/'plan',run,resume=True)==a
assert before==file_manifest(run)
statuses=[read(run/'jobs'/j['job_id']/'status.json') for j in plan['jobs']]
started=sum(s['state']!='NOT_RUN' for s in statuses)
assert started<=8
if label=='pilot':
    assert started==2 and all(s['state']=='FINISHED' for s in statuses[:2])
    assert all(s['state']=='NOT_RUN' for s in statuses[2:])
    assert all(s['category'] in ('COMPLETE','EMPTY_POOL','PREDICTED_STATIC_INSTABILITY','UNASSESSABLE') for s in statuses[:2])
    assert not a['categories']['ERROR']
    if a['categories']['UNASSESSABLE']:
        review=read(root/'pilot_monitor_scope_review.json')
        assert review['status']=='EXPLAINED_LOCALIZED_GAP' and review['continue_remaining_registered_jobs'] is True
    receipt={'version':'jev_jn0_pilot_gate_v1','status':'PASS','validated_jobs':['J0000','J0001'],
        'summary':a,'spec_digest':digest(spec),'plan_digest':digest(plan),'run_manifest':read(run/'delivery_manifest.json'),
        'run_manifest_sha256':hashlib.sha256((run/'delivery_manifest.json').read_bytes()).hexdigest(),
        'pilot_job_file_hashes':{n:h for n,h in before.items() if n.startswith(('jobs/J0000/','jobs/J0001/'))},
        'allowed_next_jobs':[f'J{i:04d}' for i in range(2,8)],'new_starts_used':2,'new_starts_remaining_max':6,
        'monitor_scope_review':'pilot_monitor_scope_review.json','record_validation':validation,'idempotent_summary':True,'read_only_resume':True,'no_execution_during_audit':True}
    write(root/'pilot_gate.json',receipt)
else:
    pilot=read(root/'pilot_gate.json')
    assert all(file_manifest(run)[n]==h for n,h in pilot['pilot_job_file_hashes'].items())
    assert read(run/'batch_history/B0001/delivery_manifest.json.snapshot.json')==pilot['run_manifest']
    cp=read(run/'jobs/J0000/checkpoint.json');task=read(run/'jobs/J0000/task.snapshot.json');cfg=plan['jobs'][0]['config']
    from semantic_pallet_planner.jev_select.stability.monitor import seal_checkpoint
    checks=[]
    for kind in ('selection','context','monitor','state','runtime_identity'):
        bad=copy.deepcopy(cp);e=next(e for e in bad['events'] if e['event']=='PLACE')
        if kind=='selection':e['selection']['selected_candidate_id']='tampered'
        elif kind=='context':e['context']['request_body']['question']='tampered'
        elif kind=='monitor':e['monitor']['status']='UNSTABLE'
        elif kind=='state':bad['state']['placed_count']+=1
        else:bad['runtime_identity']['data_identity']='tampered'
        seal_checkpoint(bad)
        try:pe.validate_saved_checkpoint(bad,task,cfg,'J0000')
        except (ValueError,KeyError,TypeError) as exc:checks.append({'kind':kind,'outer_digest_resealed':True,'rejected':True,'error':str(exc)[:240]})
        else:raise AssertionError('corruption accepted: '+kind)
    write(root/'negative_record_checks.json',checks)
    write(root/'record_validation.json',{'version':'jev_jn0_record_validation_v1','status':'PASS','standard_validation':validation,
        'idempotent_summary':True,'read_only_resume':True,'manifest_unchanged':before==file_manifest(run),
        'pilot_jobs_unchanged':True,'kernel_calls':0,'physical_commits':0,'selector_calls':0,'full_order_replays':0,
        'key_resigned_corruptions_rejected':len(checks),'actual_new_jobs':started,'cumulative_actual_jobs':started+1})
print(label,'standard record validation + repeated summary + read-only resume PASS;',started,'new starts, cumulative',started+1)
