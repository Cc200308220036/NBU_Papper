"""Frozen R1 fixed suite; no implicit retry. Uses original shared engine/store.
Every unexpected exception/outcome stops the entire run. Kernel/freezer/network
sentinels remain active. Planned checkpoint snapshot child performs no dispatch.
"""
import copy,hashlib,json,os,shutil,socket,traceback
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from test_geometry_order_p1 import SNAP,monitor_double
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p,geometry_order_execution as o
from semantic_pallet_planner.jev_select import geometry_native_shape_bridge as bridge
from semantic_pallet_planner.jev_select import ledger
from semantic_pallet_planner.jev_select.contracts import digest,canonical,JevSelectError
from semantic_pallet_planner.jev_select.geometry_runtime_contracts import same_native
OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01')

def read(path):return json.loads(Path(path).read_bytes())
def write(name,value):
 path=OUT/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def hashes(root):return {str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}
def frozen_source():
 src=Path('semantic_pallet_planner/src/semantic_pallet_planner');v=read(OUT/'source_manifest.json')
 assert all(hashlib.sha256((src/k).read_bytes()).hexdigest()==h for k,h in v['files'].items()),'SOURCE_DRIFT'

class PlannedSnapshotCut(BaseException):pass
branch_mode=False
snapshot_rows=[]

def capture_branch(root,job,phase,cp):
 """Real no-dispatch fork/exception unwind into a complete isolated prefix copy."""
 global branch_mode
 dest=OUT/'R_saved'/(job+'_'+phase)
 assert not dest.exists()
 before=hashes(root);shutil.copytree(root,dest)
 pid=os.fork()
 if pid==0:
  branch_mode=True
  # Only exception-unwind ledger writes remain. The original functions write
  # original accounting ERROR and driver failure to this isolated copy.
  original_path=ledger.Path
  original_root=root.absolute();destination=dest.absolute()
  def redirect(value,*args,**kwargs):
   path=original_path(value,*args,**kwargs)
   try:return destination/path.absolute().relative_to(original_root)
   except ValueError:return path
  ledger.Path=redirect
  # Inherited lock description is shared with parent. Do not release its lock.
  ledger.fcntl.flock=lambda *args,**kwargs:None
  raise PlannedSnapshotCut('EXPLICIT_TEST_SNAPSHOT_'+phase)
 _,status=os.waitpid(pid,0)
 assert os.WIFEXITED(status) and os.WEXITSTATUS(status)==0,'SNAPSHOT_CHILD_ERROR'
 assert hashes(root)==before,'PARENT_PREFIX_CHANGED_BY_SNAPSHOT'
 saved=read(dest/'jobs'/job/'checkpoint.json');account=read(dest/'jobs'/job/'accounting.json')
 assert same_native(saved,cp) and account['invocations'][-1]['status']=='ERROR'
 snapshot_rows.append({'job_id':job,'phase':phase,'root':str(dest),'checkpoint_digest':digest(cp),'accounting_sha256':hashlib.sha256((dest/'jobs'/job/'accounting.json').read_bytes()).hexdigest(),
  'parent_prefix_unchanged':True,'exception':'PlannedSnapshotCut','new_generation_bridge_selection_monitor_commit':0})
 write('R_snapshot_provenance.json',snapshot_rows)

