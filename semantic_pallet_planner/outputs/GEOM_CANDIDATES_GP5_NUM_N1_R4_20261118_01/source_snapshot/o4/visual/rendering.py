"""Deterministic raster diagrams and local label cards. Public facts in, PNG out."""
import hashlib
import io
import math
from functools import lru_cache
from PIL import Image,ImageDraw,ImageFont,PngImagePlugin
from ..common import digest
from .facts import FONT,VERSION,card_facts

SCENE_WIDTH=1440
CARD_SIZE=(1040,580)
VIEWS={'xy':(30,150,650,430),'xz':(760,150,650,270),'yz':(760,480,650,270)}

@lru_cache(maxsize=16)
def font(size):return ImageFont.truetype(str(FONT),size,index=0)

def text(identifier,xy,value,size=18):return {'id':identifier,'kind':'text','xy':list(xy),'text':str(value),'font':size,'fill':'#152b3b'}
def rect(identifier,xy,fill=None,outline='#405060',width=1):return {'id':identifier,'kind':'rect','xy':list(xy),'fill':fill,'outline':outline,'width':width}
def poly(identifier,xy,fill=None,outline='#405060',width=1):return {'id':identifier,'kind':'polygon','xy':[[round(x,6),round(y,6)] for x,y in xy],'fill':fill,'outline':outline,'width':width}

def wrapped(value,limit=72):return [value[i:i+limit] for i in range(0,len(value),limit)] or ['']


def card_plan(data):
    o=data['facts'];d=o['dimensions_mm'];ops=[]
    for i,line in enumerate(wrapped('对象 '+o['object_id'],50)):ops.append(text(f'id_{i}',(20,15+i*25),line,18))
    ops.append(text('local_note',(20,100),'局部箱面示意：非托盘位姿；所有印刷标签在 +X 面',18))
    # Normalize dimensions before projecting, to avoid overflow and preserve aspect ratios.
    scale=max(d.values());l,w,h=[d[k]/scale for k in ('length','width','height')]
    points={}
    for x in (-l/2,l/2):
        for y in (-w/2,w/2):
            for z in (0,h):points[(x,y,z)]=(0.8*x-0.6*y,0.3*x+0.3*y-0.85*z)
    us=[p[0] for p in points.values()];vs=[p[1] for p in points.values()]
    zoom=min(390/(max(us)-min(us)),310/(max(vs)-min(vs)))
    def project(v):return [30+(v[0]-min(us))*zoom,145+(v[1]-min(vs))*zoom]
    def p(x,y,z):return project((.8*x-.6*y,.3*x+.3*y-.85*z))
    faces={'pos_y':[p(l/2,w/2,0),p(-l/2,w/2,0),p(-l/2,w/2,h),p(l/2,w/2,h)],
           'pos_x':[p(l/2,-w/2,0),p(l/2,w/2,0),p(l/2,w/2,h),p(l/2,-w/2,h)],
           'pos_z':[p(-l/2,-w/2,h),p(l/2,-w/2,h),p(l/2,w/2,h),p(-l/2,w/2,h)]}
    for name in ('pos_y','pos_x','pos_z'):ops.append(poly('box_'+name,faces[name],{'pos_y':'#e5d4ba','pos_x':'#d8bd96','pos_z':'#f2e4cf'}[name],width=2))
    ops.append(poly('label_patch',[p(l/2,-w*.35,h*.25),p(l/2,w*.35,h*.25),p(l/2,w*.35,h*.75),p(l/2,-w*.35,h*.75)],'#fff8dc','#152b3b',2))
    ops.append(text('face_name',(40,480),'标签印刷面：+X；面内 u=0.15..0.85，v=0.25..0.75',16))
    ops.append(text('panel_title',(465,120),'+X 标签面展开（准确仿真印刷事实）',20))
    rows=[('category','货物类别',o['cargo_category']),('reinforced','包装加固',str(o['packaging']['reinforced']).lower()),
          ('no_top','禁压标记',str(o['labels']['no_top_load']).lower()),('limit','标签累计顶部限载 kg',o['labels']['max_top_load_kg']),
          ('dimensions','本地长/宽/高 mm',' / '.join(str(d[k]) for k in ('length','width','height'))),
          ('mass','质量 kg',o['mass_kg']),('physical_limit','物理顶部承载 kg',o['physical_top_load_limit_kg']),
          ('stackable','物理可堆叠',str(o['stackable']).lower()),('fragile','易碎属性',str(o['fragile']).lower()),
          ('weight_class','重量等级',o['weight_class'])]
    ops.append(text('physical_title',(465,300),'其他准确公共参数（不由标签推断）',18))
    for i,(key,name,value) in enumerate(rows):
        y=160+i*32 if i<4 else 335+(i-4)*30
        ops.append(text('field_'+key,(465,y),f'{name}: {value}',18))
    ops.append(text('card_footer',(20,550),'mm / kg | '+VERSION+' | 仿真事实；无业务允许/违规结论',16))
    return {'kind':'card','size':list(CARD_SIZE),'ops':ops}


