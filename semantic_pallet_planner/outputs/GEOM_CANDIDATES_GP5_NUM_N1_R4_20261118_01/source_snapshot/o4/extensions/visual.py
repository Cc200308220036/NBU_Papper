"""New deterministic E1 top-label PNG; old A5 side-label assets are untouched."""
import copy
import hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from ..common import digest, write, O4Error
from .protocol import validate_observation

VERSION = 'o4_e1_top_label_render_v1'
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def facts(req):
    validate_observation(req)
    if req['images']:
        raise O4Error('invalid_visual_source', 'render from image-free public request')
    objects = []
    for role, key in (('placed', 'placed_objects'), ('pending', 'available_objects')):
        for o in sorted(req[key], key=lambda o:o['object_id']):
            objects.append({'location': role, 'facts': copy.deepcopy(o),
                            'label_face': 'pos_z', 'world_normal': [0,0,1] if role=='placed' else None,
                            'label_payload': copy.deepcopy({k:o[k] for k in ('object_id','cargo_category','packaging','labels')})})
    return {'rendering_version':VERSION,'placement_convention':req['placement_convention'],
            'container':copy.deepcopy(req['container']),'regions':copy.deepcopy(req['regions']),
            'buffer_context':copy.deepcopy(req['buffer_context']),'objects':objects}


def render(req, root, relative):
    root = Path(root); relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise O4Error('invalid_asset_path')
    source = facts(req)
    font = ImageFont.truetype(FONT, 14)
    height = max(900, 100+100*len(source['objects']))
    image = Image.new('RGB',(1120,height),'white');draw=ImageDraw.Draw(image)
    c=req['container']; scale=min(640/c['length_mm'],640/c['width_mm'])
    def point(x,y):return (round(370+x*scale),round(400-y*scale))
    def rectangle(x0,y0,x1,y1):
        a,b=point(x0,y1),point(x1,y0);return [*a,*b]
    draw.rectangle(rectangle(-c['length_mm']/2,-c['width_mm']/2,c['length_mm']/2,c['width_mm']/2),outline='black',width=3)
    draw.text((50,25),'TOP VIEW: +x RIGHT, +y BACK (up on page), +z UP',fill='black',font=font)
    draw.text((50,50),'All labels on TOP; upright only; yaw 0/90 in E1',fill='black',font=font)
    for r in sorted(req['regions'],key=lambda r:r['region_id']):
        rect=rectangle(r['x_min_mm'],r['y_min_mm'],r['x_max_mm'],r['y_max_mm'])
        draw.rectangle(rect,outline=(0,128,0),width=2)
        draw.text((rect[0]+3,rect[1]+3),r['region_id'],fill=(0,100,0),font=font)
    placed=sorted(req['placed_objects'],key=lambda o:(o['pose']['z_base_mm'],o['object_id']))
    for o in placed:
        p=o['pose'];l,w=o['oriented_size_mm'][:2]
        rect=rectangle(p['x_mm']-l/2,p['y_mm']-w/2,p['x_mm']+l/2,p['y_mm']+w/2)
        draw.rectangle(rect,fill=(200,220,245),outline='navy',width=2)
        cx,cy=point(p['x_mm'],p['y_mm'])
        draw.rectangle([cx-10,cy-6,cx+10,cy+6],fill=(255,240,80),outline='black')
        draw.text((rect[0]+3,rect[1]+3),o['object_id'],fill='black',font=font)
    draw.text((750,25),'TOP-FACE LABEL CARDS (accurate facts)',fill='black',font=font)
    for i, obj in enumerate(source['objects']):
        o=obj['facts'];y=70+100*i
        draw.rectangle([750,y,1100,y+88],fill=(255,250,210),outline='black')
        draw.text((760,y+5),f"{o['object_id']} | {obj['location']} | pos_z",fill='black',font=font)
        draw.text((760,y+25),f"{o['cargo_category']} | reinforced={o['packaging']['reinforced']}",fill='black',font=font)
        draw.text((760,y+45),f"no_top={o['labels']['no_top_load']} | limit={o['labels']['max_top_load_kg']:g}kg",fill='black',font=font)
        draw.text((760,y+65),f"size={o['dimensions_mm']['length']:g}/{o['dimensions_mm']['width']:g}/{o['dimensions_mm']['height']:g}mm",fill='black',font=font)
    path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
    image.save(path,format='PNG',compress_level=9)
    write(path.with_suffix('.facts.json'),source)
    return {'path':relative.as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
