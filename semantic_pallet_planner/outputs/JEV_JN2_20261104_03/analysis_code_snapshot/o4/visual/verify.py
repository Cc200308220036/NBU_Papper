"""Independent facts/primitive/pixel audit; never calls the production renderer.

Only low-level schema/Pillow and public-input validation are shared. Expected
text, face transformations and projections are reconstructed here.
"""
import hashlib
import io
import itertools
import math
from PIL import Image,ImageDraw,ImageFont
from ..common import digest,O4Error
from .facts import unpack,validate,VERSION,FONT

NORMALS={'pos_x':(1,0,0),'neg_x':(-1,0,0),'pos_y':(0,1,0),'neg_y':(0,-1,0),'pos_z':(0,0,1),'neg_z':(0,0,-1)}

def require(ok,why):
    if not ok:raise O4Error('visual_mismatch',why)

def close(a,b):
    if isinstance(a,(tuple,list)) and isinstance(b,(tuple,list)):return len(a)==len(b) and all(close(x,y) for x,y in zip(a,b))
    return abs(a-b)<=1e-5


def audit_facts(source,facts):
    validate('facts',facts);obs,buf=unpack(source)
    require(facts['facts_digest']==digest({k:v for k,v in facts.items() if k!='facts_digest'}),'facts digest')
    require(facts['container']==obs['container'] and facts['units']==obs['units'],'container/units')
    require(facts['mode']==(buf['mode'] if buf else 'single'),'mode')
    require(facts['buffer_capacity']==(buf['buffer_capacity'] if buf else 1),'capacity')
    require(facts['end_of_stream']==(buf['end_of_stream'] if buf else None),'EOS')
    objects={o['object_id']:(role,o) for role,key in [('placed','placed_objects'),('pending','available_objects')] for o in obs[key]}
    require(len(facts['objects'])==len(objects) and {o['object_id'] for o in facts['objects']}==set(objects),'objects')
    expected_order=sorted(o['object_id'] for o in obs['placed_objects'])+sorted(o['object_id'] for o in obs['available_objects'])
    require([o['object_id'] for o in facts['objects']]==expected_order,'canonical object order')
    slots={p['object_id']:p for p in buf['pending_items']} if buf else {}
    for obj in facts['objects']:
        role,o=objects[obj['object_id']];require(obj['facts']==o and obj['location']==role,'object facts/role')
        slot=slots.get(o['object_id']);require(obj['slot']==(slot['slot'] if slot else None) and obj['arrival_index']==(slot['arrival_index'] if slot else None),'slots/arrival')
        label=obj['label'];expected={'object_id':o['object_id'],'cargo_category':o['cargo_category'],'reinforced':o['packaging']['reinforced'],'no_top_load':o['labels']['no_top_load'],'max_top_load_kg':o['labels']['max_top_load_kg']}
        require(label['payload']==expected and label['face_id']=='pos_x' and label['uv_rect']==[.15,.25,.85,.75],'label')
        require(len(obj['faces'])==6 and {f['face_id'] for f in obj['faces']}==set(NORMALS),'six faces')
        dims=o['dimensions_mm'];ranges=[[-dims['length']/2,dims['length']/2],[-dims['width']/2,dims['width']/2],[0,dims['height']]]
        for face in obj['faces']:
            normal=NORMALS[face['face_id']];axis=next(i for i,n in enumerate(normal) if n)
            choices=[list(r) for r in ranges];choices[axis]=[ranges[axis][1 if normal[axis]>0 else 0]]
            expected_vertices=sorted(itertools.product(*choices))
            require(close(sorted(face['local_vertices_mm']),expected_vertices),'local vertices')
            vertices=face['local_vertices_mm']
            require(all(sum(abs(a-b)>1e-9 for a,b in zip(vertices[i],vertices[(i+1)%4]))==1 for i in range(4)),'face perimeter')
            require(tuple(face['local_normal'])==normal,'local normal')
            if role=='pending':require(face['world_normal'] is None and face['world_vertices_mm'] is None,'pending phantom pose')
            else:
                pose=o['pose'];yaw=pose['yaw_deg'];trans=(pose['x_mm'],pose['y_mm'],pose['z_base_mm'])
                transformed=[]
                for q in face['local_vertices_mm']:
                    turn=q if yaw==0 else (-q[1],q[0],q[2]);transformed.append([turn[i]+trans[i] for i in range(3)])
                n=normal if yaw==0 else (-normal[1],normal[0],normal[2])
                require(close(face['world_vertices_mm'],transformed) and close(face['world_normal'],n),'world face/yaw')
    return True


def check_ops(plan,expected_text,expected_shapes):
    ops=plan['ops'];byid={o['id']:o for o in ops}
    require(len(ops)==len(byid) and set(byid)==set(expected_text)|set(expected_shapes),'primitive completeness')
    for key,(xy,value,size) in expected_text.items():
        op=byid[key]
        require(set(op)=={'id','kind','xy','text','font','fill'} and op['kind']=='text','text protocol')
        require(op['xy']==list(xy) and op['text']==value and op['font']==size and op['fill']=='#152b3b','text facts/layout '+key)
    for key,(kind,xy,fill,outline,width) in expected_shapes.items():
        op=byid[key]
        require(set(op)=={'id','kind','xy','fill','outline','width'} and op['kind']==kind,'shape protocol')
        require(close(op['xy'],xy) and op['fill']==fill and op['outline']==outline and op['width']==width,'shape geometry/style '+key)


