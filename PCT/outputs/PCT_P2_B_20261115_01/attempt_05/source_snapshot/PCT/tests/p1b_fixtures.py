"""Small explicitly synthetic P1-B inputs; never uses a historical order as a run."""
import copy
from pathlib import Path
from pct_baseline.contracts import read,digest
from pct_baseline.dataset import INSTRUCTION

ROOT=Path(__file__).resolve().parents[2]


def item(name,size=(100,100,100),mass=1,capacity=1000,stackable=True):
    return {'item_id':name,'dimensions_mm':dict(zip(('length','width','height'),size)),
        'mass_kg':mass,'stackable':stackable,'top_load_limit_kg_synthetic':capacity,
        'fragile':False,'weight_class':'medium','product_category':'general'}


def task(name,items,container=(1000,800,600)):
    original={'description':'CONSTRUCTED_P1B_ONLY_NOT_A_PARENT_DATASET','items':items,'container':container}
    attributes={i['item_id']:{'object_id':i['item_id'],'cargo_category':'general','packaging':{'reinforced':False},
        'labels':{'no_top_load':not i['stackable'],'max_top_load_kg':i['top_load_limit_kg_synthetic']},
        'physical_top_load_limit_kg':i['top_load_limit_kg_synthetic']} for i in items}
    value={'version':'pct_b1_task_v1','task_id':'CONSTRUCTED_'+name,'parent_data_identity':digest('CONSTRUCTED_P1B_DATA'),
        'parent_task_sha256':digest(original),'parent_task_digest':digest(original),
        'execution_spec_digest':digest(read(ROOT/'PCT/configs/data_b1_v1.json')['execution_spec']),
        'source_component_id':digest('CONSTRUCTED_P1B_NO_SOURCE_COMPONENT'),'exposure_status':'CONSTRUCTED_P1B_ONLY',
        'partition':'constructed','parent_partition':'constructed','parent_layer':'constructed','layer':'constructed',
        'container':dict(container_id='CONSTRUCTED',coordinate_frame='container_bottom_center',
            length_mm=container[0],width_mm=container[1],max_height_mm=container[2],max_payload_kg=1000),
        'arrival_order':[i['item_id'] for i in items],'items':copy.deepcopy(items),'attributes':attributes,
        'regions':[],'reference_policy':{'version':'jev_packaging_load_dataset_v1','rules':[]},'instruction_text':INSTRUCTION,
        'buffer_capacity':1,'candidate_limits':{'per_box':16,'joint':48}}
    value['derived_task_digest']=digest(value)
    return value
