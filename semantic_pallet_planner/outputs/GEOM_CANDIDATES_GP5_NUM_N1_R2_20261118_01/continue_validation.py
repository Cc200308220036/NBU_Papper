"""One-shot remaining E only; complete-prefix copy and original fixed R snapshots.
No J00 execution. First unexpected production/validator/isolation failure stops.
"""
import copy,hashlib,json,os,shutil,socket,traceback
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from geometry_native_assertions_r2 import assert_episode_shapes,same_native
from test_geometry_order_p1 import SNAP,monitor_double
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p,geometry_order_execution as o,ledger
from semantic_pallet_planner.jev_select.contracts import digest

OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N1_R2_20261118_01')
branch_mode=False
snapshots=[]

def read(p):return json.loads(Path(p).read_bytes())
def write(n,v):
    f=OUT/n;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def hashes(root):return {str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}
def check_source():
    src=Path('semantic_pallet_planner/src/semantic_pallet_planner')
    actual={str(f.relative_to(src)):hashlib.sha256(f.read_bytes()).hexdigest() for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
    assert actual==read(OUT/'source_manifest.json')['files'],'PRODUCTION_SET_OR_BYTES_DRIFT'
class PlannedSnapshotCut(BaseException):pass

def capture_branch(root,job,phase,cp):
    global branch_mode
    dest=OUT/'R_saved'/(job+'_'+phase);assert not dest.exists()
    before=hashes(root);shutil.copytree(root,dest)
    pid=os.fork()
    if pid==0:
        branch_mode=True
        original_path=ledger.Path;source=root.absolute();target=dest.absolute()
        def redirect(value,*args,**kwargs):
            f=original_path(value,*args,**kwargs)
            try:return target/f.absolute().relative_to(source)
            except ValueError:return f
        ledger.Path=redirect
        ledger.fcntl.flock=lambda *args,**kwargs:None
        raise PlannedSnapshotCut('EXPLICIT_NO_DISPATCH_SNAPSHOT_'+phase)
    _,status=os.waitpid(pid,0)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status)==0,'SNAPSHOT_CHILD_ERROR'
    assert hashes(root)==before,'PARENT_PREFIX_CHANGED'
    saved=read(dest/'jobs'/job/'checkpoint.json');account=read(dest/'jobs'/job/'accounting.json')
    assert same_native(saved,cp) and account['invocations'][-1]['status']=='ERROR'
    snapshots.append({'job_id':job,'phase':phase,'root':str(dest),'checkpoint_digest':digest(cp),'accounting_sha256':hashlib.sha256((dest/'jobs'/job/'accounting.json').read_bytes()).hexdigest(),
        'parent_prefix_unchanged':True,'planned_exception':'PlannedSnapshotCut','new_generation_bridge_selection_monitor_commit':0})
    write('R_snapshot_provenance.json',snapshots)

