"""Stdlib PNG pixel inspection only; no image edit/export or production import."""
from pathlib import Path
import struct,zlib,hashlib,json

def check(path,regions):
 data=path.read_bytes();i=8;packed=[]
 assert data[:8]==b'\x89PNG\r\n\x1a\n'
 while i<len(data):
  n=struct.unpack('>I',data[i:i+4])[0];tag=data[i+4:i+8];chunk=data[i+8:i+8+n];i+=n+12
  if tag==b'IHDR':w,h,depth,color,comp,fil,inter=struct.unpack('>IIBBBBB',chunk)
  if tag==b'IDAT':packed.append(chunk)
 assert depth==8 and color in (2,6) and inter==0
 bpp=4 if color==6 else 3;stride=w*bpp;raw=zlib.decompress(b''.join(packed));prev=bytearray(stride);off=0;buffers={k:bytearray() for k in regions}
 for y in range(h):
  f=raw[off];off+=1;row=bytearray(raw[off:off+stride]);off+=stride
  for x in range(stride):
   a=row[x-bpp] if x>=bpp else 0;b=prev[x];c=prev[x-bpp] if x>=bpp else 0
   if f==1:row[x]=(row[x]+a)&255
   elif f==2:row[x]=(row[x]+b)&255
   elif f==3:row[x]=(row[x]+((a+b)//2))&255
   elif f==4:
    p=a+b-c;pa,pb,pc=abs(p-a),abs(p-b),abs(p-c);v=a if pa<=pb and pa<=pc else b if pb<=pc else c;row[x]=(row[x]+v)&255
   else:assert f==0
  for k,(x0,y0,x1,y1) in regions.items():
   if y0<=y<y1:buffers[k].extend(row[x0*bpp:x1*bpp])
  prev=row
 return {'file':str(path),'size':[w,h],'regions':{k:{'pixel_sha256':hashlib.sha256(buf).hexdigest(),'dark_pixels':sum(max(buf[j:j+3])<120 and (bpp==3 or buf[j+3]>128) for j in range(0,len(buf),bpp))} for k,buf in buffers.items()}}

base=Path('semantic_pallet_planner/outputs');groups={}
for name,regions in [('GEOM_CANDIDATES_GP4_20261117_01',{'y_label':(115,250,151,420),'lower_title':(330,675,650,720),'top_y_ticks':(145,140,213,540)}),('GEOM_CANDIDATES_GP5_P0_20261117_01',{'y_label':(145,240,180,385),'lower_title':(340,640,590,671),'top_y_ticks':(180,145,225,475)})]:
 rows=[check(p,regions) for p in sorted((base/name/'figures').glob('*.png'))]
 groups[name]={'rows':rows,'selected_regions_pixel_identical_across_five':all(len({r['regions'][key]['pixel_sha256'] for r in rows})==1 for key in regions),'selected_regions_nonempty':all(r['regions'][k]['dark_pixels']>0 for r in rows for k in regions)}
print(json.dumps({'method':'lossless raw PNG scanline decoding and selected label-region pixel identity; no OCR/no edits','groups':groups,'scope':'checks specific y-label, lower-title and y-tick regions against the clearly visible P01 reference, not every contour pixel'},ensure_ascii=False,indent=2))
