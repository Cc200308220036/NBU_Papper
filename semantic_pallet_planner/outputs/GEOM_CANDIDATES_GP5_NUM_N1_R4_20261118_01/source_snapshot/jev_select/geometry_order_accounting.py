"""v16 observational accounting. Does not select, assess or commit actions."""
import copy
from contextlib import contextmanager
from contextvars import ContextVar
from .geometry_native_protocol import wire, is_native, identity_fields, config_fields
from .contracts import digest,validate_schema
from .packaging_geometry_protocol import require
from .ledger import read,write

FIELDS=('selector_calls','singleton_executions','monitor_entries','monitor_reuses','commit_attempts','commit_successes')
_ACTIVE=ContextVar('geometry_order_accounting',default=None)
def zero():return dict.fromkeys(FIELDS,0)

def tick(config,kind):
    active=_ACTIVE.get()
    if config.get('version') not in ('jev_packaging_geometry_order_v16','jev_packaging_geometry_order_v17') or active is None:return
    path,doc=active
    require(doc['config_digest']==digest(config) and kind in FIELDS,'geometry_accounting_binding')
    doc['invocations'][-1]['delta'][kind]+=1;doc['cumulative'][kind]+=1
    validate_schema(wire(config,'geometry_order_accounting_v1'),doc);write(path,doc)

def snapshot(config):
    active=_ACTIVE.get()
    if active is None:return {'status':'UNKNOWN_UNINSTRUMENTED','cumulative':None,'invocation_delta':None,'resume_phase':None}
    _,doc=active
    require(doc['config_digest']==digest(config),'geometry_accounting_binding')
    return {'status':'OBSERVED','cumulative':copy.deepcopy(doc['cumulative']),
        'invocation_delta':copy.deepcopy(doc['invocations'][-1]['delta']),
        'resume_phase':doc['invocations'][-1]['resume_phase']}

@contextmanager
def invocation(path,config,job_id,resume):
    binding={**identity_fields(config),'version':wire(config,'geometry_order_accounting_v1'),'plan_digest':config['plan_digest'],
        'job_id':job_id,'config_digest':digest(config)}
    if path.exists():
        doc=read(path);validate_schema(wire(config,'geometry_order_accounting_v1'),doc)
        require(all(doc[k]==v for k,v in binding.items()),'geometry_accounting_drift')
        require(resume is not None,'geometry_accounting_resume_required')
        require(all(doc['cumulative'][k]==sum(i['delta'][k] for i in doc['invocations']) for k in FIELDS),'geometry_accounting_sum')
        # A process loss between dispatch and completion cannot certify safe replay.
        require(not doc['invocations'] or doc['invocations'][-1]['status']!='STARTED','geometry_accounting_unknown_dispatch')
    else:
        require(resume is None,'geometry_accounting_missing_history')
        doc={**binding,'invocations':[],'cumulative':zero()}
    doc['invocations'].append({'index':len(doc['invocations']),'resume_phase':resume['phase'] if resume else 'FRESH','status':'STARTED','delta':zero(),'resume_checkpoint_digest':digest(resume) if resume else None,'result_checkpoint_digest':None})
    write(path,doc);token=_ACTIVE.set((path,doc))
    try:
        yield
    except BaseException:
        doc['invocations'][-1]['status']='ERROR';write(path,doc);raise
    else:
        doc['invocations'][-1]['status']='RETURNED';write(path,doc)
    finally:_ACTIVE.reset(token)


def completed(config,checkpoint):
    active=_ACTIVE.get()
    require(active is not None,'geometry_accounting_required')
    path,doc=active
    require(doc['config_digest']==digest(config),'geometry_accounting_binding')
    doc['invocations'][-1]['result_checkpoint_digest']=digest(checkpoint)
    write(path,doc)
