"""P1-C independently versioned construction admission and process recovery.

The only execution loop remains public run_episode. Old P1-B admission is not
relaxed. No official matrix, learned policy, network transport or training.
"""
import copy
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import sys

from .contracts import digest,sha,validate
from .persistence import require,RecoveryError,JobLock,JournalSink,atomic_new,fsync_dir,read_records

ROOT=Path(__file__).resolve().parents[3]
PUBLIC='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/'
DEPENDENCIES=('numpy','scipy','jsonschema','attrs','referencing','jsonschema-specifications','rpds-py','typing-extensions')


def environment_identity():
    scipy=metadata.distribution('scipy');numpy=metadata.distribution('numpy')
    core=next(p for p in scipy.files if str(p).startswith('scipy/optimize/_highspy/_core.') and str(p).endswith(('.so','.pyd')))
    ncore=next(p for p in numpy.files if str(p).startswith('numpy/_core/_multiarray_umath.') and str(p).endswith(('.so','.pyd')))
    return {'python':sys.version,'abi':sys.implementation.cache_tag,'executable_sha256':sha(sys.executable),
        'packages':{name:metadata.version(name) for name in DEPENDENCIES},
        'highs_core_sha256':sha(scipy.locate_file(core)),'numpy_core_sha256':sha(numpy.locate_file(ncore)),
        'package_records':{name:digest(metadata.distribution(name).read_text('RECORD')) for name in DEPENDENCIES}}


def freeze_identities(config,extra_source_files=()):
    from .execution import source_identity
    from semantic_pallet_planner.jev_select.packaging_runtime import physical_manifest
    files={('PCT/src/'+name if name.startswith('pct_baseline/') else PUBLIC+name):value for name,value in source_identity().items()}
    for name,value in physical_manifest().items():files['semantic_pallet_planner/src/semantic_pallet_planner/'+name]=value
    for name,value in config['stability_monitor']['algorithm_identity']['files_sha256'].items():files[PUBLIC+'stability/'+name]=value
    for name in extra_source_files:
        require((ROOT/name).resolve().is_relative_to(ROOT) and not Path(name).is_absolute(),'INVALID_EXTRA_SOURCE_PATH')
        files[name]=sha(ROOT/name)
    return {'files':files,'environment':environment_identity(),'model_weights':{'status':'NOT_IMPLEMENTED','sha256':None},
        'network_features':{'status':'NOT_IMPLEMENTED','sha256':None},'public_feature_version':config['feature_version'],
        'policy':{'method':'geometry_b1','strategy_identity':config['runtime_identity']['strategy_identity']}}


def check_header(header,*,check_current=False):
    validate('recovery_header_b1_v1',header)
    require(header['header_digest']==digest({k:v for k,v in header.items() if k!='header_digest'}),'HEADER_DIGEST_CHANGED')
    t=header['task'];c=header['config'];a=header['admission'];ids=header['identities']
    validate('task_b1_v1',t);validate('config_b1_v1',c);validate('recovery_execution_b1_v1',a)
    require(a['task_digest']==digest(t) and a['config_digest']==digest(c) and a['identity_digest']==digest(ids),'RECOVERY_IDENTITY_BINDING_CHANGED')
    require(a['job_id']==t['task_id'] and c['runtime_identity']['task_identity']==digest(t) and c['runtime_identity']['data_identity']==t['parent_data_identity'],'RECOVERY_TASK_CHANGED')
    require(c['selector']=='geometry_b1' and t['exposure_status']=='CONSTRUCTED_P1B_ONLY' and 1<=len(t['items'])<=3,'RECOVERY_SCOPE_NOT_ADMITTED')
    require(c['stability_monitor']['enabled'] is True and c['stability_monitor']['algorithm']=='pct_exact_pose_network_v3' and c['runtime_identity']['monitor_identity']==digest(c['stability_monitor']),'RECOVERY_MONITOR_CHANGED')
    require(ids['policy']['strategy_identity']==c['runtime_identity']['strategy_identity'] and ids['public_feature_version']==c['feature_version'],'RECOVERY_STRATEGY_CHANGED')
    if check_current:
        for name,expected in ids['files'].items():
            path=(ROOT/name).resolve()
            require(path.is_relative_to(ROOT) and path.is_file() and sha(path)==expected,'RECOVERY_SOURCE_DRIFT:'+name)
        require(ids['environment']==environment_identity(),'RECOVERY_DEPENDENCY_DRIFT')
        from .execution import strategy_identity
        require(c['runtime_identity']['strategy_identity']==strategy_identity('geometry_b1'),'RECOVERY_STRATEGY_SOURCE_DRIFT')
    return header


