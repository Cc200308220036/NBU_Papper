"""v16 observational accounting. Does not select, assess or commit actions."""
import copy
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from .geometry_native_protocol import wire, is_native, identity_fields, config_fields
from .contracts import digest,validate_schema
from .geometry_runtime_contracts import same_native
from .packaging_geometry_protocol import require,sha
from .ledger import read,write

FIELDS=('selector_calls','singleton_executions','monitor_entries','monitor_reuses','commit_attempts','commit_successes')
SNAPSHOT_PHASES=('SELECTED','MONITORED','COMMITTED')
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


def _binding(config,job_id):
    return {**identity_fields(config),'version':wire(config,'geometry_order_accounting_v1'),'plan_digest':config['plan_digest'],
        'job_id':job_id,'config_digest':digest(config)}


def _blob_hashes(job_root):
    blobs=Path(job_root)/'blobs'
    require(blobs.is_dir(),'geometry_phase_snapshot_missing_blobs')
    out={}
    for p in sorted(blobs.iterdir()):
        if p.is_file():
            raw=p.read_bytes();h=sha(raw)
            require(p.name==h,'geometry_phase_snapshot_blob_drift')
            out[p.name]=h
    require(bool(out),'geometry_phase_snapshot_missing_blobs')
    return out


def seal_phase_snapshot_credential(parent_job_root,snapshot_job_root,config,job_id,phase,checkpoint,*,parent_result):
    """Seal a versioned phase-snapshot credential only after the parent primary run returned and completed."""
    parent_job_root=Path(parent_job_root);snapshot_job_root=Path(snapshot_job_root)
    require(parent_job_root.resolve()!=snapshot_job_root.resolve(),'geometry_phase_snapshot_distinct_root_required')
    require(phase in SNAPSHOT_PHASES and type(checkpoint) is dict and checkpoint.get('phase')==phase and checkpoint.get('job_id')==job_id,'geometry_phase_snapshot_phase')
    binding=_binding(config,job_id)
    parent_acc_path=parent_job_root/'accounting.json';snap_acc_path=snapshot_job_root/'accounting.json'
    require(parent_acc_path.is_file() and snap_acc_path.is_file(),'geometry_phase_snapshot_missing_accounting')
    parent_acc=read(parent_acc_path);snap_acc=read(snap_acc_path)
    validate_schema(wire(config,'geometry_order_accounting_v1'),parent_acc)
    validate_schema(wire(config,'geometry_order_accounting_v1'),snap_acc)
    require(all(parent_acc[k]==v for k,v in binding.items()) and all(snap_acc[k]==v for k,v in binding.items()),'geometry_phase_snapshot_accounting_binding')
    require(len(parent_acc['invocations'])==1 and len(snap_acc['invocations'])==1,'geometry_phase_snapshot_primary_only')
    p_inv=parent_acc['invocations'][0];s_inv=snap_acc['invocations'][0]
    require(p_inv['index']==s_inv['index']==0 and p_inv['resume_phase']==s_inv['resume_phase']=='FRESH'
        and p_inv['resume_checkpoint_digest'] is None and s_inv['resume_checkpoint_digest'] is None,'geometry_phase_snapshot_invocation_origin')
    require(s_inv['status']=='STARTED' and s_inv['result_checkpoint_digest'] is None,'geometry_phase_snapshot_in_run_state')
    require(p_inv['status']=='RETURNED' and type(p_inv['result_checkpoint_digest']) is str,'geometry_phase_snapshot_parent_not_returned')
    require(type(parent_result) is dict and (parent_result.get('summary') or {}).get('completed') is True,'geometry_phase_snapshot_parent_not_completed')
    parent_cp=parent_result.get('checkpoint')
    require(type(parent_cp) is dict and parent_cp.get('phase')=='TERMINATED' and parent_cp.get('reason')=='ALL_ITEMS_PLACED'
        and digest(parent_cp)==p_inv['result_checkpoint_digest'],'geometry_phase_snapshot_parent_checkpoint_drift')
    require(all(snap_acc['cumulative'][k]==s_inv['delta'][k]<=p_inv['delta'][k]==parent_acc['cumulative'][k] for k in FIELDS),'geometry_phase_snapshot_prefix_bounds')
    cp_path=snapshot_job_root/'checkpoint.json';cfg_path=snapshot_job_root/'config.json';tid_path=snapshot_job_root/'task_identity.json'
    require(cp_path.is_file() and cfg_path.is_file() and tid_path.is_file(),'geometry_phase_snapshot_missing_files')
    require(same_native(read(cp_path),checkpoint),'geometry_phase_snapshot_checkpoint_drift')
    require(same_native(read(cfg_path),config),'geometry_phase_snapshot_config_drift')
    task_id_doc=read(tid_path);require(same_native(task_id_doc,config['order_task_identity']),'geometry_phase_snapshot_task_identity_drift')
    blobs=_blob_hashes(snapshot_job_root)
    raw_sha=task_id_doc['raw_sha256'];require(raw_sha in blobs,'geometry_phase_snapshot_missing_raw_task')
    pending=checkpoint.get('pending_event') or {}
    gref=pending.get('geometry_ref')
    require(type(gref) is dict and set(gref)=={'version','sha256'} and gref['version']=='geometry_blob_ref_v1' and gref['sha256'] in blobs,'geometry_phase_snapshot_missing_geometry_blob')
    cred={**identity_fields(config),'version':wire(config,'geometry_phase_snapshot_credential_v1'),'status':'SEALED_FOR_RECOVERY',
        'plan_digest':config['plan_digest'],'job_id':job_id,'task_id':task_id_doc['task_id'],'task_digest':task_id_doc['runtime_digest'],
        'config_digest':digest(config),'source_identity':config['runtime_identity']['source_identity'],'phase':phase,
        'checkpoint_digest':digest(checkpoint),'parent_invocation':{'index':0,'resume_phase':'FRESH','in_run_status':'STARTED',
            'final_status':'RETURNED','final_checkpoint_digest':p_inv['result_checkpoint_digest'],'final_accounting_digest':digest(parent_acc)},
        'prefix_accounting':{'in_run_accounting_digest':digest(snap_acc),'invocation_index':0,
            'delta':copy.deepcopy(s_inv['delta']),'cumulative':copy.deepcopy(snap_acc['cumulative'])},
        'durable_references':{'raw_task_sha256':raw_sha,'geometry_ref':copy.deepcopy(gref),'blob_hashes':blobs}}
    cred['credential_digest']=digest({k:v for k,v in cred.items() if k!='credential_digest'})
    validate_schema(wire(config,'geometry_phase_snapshot_credential_v1'),cred)
    write(snapshot_job_root/'phase_snapshot_credential.json',cred)
    return cred


