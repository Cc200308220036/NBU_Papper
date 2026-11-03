"""Run from repository root. Derives diagnostics only, never dispatches an order."""
from pathlib import Path
import copy
import hashlib
import shutil

from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.experiment import source_manifest,file_manifest
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError
from semantic_pallet_planner.jev_select.packaging_experiment import validate_saved_checkpoint
from semantic_pallet_planner.jev_select.packaging_metrics import job_metrics,aggregate,paired
from semantic_pallet_planner.jev_select.stability.monitor import seal_checkpoint

root=Path('semantic_pallet_planner/outputs/JEV_JN0_20261103_01')
run=root/'run';plan=read(root/'plan_revision_02/plan.json')
require=lambda ok: None if ok else (_ for _ in ()).throw(AssertionError('saved audit mismatch'))
require(file_manifest(run)==read(run/'delivery_manifest.json'))
require(file_manifest(root/'plan_revision_02')==read(root/'plan_revision_02/delivery_manifest.json'))
original=plan['source_manifest'];current=source_manifest()
diff=[n for n in set(original)|set(current) if original.get(n)!=current.get(n)]
require(diff==['jev_select/stability/metrics.py'])
for n,h in original.items():
    require(hashlib.sha256((root/'plan_revision_02/code_snapshot'/n).read_bytes()).hexdigest()==h)
# All execution routes are forbidden during the audit. Importing identity code
# is allowed; invoking candidate/selection/commit/LP machinery is not.
def forbidden(*a,**k):raise AssertionError('execution forbidden in saved audit')
import semantic_pallet_planner.jev_select.episode as episode
import semantic_pallet_planner.jev_select.execution as execution
import semantic_pallet_planner.jev_select.stability.balance_adapter as adapter
from semantic_pallet_planner.jev_select.candidates import CandidateProvider
from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
episode.run_episode=execution.commit_physical=adapter.assess_candidate=forbidden
CandidateProvider.build=LocalPackagingDouble.select=forbidden
rows=[];ledger=[]
for j in plan['jobs']:
    job=run/'jobs'/j['job_id'];status=read(job/'status.json')
    ledger.append({'job_id':j['job_id'],'task_id':j['task_id'],'method_id':j['method_id'],**status})
    task=read(job/'task.snapshot.json');cfg=read(job/'config.snapshot.json')
    require(digest(task)==j['task_digest'] and cfg==j['config'])
    if not (job/'checkpoint.json').exists():
        require(status['category']=='NOT_RUN');continue
    cp=read(job/'checkpoint.json');validate_saved_checkpoint(cp,task,cfg,j['job_id'])
    for p in (job/'stages').glob('*/*.json'):
        stage=read(p);validate_saved_checkpoint(stage,task,cfg,j['job_id'])
        require(stage['events']==cp['events'][:len(stage['events'])])
        pending=stage['pending_event'];final=next(e for e in cp['events'] if e.get('decision_id')==pending['decision_id'])
        for k in ('before','context','selection','bundle','proposed_action'):
            require(pending[k]==final[k])
        if pending['monitor']:require(pending['monitor']==final['monitor'])
    for e in cp['events']:
        if e.get('decision_id'):require(read(job/'actions'/f"{e['decision_id']}.json")==e)
    require(read(job/'final_layout.json')==cp['state']['placed_items'])
    metrics=job_metrics(task,cfg,cp,status);rows.append(metrics)
    write(root/'diagnostics'/j['job_id']/'metrics.json',metrics)
    checks=[]
    for kind in ('selection','monitor','context','state','runtime_identity'):
        bad=copy.deepcopy(cp);place=next(e for e in bad['events'] if e['event']=='PLACE')
        if kind=='selection':place['selection']['selected_candidate_id']='tampered'
        elif kind=='monitor':place['monitor']['status']='UNSTABLE'
        elif kind=='context':place['context']['request_body']['question']='tampered'
        elif kind=='state':bad['state']['placed_count']+=1
        else:bad['runtime_identity']['data_identity']='tampered'
        seal_checkpoint(bad)
        try:validate_saved_checkpoint(bad,task,cfg,j['job_id'])
        except (ValueError,KeyError,TypeError) as exc:
            checks.append({'kind':kind,'outer_digest_resealed':True,'rejected':True,'error':str(exc)[:240]})
        else:raise AssertionError('tamper accepted: '+kind)
    write(root/'diagnostics/negative_checks.json',checks)
write(root/'diagnostics/job_ledger.json',ledger)
write(root/'diagnostics/summary.json',aggregate(rows,len(plan['jobs'])))
write(root/'diagnostics/paired_differences.json',paired(rows))
write(root/'diagnostics/verification.json',{'status':'PASS_SAVED_RECORDS_ONLY','actual_jobs':len(rows),'planned_jobs':len(plan['jobs']),
    'source_changes_since_run':diff,'derivation_source_digest':digest(current),'original_source_digest':digest(original),
    'raw_records_modified':False,'order_replays':0,'kernel_calls':0,'selector_calls':0,'physical_commits':0,
    'interpretation':'Original batch remains ERROR + seven NOT_RUN; a natural EMPTY_POOL checkpoint does not erase its reporting failure. New metrics fix only the null-monitor derivation.'})
# Frozen repair identity, separate from the original plan and v5 checkpoints.
write(root/'repair/source_manifest.json',current)
package=Path(episode.__file__).resolve().parents[1]
for n in current:
    target=root/'repair/code_snapshot'/n;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(package/n,target)
write(root/'repair/revision_receipt.json',{'version':'jev_jn0_repair_receipt_v1','parent_plan_digest':digest(plan),
    'source_digest':digest(current),'changed_files':diff,'change':'null monitor guard in first instability progress statistics',
    'formal_orders_under_this_identity':0,'original_checkpoint_and_config_digests_preserved':True})
print('saved audit PASS; 1 failed batch job + 7 NOT_RUN, no reruns; five resealed corruptions rejected')
