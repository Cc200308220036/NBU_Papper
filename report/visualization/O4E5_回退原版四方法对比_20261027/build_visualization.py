"""Read saved four-method episodes; create UI and still figure. No planner/API."""
from pathlib import Path
import json,math,hashlib,os
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
EXP=ROOT/'semantic_pallet_planner/outputs/EXP_O4_E5_ROLLBACK_SMOKE_20261027_01'
METHODS=['single','buffer_fifo','buffer_heuristic','buffer_search']
NAMES={'single':'单箱','buffer_fifo':'FIFO缓冲','buffer_heuristic':'启发式缓冲','buffer_search':'搜索缓冲'}
def read(p):return json.loads(p.read_text())
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
tasks=read(EXP/'private/tasks.json');task=next(t for t in tasks if t['task_id']=='E5_SRC00_C0')
methods=[];proof={}
for method in METHODS:
    path=EXP/'episodes'/f'E5_SRC00_C0_public_parser_{method}.json';proof[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest();r=read(path)
    decisions=[e for e in r['events'] if 'groups' in e];last=decisions[-1]
    def pack(e):
        return {'state':e['after'],'event':e['event'],'request':e['request'],'response':e['response'],'action':e['action'],
                'candidates':e['candidates'],'reference':e['reference_evaluation'],'reference_after':e['reference_after'],'diagnostics':e['diagnostics'],'reason':e['reason']}
    frames=[{'state':r['events'][0]['before'],'event':'INITIAL','request':None,'response':None,'action':None,'candidates':[],'reason':None}]
    frames.extend(pack(e) for e in decisions if e['event']=='PLACE')
    final=pack(last);final['state']=r['final_state']
    c=r['final_state']['container'];vol=sum(math.prod(b['oriented_size_mm']) for b in r['final_state']['placed_items'])
    metrics={**r['summary'],'pallet_volume_utilization':vol/(c['length_mm']*c['width_mm']*c['max_height_mm']),
             'stacked_items':[b['item_id'] for b in r['final_state']['placed_items'] if b['pose']['z_base_mm']>0],
             'max_height_mm':max(b['pose']['z_base_mm']+b['oriented_size_mm'][2] for b in r['final_state']['placed_items'])}
    methods.append({'id':method,'name':NAMES[method],'frames':frames,'final':final,'metrics':metrics,
                    'sequence':[next(c['pick_item_id'] for c in e['candidates'] if c['candidate_id']==e['action']['candidate_id']) for e in decisions if e['action']]})
assert [m['metrics']['placed_items'] for m in methods]==[8,8,7,8]
assert all(m['metrics']['violating_steps']==0 for m in methods)
payload={'source':str(EXP.relative_to(ROOT)),'acceptance':read(EXP/'acceptance_report.json'),'task':task,'methods':methods,'source_hashes':proof,'new_api_attempts':0,'new_episode_runs':0}
write(OUT/'case_data.json',payload)
(OUT/'index.html').write_text((OUT/'template.html').read_text().replace('__DATA__',json.dumps(payload,ensure_ascii=False).replace('</','<\\/')))
# Standalone export: true top view and 3D, all methods on equal scales.
os.environ.setdefault('MPLCONFIGDIR','/tmp/e5-rollback-plot')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import patches,font_manager
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc');plt.rcParams.update({'font.family':'Noto Sans CJK JP','axes.unicode_minus':False,'font.size':10})
colors={'general':'#718eb8','glassware':'#c4a05c','household_cleaner':'#c4789d','food':'#369c7b','electronics':'#8979b6'}
fig=plt.figure(figsize=(20,12),facecolor='#f5f7fb');fig.suptitle('回退原版E5：订单00101152 / C0 · 四方法真实结果',fontsize=23,y=.975)
fig.text(.5,.933,'Parser本地实验，无VLM/API；4条均执行PASS，但整单均未完成。上排俯视，下排三维；编号↑表示实际叠放。',ha='center',fontsize=13,color='#4f617a')
gs=fig.add_gridspec(2,4,left=.04,right=.985,bottom=.12,top=.875,wspace=.22,hspace=.22)
for i,m in enumerate(methods):
    s=m['final']['state'];bxs=s['placed_items'];attrs=s['attributes'];me=m['metrics'];a=fig.add_subplot(gs[0,i]);a.set_title(f'{m["name"]}｜{me["placed_items"]}/12箱\n订单体积{me["placed_volume_ratio"]:.2%} · 托盘体积{me["pallet_volume_utilization"]:.2%}',fontsize=13,pad=13)
    a.add_patch(patches.Rectangle((-600,-500),300,1000,facecolor='#fde8ed'));a.add_patch(patches.Rectangle((-300,-500),900,1000,facecolor='#e8f4ef'));a.axvline(-300,c='#c4789d',ls='--',lw=1)
    for b in bxs:
        dx,dy,dz=b['oriented_size_mm'];p=b['pose'];id=b['item_id'];upper=p['z_base_mm']>0
        a.add_patch(patches.Rectangle((p['x_mm']-dx/2,p['y_mm']-dy/2),dx,dy,facecolor=colors[attrs[id]['cargo_category']],edgecolor='#20364e' if upper else 'white',linewidth=2,hatch='//' if upper else None,alpha=.82 if upper else 1))
        a.text(p['x_mm'],p['y_mm'],id[-2:]+('↑' if upper else ''),ha='center',va='center',color='white' if not upper else '#142b42',fontweight='bold',fontsize=11)
    a.set(xlim=(-620,620),ylim=(-520,520),xlabel='x (mm)',ylabel='y (mm)');a.set_aspect('equal')
    ax=fig.add_subplot(gs[1,i],projection='3d')
    for b in bxs:
        dx,dy,dz=b['oriented_size_mm'];p=b['pose'];x=p['x_mm']-dx/2;y=p['y_mm']-dy/2;z=p['z_base_mm'];v=[(x,y,z),(x+dx,y,z),(x+dx,y+dy,z),(x,y+dy,z),(x,y,z+dz),(x+dx,y,z+dz),(x+dx,y+dy,z+dz),(x,y+dy,z+dz)]
        faces=[[v[k] for k in f] for f in [(0,1,2,3),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7),(4,5,6,7)]]
        ax.add_collection3d(Poly3DCollection(faces,facecolors=colors[attrs[b['item_id']]['cargo_category']],edgecolors='white',linewidths=.8,alpha=.9));ax.text(p['x_mm'],p['y_mm'],z+dz+8,b['item_id'][-2:],ha='center',fontsize=9)
    ax.set(xlim=(-600,600),ylim=(-500,500),zlim=(0,850),xlabel='x',ylabel='y',zlabel='z mm');ax.set_box_aspect((1.2,1,.85));ax.view_init(28,-55)
    ax.set_title(f'待码：{", ".join(x[-2:] for x in me["pending_ids"])}\n未到达：{", ".join(x[-2:] for x in me["unarrived_ids"])}',fontsize=11,pad=5)
fig.text(.5,.067,'粉色箱＝清洁用品，底面必须在R区（x≥-300mm）；浅红底带为清洁用品禁入区。蓝色普通货物、金色玻璃、紫色电子产品。',ha='center',fontsize=12,color='#526278')
fig.text(.5,.035,'各方法最终STOP均为“无业务可行候选”，不是无物理采样点；搜索改变了箱体选择顺序。此图仅描述该订单，不代表方法普遍优劣。',ha='center',fontsize=12,color='#526278')
fig.savefig(OUT/'overview.png',dpi=150,facecolor=fig.get_facecolor());plt.close(fig)
write(OUT/'metrics.json',[{'method':m['id'],'name':m['name'],**m['metrics']} for m in methods])
print('Created four-method HTML, PNG and data; no API or episode execution.')
