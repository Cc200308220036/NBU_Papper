from pathlib import Path
import json,math
r=Path('/home/cyw/NBU_Papper/semantic_pallet_planner/outputs/VERIFY_JEV_PCT_MONITOR_20261103_01');rows=[]
for p in sorted((r/'p1_fixtures').glob('*.json')):
 if p.stem=='index':continue
 v=json.loads(p.read_text());res=v['result'];boxes=[*v['state']['placed'],v['candidate']];C=v['state']['container_mm']
 by={b['item_id']:b for b in boxes};ordered=sorted(by)
 def center(b):return [b['bottom_center_mm'][0]+C[0]/2,b['bottom_center_mm'][1]+C[1]/2]
 def bounds(b):
  dims=b['dimensions_mm'];s=dims[:2][::-1] if b['yaw_deg']==90 else dims[:2];c=center(b)
  return [c[0]-s[0]/2,c[1]-s[1]/2,c[0]+s[0]/2,c[1]+s[1]/2]
 if res['status']=='STABLE':
  forces=res['diagnostics']['reactions']
  for name,b in by.items():
   outgoing=[f for f in forces if f['upper']==name];incoming=[f for f in forces if f['lower']==name]
   assert abs(math.fsum(f['mass_kg'] for f in outgoing)-math.fsum(f['mass_kg'] for f in incoming)-b['mass_kg'])<1e-8
   for d in (0,1):
    assert abs(math.fsum(f['mass_kg']*f['point_mm'][d] for f in outgoing)-math.fsum(f['mass_kg']*f['point_mm'][d] for f in incoming)-b['mass_kg']*center(b)[d])<1e-6
  rows.append({'fixture':p.stem,'audit':'independent local mass and x/y moments','passed':True})
 elif res['status']=='UNSTABLE':
  cert=res['diagnostics']['infeasibility_certificate'];y=cert['y'];contacts=[]
  for upper in boxes:
   a=bounds(upper);z=upper['bottom_center_mm'][2]
   if z==0:contacts.append((upper['item_id'],None,a))
   else:
    for lower in boxes:
     if lower==upper:continue
     if abs(lower['bottom_center_mm'][2]+lower['dimensions_mm'][2]-z)>1e-6:continue
     b=bounds(lower);rect=[max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])]
     if rect[2]>rect[0] and rect[3]>rect[1]:contacts.append((upper['item_id'],lower['item_id'],rect))
  projections=[]
  for u,l,rect in sorted(contacts,key=lambda c:(c[0],c[1] or '',*c[2])):
   x0,y0,x1,y1=rect
   for x,yy in [(x0,y0),(x0,y1),(x1,y0),(x1,y1)]:
    q=0
    for n,sign in [(u,1),(l,-1)]:
     if n is None:continue
     i=3*ordered.index(n);cx,cy=center(by[n]);q+=sign*(y[i]+(x-cx)/max(C[:2])*y[i+1]+(yy-cy)/max(C[:2])*y[i+2])
    projections.append(q)
  mass=math.fsum(b['mass_kg'] for b in boxes)
  rhs=math.fsum(by[n]['mass_kg']/mass*y[3*i] for i,n in enumerate(ordered))
  gap=math.fsum(min(q,0) for q in projections)-rhs
  assert gap>1e-8 and abs(gap-cert['separation_gap'])<1e-10
  assert len(projections)==len(cert['column_projections']) and all(abs(a-b)<1e-10 for a,b in zip(projections,cert['column_projections']))
  rows.append({'fixture':p.stem,'audit':'matrix and Farkas certificate reconstructed from independent input geometry','separation_gap':gap,'passed':True})
(r/'independent_p1_audit.json').write_text(json.dumps(rows,indent=2)+'\n');print(len(rows))