def main():
 global branch_mode
 fd=os.open(OUT/'execution_started.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:json.dump({'one_shot':True,'no_implicit_retry':True},f)
 frozen_source();plan=read(OUT/'plan.json');adm=read(OUT/'admission.json');configs=read(OUT/'configs.json')
 tasks={}
 for case in ('K02_INT','K02'):
  tid='GP5_SYNTH_'+case;raw=(OUT/(tid+'.raw.json')).read_bytes()
  tasks[tid]=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=p.sha(raw))
 crows=[]
 for tag,vals in [('I',[100,80,60]),('F',[100.0,80.5,60.25]),('M',[100,80.0,60])]:
  for yaw in (0,90):
   target=vals if yaw==0 else [vals[1],vals[0],vals[2]];raw=[float(target[0]),float(target[1]),target[2]]
   actual,proof=bridge.restore_size(raw,dict(zip(('length','width','height'),vals)),yaw)
   assert same_native(actual,target) and same_native(bridge.unN(bridge.N(actual)),target)
   crows.append({'case':tag+str(yaw),'raw':raw,'target':actual,'axis_equalities':proof,'H':bridge.H('target_size',{'native_tree':bridge.N(actual)}),'L':bridge.L(actual),'B':bridge.B(canonical(actual).encode()),'status':'PASS'})
 write('C_results.json',crows)
 negative=[]
 for name,args in [('bool',([True,80,60],{'length':100,'width':80,'height':60},0)),('rounding',([99.99999999999999,80,60],{'length':100,'width':80,'height':60},0)),('unrepresentable',([9007199254740992.0,80,60],{'length':9007199254740993,'width':80,'height':60},0)),('axis',([100,80,60],{'length':100,'width':80,'height':60},90)),('yaw_float',([100,80,60],{'length':100,'width':80,'height':60},0.0))]:
  try:bridge.restore_size(*args)
  except JevSelectError as exc:negative.append({'case':name,'status':'REJECTED','code':exc.code})
  else:raise AssertionError(name)
 write('X_pure_results.json',negative)
 rows=[{**j,'status':'NOT_RUN'} for j in plan['jobs']];calls=[];rrows=[]
 def save_counts():
  write('call_accounting.json',{'old_failed_E_monitors':1,'R1_E_monitors':sum(c['group']=='E' for c in calls),'E_cumulative':1+sum(c['group']=='E' for c in calls),'R1_R_monitors':sum(c['group']=='R' for c in calls),'R1_X_H_monitors':sum(c['group']=='X_H' for c in calls),'monitor_dispatch_records':calls,'R_results':rrows,'real_kernel_LP_freeze_model_orders_GP6':0})
 with ExitStack() as stack:
  for name in ('exact_adapter.assess_candidate','balance_adapter.assess_candidate','balance_network.solve_network','balance_network.linprog','monitor.exact_freeze','monitor.freeze'):
   stack.enter_context(patch('semantic_pallet_planner.jev_select.stability.'+name,side_effect=AssertionError('REAL_KERNEL_FREEZE_LP_FORBIDDEN')))
  stack.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')))
  for job,row in zip(plan['jobs'],rows):
   frozen_source();jobid=job['job_id'];cps=[];localcalls=[];row['status']='RUNNING';write('E_results.json',rows)
   def checkpoint(cp):cps.append(copy.deepcopy(cp))
   def hook(name,cp):
    wanted={'after_selected_checkpoint':'SELECTED','after_monitored_checkpoint':'MONITORED','after_commit_checkpoint':'COMMITTED'}
    if jobid in ('J01','J03') and name in wanted and len(cp['pending_event']['before']['placed_items'])==1:
     assert cp['state']['end_of_stream'] and len(cp['pending_event']['before']['pending_items'])==1
     capture_branch(OUT/'E',jobid,wanted[name],cp)
   try:
    assert same_native(o.load_order_config(plan,jobid,monitor_snapshot=SNAP,admission=adm),configs[jobid])
    with monitor_double(localcalls):result=o.run_order_job(plan,jobid,tasks[job['task_id']],monitor_snapshot=SNAP,admission=adm,root=OUT/'E',on_checkpoint=checkpoint,hook=hook)
    calls.extend({'group':'E','job_id':jobid,'record':x} for x in localcalls);save_counts()
    write('E_phases_'+jobid+'.json',cps)
    row.update(status='COMPLETE' if result['summary']['completed'] else 'FAIL',summary=result['summary'],test_double_calls=len(localcalls));write('E_results.json',rows)
    assert result['summary']['completed'] and result['summary']['placed_items']==2 and len(localcalls)==2,'FIXED_E_JOB_DID_NOT_COMPLETE'
    assert same_native(result['final_state']['placed_items'][0]['oriented_size_mm'],list(tasks[job['task_id']]['runtime']['items'][0]['dimensions_mm'].values()))
   except PlannedSnapshotCut:
    if branch_mode:os._exit(0)
    raise
   except BaseException as exc:
    if branch_mode:os._exit(3)
    # Do not double count if assertions happened after saving normal return.
    if row['status']=='RUNNING':calls.extend({'group':'E','job_id':jobid,'record':x} for x in localcalls)
    row.update(status='TECHNICAL_FAILURE',error={'type':type(exc).__name__,'detail':str(exc)})
    write('E_phases_'+jobid+'.json',cps);write('E_results.json',rows);save_counts()
    write('stop.json',{'status':'FIRST_UNEXPECTED_FAILURE_STOPPED','group':'E','job':job,'error':str(exc),'traceback':traceback.format_exc(),'no_retry':True,'R':'NOT_RUN','remaining_X_H_ADMIN':'NOT_RUN'})
    return 2
  # No R or X/H dispatch until all eight E jobs have returned successfully.
 write('E_complete.json',{'status':'PASS_E_ONLY','jobs':8,'monitors':sum(c['group']=='E' for c in calls),'R_X_H_ADMIN':'PENDING_SEPARATE_FROZEN_ENTRYPOINT'})
 return 0
if __name__=='__main__':raise SystemExit(main())
