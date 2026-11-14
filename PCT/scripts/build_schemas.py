"""Maintainer-only deterministic schema resource generation; no business dispatch."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / 'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/schemas'
OUT = ROOT / 'PCT/src/pct_baseline/schemas'

def read(name):
    return json.loads((OLD / (name + '.schema.json')).read_text())

def closed(properties):
    return {'type':'object', 'properties':properties, 'required':list(properties), 'additionalProperties':False}

def save(name, schema):
    schema = {'$schema':'https://json-schema.org/draft/2020-12/schema', **schema}
    (OUT / (name + '.schema.json')).write_text(json.dumps(schema,ensure_ascii=False,indent=2)+'\n')

h={'type':'string','pattern':'^[0-9a-f]{64}$'}
text={'type':'string','minLength':1}
execution = closed({'version':{'const':'pct_b1_execution_spec_v1'}, 'buffer_capacity':{'const':1},
    'yaw_deg':{'const':[0,90]},'per_box':{'const':16},'joint':{'const':48},
    'candidate_manifest_digest':h,'display_order_seed':{'const':20261102},
    'monitor_algorithm':{'const':'pct_exact_pose_network_v3'}})
save('execution_spec_b1_v1',execution)
config=read('config_v13'); props=config['properties']
for k in ['endpoint','api_key_env','timeout_s','max_retries','response_max_bytes','probability_tolerance','probability_sum_validation','jm_mode']:
    del props[k]
config['required']=list(props);config.pop('allOf')
props['version']={'const':'pct_b1_config_v1'};props['buffer_capacity']={'const':1}
props['selector']={'enum':['geometry_b1','pct_geo_b1','pct_load_b1','jev_none_b1']}
props['model']={'enum':[None,'jev-1.14.0']}
# P1-A does not register transport. A later transport protocol must be separately versioned.
props['execution_spec_digest']=h
props['model_identity']={'anyOf':[{'type':'null'},h]}
config['required']=list(props)
config['allOf']=[{'if':{'properties':{'selector':{'const':'jev_none_b1'}}},'then':{'properties':{'model':{'const':'jev-1.14.0'}}},'else':{'properties':{'model':{'const':None}}}}]
save('config_b1_v1',config)
bundle=read('candidate_bundle_v13');bundle['properties']['version']={'const':'jev_candidate_bundle_b1_v1'}
bundle['properties']['generation_counts']['maxItems']=1
number={'type':'number'}
nonnegative={'type':'number','minimum':0}
pose=read('decision_context_v13')['properties']['criteria']['patternProperties']['^C[0-9]{2}$']['properties']['pose']
candidate=closed({'candidate_id':text,'candidate_fingerprint':text,'pick_item_id':text,'pose':pose,
    'oriented_size_mm':{'type':'array','minItems':3,'maxItems':3,'items':{'type':'number','exclusiveMinimum':0}},
    'ems':closed({'ems_id':text,'ems_type':{'enum':['floor_space','supported_space']}}),
    'support':closed({'support_item_ids':{'type':'array','items':text},'support_ratio':nonnegative,'com_margin_mm':nonnegative}),
    'load':closed({'downward_load_kg':nonnegative,'minimum_remaining_capacity_kg':{'anyOf':[number,{'type':'null'}]}}),
    'resulting_geometry':closed({'max_height_mm':nonnegative,'volume_utilization':nonnegative,'center_of_mass_offset_mm':nonnegative}),
    'geometry_score_components':closed({k:number for k in ('compactness','height','stability','balance')}),
    'physical_valid':{'const':True},'physical_rejection_reasons':{'const':[]}})
for key in ('physical_candidates','selectable_candidates'):bundle['properties'][key]['items']=candidate
save('candidate_bundle_b1_v1',bundle)
context=read('decision_context_v13')
context['properties']['version']={'const':'jev_decision_context_b1_v1'}
def narrow(node):
    if isinstance(node,dict):
        properties=node.get('properties',{})
        if {'capacity','end_of_stream','pending'} <= properties.keys():
            properties['capacity']={'const':1};properties['pending']['maxItems']=1
            properties['pending']['items']['properties']['slot']={'const':0}
        if 'available_objects' in properties:
            properties['available_objects']['maxItems']=1
        for v in node.values():narrow(v)
    elif isinstance(node,list):
        for v in node:narrow(v)
narrow(context)
context['properties']['request_body']['anyOf'][1]['properties']['model']={'const':'jev-1.14.0'}
save('decision_context_b1_v1',context)
parent=read('packaging_load_task_v1')['properties']
item=parent['items']['items'];fields=['item_id','dimensions_mm','mass_kg','stackable','top_load_limit_kg_synthetic','fragile','weight_class']
item_props={k:item['properties'][k] for k in fields};item_props['product_category']={'const':'general'}
attrs=closed({'object_id':text,'cargo_category':{'const':'general'},'packaging':{'const':{'reinforced':False}},
    'labels':closed({'no_top_load':{'type':'boolean'},'max_top_load_kg':{'type':'number','minimum':0}}),
    'physical_top_load_limit_kg':{'type':'number','minimum':0}})
props={'version':{'const':'pct_b1_task_v1'},'task_id':text,
       **{k:h for k in ['parent_data_identity','parent_task_sha256','parent_task_digest','execution_spec_digest','derived_task_digest','source_component_id']},
       **{k:text for k in ['parent_partition','partition','exposure_status','layer','parent_layer']},
       'container':parent['container'],'arrival_order':{'type':'array','minItems':1,'uniqueItems':True,'items':text},
       'items':{'type':'array','minItems':1,'items':closed(item_props)},
       'attributes':{'type':'object','additionalProperties':attrs},'regions':{'const':[]},
       'reference_policy':{'const':{'version':'jev_packaging_load_dataset_v1','rules':[]}},
       'instruction_text':{'const':'Packaging/load protocol v1: use current geometry, mass, support eligibility and capacity only.'},
       'buffer_capacity':{'const':1},'candidate_limits':{'const':{'per_box':16,'joint':48}}}
save('task_b1_v1',closed(props))
