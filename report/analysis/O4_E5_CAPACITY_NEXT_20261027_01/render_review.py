"""Local standalone review, actual submissions separated from search hypotheses."""
import html
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[2]; OUT=ROOT/'semantic_pallet_planner/outputs'


def read(p):return json.loads(p.read_text())


rows=read(HERE/'main_rows.json'); pairs=read(HERE/'main_pairs.json'); audit=read(HERE/'main_audit.json')
representatives=[]
for task,method in [('E5_SRC00_C0','single'),('E5_SRC04_C0','buffer_search')]:
    for group in ('A','F'):
        row=next(r for r in rows if r['task_id']==task and r['method']==method and r['group']==group)
        result=read(ROOT/row['record_path']); representatives.append((row,result))
fig=plt.figure(figsize=(14,10))
for index,(row,result) in enumerate(representatives):
    ax=fig.add_subplot(2,2,index+1,projection='3d'); container=result['final_state']['container']
    for i,obj in enumerate(result['final_state']['placed_items']):
        p=obj['pose']; dx,dy,dz=obj['oriented_size_mm']; x,y,z=p['x_mm']-dx/2,p['y_mm']-dy/2,p['z_base_mm']
        v=[(x,y,z),(x+dx,y,z),(x+dx,y+dy,z),(x,y+dy,z),(x,y,z+dz),(x+dx,y,z+dz),(x+dx,y+dy,z+dz),(x,y+dy,z+dz)]
        faces=[[v[j] for j in f] for f in [(0,1,2,3),(4,5,6,7),(0,1,5,4),(2,3,7,6),(1,2,6,5),(0,3,7,4)]]
        ax.add_collection3d(Poly3DCollection(faces,facecolors=plt.cm.tab20(i%20),edgecolors='#444',linewidths=.5,alpha=.7))
        ax.text(p['x_mm'],p['y_mm'],z+dz+6,obj['item_id'].split('_')[-1],fontsize=8)
    ax.set(xlim=(-container['length_mm']/2,container['length_mm']/2),ylim=(-container['width_mm']/2,container['width_mm']/2),zlim=(0,container['max_height_mm']),xlabel='x / mm',ylabel='y / mm',zlabel='z / mm')
    ax.set_title(f'{row["task_id"]} {row["method"]} {row["group"]}: {row["placed_items"]}/12 actual boxes')
fig.tight_layout(); fig.savefig(HERE/'actual_layouts.png',dpi=150); plt.close(fig)

# Review data includes public input/AST and a detailed local search, but never
# draws a hypothetical box as an actual submission.
payload=[]
for row,result in representatives:
    decisions=[(i,e) for i,e in enumerate(result['events']) if 'search_trace' in e]
    payload.append({'label':f'{row["task_id"]} {row["method"]} {row["group"]}', 'summary':result['summary'],
        'source':row['record_path'],'final_state':result['final_state'],
        'decisions':[{'event_index':i,'input':e['request'],'AST':e['response']['policy_ast'], 'before':e['before'],
             'actual_action':next((c for c in e['candidates'] if e.get('action') and c['candidate_id']==e['action']['candidate_id']),None),
             'trace':e['search_trace'],'stop_diagnostics':e.get('diagnostics'), 'event':e['event'],
             'hypotheses':[c for g in e['groups'] for c in g['eligible']][:6]} for i,e in decisions]})
