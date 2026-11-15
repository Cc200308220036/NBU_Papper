"""Independent formal extension; existing b1 carriers remain closed and unchanged."""
from pathlib import Path
from .contracts import read, require
from .protocol import validate_observed
VERSION='pct_p4b_config_v2'
SUFFIX='b1_v1'
PAIRS={'config':(VERSION,'config_p4b_v2')}


def schema_name(name,version):
    require(name in ('config','config_p4b_v2') and version==VERSION,'P4B_SCHEMA_VERSION')
    return 'config_p4b_v2'


def schema(name):
    require(name=='config_p4b_v2','P4B_UNKNOWN_SCHEMA')
    return read(Path(__file__).parent/'schemas/config_p4b_v2.schema.json')


def validate_value(name,value):
    require(name=='config_p4b_v2' and value['version']==VERSION,'P4B_CONFIG_VERSION')
    require(value['model'] is None and value['memory_mode']=='none' and
            value['stability_monitor']['enabled'] is True,'P4B_LOCAL_MONITORED_ONLY')


def preflight(config):
    from .p4b_formal import preflight as f
    return f(config)


def admit_execution(*args,**kwargs):
    from .p4b_formal import admit_execution as f
    return f(*args,**kwargs)


def validate_selection(*args):
    # This function validates the unchanged public selection carrier only;
    # no P3 execution/config admission or P3 version is used.
    from .p3_runtime import validate_selection as f
    return f(*args)


def summarize_episode(task,config,method,state,events,reason):
    from .execution import summarize_episode as f
    result=f(task,config,method,state,events,reason)
    result.update(version='pct_p4b_metrics_v2',scope='FORMAL_TRAIN_COLLECTION',training='COLLECTION_ONLY')
    return result
