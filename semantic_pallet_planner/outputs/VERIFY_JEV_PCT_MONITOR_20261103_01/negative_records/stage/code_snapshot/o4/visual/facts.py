"""Explicit simulated label faces, derived exclusively from validated public input."""
import copy
import json
from functools import lru_cache
from pathlib import Path
from jsonschema import Draft202012Validator
from ..common import O4Error,digest,read,canonical
from ..observation import validate_observation as single_validate
from ..buffer.buffer_protocol import validate_state,validate_observation as buffer_validate

VERSION='o4_public_render_v1'
FACE_VERSION='o4_simulated_label_pos_x_v1'
FONT=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
FACE_NORMALS={'pos_x':[1,0,0],'neg_x':[-1,0,0],'pos_y':[0,1,0],
              'neg_y':[0,-1,0],'pos_z':[0,0,1],'neg_z':[0,0,-1]}
LABEL_UV=[0.15,0.25,0.85,0.75]

@lru_cache(maxsize=4)
def schema(name):return Draft202012Validator(read(Path(__file__).parent/'schemas'/f'{name}.json'))

def validate(name,value):
    try:canonical(value);schema(name).validate(value)
    except Exception as exc:raise O4Error('invalid_visual_'+name,str(exc).splitlines()[0][:120]) from exc
    return value


@lru_cache(maxsize=512)
def _validated_source(serialized):
    source=json.loads(serialized)
    if source.get('schema_version')=='o4_buffer_state_v1':validate_state(source);return True
    if source.get('schema_version')=='o4_request_v1':single_validate(source);return False
    raise O4Error('invalid_visual_source','full public request/state required; buffer slots may not be guessed')


def unpack(source):
    try:buffer=_validated_source(canonical(source))
    except (TypeError,ValueError) as exc:
        if isinstance(exc,O4Error):raise
        raise O4Error('invalid_visual_source','non-finite/invalid public JSON') from exc
    return (source['observation'],source) if buffer else (source,None)


def rotate(vector,yaw):
    x,y,z=vector
    return [x,y,z] if yaw==0 else [-y,x,z]


def local_faces(dimensions):
    l,w,h=[dimensions[k] for k in ('length','width','height')]
    x0,x1,y0,y1=-l/2,l/2,-w/2,w/2
    vertices={'pos_x':[[x1,y0,0],[x1,y1,0],[x1,y1,h],[x1,y0,h]],
      'neg_x':[[x0,y1,0],[x0,y0,0],[x0,y0,h],[x0,y1,h]],
      'pos_y':[[x1,y1,0],[x0,y1,0],[x0,y1,h],[x1,y1,h]],
      'neg_y':[[x0,y0,0],[x1,y0,0],[x1,y0,h],[x0,y0,h]],
      'pos_z':[[x0,y0,h],[x1,y0,h],[x1,y1,h],[x0,y1,h]],
      'neg_z':[[x0,y1,0],[x1,y1,0],[x1,y0,0],[x0,y0,0]]}
    return vertices


def visual_facts(source):
    obs,buf=unpack(source)
    if obs['images']:raise O4Error('invalid_visual_source','render from image-free public facts; no recursive attachments')
    slots={p['object_id']:p for p in buf['pending_items']} if buf else {}
    result={'schema_version':'o4_visual_facts_v1','rendering_version':VERSION,
      'label_face_version':FACE_VERSION,'units':copy.deepcopy(obs['units']),
      'container':copy.deepcopy(obs['container']),'mode':buf['mode'] if buf else 'single',
      'buffer_capacity':buf['buffer_capacity'] if buf else 1,'end_of_stream':buf['end_of_stream'] if buf else None,
      'objects':[]}
    for role,key in [('placed','placed_objects'),('pending','available_objects')]:
        for obj in sorted(obs[key],key=lambda o:o['object_id']):
            faces=[]
            for name,verts in local_faces(obj['dimensions_mm']).items():
                p=obj.get('pose');world=None
                if p:
                    world=[]
                    for vertex in verts:
                        x,y,z=rotate(vertex,p['yaw_deg']);world.append([x+p['x_mm'],y+p['y_mm'],z+p['z_base_mm']])
                faces.append({'face_id':name,'local_normal':list(FACE_NORMALS[name]),
                    'local_vertices_mm':verts,'world_normal':rotate(FACE_NORMALS[name],p['yaw_deg']) if p else None,
                    'world_vertices_mm':world})
            slot=slots.get(obj['object_id'])
            result['objects'].append({'object_id':obj['object_id'],'location':role,'facts':copy.deepcopy(obj),
                'slot':slot['slot'] if slot else None,'arrival_index':slot['arrival_index'] if slot else None,
                'faces':faces,'label':{'face_id':'pos_x','uv_rect':list(LABEL_UV),
                    'source':'accurate_simulated_public_print_layout',
                    'payload':{'object_id':obj['object_id'],'cargo_category':obj['cargo_category'],
                     'reinforced':obj['packaging']['reinforced'],'no_top_load':obj['labels']['no_top_load'],
                     'max_top_load_kg':obj['labels']['max_top_load_kg']}}})
    result['facts_digest']=digest(result)
    return validate('facts',result)


def card_facts(obj):
    # Local card has no fabricated pallet pose, slot, task ID or business rule.
    fields={k:copy.deepcopy(v) for k,v in obj['facts'].items() if k not in ('pose','oriented_size_mm')}
    return {'rendering_version':VERSION,'label_face_version':FACE_VERSION,'facts':fields,
            'local_label_face':'pos_x','uv_rect':list(LABEL_UV)}