def main():
    fd=os.open(OUT/'continuation_started.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'one_shot':True,'J00_execution_forbidden':True},f)
    check_source();plan=read(OUT/'plan.json');admission=read(OUT/'admission.json');configs=read(OUT/'configs.json');monitor=read(OUT/'monitor_snapshot.json');assert same_native(monitor,SNAP)
    assert hashes(OUT/'prefix_snapshot')==read(OUT/'prefix_provenance.json')['files']
    assert hashes(OUT/'continuation')==hashes(OUT/'prefix_snapshot')
    tasks={}
    for case in ('K02_INT','K02'):
        tid='GP5_SYNTH_'+case;raw=(OUT/(tid+'.raw.json')).read_bytes()
        tasks[tid]=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=p.sha(raw))
    rows=[{**j,'production_status':'COMPLETE_SAVED_PREFIX' if j['job_id']=='J00' else 'NOT_RUN','validation_status':'PASS_SAVED_ONLY' if j['job_id']=='J00' else 'NOT_RUN','executed_this_round':False} for j in plan['jobs']]
    calls=[]
    def save():
        write('validation_outcomes.json',rows)
        write('call_accounting.json',{'E_previously_consumed':3,'E_R2_added':len(calls),'E_cumulative':3+len(calls),'E_limit':17,'R_monitor_added':0,'R_commit_added':0,'R_status':'NOT_RUN','X_H_monitor_added':0,'X_H_status':'NOT_RUN','monitor_dispatch_records':calls,'real_kernel_LP_freeze_model':0})
    save()
    with ExitStack() as stack:
        for name in ('exact_adapter.assess_candidate','balance_adapter.assess_candidate','balance_network.solve_network','balance_network.linprog','monitor.exact_freeze','monitor.freeze'):
            stack.enter_context(patch('semantic_pallet_planner.jev_select.stability.'+name,side_effect=AssertionError('REAL_KERNEL_FREEZE_LP_FORBIDDEN')))
        stack.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')))
        for job,row in zip(plan['jobs'][1:],rows[1:]):
            jid=job['job_id'];assert jid!='J00';local=[];cps=[];row['executed_this_round']=True;row['production_status']='RUNNING';row['validation_status']='RUNNING';save()
            def callback(cp):cps.append(copy.deepcopy(cp))
            def hook(name,cp):
                phases={'after_selected_checkpoint':'SELECTED','after_monitored_checkpoint':'MONITORED','after_commit_checkpoint':'COMMITTED'}
                if jid in ('J01','J03') and name in phases and len(cp['pending_event']['before']['placed_items'])==1:
                    assert cp['state']['end_of_stream'] and len(cp['pending_event']['before']['pending_items'])==1
                    capture_branch(OUT/'continuation',jid,phases[name],cp)
            try:
                check_source();assert same_native(o.load_order_config(plan,jid,monitor_snapshot=monitor,admission=admission),configs[jid]),'CONFIG_DRIFT'
                with monitor_double(local):result=o.run_order_job(plan,jid,tasks[job['task_id']],monitor_snapshot=monitor,admission=admission,root=OUT/'continuation',on_checkpoint=callback,hook=hook)
                row['production_status']=read(OUT/'continuation/run.json')['rows'][int(jid[1:])]['status']
                assert result['summary'] is not None and result['summary']['completed'] and result['summary']['placed_items']==2 and len(local)==2,'FIXED_JOB_DID_NOT_COMPLETE'
                assertions=assert_episode_shapes(result);assert len(assertions)==2
                write('assertions_'+jid+'.json',assertions);row['validation_status']='PASS';row['new_monitors']=len(local)
            except PlannedSnapshotCut:
                if branch_mode:os._exit(0)
                raise
            except BaseException as exc:
                if branch_mode:os._exit(3)
                state=read(OUT/'continuation/run.json')['rows'][int(jid[1:])]['status']
                row.update(production_status=state,validation_status='FAIL',error={'type':type(exc).__name__,'detail':str(exc)})
                calls.extend({'group':'E','job_id':jid,'record':x} for x in local);write('phases_'+jid+'.json',cps);save()
                write('stop.json',{'status':'FIRST_UNEXPECTED_FAILURE_STOPPED','group':'E','job_id':jid,'production_status':state,'validation_status':'FAIL','type':type(exc).__name__,'detail':str(exc),'traceback':traceback.format_exc(),'no_retry':True,'R_X_H_ADMIN':'NOT_RUN'})
                return 2
            calls.extend({'group':'E','job_id':jid,'record':x} for x in local);assert len(calls)<=14
            write('phases_'+jid+'.json',cps);save()
    write('E_complete.json',{'status':'PASS_REMAINING_SEVEN_PLUS_SAVED_J00','new_jobs':7,'new_monitors':len(calls),'cumulative_E':3+len(calls),'next':'original R/X/H/admin entrypoint only'})
    return 0
if __name__=='__main__':raise SystemExit(main())