def audit_card(data,plan):
    require(set(data)=={'rendering_version','label_face_version','facts','local_label_face','uv_rect'},'card facts whitelist')
    require(data['rendering_version']==VERSION and data['local_label_face']=='pos_x' and data['uv_rect']==[.15,.25,.85,.75],'card contract')
    obj=data['facts'];require(set(obj)=={'object_id','mass_kg','dimensions_mm','cargo_category','packaging','labels','physical_top_load_limit_kg','stackable','fragile','weight_class'},'card fact fields')
    require('pose' not in obj and 'oriented_size_mm' not in obj,'local card phantom pose')
    require(plan['size']==[1040,580] and plan['kind']=='card','card size')
    expected={};value='对象 '+obj['object_id']
    for i,start in enumerate(range(0,len(value),50)):expected['id_'+str(i)]=((20,15+i*25),value[start:start+50],18)
    expected.update(local_note=((20,100),'局部箱面示意：非托盘位姿；所有印刷标签在 +X 面',18),
      face_name=((40,480),'标签印刷面：+X；面内 u=0.15..0.85，v=0.25..0.75',16),
      panel_title=((465,120),'+X 标签面展开（准确仿真印刷事实）',20),
      card_footer=((20,550),'mm / kg | '+VERSION+' | 仿真事实；无业务允许/违规结论',16))
    d=obj['dimensions_mm'];values=[('category','货物类别',obj['cargo_category']),('reinforced','包装加固',str(obj['packaging']['reinforced']).lower()),
      ('no_top','禁压标记',str(obj['labels']['no_top_load']).lower()),('limit','标签累计顶部限载 kg',obj['labels']['max_top_load_kg']),
      ('dimensions','本地长/宽/高 mm',' / '.join(str(d[k]) for k in ('length','width','height'))),('mass','质量 kg',obj['mass_kg']),
      ('physical_limit','物理顶部承载 kg',obj['physical_top_load_limit_kg']),('stackable','物理可堆叠',str(obj['stackable']).lower()),
      ('fragile','易碎属性',str(obj['fragile']).lower()),('weight_class','重量等级',obj['weight_class'])]
    expected['physical_title']=((465,300),'其他准确公共参数（不由标签推断）',18)
    for i,(k,title,v) in enumerate(values):
        y=160+i*32 if i<4 else 335+(i-4)*30
        expected['field_'+k]=((465,y),title+': '+str(v),18)
    # Different construction: orthographic matrix applied to the 8 extent corners.
    a,b,c=(d[k]/max(d.values()) for k in ('length','width','height'))
    corners=list(itertools.product((-a/2,a/2),(-b/2,b/2),(0,c)))
    transform=lambda q:(sum(x*y for x,y in zip(q,(.8,-.6,0))),sum(x*y for x,y in zip(q,(.3,.3,-.85))))
    flat=list(map(transform,corners));mins=[min(v[i] for v in flat) for i in (0,1)];span=[max(v[i] for v in flat)-mins[i] for i in (0,1)]
    zoom=min(390/span[0],310/span[1])
    def project(q):
        v=transform(q);return [30+(v[0]-mins[0])*zoom,145+(v[1]-mins[1])*zoom]
    faces={'pos_y':[(a/2,b/2,0),(-a/2,b/2,0),(-a/2,b/2,c),(a/2,b/2,c)],
      'pos_x':[(a/2,-b/2,0),(a/2,b/2,0),(a/2,b/2,c),(a/2,-b/2,c)],
      'pos_z':[(-a/2,-b/2,c),(a/2,-b/2,c),(a/2,b/2,c),(-a/2,b/2,c)]}
    shapes={}
    for name,points in faces.items():shapes['box_'+name]=('polygon',list(map(project,points)),{'pos_y':'#e5d4ba','pos_x':'#d8bd96','pos_z':'#f2e4cf'}[name],'#405060',2)
    patch=[(a/2,-.35*b,.25*c),(a/2,.35*b,.25*c),(a/2,.35*b,.75*c),(a/2,-.35*b,.75*c)]
    shapes['label_patch']=('polygon',list(map(project,patch)),'#fff8dc','#152b3b',2)
    check_ops(plan,expected,shapes)