table=''.join('<tr>'+''.join(f'<td>{html.escape(str(value))}</td>' for value in [p['task_id'],p['method'],p['A'],p['F_B0'],p['count_delta'],f'{100*p["volume_delta"]:.3f}',p['A_clean'],p['F_clean'],p['default_HOLD']])+'</tr>' for p in pairs)
data=json.dumps(payload,ensure_ascii=False).replace('</','<\\/')
page='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>B0规划能力复核</title>
<style>body{font:16px system-ui;margin:24px;max-width:1200px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:5px}pre{white-space:pre-wrap;background:#f4f5f7;padding:14px;max-height:480px;overflow:auto}canvas{border:1px solid #ccc}img{max-width:100%}.legend{color:#555}</style>
<h1>B0规划能力复核</h1><p>原A默认。F=B0；新扩大开发对照，12个历史开发来源，未测独立泛化。</p>
<p>实心为已提交，绿色为当前实际动作，橙色虚线仅是假设候选。STOP处绿色为空。图中投影不能代替三维碰撞、支撑和业务检查。</p>
<img src="actual_layouts.png" alt="四个真实终态三维布局"><h2>代表输入、动作和假设</h2>
<label>记录 <select id="record"></select></label> <label>决策 <select id="decision"></select></label>
<label><input type="checkbox" id="hyp" checked>显示假设候选（未提交）</label><p id="caption"></p>
<canvas width="720" height="600" id="map"></canvas>
<details open><summary>当前输入与AST</summary><pre id="input"></pre></details>
<details><summary>取箱、选位、选路、分层预算与STOP</summary><pre id="trace"></pre></details>
<h2>全部24任务配对（每方法各24）</h2><table><thead><tr><th>任务</th><th>方法</th><th>A箱</th><th>F箱</th><th>箱差</th><th>体积差pp</th><th>A整单</th><th>F整单</th><th>HOLD</th></tr></thead><tbody>TABLE</tbody></table>
<p>原始证据：<a href="main_audit.json">主审计</a>、<a href="main_pairs.json">配对</a>、<a href="t0_interpretation.json">T0因素拆分</a>、<a href="t0_observational_equivalence.json">根动作暴露</a>。假设的后继路径不代表真实已提交，不代表未来到货信息。</p>
<script type="application/json" id="data">DATA</script><script>
const data=JSON.parse(document.getElementById('data').textContent),r=document.getElementById('record'),d=document.getElementById('decision'),h=document.getElementById('hyp');
data.forEach((v,i)=>r.add(new Option(v.label,i)));
function updateChoices(){d.innerHTML='';data[r.value].decisions.forEach((v,i)=>d.add(new Option('event '+v.event_index+' '+v.event,i)));draw()}
function draw(){const row=data[r.value],v=row.decisions[d.value],canvas=document.getElementById('map'),c=canvas.getContext('2d'),container=v.before.container,s=Math.min(680/container.length_mm,560/container.width_mm);c.clearRect(0,0,720,600);c.strokeStyle='#222';c.setLineDash([]);c.strokeRect(360-container.length_mm*s/2,300-container.width_mm*s/2,container.length_mm*s,container.width_mm*s);
function box(o,color,dashed){const p=o.pose,sz=o.oriented_size_mm;c.setLineDash(dashed?[7,5]:[]);c.strokeStyle=color;c.fillStyle=color+'33';const x=360+(p.x_mm-sz[0]/2)*s,y=300-(p.y_mm+sz[1]/2)*s;c.strokeRect(x,y,sz[0]*s,sz[1]*s);if(!dashed)c.fillRect(x,y,sz[0]*s,sz[1]*s);c.fillStyle=color;c.fillText((o.item_id||o.pick_item_id)+' z='+p.z_base_mm,x+3,y+14)}
v.before.placed_items.forEach(o=>box(o,'#345d8b',false));if(h.checked)v.hypotheses.forEach(o=>box(o,'#c67510',true));if(v.actual_action)box(v.actual_action,'#137c44',false);
document.getElementById('caption').textContent=row.label+' / event '+v.event_index+' / '+v.event+' / logical evaluations '+v.trace.evaluations;
document.getElementById('input').textContent=JSON.stringify({input:v.input,AST:v.AST},null,2);document.getElementById('trace').textContent=JSON.stringify({actual_action:v.actual_action,trace:v.trace,stop:v.stop_diagnostics,summary:row.summary,source:row.source},null,2)}
r.onchange=updateChoices;d.onchange=draw;h.onchange=draw;updateChoices();</script></html>'''.replace('TABLE',table).replace('DATA',data)
with (HERE/'review.html').open('x') as f:f.write(page)
with (HERE/'visual_validation.json').open('x') as f:json.dump({'records':4,'all_pairs':len(pairs),'actual_and_hypotheses_separate':True,'input_AST_included':True,'new_api_attempts':0,'browser_review':'NOT_PERFORMED_YET'},f,indent=2)
print('review.html and actual_layouts.png generated')
