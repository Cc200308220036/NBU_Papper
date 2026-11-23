"""Export saved facts only. No planner, oracle, monitor, model or credentials."""
from pathlib import Path
import json,hashlib
HERE=Path(__file__).parent
ROOT=HERE.parents[2]
RUN=ROOT/'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_TOP_LOAD_DISABLED_RUN_20261122_01'
files={}
def read(p):
 files[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
 return json.loads(p.read_text())
def rect(o):
 x,y=o['pose']['x_mm'],o['pose']['y_mm'];l,w=o['oriented_size_mm'][:2]
 return [x-l/2,y-w/2,x+l/2,y+w/2]
def union(rs):
 xs=sorted({a for r in rs for a in (r[0],r[2])});area=0
 for a,b in zip(xs,xs[1:]):
  ys=sorted((r[1],r[3]) for r in rs if r[0]<b and r[2]>a)
  end=None;total=0
  for c,d in ys:
   if end is None or c>end:total+=d-c;end=d
   elif d>end:total+=d-end;end=d
  area+=(b-a)*total
 return area
jobs=[]
for jid,name in [('G00','E2'),('G01','EMS')]:
 cp=read(RUN/'jobs'/jid/'checkpoint.json');metric=read(RUN/'jobs'/jid/'metrics.json');final=cp['events'][-1]
 side=read(RUN/'jobs'/jid/'blobs'/final['geometry_ref']['sha256'])
 placed=[e for e in cp['events'] if e['event']=='PLACE']
 steps=[]
 for e in placed:
  sel=e['selection'];candidate=next(c for c in e['bundle']['physical_candidates'] if c['candidate_id']==sel['selected_candidate_id'])
  steps.append({'item_id':candidate['pick_item_id'],'label':sel['selected_display_id'],'candidate_count':len(e['bundle']['physical_candidates']),
   'monitor':e['monitor']['status'],'candidate_id':candidate['candidate_id'],'pose':candidate['pose'],'size':candidate['oriented_size_mm'],
   'support_ratio':candidate['support']['support_ratio']})
 proposals=[]
 if name=='EMS':
  raw=side['audit']['generation']['audit']['items'][0]['proposal_rejections']
  unique={}
  for row in raw:
   key=tuple(row['action_key']);entry=unique.setdefault(key,{'key':list(key),'reason':row['reason'],'sources':[]})
   entry['sources'].append(row['source_type'])
  for i,p in enumerate(unique.values()):
   k=p['key'];l,w,h,yaw,x,y,z=map(float,k[1:]);rs=[];supports=[]
   for o in cp['state']['placed_items']:
    if abs(o['pose']['z_base_mm']+o['oriented_size_mm'][2]-z)>1e-6:continue
    a,b,c,d=rect(o);r=[max(a,x-l/2),max(b,y-w/2),min(c,x+l/2),min(d,y+w/2)]
    if r[2]>r[0] and r[3]>r[1]:rs.append(r);supports.append(o['item_id'])
   p.update(id=i,pose={'x_mm':x,'y_mm':y,'z_base_mm':z,'yaw_deg':int(yaw)},oriented_size_mm=[l,w,h],support_ratio=union(rs)/(l*w),contact_rectangles=rs,support_ids=supports)
   assert p['support_ratio']<.7
   proposals.append(p)
 jobs.append({'id':jid,'name':name,'container':cp['state']['container'],'placed':cp['state']['placed_items'],'metrics':metric,
  'steps':steps,'pending':[o['item'] for o in final['before']['pending_items']],
  'counts':final['bundle']['generation_counts'],'proposals':proposals,'generation_status':side['audit']['generation']['status'],
  'final_event_index':len(cp['events'])-1,'audit_blob':final['geometry_ref']['sha256']})
data={'title':'GP6-F0 关闭包装承载上限 · 停单对比','plan_digest':read(RUN/'plan.json')['source_identity'],
 'jobs':jobs,'source_hashes':files,'new_calls':0,'scope':'已保存真实运行，逐箱回看；不重新枚举或求解。支撑比例为保存姿态的几何交集派生值。'}
# Source identity and plan digest are distinct.
from hashlib import sha256
plan=json.loads((RUN/'plan.json').read_text());data['plan_digest']=sha256(json.dumps(plan,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
(HERE/'case_data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
html=(HERE/'template.html').read_text().replace('__DATA__',json.dumps(data,ensure_ascii=False).replace('</','<\\/'))
(HERE/'index.html').write_text(html)
print(json.dumps({'jobs':len(jobs),'placed':[len(j['placed']) for j in jobs],'EMS_unique_proposals':len(jobs[1]['proposals']),'EMS_support_range':[min(p['support_ratio'] for p in proposals),max(p['support_ratio'] for p in proposals)],'new_calls':0}))
