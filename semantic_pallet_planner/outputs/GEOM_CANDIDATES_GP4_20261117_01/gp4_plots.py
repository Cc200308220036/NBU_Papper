"""Five static combined figures from saved pools, never calls a provider."""
from gp4_common import *
def plots():
 import matplotlib
 matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 from matplotlib.patches import Rectangle,Patch
 result=read(OUT/'comparison.json');dest=OUT/'figures';dest.mkdir(exist_ok=True)
 colors={'INTERSECTION':'#444444','OLD_ONLY':'#d87a18','NEW_ONLY':'#176db0','NOT_COMPARABLE':'#a04466'}
 for row in result['states']:
  point=row['point_id'];s=read(OUT/'inputs'/point/'original_snapshot.json')['current_public_state'];container=s['container'];length=container['length_mm'];width=container['width_mm'];height=container['max_height_mm']
  fig,axes=plt.subplots(2,2,figsize=(12,10));comparison=row['final_comparison']
  pools={b:read(OUT/'states'/point/b/'bundle.json')['physical_candidates'] if row['backends'][b]['status'] in ('OK','OK_EMPTY') else None for b in BACKENDS}
  sets={b:{action(c) for c in cs} if cs is not None else None for b,cs in pools.items()}
  for j,b in enumerate(BACKENDS):
   for i in (0,1):
    ax=axes[i,j];ax.set_xlim(-length/2,length/2);ax.set_ylim((-width/2 if i==0 else 0),(width/2 if i==0 else height));ax.set_aspect('equal',adjustable='box');ax.grid(alpha=.2);ax.set_xlabel('x (mm)');ax.set_ylabel('y (mm)' if i==0 else 'z (mm)');ax.set_title(('OLD E2' if j==0 else 'NEW EMS + surface')+' | '+('top view' if i==0 else 'x-z view'))
    for obj in s['placed_items']:
     p=obj['pose'];l,w,h=obj['oriented_size_mm'];a=(p['x_mm']-l/2,p['y_mm']-w/2) if i==0 else (p['x_mm']-l/2,p['z_base_mm'])
     ax.add_patch(Rectangle(a,l,w if i==0 else h,facecolor='#d8d8d8',edgecolor='#999999',alpha=.7))
    if pools[b] is None:
     error=row['backends'][b]['error'] or row['common_error'] or {}
     ax.text(.02,.98,row['backends'][b]['status']+'\n'+str(error.get('code','COMMON_INPUT_NOT_ADMITTED')),transform=ax.transAxes,va='top',color='#a04466',wrap=True)
    else:
     for c in pools[b]:
      k=action(c);cat='NOT_COMPARABLE' if comparison is None else ('INTERSECTION' if k in sets[BACKENDS[0]]&sets[BACKENDS[1]] else ('OLD_ONLY' if j==0 else 'NEW_ONLY'))
      p=c['pose'];l,w,h=c['oriented_size_mm'];x=p['x_mm'];y=p['y_mm'] if i==0 else p['z_base_mm']
      ax.scatter(x,y,s=24,color=colors[cat],marker='o' if p['yaw_deg']==0 else 'x',alpha=.7)
      ax.add_patch(Rectangle((x-l/2,y-w/2 if i==0 else y),l,w if i==0 else h,fill=False,edgecolor=colors[cat],alpha=.12,linewidth=.7))
  title=point+' | '+('I='+str(comparison['intersection_count'])+' OLD_ONLY='+str(comparison['old_only_count'])+' NEW_ONLY='+str(comparison['new_only_count']) if comparison is not None else 'NOT COMPARABLE; failures retained')
  fig.suptitle(title);fig.legend(handles=[Patch(color=v,label=k) for k,v in colors.items()],loc='lower center',ncol=4)
  fig.text(.5,.065,'Centers/footprints of alternative candidates; grey = saved placed boxes. Circles yaw0; x yaw90.\nNo selection, monitor, placement, order benefit or global completeness claim.',ha='center',fontsize=9)
  fig.tight_layout(rect=(0,.10,1,.95));fig.savefig(dest/(point+'.png'),dpi=140);plt.close(fig)
 print('SAVED_FIGURES',len(list(dest.glob('*.png'))),flush=True)
if __name__=='__main__':plots()