def validate_phase_snapshot_credential(credential,snapshot_job_root,config,job_id,resume):
    require(type(credential) is dict and type(resume) is dict,'geometry_phase_snapshot_credential_required')
    validate_schema(wire(config,'geometry_phase_snapshot_credential_v1'),credential)
    require(credential['credential_digest']==digest({k:v for k,v in credential.items() if k!='credential_digest'}),'geometry_phase_snapshot_credential_digest_drift')
    task_id_doc=config['order_task_identity']
    expected={**identity_fields(config),'version':wire(config,'geometry_phase_snapshot_credential_v1'),'status':'SEALED_FOR_RECOVERY',
        'plan_digest':config['plan_digest'],'job_id':job_id,'task_id':task_id_doc['task_id'],'task_digest':task_id_doc['runtime_digest'],
        'config_digest':digest(config),'source_identity':config['runtime_identity']['source_identity'],
        'phase':resume.get('phase'),'checkpoint_digest':digest(resume)}
    require(all(credential.get(k)==v for k,v in expected.items()),'geometry_phase_snapshot_credential_binding_drift')
    snapshot_job_root=Path(snapshot_job_root)
    cp_path=snapshot_job_root/'checkpoint.json';cfg_path=snapshot_job_root/'config.json';tid_path=snapshot_job_root/'task_identity.json';acc_path=snapshot_job_root/'accounting.json'
    require(cp_path.is_file() and cfg_path.is_file() and tid_path.is_file() and acc_path.is_file(),'geometry_phase_snapshot_missing_files')
    require(same_native(read(cp_path),resume) and same_native(read(cfg_path),config) and same_native(read(tid_path),task_id_doc),'geometry_phase_snapshot_durable_drift')
    blobs=_blob_hashes(snapshot_job_root)
    drefs=credential['durable_references']
    require(drefs['raw_task_sha256']==task_id_doc['raw_sha256'] and drefs['blob_hashes']==blobs
        and same_native(drefs['geometry_ref'],(resume.get('pending_event') or {}).get('geometry_ref')),'geometry_phase_snapshot_reference_drift')
    doc=read(acc_path);validate_schema(wire(config,'geometry_order_accounting_v1'),doc)
    binding=_binding(config,job_id)
    require(all(doc[k]==v for k,v in binding.items()),'geometry_accounting_drift')
    p_acc=credential['prefix_accounting']
    require(digest(doc)==p_acc['in_run_accounting_digest'] and len(doc['invocations'])==1,'geometry_phase_snapshot_accounting_drift')
    inv0=doc['invocations'][0]
    require(inv0['index']==0 and inv0['resume_phase']=='FRESH' and inv0['status']=='STARTED'
        and inv0['resume_checkpoint_digest'] is None and inv0['result_checkpoint_digest'] is None
        and same_native(inv0['delta'],p_acc['delta']) and same_native(doc['cumulative'],p_acc['cumulative'])
        and all(doc['cumulative'][k]==inv0['delta'][k] for k in FIELDS),'geometry_phase_snapshot_accounting_prefix_drift')
    return doc


@contextmanager
def invocation(path,config,job_id,resume,*,phase_credential=None):
    binding=_binding(config,job_id)
    if path.exists():
        doc=read(path);validate_schema(wire(config,'geometry_order_accounting_v1'),doc)
        require(all(doc[k]==v for k,v in binding.items()),'geometry_accounting_drift')
        require(resume is not None,'geometry_accounting_resume_required')
        require(all(doc['cumulative'][k]==sum(i['delta'][k] for i in doc['invocations']) for k in FIELDS),'geometry_accounting_sum')
        if phase_credential is not None:
            validate_phase_snapshot_credential(phase_credential,Path(path).parent,config,job_id,resume)
        else:
            # A process loss between dispatch and completion cannot certify safe replay.
            require(not doc['invocations'] or doc['invocations'][-1]['status']!='STARTED','geometry_accounting_unknown_dispatch')
    else:
        require(resume is None and phase_credential is None,'geometry_accounting_missing_history')
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
