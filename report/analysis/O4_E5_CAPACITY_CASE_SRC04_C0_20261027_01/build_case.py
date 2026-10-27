"""Saved-trajectory visualization only. No planner or API imports."""
import base64
import hashlib
import json
import math
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Rectangle
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
EVIDENCE=ROOT/'report/analysis/O4_E5_CAPACITY_NEXT_20261027_01'
rows=json.loads((EVIDENCE/'main_rows.json').read_text())
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':'Noto Sans CJK JP','axes.unicode_minus':False,'font.size':11})
COLORS=['#3685ba','#ed9b40','#58aa8e','#9a82c4','#da7182','#8db657','#ad8261','#5ba9b4','#bc93c5','#dcba50','#899ab8','#14a36f']


def color(obj):return COLORS[int(obj['item_id'].split('_')[-1])-1]


def vertices(o):
    p=o['pose'];dx,dy,dz=o['oriented_size_mm'];x,y,z=p['x_mm']-dx/2,p['y_mm']-dy/2,p['z_base_mm']
    return [(x,y,z),(x+dx,y,z),(x+dx,y+dy,z),(x,y+dy,z),(x,y,z+dz),(x+dx,y,z+dz),(x+dx,y+dy,z+dz),(x,y+dy,z+dz)]


payload=[];hashes={}
for group,label in [('A','原版 A'),('F','改进 B0')]:
    row=next(r for r in rows if (r['task_id'],r['method'],r['group'])==('E5_SRC04_C0','buffer_search',group))
    path=ROOT/row['record_path'];raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==row['sha256']
    hashes[row['record_path']]=row['sha256'];result=json.loads(raw)
    decisions=[(i,e) for i,e in enumerate(result['events']) if 'search_trace'in e]
    steps=[{'state':decisions[0][1]['before'],'event':'开始','action':None,'event_index':None,'trace':None}]
    for i,e in decisions:
        action=next((c for c in e['candidates'] if e.get('action') and c['candidate_id']==e['action']['candidate_id']),None)
        steps.append({'state':e['after'],'event':e['event'],'action':action,'event_index':i,'trace':e['search_trace'],
                      'request':e['request'],'AST':e['response']['policy_ast'],'diagnostics':e['diagnostics']})
    payload.append({'group':group,'label':label,'summary':result['summary'],'source':row['record_path'],'steps':steps})
assert len(payload[0]['steps'])==len(payload[1]['steps'])==13
assert payload[0]['steps'][2]['request']==payload[1]['steps'][2]['request']
total_volume=sum(math.prod(o['oriented_size_mm']) for o in payload[1]['steps'][-1]['state']['placed_items'])

fig=plt.figure(figsize=(14,12),facecolor='#fafbfc')
fig.suptitle('同一订单：原版停在11箱，B0装完12箱',fontsize=23,fontweight='bold',y=.98)
fig.text(.5,.935,'00102371 / C0 · 三箱缓冲搜索 · 相同订单、业务规则与16/48/3/8/256预算',ha='center',fontsize=12,color='#526071')
for index,record in enumerate(payload):
    state=record['steps'][-1]['state'];s=record['summary'];ax=fig.add_subplot(2,2,index+1,projection='3d')
    for o in state['placed_items']:
        v=vertices(o);faces=[[v[j] for j in f] for f in [(0,1,2,3),(4,5,6,7),(0,1,5,4),(2,3,7,6),(1,2,6,5),(0,3,7,4)]]
        ax.add_collection3d(Poly3DCollection(faces,facecolors=color(o),edgecolors='#263442',linewidths=.7,alpha=.78))
        p=o['pose'];ax.text(p['x_mm'],p['y_mm'],p['z_base_mm']+o['oriented_size_mm'][2]+8,o['item_id'].split('_')[-1],fontsize=10,color='#19242d')
    ax.set(xlim=(-600,600),ylim=(-500,500),zlim=(0,850),xlabel='x / mm',ylabel='y / mm',zlabel='高度 / mm')
    ax.view_init(elev=27,azim=-57);ax.set_box_aspect((1200,1000,850))
    if index==1:ax.text2D(.05,.92,'绿色12号：新增实际装入',transform=ax.transAxes,color='#128052',fontsize=12,fontweight='bold')
    ax.set_title(f'{record["label"]}：{s["placed_items"]}/12箱\n订单体积完成 {s["placed_volume_ratio"]:.2%} · '+('整单完成' if s['clean_completed'] else '12号箱未装入'),pad=16,fontweight='bold')
    bottom=fig.add_subplot(2,2,index+3);bottom.set_aspect('equal')
    bottom.add_patch(Rectangle((-600,-500),1200,1000,facecolor='white',edgecolor='#43536a',lw=1.5))
    for o in record['steps'][2]['state']['placed_items']:
        p=o['pose'];dx,dy,_=o['oriented_size_mm'];bottom.add_patch(Rectangle((p['x_mm']-dx/2,p['y_mm']-dy/2),dx,dy,facecolor=color(o),edgecolor='#233242',lw=2,alpha=.8))
        bottom.text(p['x_mm'],p['y_mm'],o['item_id'].split('_')[-1],ha='center',va='center',fontsize=15,fontweight='bold')
    c=record['steps'][2]['action'];p=c['pose']
    bottom.set(xlim=(-630,630),ylim=(-530,530),xlabel='x / mm',ylabel='y / mm')
    bottom.set_title(f'第二次实际决策：02号箱\n中心 ({p["x_mm"]:g}, {p["y_mm"]:g}) mm，朝向 {p["yaw_deg"]}°',pad=10)
    bottom.grid(alpha=.15)
