"""Independent P3 execution descriptor; reuse unchanged b1 data/context carriers."""
from .contracts import require
from .protocol import validate_observed
VERSION='pct_p3_config_v1'
SUFFIX='b1_v1'
PAIRS={'config':(VERSION,'config_p3_v1')}

def schema_name(name,version):
    require(name in ('config','config_p3_v1') and version==VERSION,'P3_CONFIG_SCHEMA_VERSION')
    return 'config_p3_v1'

def validate_value(name,value):
    require(name=='config_p3_v1' and value['version']==VERSION,'P3_CONFIG_VERSION')
    require(value['model'] is None and value['memory_mode']=='none','P3_LOCAL_ONLY')

def admit_execution(*args,**kwargs):
    from .p3_runtime import admit_execution as f
    return f(*args,**kwargs)

def preflight(config):
    from .p3_runtime import preflight as f
    return f(config)

def validate_selection(*args):
    from .p3_runtime import validate_selection as f
    return f(*args)

def summarize_episode(*args):
    from .p3_runtime import summarize_episode as f
    return f(*args)

def schema(name):
    from pathlib import Path
    from .contracts import read
    require(name == "config_p3_v1", "P3_UNKNOWN_SCHEMA")
    return read(Path(__file__).parent/"schemas/config_p3_v1.schema.json")
