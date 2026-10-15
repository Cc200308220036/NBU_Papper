"""Build an offline, source-linked 3D explanation of O2b case 004 A0.

Reads only the published public request and per-decision rows. The reference
method is described as privileged, but hidden AST content is never embedded.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from plotly.offline import get_plotlyjs


ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05"
OUT = Path(__file__).resolve().parent
CASE = "O1B_GROUP_004_A0"


def main() -> None:
    request_path = EXP / "selector_inputs/flash_direct_text" / CASE / "public_request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    with (EXP / "metrics/per_decision.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = {row["method"]: row for row in csv.DictReader(stream) if row["request_id"] == CASE}

    methods = [
        ("geometry_greedy", "Geometry-Greedy", "公开几何与候选几何分", "按几何分排序，选择分数最高的候选；不使用当前业务指令进行排序。"),
        ("fixed_attribute", "固定属性启发式", "公开物料属性、候选关系；冻结的通用属性政策", "按固定属性规则评价并排序；该政策不随本题自然语言切换。"),
        ("flash_direct_text", "Flash Direct-Text", "公开状态、指令、属性、16 个候选及关系事实", "Flash 直接给出 Cxx 候选编号；不先交给执行器逐项精算。"),
        ("public_parser", "Public Parser＋Executor", "同一公开状态、指令、属性和候选事实", "编写的解析器从指令生成受限政策 AST；共用执行器筛硬约束并按优先级排序。"),
        ("flash_policy_parser", "Flash AST＋Executor", "同一公开状态、指令、属性和候选事实", "Flash 输出受限政策 AST；共用执行器检查全部候选并排序。"),
        ("truth_ast_executor", "真值 AST＋Executor", "隐藏真值 AST＋同一物理状态和候选；特权参考", "直接用出题侧真值政策驱动同一执行器；仅作候选集内参考上界。"),
    ]
    view = []
    for key, label, inputs, process in methods:
        row = rows[key]
        view.append({
            "key": key, "label": label, "inputs": inputs, "process": process,
            "proposed": row["proposed_label"] or None,
            "committed": row["committed_label"] or None,
            "status": row["status"], "screen": row["screen_intervened"] == "True",
            "raw_violation_count": int(row["raw_new_business_violations"]) if row["raw_new_business_violations"] else None,
            "raw_optimal": row["raw_optimal_hit"] == "True",
            "privileged": key == "truth_ast_executor",
        })
    payload = {
        "case": CASE,
        "request": {k: request[k] for k in ("request_id", "state_hash", "policy_digest", "instruction_text", "container", "placed_items", "available_items", "candidates")},
        "methods": view,
    }
    page = TEMPLATE.replace("__PLOTLY_JS__", get_plotlyjs()).replace(
        "__CASE_DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    )
    out = OUT / "O2b_六方法同题3D案例_GROUP004_A0.html"
    out.write_text(page, encoding="utf-8")
    render_comparison_png(request, OUT / "O2b_案例004_C08与C10_3D对照.png")
    print(out)
    print(f"bytes={out.stat().st_size}; methods={len(view)}; candidates={len(request['candidates'])}")


def render_comparison_png(request: dict, output: Path) -> None:
    """Static 3D view for slides; geometry is read from the same public JSON."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    candidates = {c["display_label"]: c for c in request["candidates"]}
    fig = plt.figure(figsize=(16, 7.4), dpi=170, facecolor="white")
    panels = [
        ("C08", "#d9574e", "PROPOSED: C08 | forbidden face contact"),
        ("C10", "#35a876", "COMMITTED: C10 | business feasible"),
    ]
    for index, (label, color, title) in enumerate(panels, 1):
        ax = fig.add_subplot(1, 2, index, projection="3d")
        for item in request["placed_items"]:
            p = item["pose"]
            sx, sy, sz = item["oriented_size_mm"]
            shade = "#e4a15d" if item["fragile"] else "#365c8d" if item["weight_class"] == "heavy" else "#8ba3a9"
            ax.bar3d(p["x_mm"] - sx / 2, p["y_mm"] - sy / 2, p["z_base_mm"], sx, sy, sz,
                     color=shade, alpha=0.72, edgecolor="#263b43", linewidth=0.7, shade=True)
            if item["item_id"] == "item_04":
                ax.text(p["x_mm"] - 100, p["y_mm"], p["z_base_mm"] + sz + 35,
                        "item_04 / heavy", ha="center", fontsize=10,
                        weight="bold", color="#16395e")
        c = candidates[label]
        p = c["pose"]
        sx, sy, sz = c["oriented_size_mm"]
        ax.bar3d(p["x_mm"] - sx / 2, p["y_mm"] - sy / 2, p["z_base_mm"], sx, sy, sz,
                 color=color, alpha=0.60, edgecolor="#12353d", linewidth=1.2, shade=True)
        ax.text(p["x_mm"], p["y_mm"], p["z_base_mm"] + sz + 30, label + " / item_05",
                ha="center", fontsize=11, weight="bold", color=color)
        if label == "C08":
            face = [[(80, 120, 0), (80, 300, 0), (80, 300, 230), (80, 120, 230)]]
            ax.add_collection3d(Poly3DCollection(face, facecolors="#ef2d35", edgecolors="#ac1d25",
                                                   alpha=0.85, linewidth=1.2))
            ax.text(80, 155, 315, "FORBIDDEN\nCONTACT", color="#bb2930", fontsize=10, weight="bold")
        ax.set(xlim=(-600, 600), ylim=(-500, 500), zlim=(0, 850), xlabel="X / mm", ylabel="Y / mm", zlabel="Z / mm")
        ax.set_box_aspect((1200, 1000, 850))
        ax.view_init(elev=24, azim=-58)
        ax.set_title(title, fontsize=13, weight="bold", pad=22, color="#17343b")
        ax.tick_params(labelsize=8)
    fig.text(0.5, 0.03,
             "Same 4 placed boxes and 16 physical candidates | C08 geometry 0.79515330; "
             "C10 geometry 0.79483485 | Red face: item_04 / item_05",
             ha="center", fontsize=11, color="#52656c")
    fig.subplots_adjust(left=0.02, right=0.98, top=0.87, bottom=0.10, wspace=0.02)
    fig.savefig(output, facecolor="white")
    plt.close(fig)


TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>O2b 六方法同题 3D 码垛案例</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f7f8;color:#16252b;font:15px/1.6 system-ui,"Noto Sans CJK SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1440px;margin:auto;padding:28px}h1{font-size:28px;margin:0 0 4px}h2{font-size:19px;margin:0 0 12px}.sub{color:#506169;margin:0 0 20px}.grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(335px,1fr);gap:18px}.card{background:#fff;border:1px solid #dce4e7;border-radius:12px;padding:18px;box-shadow:0 3px 14px #22313a08}.wide{grid-column:1/-1}.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:8px}select,button{font:inherit;background:#fff;border:1px solid #b9cbd0;border-radius:7px;padding:7px 10px;color:#18363b}button{cursor:pointer}button.active{background:#166b75;color:#fff;border-color:#166b75}.hint{font-size:13px;color:#5a6a70}.badge{display:inline-block;padding:3px 9px;border-radius:20px;font-size:13px;font-weight:650}.bad{color:#983b35;background:#fce9e6}.good{color:#146145;background:#e2f4eb}.ref{color:#566080;background:#edf0f9}.flow{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:14px 0}.step{background:#eff5f6;border-radius:8px;padding:10px;min-height:92px}.step b{display:block;color:#116b74;margin-bottom:3px}.num{font-size:34px;color:#166b75;font-weight:750;line-height:1}.small{font-size:13px;color:#596970}.comparison{display:grid;grid-template-columns:1fr 1fr;gap:12px}.compare{border:1px solid #e0e7e8;border-radius:8px;padding:14px}.compare.badbox{border-left:5px solid #d4574c}.compare.goodbox{border-left:5px solid #35a876}code{font-family:ui-monospace,Consolas,monospace;background:#f0f3f4;padding:2px 5px;border-radius:4px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;border-bottom:1px solid #e2e9eb;padding:8px}th{background:#edf3f4}.legend{display:flex;gap:15px;flex-wrap:wrap}.dot{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px}.details{margin-top:12px}.details summary{cursor:pointer;color:#116b74}a{color:#126d78}.foot{font-size:12px;color:#687980;margin-top:24px}#scene{height:620px;width:100%}@media(max-width:930px){.grid{grid-template-columns:1fr}.flow{grid-template-columns:1fr 1fr}#scene{height:480px}}@media(max-width:560px){.comparison{grid-template-columns:1fr}.flow{grid-template-columns:1fr}}
</style><script>__PLOTLY_JS__</script></head><body><main class="wrap">
<h1>同一题，六种方法怎么选码垛位置？</h1>
<p class="sub">真实开发实验 O1B_GROUP_004_A0 · 4 个已有箱体 · 当前待放电子产品箱 item_05 · 16 个物理候选 · 可旋转 3D 场景</p>
<div class="grid"><section class="card"><div class="toolbar"><label>方法 <select id="method"></select></label><button id="proposed" class="active">看原始提议</button><button id="actual">看实际提交</button><button id="contrast">C08 / C10 对照</button><label class="hint"><input id="all" type="checkbox">显示全部候选中心</label></div><div id="scene"></div><div class="legend"><span><i class="dot" style="background:#e4a15d"></i>已有易碎箱</span><span><i class="dot" style="background:#365c8d"></i>已有重箱</span><span><i class="dot" style="background:#8ba3a9"></i>其他已有箱</span><span><i class="dot" style="background:#d9574e"></i>违规提议</span><span><i class="dot" style="background:#35a876"></i>可提交候选</span></div><p class="hint">拖动旋转、滚轮缩放、悬停看箱体与候选信息。半透明箱体是“本步可能放入的位置”，不是已有箱体；红色接触面只出现在 C08。</p></section>
<section class="card"><h2 id="name"></h2><div id="badge"></div><div class="flow"><div class="step"><b>① 输入</b><span id="inputs"></span></div><div class="step"><b>② 解析 / 排序</b><span id="process"></span></div><div class="step"><b>③ 原始提议</b><span id="proposal"></span></div><div class="step"><b>④ 屏障后提交</b><span id="commit"></span></div></div><p id="explain"></p><p class="hint">六种方法共用同一个物理状态和候选集；“真值 AST”一行拥有隐藏政策，仅用作特权参考。业务屏障拦截违规提议并 abstain，不会替方法改选 C10。</p><details class="details"><summary>查看本题公开指令及事实</summary><p id="instruction"></p><p>托盘 1200 × 1000 × 850 mm，坐标原点在底面中心。当前箱 item_05：5.27 kg，<code>electronics</code>，<code>light</code>。已有 item_04 同时为 <code>heavy</code> 和 <code>electronics</code>。两个易碎箱为 item_01 / item_02。</p></details></section>
<section class="card wide"><h2>同一物理题的关键差异：C08 与 C10</h2><div class="comparison"><div class="compare badbox"><h2>C08 · 几何分略高，但业务违规</h2><p>中心位置 (230, 195, 0) mm；几何分 <b>0.79515330</b>。当前电子产品箱 item_05 与已有重箱 item_04 在 X 方向形成直接面接触，新增业务违规 <b>1</b>。Geometry-Greedy 和 Flash Direct-Text 原始提议 C08；业务屏障拦截，实际没有放入新箱。</p></div><div class="compare goodbox"><h2>C10 · 几何分略低，满足业务要求</h2><p>中心位置 (450, 195, 0) mm；几何分 <b>0.79483485</b>，仅比 C08 低 <b>0.00031845</b>。没有新增与重箱的禁止面接触，易碎箱新增承载为 0 kg。其余四种方法选择 C10 并提交。</p></div></div><p class="hint">注意：本题“重箱放低、靠中心”的软优先级对当前轻箱没有形成区分；决定结果的是禁止接触硬约束。item_05 与其他箱体的普通接触不等于禁止接触，易碎箱的侧面接触也不等于被堆压。</p></section>
<section class="card wide"><h2>六方法原始结果一览</h2><table id="results"></table><p class="hint">本页是单题的真实记录和可视化解释，不能替代总体统计，更不能证明视觉模型优势；这次是 Text＋JSON 固定候选实验，没有图像输入。</p></section></div>
<p class="foot">数据来源：EXP_OPT_O2B_AST_PILOT_20261009_05 / selector_inputs/flash_direct_text/O1B_GROUP_004_A0/public_request.json 与 metrics/per_decision.csv。离线 HTML 内嵌 Plotly，可直接在浏览器打开；不调用 API，不加载外部脚本。</p>
</main><script>
const DATA=__CASE_DATA__;
const R=DATA.request, M=DATA.methods, C=Object.fromEntries(R.candidates.map(c=>[c.display_label,c]));
let selected=M[0], mode='proposed', camera={eye:{x:1.55,y:-1.8,z:1.05}};
const COLOR={fragile:'#e4a15d',heavy:'#365c8d',other:'#8ba3a9'};
function boxGeometry(record){const p=record.pose,s=record.oriented_size_mm,x=p.x_mm,y=p.y_mm,z=p.z_base_mm,l=s[0]/2,w=s[1]/2,h=s[2];return {x:[x-l,x+l,x+l,x-l,x-l,x+l,x+l,x-l],y:[y-w,y-w,y+w,y+w,y-w,y-w,y+w,y+w],z:[z,z,z,z,z+h,z+h,z+h,z+h]};}
const ei=[0,1,1,2,2,3,3,0,4,5,5,6,6,7,7,4,0,4,1,5,2,6,3,7];
function boxTraces(rec,color,name,opacity){const v=boxGeometry(rec),triI=[0,0,4,4,0,0,1,1,2,2,3,3],triJ=[1,2,5,6,1,5,2,6,3,7,0,4],triK=[2,3,6,7,5,4,6,5,7,6,4,7];let ex=[],ey=[],ez=[];for(let k=0;k<ei.length;k+=2){let a=ei[k],b=ei[k+1];ex.push(v.x[a],v.x[b],null);ey.push(v.y[a],v.y[b],null);ez.push(v.z[a],v.z[b],null)}return [{type:'mesh3d',x:v.x,y:v.y,z:v.z,i:triI,j:triJ,k:triK,flatshading:true,color,opacity,name,hovertemplate:name+'<extra></extra>',showlegend:false},{type:'scatter3d',mode:'lines',x:ex,y:ey,z:ez,line:{color:color==='\#d9574e'?'#a73932':'#42535a',width:3},hoverinfo:'skip',showlegend:false}];}
function pallet(){let x=[-600,600,600,-600,-600],y=[-500,-500,500,500,-500],z=[0,0,0,0,0];return {type:'scatter3d',mode:'lines',x,y,z,line:{color:'#51656d',width:6},hoverinfo:'skip',showlegend:false};}
function labelTrace(x,y,z,text,color,size=10){return {type:'scatter3d',mode:'text',x:[x],y:[y],z:[z],text:[text],textfont:{color,size},hoverinfo:'skip',showlegend:false};}
function contactPatch(){return {type:'mesh3d',x:[80,80,80,80],y:[120,300,300,120],z:[0,0,230,230],i:[0,0],j:[1,2],k:[2,3],color:'#ff2c35',opacity:0.78,hovertemplate:'item_04 与 item_05 的禁止面接触<extra></extra>',showlegend:false};}
function render3d(){const traces=[pallet()];for(const it of R.placed_items){let color=it.fragile?COLOR.fragile:it.weight_class==='heavy'?COLOR.heavy:COLOR.other;traces.push(...boxTraces(it,color,it.item_id+' / '+it.weight_class+(it.fragile?' / fragile':''),0.73));traces.push(labelTrace(it.pose.x_mm,it.pose.y_mm,it.pose.z_base_mm+it.oriented_size_mm[2]+16,it.item_id,'#192e35',10));}
if(document.querySelector('#all').checked){traces.push({type:'scatter3d',mode:'markers+text',x:R.candidates.map(c=>c.pose.x_mm),y:R.candidates.map(c=>c.pose.y_mm),z:R.candidates.map(c=>c.pose.z_base_mm+c.oriented_size_mm[2]+30),text:R.candidates.map(c=>c.display_label),textposition:'top center',marker:{size:3,color:'#7b96a0'},textfont:{size:9,color:'#637c85'},hovertemplate:R.candidates.map(c=>c.display_label+'<br>geometry='+c.geometry_score+'<extra></extra>'),showlegend:false});}
let picks=[];if(mode==='contrast')picks=[['C08','#d9574e',0.34],['C10','#35a876',0.34]];else if(mode==='actual'&&selected.committed)picks=[[selected.committed,'#35a876',0.65]];else if(mode==='proposed'&&selected.proposed)picks=[[selected.proposed,selected.screen?'#d9574e':'#35a876',0.5]];
for(const [id,color,opacity] of picks){const c=C[id];traces.push(...boxTraces(c,color,id+' / 提议候选',opacity));traces.push(labelTrace(c.pose.x_mm,c.pose.y_mm,c.pose.z_base_mm+c.oriented_size_mm[2]+43,id,color,16));if(id==='C08')traces.push(contactPatch());}
const layout={margin:{l:0,r:0,t:4,b:0},paper_bgcolor:'#fff',scene:{aspectmode:'manual',aspectratio:{x:1.2,y:1,z:0.7},xaxis:{title:'X / mm',range:[-650,650],backgroundcolor:'#f7fafb',gridcolor:'#e3eaed'},yaxis:{title:'Y / mm',range:[-550,550],backgroundcolor:'#f7fafb',gridcolor:'#e3eaed'},zaxis:{title:'Z / mm',range:[0,850],backgroundcolor:'#fff',gridcolor:'#e3eaed'},camera},uirevision:'same-camera'};
return Plotly.react('scene',traces,layout,{responsive:true,displaylogo:false});}
function renderText(){document.getElementById('name').textContent=selected.label;document.getElementById('inputs').textContent=selected.inputs;document.getElementById('process').textContent=selected.process;document.getElementById('proposal').innerHTML='<b>'+selected.proposed+'</b>'+(selected.raw_violation_count?' · 新增业务违规 '+selected.raw_violation_count:' · 无新增业务违规');document.getElementById('commit').innerHTML=selected.committed?'<b>'+selected.committed+'</b> · 已提交':'<b>abstain</b> · 未提交新箱';const b=document.getElementById('badge');b.className='badge '+(selected.privileged?'ref':selected.screen?'bad':'good');b.textContent=selected.privileged?'特权参考':selected.screen?'提议被业务屏障拦截':'本题提议满足要求';document.getElementById('explain').textContent=selected.screen?'它提议的 C08 与已有重箱 item_04 产生禁止面接触。屏障只拦截并记录 abstain，不会替它改选 C10。':selected.privileged?'它读取隐藏真值 AST，因此只能作为候选集内参考，不能与同权限方法直接比较。':'它提议 C10，满足本题业务硬约束，并命中候选集内最优等价集合。';}
const select=document.getElementById('method');for(const m of M){let o=document.createElement('option');o.value=m.key;o.textContent=m.label;select.append(o);}select.onchange=()=>{selected=M.find(m=>m.key===select.value);renderText();render3d();};
for(const v of ['proposed','actual','contrast'])document.getElementById(v).onclick=()=>{mode=v;for(const z of ['proposed','actual','contrast'])document.getElementById(z).classList.toggle('active',z===v);render3d();};document.getElementById('all').onchange=render3d;
document.getElementById('instruction').textContent=R.instruction_text;
document.getElementById('results').innerHTML='<thead><tr><th>方法</th><th>使用的政策来源</th><th>原始提议</th><th>屏障后</th><th>本题判断</th></tr></thead><tbody>'+M.map(m=>'<tr><td>'+m.label+'</td><td>'+m.inputs+'</td><td>'+m.proposed+'</td><td>'+(m.committed||'abstain')+'</td><td>'+(m.screen?'可避免硬违规，已拦截':m.privileged?'特权参考':'业务可行 / 最优')+'</td></tr>').join('')+'</tbody>';
renderText();render3d().then(()=>document.getElementById('scene').on('plotly_relayout',e=>{if(e['scene.camera'])camera=e['scene.camera'];}));
</script></body></html>'''


if __name__ == "__main__":
    main()