def audit_scene(facts,plan):
    entries=facts['objects'];placed=[o for o in entries if o['location']=='placed'];pending=[o for o in entries if o['location']=='pending']
    ids={o['object_id']:'B'+str(i).zfill(2) for i,o in enumerate(entries,1)}
    rows=[]
    for o in entries:
        value=ids[o['object_id']]+' '+('已码' if o['location']=='placed' else '待码')+' = '+o['object_id']
        rows.extend(value[i:i+90] for i in range(0,len(value),90))
    require(plan['kind']=='scene' and plan['size']==[1440,max(980,850+len(rows)*25)],'scene shape')
    expected={'title':((20,16),'准确公共状态：托盘线框投影与独立待码区',26),
      'coordinate_note':((20,58),'坐标原点=托盘底面中心；mm / kg；线框显示遮挡对象，逐箱标签详见独立卡片',18),
      'status':((20,92),f"模式：{'单箱' if facts['mode']=='single' else '缓冲'} 容量：{facts['buffer_capacity']} 已码：{len(placed)} 待码：{len(pending)} 到货结束：{'未提供' if facts['end_of_stream'] is None else ('是' if facts['end_of_stream'] else '否')}",18),
      'pending_title':((30,625),'待码槽位示意：不是托盘坐标；未赋予箱体托盘位姿',18),
      'legend_title':((30,790),'对象索引（ID完整显示；标签、属性及局部箱面见逐箱卡片）',18)}
    shapes={};c=facts['container'];dims=[c[k] for k in ('length_mm','width_mm','max_height_mm')]
    expected['container_dims']=((760,92),'托盘长/宽/限高 mm: '+' / '.join(str(v) for v in dims),16)
    for name,axes,region,label in [('xy',(0,1),(30,150,650,430),'俯视 XY（+Y 向上）'),('xz',(0,2),(760,150,650,270),'正视 XZ（+Z 向上）'),('yz',(1,2),(760,480,650,270),'侧视 YZ（+Z 向上）')]:
        left,top,w,h=region;expected['view_title_'+name]=((left,top-28),label,18)
        shapes['view_frame_'+name]=('rect',[left,top,left+w,top+h],None,'#405060',2)
        def projected(point):
            a,b=axes
            u=point[a]/dims[a]+.5;v=(.5 if b==1 else 1.)-point[b]/dims[b]
            return [left+w*u,top+h*v]
        for obj in sorted(placed,key=lambda o:(o['facts']['pose']['z_base_mm'],o['object_id'])):
            o=obj['facts'];p=o['pose'];center=[p['x_mm'],p['y_mm'],p['z_base_mm']+o['oriented_size_mm'][2]/2]
            lo=[center[i]-o['oriented_size_mm'][i]/2 for i in range(3)];hi=[center[i]+o['oriented_size_mm'][i]/2 for i in range(3)]
            a,b=axes;points=[]
            for va,vb in [(lo[a],lo[b]),(hi[a],lo[b]),(hi[a],hi[b]),(lo[a],hi[b])]:
                v=list(center);v[a]=va;v[b]=vb;points.append(projected(v))
            key=o['object_id'];shapes[name+'_box_'+key]=('polygon',points,None,'#405060',2)
            face=next(f for f in obj['faces'] if f['face_id']=='pos_x');shapes[name+'_face_'+key]=('polygon',list(map(projected,face['world_vertices_mm'])),None,'#7a541f',2)
            expected[name+'_id_'+key]=(projected(center),ids[key],13)
    for slot in range(facts['buffer_capacity']):
        left=30+210*slot;shapes['slot_'+str(slot)]=('rect',[left,665,left+190,755],'#f3f6f8','#405060',1)
        picks=[o for o in pending if o['slot']==slot or (o['slot'] is None and slot==0)]
        value=' / '.join(ids[o['object_id']] for o in picks) if picks else '空'
        line=f'槽 {slot}: {value}' if any(o['slot'] is not None for o in pending) else '当前箱: '+value
        expected['slot_text_'+str(slot)]=((left+10,685),line,16);expected['slot_note_'+str(slot)]=((left+10,720),'托盘位姿：未定义',14)
    for i,line in enumerate(rows):expected['legend_'+str(i)]=((30,830+i*25),line,16)
    check_ops(plan,expected,shapes)


def audit_pixels(png,plan,facts_digest,font_path=FONT):
    actual=Image.open(io.BytesIO(png));actual.load()
    require(actual.format=='PNG' and actual.mode=='RGB' and list(actual.size)==plan['size'],'PNG shape/mode')
    require(actual.info=={'rendering_version':VERSION,'facts_digest':facts_digest},'PNG metadata whitelist')
    reference=Image.new('RGB',tuple(plan['size']),(255,255,255));canvas=ImageDraw.Draw(reference);fonts={}
    for op in plan['ops']:
        kind=op['kind'];coords=op['xy']
        if kind=='text':
            if op['font'] not in fonts:fonts[op['font']]=ImageFont.truetype(str(font_path),op['font'],index=0)
            canvas.text((coords[0],coords[1]),op['text'],font=fonts[op['font']],fill=op['fill'])
        elif kind=='rect':canvas.rectangle(tuple(coords),fill=op['fill'],outline=op['outline'],width=op['width'])
        else:canvas.polygon(tuple((q[0],q[1]) for q in coords),fill=op['fill'],outline=op['outline'],width=op['width'])
    require(actual.tobytes()==reference.tobytes(),'pixel content (including text/labels)')
    return {'sha256':hashlib.sha256(png).hexdigest(),'pixel_sha256':hashlib.sha256(actual.tobytes()).hexdigest()}
