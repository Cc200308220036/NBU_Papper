"""Create a read-only case visualization from saved E5 records. No experiment replay."""
from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
EXP=ROOT/'semantic_pallet_planner/outputs/EXP_O4_E5_090_REAL_20261026_01'
JOB='E5_SRC02_C0_remote_text_single'
def read(p):return json.loads(p.read_text())
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
episode=read(EXP/'episodes'/f'{JOB}.json');events=[e for e in episode['events'] if 'compilation_metrics' in e];last=events[-1]
task=next(t for t in read(EXP/'private/tasks.json') if t['task_id']=='E5_SRC02_C0')
failures=read(EXP/'metrics/failure_attribution.json')
cohort=sorted([f for f in failures if '_remote_text_single' in f['job_id']],key=lambda f:(f['placed_items']/f['planned_items'],f['job_id']))
assert cohort[len(cohort)//2]['job_id']==JOB
assert all(e['compilation_metrics']['semantic_equal'] for e in events)
assert all(e['compilation']['first_valid'] for e in events)
evaluations={v['candidate_id']:v for v in last['reference_evaluation']['evaluations']}
cs=[]
for c in last['candidates']:
 v=evaluations[c['candidate_id']];cs.append({**c,'violations':v['new_violations'],'loads_kg':v['after']['loads_kg'],'limits_kg':v['after']['limits_kg']})
assert len(cs)==16 and all(any(x.startswith('load:') for x in c['violations']) for c in cs)
placed=last['request']['placed_objects'];limits=last['reference_evaluation']['evaluations'][0]['before']['limits_kg']
volume=sum(x['oriented_size_mm'][0]*x['oriented_size_mm'][1]*x['oriented_size_mm'][2] for x in placed)
area=sum(x['oriented_size_mm'][0]*x['oriented_size_mm'][1] for x in placed)
assert all(x['pose']['z_base_mm']==0 for x in placed)
metrics={'source_order_key':task['source_order_key'],'job_id':JOB,'selection':'Upper median of all 24 remote_text/single placed-item ratios, stable job-ID tie break; dominant termination category (184/240).','placed_items':6,'planned_items':12,'placed_item_ratio':0.5,'fulfilled_order_volume_ratio':episode['summary']['placed_volume_ratio'],'pallet_volume_utilization':volume/(1200*1000*850),'floor_area_utilization':area/(1200*1000),'max_height_mm':max(x['oriented_size_mm'][2] for x in placed),'arrived':7,'pending':1,'unarrived':5,'compile_decisions':7,'first_valid':7,'semantic_equal':7,'real_api_attempts':sum(len(e['compilation']['attempt_ids']) for e in events),'physical_sampled':last['diagnostics']['groups'][0]['sampled_physical_candidates'],'topk':len(cs),'topk_allowed':len(last['reference_evaluation']['allowed_ids']),'sampled_allowed':last['diagnostics']['groups'][0]['reference_sampled_allowed'],'load_rejected_candidates':16,'region_rejected_candidates':sum(any(v.startswith('region:') for v in c['violations']) for c in cs),'violating_commits':0,'sum_effective_top_capacity_kg':sum(limits.values()),'pending_mass_kg':3.1,'termination':episode['summary']['termination_reason']}
comparisons=[]
for method in ['single','buffer_fifo','buffer_heuristic','buffer_search']:
 d=read(EXP/'episodes'/f'E5_SRC02_C0_remote_text_{method}.json')['summary'];comparisons.append({k:d[k] for k in ['planner','placed_items','planned_items','completed','placed_volume_ratio','termination_reason']})
ledger=read(EXP/'audit/ledger.json');attempts=[a for a in ledger['attempts'] if a['job_id']==JOB];assert len(attempts)==7
write(OUT/'metrics.json',metrics);write(OUT/'last_input.json',last['request']);write(OUT/'last_output.json',last['response']);write(OUT/'last_candidates.json',cs);write(OUT/'order_snapshot.json',task)
(OUT/'last_output_raw.txt').write_text(attempts[-1]['raw_text'])
frames=[{'title':'初始空托盘','placed':[],'event':None}]+[{'title':f'放入第{i+1}箱' if e['event']=='PLACE' else '第7箱到达：STOP','placed':[],'event':e} for i,e in enumerate(events)]
# The request of the following decision holds the exact committed public box list.
for i,e in enumerate(events):
 frames[i+1]['placed']=events[min(i+1,len(events)-1)]['request']['placed_objects']
frames[0]['placed']=[]
payload={'metrics':metrics,'frames':frames,'candidates':cs,'limits':limits,'task':task,'comparison':comparisons,'raw_final':attempts[-1]['raw_text'],'global_stops':{'无业务候选':184,'FIFO队首阻塞':24,'无物理候选':16,'全部放完':16}}
write(OUT/'case_data.json',payload)
inputs=[EXP/'episodes'/f'{JOB}.json',EXP/'metrics/failure_attribution.json',EXP/'metrics/summary.json',EXP/'private/tasks.json',EXP/'responses'/JOB/'D0006.json']
write(OUT/'provenance.json',{'case':JOB,'analysis_only':True,'new_api_attempts':0,'episode_replays':0,'inputs':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}})
html=Path(__file__).with_name('template.html').read_text().replace('__CASE_DATA__',json.dumps(payload,ensure_ascii=False).replace('</','<\\/'))
(OUT/'index.html').write_text(html)
# Publication/shareable still image, with the same actual geometry and a rejected ghost candidate.
import os
os.environ.setdefault('MPLCONFIGDIR','/tmp/e5_case_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager,patches
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':'Noto Sans CJK JP','axes.unicode_minus':False,'font.size':11})
fig=plt.figure(figsize=(16,10),facecolor='#f5f7fc');fig.suptitle('为什么只放下6/12箱？｜真实订单00102047 · Text / single',fontsize=22,fontweight='bold',y=.97)
fig.text(.5,.925,'中位数案例：模型7/7次解析正确；第7箱没有业务可行候选，停止而未违规提交',ha='center',fontsize=13,color='#526074')
gs=fig.add_gridspec(2,2,left=.055,right=.97,bottom=.075,top=.87,hspace=.38,wspace=.23,height_ratios=[1.2,1])
ax=fig.add_subplot(gs[0,0]);ax.set_title('A 真实停止布局 · 食品必须完全位于F区',loc='left',fontweight='bold')
ax.add_patch(patches.Rectangle((-600,-500),1200,750,facecolor='#e7f5ee',edgecolor='none'))
ax.add_patch(patches.Rectangle((-600,250),1200,250,facecolor='#ffe8e7',edgecolor='none'));ax.axhline(250,c='#e56464',ls='--')
colors={'food':'#32a17a','general':'#7290bc','glassware':'#c19b4f'}
for x in placed:
 dx,dy,dz=x['oriented_size_mm'];xx=x['pose']['x_mm'];yy=x['pose']['y_mm'];oid=x['object_id'];ax.add_patch(patches.Rectangle((xx-dx/2,yy-dy/2),dx,dy,facecolor=colors[x['cargo_category']],edgecolor='white',lw=2));ax.text(xx,yy,f"{oid[-2:]}\n顶部≤{limits[oid]:g}kg",ha='center',va='center',fontsize=10,color='white')
ax.set(xlim=(-620,620),ylim=(-520,520),xlabel='x (mm)',ylabel='y (mm)');ax.set_aspect('equal');ax.text(-580,455,'食品禁入带（y > 250）',color='#b54747',fontsize=10)
ax2=fig.add_subplot(gs[0,1],projection='3d');ax2.set_title('B 拒绝候选示例 · 区域合规仍违反禁压',loc='left',fontweight='bold')
def cuboid(ax,x,color,alpha=1):
 dx,dy,dz=x['oriented_size_mm'];p=x['pose'];xx=p['x_mm']-dx/2;yy=p['y_mm']-dy/2;z=p['z_base_mm'];vs=[(xx,yy,z),(xx+dx,yy,z),(xx+dx,yy+dy,z),(xx,yy+dy,z),(xx,yy,z+dz),(xx+dx,yy,z+dz),(xx+dx,yy+dy,z+dz),(xx,yy+dy,z+dz)];faces=[[vs[i] for i in f] for f in [(0,1,2,3),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7),(4,5,6,7)]];ax.add_collection3d(Poly3DCollection(faces,facecolors=color,edgecolors='white' if alpha==1 else '#d94350',alpha=alpha,linewidths=.8));return p['x_mm'],p['y_mm'],z+dz