def create_job(task,output,*,extra_source_files=()):
    from .execution import build_config
    root=Path(output)
    require(not root.exists(),'RECOVERY_OUTPUT_EXISTS')
    config=build_config(task);identities=freeze_identities(config,extra_source_files)
    admission={'version':'pct_b1_recovery_execution_v1','scope':'P1C_CONSTRUCTED_ONLY','job_id':task['task_id'],
        'task_digest':digest(task),'config_digest':digest(config),'identity_digest':digest(identities),
        'max_items':3,'resume_admitted':True,'network_admitted':False}
    header={'version':'pct_b1_recovery_header_v1','task':copy.deepcopy(task),'config':config,'identities':identities,'admission':admission}
    header['header_digest']=digest(header);check_header(header,check_current=True)
    root.mkdir(parents=True,exist_ok=False);fsync_dir(root.parent)
    with JobLock(root):
        (root/'journal').mkdir();fsync_dir(root)
        atomic_new(root/'header.json',header)
    return header


def admit_execution(task,selector,config,*,execution,job_id,method,resume,on_checkpoint,
                    expected_events,training_fork,memory_snapshot,memory_view,memory_driver):
    from .execution import GeometrySelector
    require(isinstance(on_checkpoint,JournalSink) and on_checkpoint.lock.stream is not None,'RECOVERY_LOCKED_JOURNAL_REQUIRED')
    header=on_checkpoint.header;check_header(header,check_current=True)
    require(all(v is None for v in (expected_events,training_fork,memory_snapshot,memory_view,memory_driver)),'RECOVERY_MEMORY_REPLAY_NOT_ADMITTED')
    require(execution==header['admission'] and task==header['task'] and config==header['config'] and job_id==execution['job_id'] and method=='geometry_b1','RECOVERY_ROUTE_CHANGED')
    require(isinstance(selector,GeometrySelector) and selector.config==config,'RECOVERY_SELECTOR_CHANGED')
    expected=on_checkpoint.rows[-1]['checkpoint'] if on_checkpoint.rows else None
    require(resume==expected,'RECOVERY_CHECKPOINT_NOT_JOURNAL_TAIL')


def run_job(root,*,cut=None,selector_factory=None):
    from .execution import GeometrySelector
    from .saved import validate_job
    from semantic_pallet_planner.jev_select.episode import run_episode
    root=Path(root)
    with JobLock(root) as lock:
        verified=validate_job(root,check_current=True)
        header=verified['header'];rows=verified['rows'];checkpoint=verified['checkpoint']
        if (root/'commit_intent.json').exists():
            # Only an already journaled COMMITTED state can disambiguate intent.
            (root/'commit_intent.json').unlink();fsync_dir(root)
        config=header['config'];task=header['task']
        selector=GeometrySelector(config) if selector_factory is None else selector_factory(config)
        sink=JournalSink(root,header,rows,lock,cut=cut)
        episode=run_episode(task,selector,config,job_id=header['admission']['job_id'],method='geometry_b1',
            resume=checkpoint,on_checkpoint=sink,extension_execution=header['admission'],hook=sink.hook)
        if not (root/'episode.json').exists():atomic_new(root/'episode.json',episode)
        else:
            stored=json.loads((root/'episode.json').read_text())
            require(stored['final_state']==episode['final_state'] and stored['checkpoint']==episode['checkpoint'],'RECOVERY_EPISODE_CHANGED')
        return episode