def scene_plan(facts):
    placed=[o for o in facts['objects'] if o['location']=='placed'];pending=[o for o in facts['objects'] if o['location']=='pending']
    ids={o['object_id']:f'B{i:02d}' for i,o in enumerate(facts['objects'],1)}
    rows=[]
    for o in facts['objects']:
        prefix=ids[o['object_id']]+' '+('已码' if o['location']=='placed' else '待码')+' = '
        rows.extend(wrapped(prefix+o['object_id'],90))
    height=max(980,850+len(rows)*25)
    ops=[text('title',(20,16),'准确公共状态：托盘线框投影与独立待码区',26),
         text('coordinate_note',(20,58),'坐标原点=托盘底面中心；mm / kg；线框显示遮挡对象，逐箱标签详见独立卡片',18),
         text('status',(20,92),f"模式：{'单箱' if facts['mode']=='single' else '缓冲'} 容量：{facts['buffer_capacity']} 已码：{len(placed)} 待码：{len(pending)} 到货结束：{'未提供' if facts['end_of_stream'] is None else ('是' if facts['end_of_stream'] else '否')}",18)]
    c=facts['container'];L,W,H=[c[k] for k in ('length_mm','width_mm','max_height_mm')]
    ops.append(text('container_dims',(760,92),'托盘长/宽/限高 mm: '+' / '.join(str(v) for v in (L,W,H)),16))
    names={'xy':'俯视 XY（+Y 向上）','xz':'正视 XZ（+Z 向上）','yz':'侧视 YZ（+Z 向上）'}
    def project(v,view):
        x,y,z=v;left,top,width,high=VIEWS[view]
        if view=='xy':u,v=x/L+.5,.5-y/W
        elif view=='xz':u,v=x/L+.5,1-z/H
        else:u,v=y/W+.5,1-z/H
        return [left+u*width,top+v*high]
    for name,(left,top,width,high) in VIEWS.items():
        ops.append(text('view_title_'+name,(left,top-28),names[name],18));ops.append(rect('view_frame_'+name,[left,top,left+width,top+high],None,width=2))
        for o in sorted(placed,key=lambda o:(o['facts']['pose']['z_base_mm'],o['object_id'])):
            ob=o['facts'];p=ob['pose'];l,w,h=ob['oriented_size_mm'];x,y,z=p['x_mm'],p['y_mm'],p['z_base_mm']
            if name=='xy':v=[(x-l/2,y-w/2,z),(x+l/2,y-w/2,z),(x+l/2,y+w/2,z),(x-l/2,y+w/2,z)]
            elif name=='xz':v=[(x-l/2,y,z),(x+l/2,y,z),(x+l/2,y,z+h),(x-l/2,y,z+h)]
            else:v=[(x,y-w/2,z),(x,y+w/2,z),(x,y+w/2,z+h),(x,y-w/2,z+h)]
            ops.append(poly(name+'_box_'+o['object_id'],[project(q,name) for q in v],None,width=2))
            # Label face's actual world vertices; not a guessed outward-facing target.
            face=next(f for f in o['faces'] if f['face_id']=='pos_x')
            ops.append(poly(name+'_face_'+o['object_id'],[project(q,name) for q in face['world_vertices_mm']],None,'#7a541f',2))
            mid=project((x,y,z+h/2),name);ops.append(text(name+'_id_'+o['object_id'],mid,ids[o['object_id']],13))
    ops.append(text('pending_title',(30,625),'待码槽位示意：不是托盘坐标；未赋予箱体托盘位姿',18))
    capacity=facts['buffer_capacity']
    for slot in range(capacity):
        left=30+slot*210;ops.append(rect(f'slot_{slot}',[left,665,left+190,755],'#f3f6f8'))
        matches=[o for o in pending if o['slot']==slot or (o['slot'] is None and slot==0)]
        label=' / '.join(ids[o['object_id']] for o in matches) if matches else '空'
        ops.append(text(f'slot_text_{slot}',(left+10,685),f'槽 {slot}: {label}' if any(o['slot'] is not None for o in pending) else '当前箱: '+label,16))
        ops.append(text(f'slot_note_{slot}',(left+10,720),'托盘位姿：未定义',14))
    ops.append(text('legend_title',(30,790),'对象索引（ID完整显示；标签、属性及局部箱面见逐箱卡片）',18))
    for i,line in enumerate(rows):ops.append(text(f'legend_{i}',(30,830+i*25),line,16))
    return {'kind':'scene','size':[SCENE_WIDTH,height],'ops':ops}


def raster(plan):
    image=Image.new('RGB',tuple(plan['size']),'white');draw=ImageDraw.Draw(image)
    for op in plan['ops']:
        if op['kind']=='text':draw.text(tuple(op['xy']),op['text'],font=font(op['font']),fill=op['fill'])
        elif op['kind']=='rect':draw.rectangle(op['xy'],fill=op['fill'],outline=op['outline'],width=op['width'])
        else:draw.polygon([tuple(v) for v in op['xy']],fill=op['fill'],outline=op['outline'],width=op['width'])
    return image


def png_bytes(plan,facts_digest):
    im=raster(plan);info=PngImagePlugin.PngInfo();info.add_text('rendering_version',VERSION);info.add_text('facts_digest',facts_digest)
    out=io.BytesIO();im.save(out,format='PNG',pnginfo=info,optimize=False,compress_level=6)
    return out.getvalue(),hashlib.sha256(im.tobytes()).hexdigest()
