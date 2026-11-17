"""Independent bounded entry/solver instrumentation, inactive unless explicitly entered.

Reservations are fsynced before invocation. An unfinished reservation stops resume
as UNKNOWN_CALL; it is never retried. Wrappers forward original arguments/results.
"""
import copy
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from threading import Lock

from .contracts import digest
from .ledger import read,write
from .packaging_geometry_protocol import require,DEVELOPMENT

_ACTIVE=ContextVar('geometry_order_meter',default=None)
_LOCK=Lock()


class CallBudget:
    def __init__(self,path,plan,*,evidence='COUNTER_TEST',job_id='COUNTER_TEST'):
        self.job_id=job_id
        self.path=Path(path);self.plan_digest=digest(plan)
        self.limits={'assessment_entries':plan['assessment_limit'],'solver_calls':plan['solver_limit']}
        if self.path.exists():
            self.value=read(self.path)
            require(self.value['plan_digest']==self.plan_digest and self.value['limits']==self.limits and self.value['evidence']==evidence,'geometry_meter_identity')
            require(all(r['state']!='STARTED' for r in self.value['calls']),'geometry_meter_unknown_call')
        else:self.value={'version':'geometry_call_ledger_v1','plan_digest':self.plan_digest,
            'evidence':evidence,'limits':self.limits,'calls':[],
            'counts':{'assessment_entries':0,'solver_calls':0,'test_double_assessments':0}}
        require(set(self.value)=={'version','plan_digest','evidence','limits','calls','counts'} and self.value['version']=='geometry_call_ledger_v1','geometry_meter_contract')
        for kind in self.limits:
            require(type(self.value['counts'][kind]) is int and self.value['counts'][kind]==sum(r['kind']==kind for r in self.value['calls']) and self.value['counts'][kind]<=self.limits[kind],'geometry_meter_count_drift')
        require(self.value['counts']['test_double_assessments']==0,'geometry_meter_test_double')
        self.invocation_start=len(self.value['calls'])
        self._save()
    def _save(self):
        import os
        write(self.path,self.value)
        fd=os.open(self.path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
        require(read(self.path)==self.value,'geometry_meter_readback')
    def call(self,kind,fn,*args,**kwargs):
        require(kind in self.limits,'geometry_meter_kind')
        count=self.value['counts'][kind]
        require(count<self.limits[kind],'geometry_'+kind+'_budget_exhausted')
        self.value['counts'][kind]+=1
        row={'kind':kind,'state':'STARTED','index':len(self.value['calls']),'job_id':self.job_id};self.value['calls'].append(row);self._save()
        try:result=fn(*args,**kwargs)
        except BaseException:
            row['state']='ERROR';self._save();raise
        row['state']='DONE';self._save();return result


def current_counts(plan_digest):
    budget=_ACTIVE.get()
    require(budget is not None and budget.plan_digest==plan_digest,'geometry_active_meter_required')
    return {**{kind:sum(r['kind']==kind and r['job_id']==budget.job_id for r in budget.value['calls']) for kind in budget.limits},'test_double_assessments':0}


def current_increment(plan_digest):
    budget=_ACTIVE.get()
    require(budget is not None and budget.plan_digest==plan_digest,'geometry_active_meter_required')
    return {**{kind:sum(r['kind']==kind and r['job_id']==budget.job_id for r in budget.value['calls'][budget.invocation_start:]) for kind in budget.limits},'test_double_assessments':0}


@contextmanager
def metered_run(plan,*,job_id,monitor_snapshot,admission,kernel_receipt=None):
    """Future real scope only. No caller can turn a development fixture into real evidence."""
    from .packaging_geometry_protocol import validate_admission,ACCEPTANCE
    validate_admission(plan,monitor_snapshot,admission,kernel_receipt)
    require(job_id in {j['job_id'] for j in plan['jobs']} or (plan['scope']==ACCEPTANCE and job_id=='K03_ADAPTER'),'geometry_meter_job')
    require(plan['scope']!=DEVELOPMENT and plan['status']=='FROZEN' and plan['call_ledger_path'] is not None,'geometry_meter_scope')
    require(_LOCK.acquire(blocking=False),'geometry_meter_concurrent_run')
    token=None;lock_stream=None
    try:
        import fcntl
        ledger=Path(plan['call_ledger_path']);ledger.parent.mkdir(parents=True,exist_ok=True)
        lock_stream=ledger.with_suffix(ledger.suffix+'.lock').open('a+b')
        try:fcntl.flock(lock_stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:require(False,'geometry_meter_process_locked')
        from .stability import exact_adapter,balance_network
        budget=CallBudget(plan['call_ledger_path'],plan,evidence='REAL_KERNEL',job_id=job_id)
        original_assess=exact_adapter.assess_candidate;original_solver=balance_network.linprog
        def assess(*a,**kw):return budget.call('assessment_entries',original_assess,*a,**kw)
        def solver(*a,**kw):return budget.call('solver_calls',original_solver,*a,**kw)
        token=_ACTIVE.set(budget)
        exact_adapter.assess_candidate=assess;balance_network.linprog=solver
        try:yield budget
        finally:exact_adapter.assess_candidate=original_assess;balance_network.linprog=original_solver
    finally:
        if token is not None:_ACTIVE.reset(token)
        if lock_stream is not None:lock_stream.close()
        _LOCK.release()
