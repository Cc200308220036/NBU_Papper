"""Fixed C/E/R/X/H/admin suite. NOT executed during R4 entrypoint delivery.
Requires a separately supplied explicit user authorization receipt; no defaults.
"""
import argparse,copy,hashlib,json,os,shutil,socket,traceback
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
from harness import JobHarness,read,write,job_status
O=Path(__file__).resolve().parent
E=O/'E'
branch_mode=False
class PlannedSnapshotCut(BaseException):pass

def hashes(root):return {str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}
def check_frozen():
    for rel,h in read(O/'frozen_identity.json')['files'].items():
        assert hashlib.sha256(Path(rel).read_bytes()).hexdigest()==h,'FROZEN_IDENTITY_DRIFT:'+rel
    src=Path('semantic_pallet_planner/src/semantic_pallet_planner')
    current={str(f.relative_to(src)):hashlib.sha256(f.read_bytes()).hexdigest() for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
    assert current==read(O/'source_manifest.json')['files'],'SOURCE_SET_OR_BYTE_DRIFT'

def capture_branch(root,job,phase,cp):
    """Same live E root used for run, snapshot and status; no dispatch child."""
    global branch_mode
    from semantic_pallet_planner.jev_select import ledger
    from semantic_pallet_planner.jev_select.geometry_runtime_contracts import same_native
    dest=O/'R_saved'/(job+'_'+phase);assert not dest.exists()
    before=hashes(root);shutil.copytree(root,dest)
    pid=os.fork()
    if pid==0:
        branch_mode=True;original=ledger.Path;source=root.absolute();target=dest.absolute()
        def redirect(value,*args,**kwargs):
            p=original(value,*args,**kwargs)
            try:return target/p.absolute().relative_to(source)
            except ValueError:return p
        ledger.Path=redirect;ledger.fcntl.flock=lambda *args,**kwargs:None
        raise PlannedSnapshotCut('EXPLICIT_NO_DISPATCH_SNAPSHOT_'+phase)
    _,status=os.waitpid(pid,0)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status)==0,'SNAPSHOT_CHILD_ERROR'
    assert hashes(root)==before,'PARENT_PREFIX_CHANGED'
    assert same_native(read(dest/'jobs'/job/'checkpoint.json'),cp)
    assert read(dest/'jobs'/job/'accounting.json')['invocations'][-1]['status']=='ERROR'
    rows=read(O/'R_snapshot_provenance.json') if (O/'R_snapshot_provenance.json').exists() else []
    rows.append({'job_id':job,'phase':phase,'root':str(dest),'files':hashes(dest),'parent_prefix_unchanged':True,'new_business_dispatches':0})
    write(O/'R_snapshot_provenance.json',rows)

