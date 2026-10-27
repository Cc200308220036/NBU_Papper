"""Compare two new local episodes on the same source; no execution or API."""
from pathlib import Path
import json,os
os.environ.setdefault('MPLCONFIGDIR','/tmp/e5-spatial-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import patches,font_manager
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
EXP=ROOT/'semantic_pallet_planner/outputs/EXP_O4_E5_SPATIAL_LOCAL_20261027_01'
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc');plt.rcParams.update({'font.family':'Noto Sans CJK JP','axes.unicode_minus':False})
paths=[EXP/'episodes/SP000_E5_SRC02_C0_baseline_single_oracle_ast.json',EXP/'episodes/SP003_E5_SRC02_C0_combined_single_oracle_ast.json']
fig,axs=plt.subplots(1,2,figsize=(14,7),facecolor='#f5f7fb');fig.suptitle('同一订单00102047 / C0：原规划与空间规划V1',fontsize=20,y=.97)
colors={'food':'#32a17a','general':'#7290bc','glassware':'#c19b4f','electronics':'#8d7ac2','household_cleaner':'#ce7ea6'}
for ax,path,title in zip(axs,paths,['原候选＋原评分','新候选＋新空间评分']):
    r=json.loads(path.read_text());m=r['measurement'];s=r['final_state'];attrs=s['attributes']
    ax.add_patch(patches.Rectangle((-600,-500),1200,750,facecolor='#e6f5ee'))
    ax.add_patch(patches.Rectangle((-600,250),1200,250,facecolor='#ffe8e7'));ax.axhline(250,c='#d65c6b',ls='--')
    for b in s['placed_items']:
        dx,dy,dz=b['oriented_size_mm'];p=b['pose'];oid=b['item_id'];cat=attrs[oid]['cargo_category'];ax.add_patch(patches.Rectangle((p['x_mm']-dx/2,p['y_mm']-dy/2),dx,dy,facecolor=colors[cat],edgecolor='white',lw=2,alpha=.9));ax.text(p['x_mm'],p['y_mm'],oid[-2:]+('↑' if p['z_base_mm'] else ''),ha='center',va='center',color='white',fontweight='bold')
    ax.set(xlim=(-620,620),ylim=(-520,520),xlabel='x (mm)',ylabel='y (mm)');ax.set_aspect('equal');ax.set_title(title+f'\n已放{m["placed_items"]}/12箱 · 订单体积{m["placed_volume_ratio"]:.2%}',fontsize=14,pad=14)
fig.text(.5,.06,'同样规则、同样来源、Oracle AST；两组实际违规均为0。新布局多放1箱，但仍未整单完成。',ha='center',fontsize=12,color='#425976')
fig.subplots_adjust(left=.07,right=.96,bottom=.16,top=.83,wspace=.18)
fig.savefig(OUT/'representative_before_after.png',dpi=160,facecolor=fig.get_facecolor());plt.close(fig)
print('saved representative_before_after.png')
