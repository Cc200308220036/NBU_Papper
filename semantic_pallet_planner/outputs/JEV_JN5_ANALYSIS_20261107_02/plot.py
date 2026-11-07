"""Static scientific figures from analyze.py output only; no runtime imports."""
import argparse, json, hashlib, os
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Patch
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

COLORS=['#667785','#a7afb5','#3469a4','#29997b','#d16b47','#9d78a8']
METHODS=['geometry','fixed','none','T','E','unrelated_E']
LABELS=['Geometry','Fixed order','No memory','T','E','Unrelated E']

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,default=Path(__file__).parent);a=ap.parse_args();b=Path(os.path.relpath(a.input,Path.cwd()))
    if (b/'delivery_manifest.json').exists():raise RuntimeError('sealed_output_refuse_overwrite')
    figs=b/'figures';figs.mkdir(exist_ok=True)
    def read(n):return json.loads((b/n).read_text())
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none','pdf.fonttype':42})
    records=[]
    def save(fig,name,sources,extra=None):
        paths=[]
        for ext in ['png','svg','pdf']:
            p=figs/(name+'.'+ext);fig.savefig(p,dpi=240,bbox_inches='tight',facecolor='white');paths.append(str(p))
        records.append({'figure':name,'files':paths,'inputs':[{'path':str(b/s),'sha256':hashlib.sha256((b/s).read_bytes()).hexdigest()} for s in sources],'settings':extra or {}});plt.close(fig)
    data=read('main_24_metrics.json')
    fig,axes=plt.subplots(2,2,figsize=(12,8),sharex=True)
    for ax,task in zip(axes.flat,sorted({r['task_id'] for r in data})):
        rs=[next(r for r in data if r['task_id']==task and r['method']==m) for m in METHODS]
        ax.barh(np.arange(6),[100*r['placed_volume_ratio'] for r in rs],height=.66,color=COLORS)
        for i,r in enumerate(rs): ax.text(100*r['placed_volume_ratio']+1,i,f"{100*r['placed_volume_ratio']:.1f}%   {r['placed_items']}/{r['planned_items']}",va='center',fontsize=10)
        ax.set_yticks(range(6),LABELS);ax.invert_yaxis();ax.set_xlim(0,100);ax.set_xticks([0,25,50,75,100]);ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
        ax.set_title(task+'  |  all six: EMPTY_POOL',loc='left',fontsize=11,pad=12)
    for ax in axes[-1]:ax.set_xlabel('Loaded volume / full planned volume (%)')
    fig.suptitle('F1  |  Main synthetic tasks: six methods',fontsize=16,x=.08,ha='left',y=1.01)
    fig.text(.08,-.025,'Labels: volume ratio and committed / planned items. Full order is the denominator.\nAll 24 jobs executed; empty sampled pool does not prove global infeasibility. Same v3 / R2 revision.',fontsize=10)
    fig.tight_layout(h_pad=2.5,w_pad=2)
    save(fig,'F1_main_loading',['main_24_metrics.json'],{'xlim_percent':[0,100],'states':{r['job_id']:r['category'] for r in data}})
    pairs=read('main_16_pairs.json');tasks=sorted({p['task_id'] for p in pairs});comps=['T/none','E/none','E/T','E/unrelated_E']
    matrix=np.array([[next(p['volume_delta_pp'] for p in pairs if p['task_id']==t and p['comparison']==c) for c in comps] for t in tasks]);v=float(np.max(abs(matrix)))
    fig,ax=plt.subplots(figsize=(9,5.4));im=ax.imshow(matrix,cmap='RdBu',vmin=-v,vmax=v,aspect='auto')
    ax.set_xticks(range(4),['T / none','E / none','E / T','E / unrelated E']);ax.set_yticks(range(4),tasks)
    for i in range(4):
        for j in range(4):
            p=next(p for p in pairs if p['task_id']==tasks[i] and p['comparison']==comps[j]);txt=f"{matrix[i,j]:+.2f} pp\n{p['evaluation']['label_v2']}";ax.text(j,i,txt,ha='center',va='center',color='white' if abs(matrix[i,j])>v*.60 else '#182330',fontsize=11)
    fig.colorbar(im,ax=ax,label='Volume ratio difference (percentage points)',pad=.025)
    ax.set_title('F2  |  Alternative minus reference',loc='left',pad=16,fontsize=15)
    fig.text(.08,-.02,'Four task-level observations; observed differences are not confidence intervals.\nZero-centered symmetric scale. Heights, mass and count differences remain in the paired table.',fontsize=10)
    fig.tight_layout();save(fig,'F2_pair_deltas',['main_16_pairs.json'],{'matrix_pp':matrix.tolist(),'color_limits_pp':[-v,v],'comparison_order':comps,'task_order':tasks})
    layouts=read('F3_plot_data.json');fig=plt.figure(figsize=(18,6.8));itemcolors=list(plt.get_cmap('tab20').colors)+list(plt.get_cmap('Set2').colors)
    def boxfaces(z):
        x,y,h=z['pose']['x_mm'],z['pose']['y_mm'],z['pose']['z_base_mm'];l,w,d=z['oriented_size_mm'];x0,x1=x-l/2,x+l/2;y0,y1=y-w/2,y+w/2
        pts=np.array([[x0,y0,h],[x1,y0,h],[x1,y1,h],[x0,y1,h],[x0,y0,h+d],[x1,y0,h+d],[x1,y1,h+d],[x0,y1,h+d]])
        return [[pts[k] for k in face] for face in [[0,1,2,3],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]]
    for i,z in enumerate(layouts):
        ax=fig.add_subplot(1,3,i+1,projection='3d');c=z['container'];L,W,H=c['length_mm'],c['width_mm'],c['max_height_mm']
        for item in z['layout']:
            idx=int(item['item_id'].split('I')[-1])-1;color=itemcolors[idx];ax.add_collection3d(Poly3DCollection(boxfaces(item),facecolors=[color],edgecolors='#27333d',linewidths=.55,alpha=1))
            x,y,h=item['pose']['x_mm'],item['pose']['y_mm'],item['pose']['z_base_mm']+item['oriented_size_mm'][2];ax.text(x,y,h+7,f'{idx+1:02d}',ha='center',va='center',fontsize=7,color='black',bbox={'facecolor':'white','alpha':.75,'pad':.5,'edgecolor':'none'})
        for h in [0,H]:ax.plot([-L/2,L/2,L/2,-L/2,-L/2],[-W/2,-W/2,W/2,W/2,-W/2],[h]*5,color='#8e969d',lw=.65,ls='--')
        for xx in [-L/2,L/2]:
            for yy in [-W/2,W/2]:ax.plot([xx,xx],[yy,yy],[0,H],color='#adb4ba',lw=.6,ls='--')
        ax.set(xlim=(-L/2,L/2),ylim=(-W/2,W/2),zlim=(0,H),xlabel='X (mm)',ylabel='Y (mm)',zlabel='Z (mm)');ax.set_box_aspect([L,W,H]);ax.view_init(elev=26,azim=-58);ax.set_proj_type('ortho');ax.tick_params(labelsize=8);ax.set_zticks([0,400,850])
        m=z['metrics'];ax.set_title(f"{m['method']}  |  {z['job_id']}\n{m['placed_items']}/{m['planned_items']} items; volume {100*m['placed_volume_ratio']:.1f}%\nheight {m['actual_height_mm']:.0f} mm; EMPTY_POOL",fontsize=11,pad=10)
    fig.suptitle('F3  |  SYN_COMBO_03: saved final layouts',fontsize=16,y=1.01)
    fig.text(.10,.02,'Container 1200 x 1000 x 850 mm; identical camera and physical axis proportions. Box color follows item identity (legend I0001-I0024).\nOnly committed boxes are rendered. Lower height with less loading is not an independent improvement; occluded boxes remain in source data.',fontsize=11)
    fig.legend(handles=[Patch(facecolor=itemcolors[i],edgecolor='#27333d',label=f'I{i+1:04d}') for i in range(24)],loc='lower center',bbox_to_anchor=(.5,.095),ncol=12,frameon=False,fontsize=9,columnspacing=1.1)
    fig.subplots_adjust(left=.01,right=.98,bottom=.23,top=.83,wspace=.05)
    save(fig,'F3_saved_layouts',['F3_plot_data.json'],{'view':{'elevation':26,'azimuth':-58,'projection':'orthographic'},'box_aspect':[1200,1000,850],'limits_mm':[[-600,600],[-500,500],[0,850]],'identity_colors':{f'I{i+1:04d}':list(itemcolors[i]) for i in range(24)},'vector_note':'matplotlib projected polygons exported as SVG/PDF; depth occlusion is a display property, originals retain all boxes'})
    f=read('F4_plot_data.json');g=f['gap'];t=f['timeout'];fig,(ax,bx)=plt.subplots(1,2,figsize=(13,5.7),gridspec_kw={'width_ratios':[1.25,1]})
    for z in g['section_boxes']:
        x,h=z['pose']['x_mm'],z['pose']['z_base_mm'];l,w,d=z['oriented_size_mm'];ax.add_patch(Rectangle((x-l/2,h),l,d,facecolor='#bbc8d0',edgecolor='#546472',lw=1));ax.text(x,h+d/2,z['item_id'].split('_')[-1],ha='center',va='center',fontsize=9)
    z=g['candidate'];x,h=z['pose']['x_mm'],z['pose']['z_base_mm'];l,w,d=z['oriented_size_mm'];ax.add_patch(Rectangle((x-l/2,h),l,d,fill=False,edgecolor='#d46034',lw=2,ls='--'))
    ax.add_patch(Rectangle((x-l/2,h+g['height_delta_mm']),l,d,fill=False,edgecolor='#8a5e9e',lw=2,ls=':'))
    ax.annotate('Requested z=0\nNOT COMMITTED',xy=(x,h+d/2),xytext=(230,410),arrowprops={'arrowstyle':'->','color':'#d46034'},color='#a4411d',fontsize=10)
    ax.annotate('Old kernel restored z=490\nnot the requested action',xy=(x,h+g['height_delta_mm']+d/2),xytext=(-60,690),arrowprops={'arrowstyle':'->','color':'#8a5e9e'},color='#694279',fontsize=10)
    ax.set(xlim=(-600,600),ylim=(0,850),xlabel='X (mm)',ylabel='Z (mm)');ax.set_aspect('equal');ax.set_title(f"J0006_D0014 | old v2\nExact section at Y={g['section_y_mm']:.0f} mm",loc='left',fontsize=12);ax.grid(alpha=.13);ax.axhline(0,color='black',lw=1)
    bx.step(range(7),range(7),where='post',color='#3469a4',lw=2,marker='o');bx.scatter([7],[6],marker='x',s=100,color='#c34f3e',zorder=5);bx.plot([6,7],[6,6],ls='--',color='#c34f3e');bx.set(xlim=(-.3,7.6),ylim=(0,20),xlabel='Decisions (saved commit count, then timeout)',ylabel='Committed items / 20 planned');bx.set_xticks(range(8),['start','D0000','D0001','D0002','D0003','D0004','D0005','D0006'],rotation=35);bx.set_yticks([0,6,10,15,20]);bx.grid(alpha=.15)
    bx.set_title('J0011_D0006 | v3 technical timeout',loc='left',fontsize=12)
    bx.text(.05,.87,'A000057  |  UNKNOWN_SEND\n30.023 s; outcome remains unknown\n6/20 committed before and after\nNo selection, monitor or new commit\nE / unrelated E: invalid, not ranked',transform=bx.transAxes,va='top',linespacing=1.7,fontsize=11,bbox={'facecolor':'#f5f6f7','edgecolor':'#d4d9dd','pad':9})
    fig.suptitle('F4  |  Historical range stop and technical failure',fontsize=16,y=1.01)
    fig.text(.06,-.06,'Left: UNASSESSABLE / POSE_HEIGHT_MISMATCH; baseline STABLE, 14/20 committed. Dashed outlines are uncommitted diagnostic poses.\nRight: SELECTION_FAILURE / UNKNOWN_IN_FLIGHT; no refund or retry. Neither panel demonstrates physical collapse.',fontsize=10)
    fig.tight_layout(w_pad=3);save(fig,'F4_historical_failures',['F4_plot_data.json'],{'section_y_mm':g['section_y_mm'],'candidate_actual_z_mm':h,'kernel_restored_z_mm':h+g['height_delta_mm'],'timeout_progress':[6,6],'timeout_planned_items':20})
    (b/'figure_manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    print('F1-F4 written as PNG / SVG / PDF from saved analysis data.')
if __name__=='__main__':main()
