"""Fixed GP5-P2 4+6 driver. No approvals/freezes are issued here."""
import argparse, copy, hashlib, json, shutil
from contextlib import ExitStack
from unittest.mock import patch
from pathlib import Path
from semantic_pallet_planner.jev_select import geometry_order_execution as order
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.geometry_kernel_completion import required_coverage, check_success
from semantic_pallet_planner.jev_select.ledger import write
R=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01')
PHASES=('SELECTED','MONITORED','COMMITTED')
class ControlledCut(Exception): pass
def read(path): return json.loads(Path(path).read_bytes())
def hashes(root):
 return {str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}
def check_counts(plan):
 v=read(plan['call_ledger_path'])
 assert v['evidence']=='REAL_KERNEL' and v['plan_digest']==digest(plan)
 assert v['limits']=={'assessment_entries':8,'solver_calls':128}
 assert v['counts']['test_double_assessments']==0
 assert all(c['state']=='DONE' and c['kind'] in v['limits'] for c in v['calls']), 'UNKNOWN_OR_FAILED_CALL'
 for k,limit in v['limits'].items():
  assert v['counts'][k]==sum(c['kind']==k for c in v['calls'])<=limit
 return copy.deepcopy(v['counts'])
def prepare(runtime,review_path,launch_path):
 plan=read(runtime/'acceptance_plan_FROZEN.json');snap=read(runtime/'monitor_snapshot.json');req=read(runtime/'startup_review_request.json')
 for k,v in [('plan_digest',digest(plan)),('monitor_digest',digest(snap)),('source_identity',plan['source_identity']),('environment_digest',plan['environment_digest'])]: assert req[k]==v
 for key in ('plan_reference','monitor_reference','authorization_reference'):p.read_reference(req[key])
 assert (plan['assessment_limit'],plan['solver_limit'],plan['model_calls_max'])==(8,128,0)
 assert [(j['job_id'],j['task_id'],j['backend']) for j in plan['jobs']]==[(f'J{i:02}',f'GP5_SYNTH_K{1+i//2:02}',('e2_original_v1','ems_surface_hybrid_v1')[i%2]) for i in range(4)]
 assert digest(plan)=='2e97da50ad87c91b50b0259129f1dfc0b584e11c653d23a9a25830f3499d6433'
 assert digest(snap)=='b6cda604eaf1640c48c7d6d71fb536f4ef777cac56ca2de0c01b8ed4dda3ab07'
 review=read(review_path);launch=read(launch_path)
 assert Path(launch['review']['path']).resolve()==Path(review_path).resolve()
 assert p.read_reference(launch['review'])==review
 p.validate_admission(plan,snap,launch)
 # Joint read-only preflight: absolutely no dispatch until all four succeed.
 configs=[order.load_order_config(plan,j['job_id'],monitor_snapshot=snap,admission=launch) for j in plan['jobs']]
 tasks={}
 for case,t in zip(('K01','K02'),plan['tasks'],strict=True):
  tasks[t['task_id']]=p.adapt_task((runtime/f'{case}_task.json').read_bytes(),origin=t['origin'],expected_sha256=t['raw_sha256'])
  assert tasks[t['task_id']]['identity']==t
 check_counts(plan)
 return plan,snap,launch,tasks,configs

