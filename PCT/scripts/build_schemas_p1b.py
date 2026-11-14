"""Add P0-named P1-B records; never regenerate or relax existing resources."""
import copy
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OLD=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/schemas'
OUT=ROOT/'PCT/src/pct_baseline/schemas'

def read(name):return json.loads((OLD/(name+'.schema.json')).read_text())
def save(name,value):
    with (OUT/(name+'.schema.json')).open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')

h={'type':'string','pattern':'^[0-9a-f]{64}$'}
s=read('selection_result_v13');s['properties']['version']={'const':'jev_selection_result_b1_v1'}
s['properties']['source']={'enum':['pct_local','local_baseline','jev','singleton']}
s['properties']['inference_receipt']={'anyOf':[{'type':'null'},{'type':'object','additionalProperties':False,
    'required':['feature_digest','weights_sha256','leaf_index','inference_s'],
    'properties':{'feature_digest':h,'weights_sha256':h,'leaf_index':{'type':['integer','null'],'minimum':0},'inference_s':{'type':'number','minimum':0}}}]}
s['required'].append('inference_receipt')
s['allOf'].append({'if':{'properties':{'source':{'const':'pct_local'}}},'then':{'properties':{'inference_receipt':{'type':'object'}}},'else':{'properties':{'inference_receipt':{'type':'null'}}}})
save('selection_result_b1_v1',s)
s=read('checkpoint_v13');s['properties']['version']={'const':'jev_checkpoint_b1_v1'}
s['properties']['method']={'enum':['geometry_b1','pct_geo_b1','pct_load_b1','jev_none_b1']}
s['properties']['state']['properties']['buffer_capacity']={'const':1}
s['properties']['state']['properties']['pending_items']['maxItems']=1
save('checkpoint_b1_v1',s)
s={'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','additionalProperties':False,
    'properties':{'version':{'const':'pct_b1_constructed_execution_v1'},'scope':{'const':'P1B_CONSTRUCTED_ONLY'},
        'job_id':{'type':'string','minLength':1},'task_digest':h,'config_digest':h,'max_items':{'const':3},
        'resume_admitted':{'const':False},'network_admitted':{'const':False}},
    'required':['version','scope','job_id','task_digest','config_digest','max_items','resume_admitted','network_admitted']}
save('constructed_execution_b1_v1',s)
