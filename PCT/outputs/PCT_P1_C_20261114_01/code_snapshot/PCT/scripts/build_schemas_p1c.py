"""Create independent P1-C records exclusively; leave P1-B Schemas untouched."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'PCT/src/pct_baseline/schemas'
h={'type':'string','pattern':'^[a-f0-9]{64}$'}
def closed(props):return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}
def save(name,schema):
    with (OUT/(name+'.schema.json')).open('x') as stream:json.dump({'$schema':'https://json-schema.org/draft/2020-12/schema',**schema},stream,indent=2);stream.write('\n')
permit=closed({'version':{'const':'pct_b1_recovery_execution_v1'},'scope':{'const':'P1C_CONSTRUCTED_ONLY'},'job_id':{'type':'string','minLength':1},
    'task_digest':h,'config_digest':h,'identity_digest':h,'max_items':{'const':3},'resume_admitted':{'const':True},'network_admitted':{'const':False}})
save('recovery_execution_b1_v1',permit)
na=closed({'status':{'const':'NOT_IMPLEMENTED'},'sha256':{'type':'null'}})
environment=closed({'python':{'type':'string'},'abi':{'type':'string'},'executable_sha256':h,
    'packages':closed({k:{'type':'string'} for k in ['numpy','scipy','jsonschema','attrs','referencing','jsonschema-specifications','rpds-py','typing-extensions']}),
    'highs_core_sha256':h,'numpy_core_sha256':h,'package_records':closed({k:h for k in ['numpy','scipy','jsonschema','attrs','referencing','jsonschema-specifications','rpds-py','typing-extensions']})})
identities=closed({'files':{'type':'object','minProperties':1,'additionalProperties':h},'environment':environment,
    'model_weights':na,'network_features':na,'public_feature_version':{'type':'string'},
    'policy':closed({'method':{'const':'geometry_b1'},'strategy_identity':h})})
header=closed({'version':{'const':'pct_b1_recovery_header_v1'},
    'task':json.loads((OUT/'task_b1_v1.schema.json').read_text()),'config':json.loads((OUT/'config_b1_v1.schema.json').read_text()),
    'admission':permit,'identities':identities,'header_digest':h})
save('recovery_header_b1_v1',header)

journal=closed({'version':{'const':'pct_b1_recovery_journal_v1'},'sequence':{'type':'integer','minimum':0},
    'previous_digest':h,'checkpoint_digest':h,'checkpoint':json.loads((OUT/'checkpoint_b1_v1.schema.json').read_text()),'record_digest':h})
save('recovery_journal_b1_v1',journal)
