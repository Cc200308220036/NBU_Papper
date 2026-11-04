"""Independent source/fact/PNG checks; no rendering function imports."""
import hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageChops
from ..common import read, O4Error


def verify(req, root, asset):
    root=Path(root).resolve();path=(root/asset['path']).resolve()
    if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest()!=asset['sha256']:
        raise O4Error('invalid_visual_digest')
    f=read(path.with_suffix('.facts.json'))
    if f['container']!=req['container'] or f['regions']!=req['regions'] or f['buffer_context']!=req['buffer_context']:
        raise O4Error('invalid_visual_facts')
    expected={o['object_id']:(role,o) for role,key in (('placed','placed_objects'),('pending','available_objects')) for o in req[key]}
    if len(f['objects'])!=len(expected):raise O4Error('invalid_visual_object_count')
    for record in f['objects']:
        role,o=expected[record['facts']['object_id']]
        if (record['location']!=role or record['facts']!=o or record['label_face']!='pos_z'
                or record['world_normal']!=([0,0,1] if role=='placed' else None)
                or record['label_payload']!={k:o[k] for k in ('object_id','cargo_category','packaging','labels')}):
            raise O4Error('invalid_visual_label_or_geometry')
    # Pixel checks independently project pallet corners and read a top-label
    # patch on every card. They check actual encoded PNG, not only facts JSON.
    with Image.open(path) as im:
        if im.format!='PNG' or im.size!=(1120,max(900,100+100*len(expected))):
            raise O4Error('invalid_visual_size')
        c=req['container'];s=min(640/c['length_mm'],640/c['width_mm'])
        # Independent raster oracle derives every scene rectangle from source
        # coordinates (not from renderer facts or saved pixel coordinates).
        expected_scene=Image.new('RGB',(740,800),'white');scene=ImageDraw.Draw(expected_scene)
        font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)
        def projected(xlo,ylo,xhi,yhi):
            return [round(370+xlo*s),round(400-yhi*s),round(370+xhi*s),round(400-ylo*s)]
        scene.rectangle(projected(-c['length_mm']/2,-c['width_mm']/2,c['length_mm']/2,c['width_mm']/2),outline='black',width=3)
        scene.text((50,25),'TOP VIEW: +x RIGHT, +y BACK (up on page), +z UP',font=font,fill='black')
        scene.text((50,50),'All labels on TOP; upright only; yaw 0/90 in E1',font=font,fill='black')
        for r in sorted(req['regions'],key=lambda r:r['region_id']):
            b=projected(r['x_min_mm'],r['y_min_mm'],r['x_max_mm'],r['y_max_mm'])
            scene.rectangle(b,outline=(0,128,0),width=2)
            scene.text((b[0]+3,b[1]+3),r['region_id'],font=font,fill=(0,100,0))
        for o in sorted(req['placed_objects'],key=lambda o:(o['pose']['z_base_mm'],o['object_id'])):
            dims=o['dimensions_mm'];length,width=dims['length'],dims['width']
            if o['pose']['yaw_deg']==90:length,width=width,length
            p=o['pose'];b=projected(p['x_mm']-length/2,p['y_mm']-width/2,p['x_mm']+length/2,p['y_mm']+width/2)
            scene.rectangle(b,fill=(200,220,245),outline='navy',width=2)
            cx,cy=round(370+p['x_mm']*s),round(400-p['y_mm']*s)
            scene.rectangle([cx-10,cy-6,cx+10,cy+6],fill=(255,240,80),outline='black')
            scene.text((b[0]+3,b[1]+3),o['object_id'],font=font,fill='black')
        if ImageChops.difference(im.crop((0,0,740,800)),expected_scene).getbbox():
            raise O4Error('invalid_visual_scene_geometry')
        samples=0
        for x,y in ((-c['length_mm']/2,-c['width_mm']/2),(c['length_mm']/2,c['width_mm']/2)):
            px,py=round(370+x*s),round(400-y*s)
            # Region borders may coincide with pallet border.
            if im.getpixel((px,py)) not in ((0,0,0),(0,128,0),(0,0,128)):
                raise O4Error('invalid_visual_pallet')
            samples+=1
        font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)
        ordered=[(role,o) for role,key in (('placed','placed_objects'),('pending','available_objects'))
                 for o in sorted(req[key],key=lambda o:o['object_id'])]
        for i,(role,o) in enumerate(ordered):
            expected_card=Image.new('RGB',(351,89),(255,250,210));d=ImageDraw.Draw(expected_card)
            d.rectangle([0,0,350,88],outline='black')
            texts=[f"{o['object_id']} | {role} | pos_z",
                   f"{o['cargo_category']} | reinforced={o['packaging']['reinforced']}",
                   f"no_top={o['labels']['no_top_load']} | limit={o['labels']['max_top_load_kg']:g}kg",
                   f"size={o['dimensions_mm']['length']:g}/{o['dimensions_mm']['width']:g}/{o['dimensions_mm']['height']:g}mm"]
            for row,text in enumerate(texts):d.text((10,5+20*row),text,font=font,fill='black')
            actual=im.crop((750,70+100*i,1101,70+100*i+89))
            if ImageChops.difference(actual,expected_card).getbbox():raise O4Error('invalid_visual_card_text')
            samples+=1
    return {'source_facts_equal':True,'top_face_labels':True,'pixel_samples':samples,'scene_geometry_pixels_equal':True,
            'png_bytes_verified':True,'scope':'axis-aligned engineering top view and accurate top-label cards, not photographic perception'}