fig.text(.5,.035,'上排：真实终态三维布局；下排：共同状态下的第二次实际选位。颜色与编号在两版本间一致，绿色12号仅在B0中真实装入。',ha='center',fontsize=10,color='#526071')
fig.text(.5,.012,'这是成功代表例，并非平均提升：24任务搜索整体体积 +1.49个百分点；SRC10/C0、C1各少1箱。原版仍默认。',ha='center',fontsize=10,color='#526071')
fig.subplots_adjust(top=.86,bottom=.09,hspace=.28,wspace=.12);fig.savefig(HERE/'comparison.png',dpi=170,bbox_inches='tight');plt.close(fig)

data=json.dumps({'records':payload,'total_volume':total_volume,'colors':COLORS},ensure_ascii=False).replace('</','<\\/')
image_data=base64.b64encode((HERE/'comparison.png').read_bytes()).decode()
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>11箱 → 12箱｜B0代表案例</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f4f6f9;color:#233142;font:16px system-ui,"Noto Sans CJK SC",sans-serif}main{max-width:1320px;margin:auto;padding:30px}h1{font-size:32px;margin:8px 0}h2{font-size:21px}p{line-height:1.7}.muted{color:#627185}.badge{display:inline-block;background:#e4f5ec;color:#16724d;padding:6px 12px;border-radius:20px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.card,.controls,details{background:white;border:1px solid #dfe5ec;border-radius:14px;padding:18px;margin:16px 0}.metrics{font-size:23px;font-weight:700}.metrics small{font-size:14px;font-weight:400}.card canvas{width:100%;height:430px;touch-action:none;cursor:grab}input[type=range]{width:min(55vw,620px)}button{background:#edf3fa;border:1px solid #ccd8e5;border-radius:7px;padding:8px 13px;cursor:pointer;margin:5px}button.primary{background:#1675b5;color:white}pre{white-space:pre-wrap;overflow:auto;max-height:460px;font-size:13px}img{width:100%;border-radius:12px}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #e4e9ef;padding:10px;text-align:left}.note{border-left:4px solid #dda841;padding:8px 16px;background:#fff8e8}@media(max-width:800px){main{padding:16px}.grid{grid-template-columns:1fr}.card canvas{height:350px}}</style>
<main><div class="badge">只读已有真实轨迹 · 未重跑规划 · API 0</div><h1>一箱之差：从“12号箱装不下”到整单完成</h1>
<p class="muted">订单 00102371 / C0（SRC04）｜12箱｜1200 × 1000 × 850 mm托盘｜三箱缓冲搜索</p>
<p>相同到货顺序、业务规则和计算预算。B0仅改变公开候选保留，位置与搜索规则沿用原版。下面所有箱体均来自实际提交，没有绘制未执行的假设路径。</p>
<div class="controls"><strong id="stepLabel"></strong><br><button id="previous">上一步</button><input id="step" type="range" min="0" max="12" value="12"><button id="next">下一步</button><br><button id="start">看首箱</button><button class="primary" id="key">看关键第二步</button><button id="end">看最终结果</button><button id="reset">重置视角</button><span class="muted">拖动任一图可同步旋转两侧，编号/颜色对应同一箱。</span></div>
<section class="grid"><article class="card"><h2>原版 A</h2><div class="metrics" id="metric0"></div><canvas id="c0"></canvas><p id="action0"></p></article><article class="card"><h2>改进 B0</h2><div class="metrics" id="metric1"></div><canvas id="c1"></canvas><p id="action1"></p></article></section>
<p class="muted">“订单体积完成”＝已装箱体积 ÷ 这12箱的总体积，并非托盘空间填充率。第N步表示第N次规划决策；第12步原版STOP，B0实际放入12号。</p>
<section class="card"><h2>为什么选这个案例？</h2><table><tr><th>结果</th><th>原版 A</th><th>B0</th></tr><tr><td>实际装入</td><td>11 / 12箱</td><td>12 / 12箱</td></tr><tr><td>订单体积完成</td><td>89.94%</td><td>100.00%</td></tr><tr><td>实际业务违规</td><td>0</td><td>0</td></tr><tr><td>末次动作</td><td>STOP，12号仍待装</td><td>PLACE，装入12号</td></tr></table>
<p>首箱相同；第二次决策的公共状态也相同。原版把02号放在 <b>(−500, −75)</b>，B0放在 <b>(−500, 0)</b>。B0所选点在原版根候选中也存在且eligible，因此不能简单解释为“多生成了这个根点”。固定状态诊断显示，候选保留改变了其他根候选与后继候选、beam竞争和深层预算暴露。</p>
<p>原版最终布局中，12号箱的完整物理采样池有48个点，但业务允许0；B0另一布局下完整采样池有116个点、业务允许9，最终Top-K有1个允许动作并实际提交。这是不同布局的终点观察，不是同一状态下的全局无解证明，也不是首个分歧的唯一整单因果证明。</p>
<p><b>共同预算：</b>每箱16候选、根联合48、深度3、beam 8、逻辑评价256。不是靠扩大预算装入额外一箱。</p></section>
<details><summary>查看当前两侧决策的公共输入、AST、实际动作、搜索预算与STOP证据</summary><pre id="details"></pre></details>
<details><summary>业务约束与原始记录出处</summary><p>累计顶部限载按标签；禁压覆盖限载规则；食品与清洁用品禁止直接面接触；食品底面必须完全位于L区、清洁用品位于R区。优先级、区域、载荷和支撑沿用原规则。两组AST相同，完整文本见当前决策详情。</p><pre id="sources"></pre></details>
<h2>可下载的静态对比图</h2><img alt="真实终态与关键第二步对照" src="data:image/png;base64,IMAGE">
<p class="note"><b>代表范围：</b>这是能清楚展示“从未完成到整单完成”的成功例，不是24任务平均水平。总体搜索为195→197箱、平均订单体积比例+1.49个百分点；single持平。SRC10/C0、C1各少1箱，负例保留待查。原版仍保持默认。</p></main>
<script type="application/json" id="payload">PAYLOAD</script><script>
const D=JSON.parse(document.getElementById('payload').textContent),slider=document.getElementById('step');let yaw=-.65,pitch=.56,drag=null;
function project(v,w,h){const a=Math.cos(yaw)*v[0]-Math.sin(yaw)*v[1],b=Math.sin(yaw)*v[0]+Math.cos(yaw)*v[1],z=v[2]-180,s=Math.min(w/1780,h/1200);return [w/2+a*s,h*.54-(Math.cos(pitch)*z-Math.sin(pitch)*b)*s,Math.cos(pitch)*b+Math.sin(pitch)*z]}
function draw(index){const canvas=document.getElementById('c'+index),w=canvas.clientWidth||580,h=canvas.clientHeight||430,ratio=window.devicePixelRatio||1;canvas.width=w*ratio;canvas.height=h*ratio;const c=canvas.getContext('2d');c.scale(ratio,ratio);c.clearRect(0,0,w,h);const step=D.records[index].steps[Number(slider.value)],placed=step.state.placed_items;
function line(points,color){c.beginPath();points.map(p=>project(p,w,h)).forEach((p,i)=>i?c.lineTo(p[0],p[1]):c.moveTo(p[0],p[1]));c.strokeStyle=color;c.lineWidth=1;c.stroke()}
for(let x=-600;x<=600;x+=200)line([[x,-500,0],[x,500,0]],'#e1e7ed');for(let y=-500;y<=500;y+=200)line([[-600,y,0],[600,y,0]],'#e1e7ed');line([[-600,-500,0],[600,-500,0],[600,500,0],[-600,500,0],[-600,-500,0]],'#8194a9');line([[-600,-500,0],[-600,-500,850]],'#a3afbb');
const faces=[],labels=[];placed.forEach(o=>{const p=o.pose,sz=o.oriented_size_mm,x=p.x_mm-sz[0]/2,y=p.y_mm-sz[1]/2,z=p.z_base_mm,v=[[x,y,z],[x+sz[0],y,z],[x+sz[0],y+sz[1],z],[x,y+sz[1],z],[x,y,z+sz[2]],[x+sz[0],y,z+sz[2]],[x+sz[0],y+sz[1],z+sz[2]],[x,y+sz[1],z+sz[2]]].map(q=>project(q,w,h)),id=Number(o.item_id.split('_')[1]);[[0,1,2,3],[4,5,6,7],[0,1,5,4],[2,3,7,6],[1,2,6,5],[0,3,7,4]].forEach(f=>faces.push({v:f.map(j=>v[j]),depth:f.reduce((a,j)=>a+v[j][2],0)/4,color:D.colors[id-1]}));labels.push({p:project([p.x_mm,p.y_mm,z+sz[2]+10],w,h),id})});faces.sort((a,b)=>a.depth-b.depth).forEach(f=>{c.beginPath();f.v.forEach((p,i)=>i?c.lineTo(p[0],p[1]):c.moveTo(p[0],p[1]));c.closePath();c.fillStyle=f.color;c.globalAlpha=.94;c.fill();c.globalAlpha=1;c.strokeStyle='#344454';c.lineWidth=.8;c.stroke()});labels.forEach(l=>{c.font='bold 13px system-ui';c.textAlign='center';c.fillStyle='#17212b';c.strokeStyle='#ffffff';c.lineWidth=3;c.strokeText(String(l.id).padStart(2,'0'),l.p[0],l.p[1]);c.fillText(String(l.id).padStart(2,'0'),l.p[0],l.p[1])});
const volume=placed.reduce((a,o)=>a+o.oriented_size_mm.reduce((x,y)=>x*y,1),0);document.getElementById('metric'+index).textContent=placed.length+' / 12 箱 · 订单体积 '+(100*volume/D.total_volume).toFixed(2)+'%';const a=step.action;document.getElementById('action'+index).textContent=a?'实际放入 '+a.pick_item_id+'，中心('+a.pose.x_mm+', '+a.pose.y_mm+')，底高 '+a.pose.z_base_mm+' mm，朝向 '+a.pose.yaw_deg+'°':step.event==='STOP'?'STOP：当前已形成布局中无编译业务允许动作，12号未装入。':'开始：3箱已到货，尚未放置。'}
function update(){const k=Number(slider.value);document.getElementById('stepLabel').textContent=k===0?'开始状态':'第 '+k+' 次决策'+(k===2?'：首个实际分歧':k===12?'：最终对比':'');draw(0);draw(1);document.getElementById('details').textContent=JSON.stringify(D.records.map(r=>({版本:r.label,决策:r.steps[k]})),null,2)}
slider.oninput=update;document.getElementById('previous').onclick=()=>{slider.value=Math.max(0,Number(slider.value)-1);update()};document.getElementById('next').onclick=()=>{slider.value=Math.min(12,Number(slider.value)+1);update()};for(const [id,k] of [['start',1],['key',2],['end',12]])document.getElementById(id).onclick=()=>{slider.value=k;update()};document.getElementById('reset').onclick=()=>{yaw=-.65;pitch=.56;update()};
for(let i=0;i<2;i++){const canvas=document.getElementById('c'+i);canvas.onpointerdown=e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId)};canvas.onpointermove=e=>{if(!drag)return;yaw+=(e.clientX-drag[0])*.008;pitch=Math.max(.12,Math.min(1.35,pitch+(e.clientY-drag[1])*.006));drag=[e.clientX,e.clientY];draw(0);draw(1)};canvas.onpointerup=()=>drag=null;canvas.onpointercancel=()=>drag=null}
document.getElementById('sources').textContent=D.records.map(r=>r.label+String.fromCharCode(10)+r.source).join(String.fromCharCode(10,10));window.onresize=update;update();
</script></html>'''.replace('IMAGE',image_data).replace('PAYLOAD',data)
with (HERE/'case.html').open('w') as f:f.write(page)
with (HERE/'case_data.json').open('w') as f:json.dump({'records':payload,'total_volume':total_volume},f,ensure_ascii=False,indent=2)
with (HERE/'manifest.json').open('w') as f:json.dump({'case':'E5_SRC04_C0','selection':'successful completion case with existing T0 mechanism evidence, not average case','source_sha256':hashes,'new_planning_runs':0,'new_api_attempts':0,'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE/'comparison.png',HERE/'case.html',HERE/'case_data.json',Path(__file__)]}},f,ensure_ascii=False,indent=2)
print('Saved-only case visualization generated:',HERE)