for x in placed:
 xyz=cuboid(ax2,x,colors[x['cargo_category']]);ax2.text(*xyz,x['object_id'][-2:],ha='center',color='#20304e')
c=cs[2];xyz=cuboid(ax2,c,'#ef6f77',.3);ax2.text(*xyz,'07（未提交）',color='#b12937',fontsize=10)
ax2.set(xlim=(-600,600),ylim=(-500,500),zlim=(0,850),xlabel='x',ylabel='y',zlabel='z (mm)');ax2.view_init(27,-58);ax2.set_box_aspect((1.2,1,.85))
ax3=fig.add_subplot(gs[1,0]);ax3.axis('off');ax3.set_title('C 输入 → 输出 → 停止原因',loc='left',fontweight='bold')
text='输入：第7箱为食品，580×200×170mm，3.1kg\n规则：食品底面必须在F区；禁压覆盖标签限载\nVLM输出：6条规则AST正确，未输出放置坐标\n\n33个采样物理候选 → 16个Top-K → 0个业务允许\n16/16触发限载；其中12/16还违反食品区域\n示例C03：放在04箱上，区域合规，但3.1kg > 0kg\n示例C13：放在05箱上，区域合规，但3.1kg > 2kg'
ax3.text(0,.92,text,va='top',linespacing=1.7,fontsize=12,color='#23334b')
ax4=fig.add_subplot(gs[1,1]);ax4.axis('off');ax4.set_title('D 指标：解析正确 ≠ 整单装满',loc='left',fontweight='bold')
text=f'已放箱数：6/12（50.00%）   违规提交：0\n已放订单体积 / 全订单体积：52.73%\n箱体体积 / 托盘可用体积：{metrics["pallet_volume_utilization"]:.2%}\n底面积占用：{metrics["floor_area_utilization"]:.2%}   最高箱顶：280/850mm\n\n底层6箱有效顶部限载：0+0+0+0+2+1 = 3.0kg\n若完全由这些箱承托，第7箱3.1kg已超出合计上限\n低限载压缩了堆叠空间；当前底层又缺少合适落点\n此处未证明更早换布局或连续空间全局无解。'
ax4.text(0,.92,text,va='top',linespacing=1.7,fontsize=12,color='#23334b')
fig.text(.055,.025,'证据：EXP_O4_E5_090_REAL_20261026_01 / E5_SRC02_C0_remote_text_single；红色候选为被拒绝的假设位置，不是实际放置。',fontsize=10,color='#64718a')
fig.savefig(OUT/'overview.png',dpi=160,facecolor=fig.get_facecolor());fig.savefig(OUT/'overview.pdf',facecolor=fig.get_facecolor());plt.close(fig)
print(json.dumps(metrics,ensure_ascii=False,indent=2))
