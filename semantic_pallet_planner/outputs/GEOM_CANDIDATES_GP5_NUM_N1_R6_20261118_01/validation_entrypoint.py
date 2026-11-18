"""R6 test-layer suite: sealed inputs read-only; explicitly new output root.
Not authorized or executed during delivery. No default business execution.
"""
import argparse,copy,hashlib,json,os,shutil,socket,traceback,sys
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
from harness import JobHarness,read,write
from run_state import RunState
INPUTS=Path(__file__).resolve().parent
branch_mode=False
class PlannedSnapshotCut(BaseException):pass

def hashes(root):return {str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}
def check_frozen(inputs):
    for rel,h in read(inputs/'frozen_identity.json')['files'].items():
        assert hashlib.sha256(Path(rel).read_bytes()).hexdigest()==h,'FROZEN_IDENTITY_DRIFT:'+rel
    for rel,h in read(inputs/'archive_member_identity.json')['files'].items():
        assert hashlib.sha256(Path(rel).read_bytes()).hexdigest()==h,'ORIGINAL_ARCHIVE_DRIFT:'+rel
    src=Path('semantic_pallet_planner/src/semantic_pallet_planner')
    current={str(f.relative_to(src)):hashlib.sha256(f.read_bytes()).hexdigest() for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
    assert current==read(inputs/'source_manifest.json')['files'],'SOURCE_SET_OR_BYTE_DRIFT'
def capture_branch(output,root,job,phase,cp):
    """Same live E root used for run, snapshot and status; no dispatch child."""
    global branch_mode
    from semantic_pallet_planner.jev_select import ledger
    from semantic_pallet_planner.jev_select.geometry_runtime_contracts import same_native
    dest=output/'R_saved'/(job+'_'+phase);assert not dest.exists()
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
    rows=read(output/'R_snapshot_provenance.json') if (output/'R_snapshot_provenance.json').exists() else []
    rows.append({'job_id':job,'phase':phase,'root':str(dest),'files':hashes(dest),'parent_prefix_unchanged':True,'new_business_dispatches':0})
    write(output/'R_snapshot_provenance.json',rows)

class Suite:
    def __init__(self,inputs,output,state):
        self.inputs=Path(inputs);self.output=Path(output);self.state=state;self.f0_receipts=[];self.R_commit_attempts=0
        from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
        self.p=p;self.plan=read(self.inputs/'plan.json');self.adm=read(self.inputs/'admission.json');self.monitor_snapshot_value=read(self.inputs/'monitor_snapshot.json')
        self.tasks={}
        for tid in ('GP5_SYNTH_K02_INT','GP5_SYNTH_K02'):
            raw=(self.inputs/(tid+'.raw.json')).read_bytes();self.tasks[tid]=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=p.sha(raw))
        self.calls=[];self.recoveries=[];self.outcomes=[]
    def check_frozen(self):check_frozen(self.inputs)
    def save(self):
        e=sum(x['group']=='E' for x in self.calls);r=sum(x['group']=='R' for x in self.calls);h=sum(x['group']=='X_H' for x in self.calls)
        accounts=[read(f) for f in (self.output/'R_recovery').glob('*/jobs/*/accounting.json')]
        commits=sum(a['invocations'][-1]['delta']['commit_successes'] for a in accounts if len(a['invocations'])>1)
        write(self.output/'call_accounting.json',{'historical_E_used':5,'old17_receipt_preserved':True,'new_E':e,'cross_history_E':5+e,'cross_history_E_max':21,'new_R_monitors':r,'new_R_commits':commits,'R_commit_dispatch_attempts':self.R_commit_attempts,'R_resumes_attempted':sum(r['attempts'] for r in self.state.rows if r['group']=='R'),'R_resumes_passed':sum(r['status']=='PASS' for r in self.state.rows if r['group']=='R'),'new_X_H_monitors':h,'dispatch_records':self.calls,'R_results':self.recoveries,'real_calls':0})
        assert e<=16 and r<=2 and h<=1 and commits<=4 and sum(r['attempts'] for r in self.state.rows if r['group']=='R')<=6,'BUDGET_EXCEEDED'
        self.state.save()
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
        from coverage_checks import conversion_case
        rows=[]
        for tag,values in [('I',[100,80,60]),('F',[100.0,80.5,60.25]),('M',[100,80.0,60])]:
            for yaw in (0,90):
                identity=tag+str(yaw)
                with self.state.case('C/'+identity) as evidence:
                    self.check_frozen();receipt=conversion_case(tag,values,yaw)
                    path=self.output/'C'/(identity+'.json');write(path,receipt)
                    evidence.append({'path':str(path),'requirements':receipt['requirements']});rows.append(receipt)
                    write(self.output/'C_results.json',rows)
    def run_E(self):
        from semantic_pallet_planner.jev_select import geometry_order_execution as order
        from geometry_native_assertions_r2 import assert_episode_shapes
        assert not (self.output/'E').exists(),'FRESH_ROOT_REQUIRED'
        harness=JobHarness(self.output/'E',self.output/'E_receipts')
        for job in self.plan['jobs']:
            jid=job['job_id']
            with self.state.case('E/'+jid) as evidence:
                self.check_frozen();cps=[]
                def hook(name,cp):
                    phases={'after_selected_checkpoint':'SELECTED','after_monitored_checkpoint':'MONITORED','after_commit_checkpoint':'COMMITTED'}
                    if jid in ('J01','J03') and name in phases and len(cp['pending_event']['before']['placed_items'])==1:
                        assert cp['state']['end_of_stream'] and len(cp['pending_event']['before']['pending_items'])==1
                        capture_branch(self.output,harness.root,jid,phases[name],cp)
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
                        if not branch_mode:write(self.output/('E_phases_'+jid+'.json'),cps)
                    assert row['production_status']=='COMPLETE' and result['summary']['completed'] and result['summary']['placed_items']==2 and len(local)==2,'E_JOB_NOT_COMPLETE'
                    shapes=assert_episode_shapes(result);assert len(shapes)==2
                    write(self.output/('E_assertions_'+jid+'.json'),shapes)
                    from coverage_checks import f0_receipt,compare_f0
                    cfg=read(self.inputs/'configs.json')[jid]
                    store=order.OrderStore(harness.root/'jobs'/jid,plan=self.plan,job_id=jid,adapted=self.tasks[job['task_id']],monitor_snapshot=self.monitor_snapshot,admission=self.adm)
                    closed=[]
                    for idx,ev in enumerate(result['events']):
                        if ev.get('bundle') is not None:
                            store.load_event(ev,cfg)
                            closed.append({'event_index':idx,'geometry_ref':ev['geometry_ref'],'status':'PASS_COMPLETE_SAVED_REFERENCE_CLOSURE'})
                    f0=f0_receipt(result,cfg);self.f0_receipts.append(f0)
                    path=self.output/('E_f0_'+jid+'.json');write(path,{'f0':f0,'production_saved_closure':closed})
                    evidence.append({'path':str(path),'complete_production_identity_closure':closed,'F0_fields':'PASS'})
                    if len(self.f0_receipts)==8:
                        pairs=compare_f0(self.f0_receipts);write(self.output/'E_f0_pairs.json',pairs)
                        evidence.append({'paired_public_field_contract':str(self.output/'E_f0_pairs.json'),'pairs':4})
    @property
    def monitor_snapshot(self):return self.__dict__['monitor_snapshot_value']
    def run_R(self):
        from semantic_pallet_planner.jev_select import geometry_order_execution as order
        from geometry_native_assertions_r2 import assert_episode_shapes
        from semantic_pallet_planner.jev_select.candidates import CandidateProvider
        from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
        from semantic_pallet_planner.jev_select import geometry_native_shape_bridge as bridge,execution
        original_commit=execution.commit_physical
        def bounded_commit(*args,**kwargs):
            assert self.R_commit_attempts<4,'R_COMMIT_BUDGET_WOULD_EXCEED'
            self.R_commit_attempts+=1
            return original_commit(*args,**kwargs)
        for job in ('J01','J03'):
            j=next(x for x in self.plan['jobs'] if x['job_id']==job)
            for phase in ('SELECTED','MONITORED','COMMITTED'):
                with self.state.case('R/'+job+'/'+phase) as evidence:
                    self.check_frozen();saved=self.output/'R_saved'/(job+'_'+phase);root=self.output/'R_recovery'/(job+'_'+phase)
                    provenance=next(x for x in read(self.output/'R_snapshot_provenance.json') if x['job_id']==job and x['phase']==phase)
                    assert hashes(saved)==provenance['files'] and not root.exists()
                    shutil.copytree(saved,root);cp=read(root/'jobs'/job/'checkpoint.json')
                    with ExitStack() as guards,self.monitor('R',job,local_limit=int(phase=='SELECTED')) as local:
                        guards.enter_context(patch.object(execution,'commit_physical',side_effect=bounded_commit))
                        guards.enter_context(patch.object(CandidateProvider,'build',side_effect=AssertionError('RESUME_GENERATED')))
                        guards.enter_context(patch.object(bridge,'publish_native_shape_pool_v3',side_effect=AssertionError('RESUME_PUBLISHED')))
                        guards.enter_context(patch.object(LocalPackagingDouble,'select',side_effect=AssertionError('RESUME_SELECTED')))
                        result,_=JobHarness(root,self.output/'R_receipts'/(job+'_'+phase)).run(job,lambda r:order.run_order_job(self.plan,job,self.tasks[j['task_id']],monitor_snapshot=self.monitor_snapshot,admission=self.adm,root=r,resume=cp),local)
                        delta=read(root/'jobs'/job/'accounting.json')['invocations'][-1]['delta']
                        expected={'selector_calls':0,'singleton_executions':0,'monitor_entries':int(phase=='SELECTED'),'monitor_reuses':int(phase=='MONITORED'),'commit_attempts':int(phase!='COMMITTED'),'commit_successes':int(phase!='COMMITTED')}
                        assert delta==expected and len(local)==expected['monitor_entries'] and result['summary']['completed']
                        assert_episode_shapes(result)
                        self.recoveries.append({'job_id':job,'phase':phase,'delta':delta,'generation_publication_selection_increment':0,'status':'PASS'})
                    assert hashes(saved)==provenance['files']
                    self.save()
                    evidence.append({'job_id':job,'phase':phase,'delta':delta,'generation_publication_selection':0})
    def X_H_admin(self):
        from remaining_checks import run_checks
        run_checks(self)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-root',required=True);parser.add_argument('--authorization-receipt',required=True)
    args=parser.parse_args();auth=read(args.authorization_receipt);output=Path(args.run_root).resolve()
    assert output.parent==(Path.cwd()/'semantic_pallet_planner/outputs').resolve(),'NEW_DIRECT_OUTPUT_ROOT_REQUIRED'
    assert auth['unit']=='GP5_NUM_N1_R6_F0_SINGLETON_RECEIPT_FIX' and auth['explicit_user_assignment'] is True
    assert auth['source_identity']=='94e4c37838f0a82f84c200d12fbed5d92c93eb7486085e9c3014c514ba886fa2'
    assert auth['input_freeze_sha256']==hashlib.sha256((INPUTS/'frozen_identity.json').read_bytes()).hexdigest()
    assert auth['validation_scope_sha256']==hashlib.sha256((INPUTS/'validation_scope.json').read_bytes()).hexdigest()
    assert Path(auth['run_root']).resolve()==output,'AUTH_OUTPUT_ROOT_MISMATCH'
    protected=[INPUTS.parent/n for n in ('GEOM_CANDIDATES_GP5_NUM_N1_R4_20261118_01','GEOM_CANDIDATES_GP5_NUM_N1_R4_QA_20261118_01','GEOM_CANDIDATES_GP5_NUM_N1_R5_20261118_01','GEOM_CANDIDATES_GP5_NUM_N1_R5_QA_20261118_01')]
    state=RunState(INPUTS,output,read(INPUTS/'validation_scope.json'),protected=protected,authorization=auth)
    suite=None
    try:
        check_frozen(INPUTS)
        with ExitStack() as guards:
            for name in ('exact_adapter.assess_candidate','balance_adapter.assess_candidate','balance_network.solve_network','balance_network.linprog','monitor.exact_freeze','monitor.freeze'):
                guards.enter_context(patch('semantic_pallet_planner.jev_select.stability.'+name,side_effect=AssertionError('REAL_KERNEL_FREEZE_LP_FORBIDDEN')))
            guards.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')))
            suite=Suite(INPUTS,output,state);suite.C();suite.run_E();suite.run_R();suite.X_H_admin();suite.save()
        state.verify_archives();write(output/'bounded_complete.json',{'status':'COMPLETED_PENDING_INDEPENDENT_QA','advance_P2':False})
    except BaseException as exc:
        if branch_mode:os._exit(3)
        original_trace=traceback.format_exc();secondary=None;state.stopped=True
        try:
            state.save()
            if suite:suite.save()
            state.verify_archives()
        except Exception as archival:secondary=repr(archival)
        write(output/'validation_stop.json',{'status':'FIRST_UNEXPECTED_FAILURE_STOPPED','type':type(exc).__name__,'code':getattr(exc,'code',None),'detail':str(exc),'traceback':original_trace,'archival_error':secondary,'no_retry':True})
        raise
if __name__=='__main__':
    # Remaining checks receive the active suite explicitly; never import a second
    # copy of this module with another global output root.
    main()
