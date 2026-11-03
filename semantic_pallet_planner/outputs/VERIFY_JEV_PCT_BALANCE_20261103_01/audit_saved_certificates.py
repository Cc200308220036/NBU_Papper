"""Reconstruct the physical matrix from fixture input, not from solver helpers."""
from pathlib import Path
import json
import math
import sys
import numpy as np
out=Path(sys.argv[1]);checks=[]
for path in sorted((out/'fixtures_v2').glob('*.json')):
    if path.name=='index.json':continue
    data=json.loads(path.read_text());result=data['result']
    if result['status']!='UNSTABLE':continue
    objects=[*data['state']['placed'],data['candidate']]
    container=data['state']['container_mm'];length=max(container[:2]);total=math.fsum(b['mass_kg'] for b in objects)
    geometry={}
    for b in objects:
        sx,sy,sz=b['dimensions_mm']
        if b['yaw_deg']==90:sx,sy=sy,sx
        x,y,z=b['bottom_center_mm'];cx=x+container[0]/2;cy=y+container[1]/2
        geometry[b['item_id']]=dict(center=(cx,cy),low=(cx-sx/2,cy-sy/2,z),high=(cx+sx/2,cy+sy/2,z+sz))
    contacts=[]
    for b in objects:
        g=geometry[b['item_id']];lo,hi=g['low'],g['high']
        if lo[2]==0:contacts.append((b['item_id'],None,(lo[0],lo[1],hi[0],hi[1])))
        else:
            for other in objects:
                q=geometry[other['item_id']]
                if abs(q['high'][2]-lo[2])<1e-6:
                    rectangle=(max(lo[0],q['low'][0]),max(lo[1],q['low'][1]),min(hi[0],q['high'][0]),min(hi[1],q['high'][1]))
                    if rectangle[2]>rectangle[0] and rectangle[3]>rectangle[1]:contacts.append((b['item_id'],other['item_id'],rectangle))
    contacts.sort(key=lambda c:(c[0],c[1] or '',*c[2]))
    columns=[]
    for upper,lower,(x0,y0,x1,y1) in contacts:
        columns.extend((upper,lower,x,y) for x,y in [(x0,y0),(x0,y1),(x1,y0),(x1,y1)])
    ordered=sorted(objects,key=lambda b:b['item_id']);row={b['item_id']:3*i for i,b in enumerate(ordered)}
    a=np.zeros((3*len(objects),len(columns)));rhs=np.zeros(3*len(objects))
    for b in ordered:rhs[row[b['item_id']]]=b['mass_kg']/total
    for j,(upper,lower,x,y) in enumerate(columns):
        for name,sign in [(upper,1),(lower,-1)]:
            if name is not None:
                cx,cy=geometry[name]['center'];i=row[name]
                a[i,j]+=sign;a[i+1,j]+=sign*(x-cx)/length;a[i+2,j]+=sign*(y-cy)/length
    cert=result['diagnostics']['infeasibility_certificate'];y=np.array(cert['y'])
    projection=a.T@y;dot=float(rhs@y);lower=float(np.minimum(projection,0).sum());gap=lower-dot
    mismatch=float(np.max(abs(projection-np.array(cert['column_projections'])),initial=0))
    assert mismatch<1e-12 and abs(dot-cert['rhs_dot'])<1e-12
    assert gap>1e-8 and math.isfinite(gap)
    checks.append(dict(fixture=data['fixture'],independent_separation_gap=gap,projection_reconstruction_error=mismatch,rhs_reconstruction_error=abs(dot-cert['rhs_dot']),status='PASS'))
assert len(checks)==2
(out/'independent_infeasibility_audit.json').write_text(json.dumps({'method':'reconstruct actual physical contact rectangles and per-box mass/moment matrix from input geometry; verify bounded separation without running LP or importing production solver','checks':checks},indent=2)+'\n')
print('independent infeasibility certificates',len(checks),'verified')
