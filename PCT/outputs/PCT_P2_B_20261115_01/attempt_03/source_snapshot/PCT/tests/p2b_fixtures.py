"""Explicit public geometry fixtures; no generation, physical feasibility or orders."""
import copy
import json
from pathlib import Path
from pct_baseline.contracts import digest
from semantic_pallet_planner.jev_select.contracts import DecisionContext

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'PCT/outputs/PCT_P1_C_20261114_01/attempt_02/baseline_stable/journal/00000001.json'


def fixture(config,*,count=3,placed=False,symmetric=False):
    saved=json.loads(SOURCE.read_text())['checkpoint']['pending_event']
    v=copy.deepcopy(saved['context']); prototype=copy.deepcopy(saved['bundle']['physical_candidates'][0])
    s=v['model_state'];s['placed_objects']=[]
    dims=[100.25,100.25 if symmetric else 60.5,40.75]
    current=s['available_objects'][0];current['dimensions_mm']=dict(zip(['length','width','height'],dims))
    current['object_id']='B099';s['buffer']['pending'][0]['object_id']='B099'
    if placed:
        o=copy.deepcopy(current);o.update(object_id='B001',pose={'x_mm':-100.125,'y_mm':-20.25,'z_base_mm':0.,'yaw_deg':90},oriented_size_mm=[dims[1],dims[0],dims[2]],centroid_mm=[-100.125,-20.25,dims[2]/2],support_fractions=[])
        s['placed_objects']=[o]
    v['criteria']={};v['display_mapping']={};candidates=[]
    for i in range(count):
        yaw=0 if i%2==0 else 90
        size=dims[:] if yaw==0 else [dims[1],dims[0],dims[2]]
        # First at negative exact container boundary, second at positive boundary;
        # others include decimal center and nonzero contact height.
        if i==0: x,y,z=-500+size[0]/2,-400+size[1]/2,0.
        elif i==1:x,y,z=500-size[0]/2,400-size[1]/2,0.
        else:x,y,z=-100.125+i*0.25,-20.25,dims[2] if placed else 0.
        pose={'x_mm':x,'y_mm':y,'z_base_mm':z,'yaw_deg':yaw}
        c=copy.deepcopy(prototype);c.update(candidate_id=f'P2B_FIXTURE_{i:02d}',candidate_fingerprint=digest(['fixture',i]),pick_item_id='CURRENT_FIXTURE',pose=pose,oriented_size_mm=size)
        c['resulting_geometry']['max_height_mm']=z+size[2]
        label=f'C{i+1:02d}';crit=copy.deepcopy(saved['context']['criteria']['C01'])
        crit.update(pick_object='B099',pose=copy.deepcopy(pose),oriented_size_mm=size[:]);crit['features']['resulting_max_height_mm']=z+size[2]
        v['criteria'][label]=crit
        v['display_mapping'][label]={'candidate_id':c['candidate_id'],'candidate_digest':digest(c),'pick_item_id':c['pick_item_id']}
        candidates.append(c)
    v['route']='CHOICE_REQUIRED' if count>1 else 'SINGLETON_BYPASS' if count else 'STOP_NO_PHYSICAL_CANDIDATE'
    b=v['local_binding'];b['runtime_identity']=copy.deepcopy(config['runtime_identity']);b['config_digest']=digest(config)
    b.update(job_id='P2B_SINGLE_STEP_FIXTURE',decision_id='P2B_D0000')
    b['physical_digest']=b['selectable_digest']=digest(candidates)
    for field,key in [('mapping_digest','display_mapping'),('criteria_digest','criteria'),('model_state_digest','model_state'),('request_body_digest','request_body')]: b[field]=digest(v[key])
    return DecisionContext.from_dict(v),candidates


def rebind(v):
    for field,key in [('mapping_digest','display_mapping'),('criteria_digest','criteria'),('model_state_digest','model_state'),('request_body_digest','request_body')]:v['local_binding'][field]=digest(v[key])
    return DecisionContext.from_dict(v)