class Suite:
    def __init__(self):
        from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
        self.p=p;self.plan=read(O/'plan.json');self.adm=read(O/'admission.json');self.monitor_snapshot_value=read(O/'monitor_snapshot.json')
        self.tasks={}
        for tid in ('GP5_SYNTH_K02_INT','GP5_SYNTH_K02'):
            raw=(O/(tid+'.raw.json')).read_bytes();self.tasks[tid]=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=p.sha(raw))
        self.calls=[];self.recoveries=[];self.outcomes=[]
    def save(self):
        e=sum(x['group']=='E' for x in self.calls);r=sum(x['group']=='R' for x in self.calls);h=sum(x['group']=='X_H' for x in self.calls)
        accounts=[read(f) for f in (O/'R_recovery').glob('*/jobs/*/accounting.json')]
        commits=sum(a['invocations'][-1]['delta']['commit_successes'] for a in accounts if len(a['invocations'])>1)
        write(O/'call_accounting.json',{'historical_E_used':5,'old17_receipt_preserved':True,'new_E':e,'cross_history_E':5+e,'cross_history_E_max':21,'new_R_monitors':r,'new_R_commits':commits,'R_resumes':len(self.recoveries),'new_X_H_monitors':h,'dispatch_records':self.calls,'R_results':self.recoveries,'real_calls':0})
        assert e<=16 and r<=2 and h<=1 and commits<=4 and len(self.recoveries)<=6,'BUDGET_EXCEEDED'
        write(O/'suite_results.json',self.outcomes)
    def monitor(self,group,job,local_limit=None):
        from test_geometry_order_p1 import monitor_double
        from contextlib import contextmanager
        @contextmanager
        def guarded():
            local=[]
            limits={'E':16,'R':2,'X_H':1}
            # Count before every dispatch, never discover an overshoot after it.
            class Bounded(list):
                def append(_,value):
                    used=sum(x['group']==group for x in self.calls)
                    assert used+len(local)<limits[group] and len(local)<(local_limit if local_limit is not None else (2 if group=='E' else 1)),'MONITOR_BUDGET_WOULD_EXCEED'
                    local.append(value)
            try:
                with monitor_double(Bounded()):yield local
            finally:
                self.calls.extend({'group':group,'job_id':job,'record':v} for v in local)
                if not branch_mode:self.save()
        return guarded()
    def C(self):
        from semantic_pallet_planner.jev_select import geometry_native_shape_bridge as b
        from semantic_pallet_planner.jev_select.geometry_runtime_contracts import same_native
        rows=[]
        for tag,vals in [('I',[100,80,60]),('F',[100.0,80.5,60.25]),('M',[100,80.0,60])]:
            for yaw in (0,90):
                target=vals if yaw==0 else [vals[1],vals[0],vals[2]];raw=[float(target[0]),float(target[1]),target[2]]
                actual,proof=b.restore_size(raw,dict(zip(('length','width','height'),vals)),yaw)
                assert same_native(actual,target) and same_native(b.unN(b.N(actual)),target)
                rows.append({'case':tag+str(yaw),'raw':raw,'target':actual,'axis_equalities':proof,'digest':b.H('target_size',{'native_tree':b.N(actual)}),'status':'PASS'})
        write(O/'C_results.json',rows)
    def run_E(self):
        from semantic_pallet_planner.jev_select import geometry_order_execution as order
        from geometry_native_assertions_r2 import assert_episode_shapes
        assert not E.exists(),'FRESH_ROOT_REQUIRED'
        harness=JobHarness(E,O/'E_receipts')
        for job in self.plan['jobs']:
            check_frozen();jid=job['job_id'];cps=[]
            def hook(name,cp):
                phases={'after_selected_checkpoint':'SELECTED','after_monitored_checkpoint':'MONITORED','after_commit_checkpoint':'COMMITTED'}
                if jid in ('J01','J03') and name in phases and len(cp['pending_event']['before']['placed_items'])==1:
                    assert cp['state']['end_of_stream'] and len(cp['pending_event']['before']['pending_items'])==1
                    capture_branch(harness.root,jid,phases[name],cp)
            with self.monitor('E',jid) as local:
                try:
                    result,row=harness.run(jid,lambda root:order.run_order_job(self.plan,jid,self.tasks[job['task_id']],monitor_snapshot=self.monitor_snapshot,admission=self.adm,root=root,on_checkpoint=lambda cp:cps.append(copy.deepcopy(cp)),hook=hook),local,passthrough=(PlannedSnapshotCut,))
                except PlannedSnapshotCut:
                    if branch_mode:os._exit(0)
                    raise
                except BaseException:
                    if branch_mode:os._exit(3)
                    raise
                finally:
                    if not branch_mode:write(O/('E_phases_'+jid+'.json'),cps)
                assert row['production_status']=='COMPLETE' and result['summary']['completed'] and result['summary']['placed_items']==2 and len(local)==2,'E_JOB_NOT_COMPLETE'
                shapes=assert_episode_shapes(result);assert len(shapes)==2
                write(O/('E_assertions_'+jid+'.json'),shapes)
                self.outcomes.append({'group':'E','job_id':jid,'production_status':row['production_status'],'validation_status':'PASS'})
    @property
    def monitor_snapshot(self):return self.__dict__['monitor_snapshot_value']
    def run_R(self):
        from semantic_pallet_planner.jev_select import geometry_order_execution as order
        from geometry_native_assertions_r2 import assert_episode_shapes
        from semantic_pallet_planner.jev_select.candidates import CandidateProvider
        from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
        from semantic_pallet_planner.jev_select import geometry_native_shape_bridge as bridge
        for job in ('J01','J03'):
            j=next(x for x in self.plan['jobs'] if x['job_id']==job)
            for phase in ('SELECTED','MONITORED','COMMITTED'):
                check_frozen();saved=O/'R_saved'/(job+'_'+phase);root=O/'R_recovery'/(job+'_'+phase)
                provenance=next(x for x in read(O/'R_snapshot_provenance.json') if x['job_id']==job and x['phase']==phase)
                assert hashes(saved)==provenance['files'] and not root.exists()
                shutil.copytree(saved,root);cp=read(root/'jobs'/job/'checkpoint.json')
                with ExitStack() as guards,self.monitor('R',job,local_limit=int(phase=='SELECTED')) as local:
                    guards.enter_context(patch.object(CandidateProvider,'build',side_effect=AssertionError('RESUME_GENERATED')))
                    guards.enter_context(patch.object(bridge,'publish_native_shape_pool_v3',side_effect=AssertionError('RESUME_PUBLISHED')))
                    guards.enter_context(patch.object(LocalPackagingDouble,'select',side_effect=AssertionError('RESUME_SELECTED')))
                    result,_=JobHarness(root,O/'R_receipts'/(job+'_'+phase)).run(job,lambda r:order.run_order_job(self.plan,job,self.tasks[j['task_id']],monitor_snapshot=self.monitor_snapshot,admission=self.adm,root=r,resume=cp),local)
                    delta=read(root/'jobs'/job/'accounting.json')['invocations'][-1]['delta']
                    expected={'selector_calls':0,'singleton_executions':0,'monitor_entries':int(phase=='SELECTED'),'monitor_reuses':int(phase=='MONITORED'),'commit_attempts':int(phase!='COMMITTED'),'commit_successes':int(phase!='COMMITTED')}
                    assert delta==expected and len(local)==expected['monitor_entries'] and result['summary']['completed']
                    assert_episode_shapes(result)
                    self.recoveries.append({'job_id':job,'phase':phase,'delta':delta,'generation_publication_selection_increment':0,'status':'PASS'})
                assert hashes(saved)==provenance['files']
                self.save()
    def X_H_admin(self):
        from remaining_checks import run_checks
        run_checks(self)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--authorization-receipt',required=True)
    args=parser.parse_args();auth=read(args.authorization_receipt)
    assert auth['unit']=='GP5_NUM_N1_R4_ENVIRONMENT_AND_VALIDATION_ENTRYPOINT' and auth['explicit_user_assignment'] is True and auth['source_identity']=='94e4c37838f0a82f84c200d12fbed5d92c93eb7486085e9c3014c514ba886fa2'
    assert auth['validation_scope_sha256']==hashlib.sha256((O/'validation_scope.json').read_bytes()).hexdigest(),'AUTH_SCOPE_MISMATCH'
    check_frozen();fd=os.open(O/'execution_started.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'authorization':auth,'one_shot':True},f)
    suite=None
    try:
        with ExitStack() as guards:
            for name in ('exact_adapter.assess_candidate','balance_adapter.assess_candidate','balance_network.solve_network','balance_network.linprog','monitor.exact_freeze','monitor.freeze'):
                guards.enter_context(patch('semantic_pallet_planner.jev_select.stability.'+name,side_effect=AssertionError('REAL_KERNEL_FREEZE_LP_FORBIDDEN')))
            guards.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')))
            suite=Suite();suite.C();suite.run_E();suite.run_R();suite.X_H_admin();suite.save()
        write(O/'bounded_complete.json',{'status':'FIXED_SUITE_COMPLETED_PENDING_INDEPENDENT_QA','advance_P2':False})
    except BaseException as exc:
        if branch_mode:os._exit(3)
        original_trace=traceback.format_exc();secondary=None
        if suite:
            try:suite.save()
            except Exception as archival:secondary=repr(archival)
        write(O/'validation_stop.json',{'status':'FIRST_UNEXPECTED_FAILURE_STOPPED','type':type(exc).__name__,'detail':str(exc),'traceback':original_trace,'accounting_archival_error':secondary,'no_retry':True})
        raise
if __name__=='__main__':main()