def execute(runtime,review,launch,dest):
 dest=Path(dest);dest.mkdir(parents=True,exist_ok=False)
 rows=[{'kind':'primary','job_id':f'J{i:02}','status':'NOT_RUN'} for i in range(4)]+[{'kind':'recovery','job_id':j,'phase':ph,'status':'NOT_RUN'} for j in ('J00','J01') for ph in PHASES]
 receipt={'evidence':'REAL_EXECUTION_REQUEST','rows':rows,'model_calls':0,'status':'PREFLIGHT','stop':None}
 def save():write(dest/'driver_receipt.json',receipt)
 save()
 try:
  plan,snap,adm,tasks,_=prepare(runtime,review,launch)
  receipt['joint_preflight']='4/4 PASS';receipt['plan_digest']=digest(plan);save()
  coverage=required_coverage(plan)
  def success(root,job):
   record=read(Path(root)/'jobs'/job['job_id']/'record.json')
   check_success(record,next(r for r in coverage['primary'] if r['job_id']==job['job_id']))
  def invoke(job,root,cp=None,callback=None,hook=None):
   check_counts(plan)
   return order.run_order_job(plan,job['job_id'],tasks[job['task_id']],monitor_snapshot=snap,admission=adm,root=root,resume=cp,on_checkpoint=callback,hook=hook)
  for row,job in zip(rows[:4],plan['jobs'],strict=True):
   row['status']='RUNNING';save();cp=None
   if job['job_id'] in ('J00','J01'):
    for phase in PHASES:
     captured=[]
     def callback(value):captured.append(copy.deepcopy(value))
     def cut(name,value):
      if name=={'SELECTED':'after_selected_checkpoint','MONITORED':'after_monitored_checkpoint','COMMITTED':'after_commit_checkpoint'}[phase]: raise ControlledCut(phase)
     try:invoke(job,dest/'primary',cp,callback,cut)
     except ControlledCut:pass
     else:raise RuntimeError('EXPECTED_CHECKPOINT_NOT_REACHED')
     cp=captured[-1];assert cp['phase']==phase
     target=dest/'saved'/job['job_id']/phase
     shutil.copytree(dest/'primary',target)
     write(target/'saved_checkpoint.json',cp)
     write(dest/f'{job["job_id"]}_{phase}_files.json',hashes(target))
   result=invoke(job,dest/'primary',cp)
   assert result['summary']['completed'], 'UNEXPECTED_PRIMARY_STOP'
   success(dest/'primary',job)
   row.update(status='COMPLETE',counts=check_counts(plan));save()
  for row in rows[4:]:
   job=next(j for j in plan['jobs'] if j['job_id']==row['job_id']);phase=row['phase']
   root=dest/'recovery'/job['job_id']/phase
   saved=dest/'saved'/job['job_id']/phase
   assert hashes(saved)==read(dest/f'{job["job_id"]}_{phase}_files.json'), 'SAVED_DURABLE_DRIFT'
   shutil.copytree(saved,root)
   cp=read(root/'saved_checkpoint.json');before=check_counts(plan)
   row['status']='RUNNING';save()
   with ExitStack() as guards:
    for target in ('candidate_backends.build_geometry_bundle','geometry_native_shape_bridge.publish_native_shape_pool_v3','packaging_runtime.LocalPackagingDouble.select'):
     guards.enter_context(patch('semantic_pallet_planner.jev_select.'+target,side_effect=RuntimeError('RECOVERY_FORBIDDEN:'+target)))
    result=invoke(job,root,cp)
   after=check_counts(plan);delta=result['summary']['accounting']['invocation_delta']
   success(root,job)
   event=result['checkpoint']['events'][-1];pending=cp['pending_event']
   assert event['selection']==pending['selection'] and event['proposed_action']==pending['proposed_action']
   if phase!='SELECTED':assert event['monitor']['result_digest']==pending['monitor']['result_digest']
   assert result['summary']['completed'], 'UNEXPECTED_RECOVERY_STOP'
   assert delta['selector_calls']==delta['singleton_executions']==0
   assert delta['commit_attempts']==delta['commit_successes']
   assert (delta['monitor_entries'],delta['commit_successes'])==(int(phase=='SELECTED'),int(phase!='COMMITTED'))
   assert delta['monitor_reuses']==int(phase=='MONITORED')
   assert after['assessment_entries']-before['assessment_entries']==int(phase=='SELECTED')
   row.update(status='COMPLETE',before=before,after=after,accounting=delta);save()
  receipt['status']='COMPLETE'
 except BaseException as exc:
  receipt.update(status='STOPPED',stop={'type':type(exc).__name__,'reason':str(exc)})
  for row in rows:
   if row['status']=='RUNNING':row['status']='FAILED'
  raise
 finally:save()
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--review',required=True);a.add_argument('--launch',required=True);a.add_argument('--output',required=True);args=a.parse_args()
 execute(R,args.review,args.launch,args.output)
