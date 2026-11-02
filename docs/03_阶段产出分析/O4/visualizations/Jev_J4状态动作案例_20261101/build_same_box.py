"""Visualize the preserved three same-box rollouts, without replay."""
from pathlib import Path
import json
from html import escape

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'semantic_pallet_planner/outputs').is_dir())
SOURCE=ROOT/'semantic_pallet_planner/outputs/CASE_JEV_J4_SAME_BOX_RANK_20261101_01'
r=json.loads((SOURCE/'comparison.json').read_text())
colors=['#365d7b','#ad6142','#207663']
rows=[];lines=[];poses=[]
for i,b in enumerate(r['rows']):
    groups=b['final_violations']['by_rule']
    def metric(key,unit=None):
        v=groups.get(key,{'count':0,'severity_by_unit':{}})
        return f"{v['count']}"+(f" / {v['severity_by_unit'].get(unit,0):g} {unit}" if unit else '')
    p=b['candidate']['pose'];angle=p['yaw_deg'];size=b['candidate']['oriented_size_mm']
    rows.append(f"<tr><td>C{['15','36','39'][i]}<br><small>{'实际第一名' if i==0 else '概率0.05并列'}</small></td><td>{b['placed_items']}/15</td><td>{b['final_violations']['instance_count']}</td><td>{b['trajectory_violation_instance_steps']}</td><td>{metric('food_cleaner_segregation:forbidden_co_pallet')}</td><td>{metric('label:max_top_load','kg')}</td><td>{metric('no_top:no_top_load','kg')}</td></tr>")
    points=[]
    for j,n in enumerate(b['per_step_instances']):
        x=70+j*165;y=275-n*18;points.append(f'{x},{y}')
        lines.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{colors[i]}"/><text x="{x+9}" y="{y-8+i*12}" fill="{colors[i]}" font-size="15">{n}</text>')
    lines.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{colors[i]}" stroke-width="3"/>')
    if b['placed_items']<6:lines.append(f'<text x="{70+(b["placed_items"]-1)*165+12}" y="{275-b["per_step_instances"][-1]*18+32}" fill="{colors[i]}" font-size="15">候选耗尽，后续无数据</text>')
    x=35+(p['x_mm']-size[0]/2+600)*.23;y=115-size[1]*.23/2
    poses.append(f'<div><h3>{b["display_id"]} · {b["native_probability"]:g}</h3><svg viewBox="0 0 350 245" role="img" aria-label="候选{b["display_id"]}初始位置"><rect x="35" y="0" width="276" height="230" fill="#f1f5f7" stroke="#a5b6c4"/><line x1="173" y1="0" x2="173" y2="230" stroke="#a5b6c4" stroke-dasharray="4 4"/><rect x="{x}" y="{y}" width="{size[0]*.23}" height="{size[1]*.23}" fill="{colors[i]}" opacity=".75"/><text x="42" y="22" font-size="13">俯视：同一清洁品箱9.8 kg</text></svg><p>x={p["x_mm"]:g} mm · 朝向{angle}°</p></div>')
grid=[]
for n in (0,3,6,9,12):grid.append(f'<line x1="70" y1="{275-n*18}" x2="895" y2="{275-n*18}" stroke="#dce4eb"/><text x="35" y="{280-n*18}" font-size="14">{n}</text>')
for j in range(6):grid.append(f'<text x="{50+j*165}" y="313" font-size="14">第{j+1}件</text>')
html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>同箱候选排名对照：本次未找到全面更优候选</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f2f6f9;color:#18364a;font:16px/1.7 system-ui,'Microsoft YaHei',sans-serif}main{max-width:1200px;margin:auto;padding:30px 22px}h1{line-height:1.35;font-size:32px}h2{font-size:23px;margin:0 0 12px}h3{margin:0 0 8px}p{margin:8px 0 16px}.card{padding:24px;background:white;border:1px solid #d9e3eb;border-radius:14px;margin:20px 0}.warn{background:#fff0df;border-left:5px solid #ad6142;padding:18px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}svg{display:block;width:100%;height:auto}svg text{font-family:inherit}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:12px 10px;border-bottom:1px solid #dce4eb}th{font-size:14px;color:#536b7b}.scroll{overflow:auto}.legend{display:flex;gap:24px;flex-wrap:wrap}.dot{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:6px}.muted,small{color:#536b7b}a{color:#1c715f}summary{cursor:pointer}code{overflow-wrap:anywhere}button{font:inherit;padding:9px 16px;border:1px solid #abc3d2;border-radius:8px;background:white;color:#18364a;cursor:pointer}@media(max-width:740px){.grid{grid-template-columns:1fr}h1{font-size:27px}.card{padding:16px}table{min-width:760px}}@media print{.card{break-inside:avoid}button{display:none}}</style><main>
<p class="muted">00100153 / D0000 / 固定同一箱体 / 3条本地分支 / 0次模型请求</p>
<h1>把实际第一名换成同箱第二名，后续业务是否更好？</h1>
<div class="warn"><strong>本次没有发现全面更优候选。</strong>第二个候选的违规少，但只放3件；并列候选也可放6件，违规实例减少，却加重了业务超限。不能只看总违规数量就推荐换候选。</div>
<section class="card"><h2>01　同一状态、同一箱体，改变放置候选</h2><p>第一步实际选中清洁品箱item_02。将保存的Jev候选概率限定在该箱体内，取前三项；后续全部使用固定的本地几何策略，重新生成各状态候选。未调用Jev续跑，也未复用分叉后的旧概率。</p><div class="grid">__POSES__</div><p class="muted">C36与C39的0.05并列；按显示ID确定展示顺序，不能称为模型给出了严格第二、第三名。数值为保存的原始声明概率，未重新归一化。</p></section>
<section class="card"><h2>02　结果对照：放置量与违规必须一起看</h2><div class="scroll"><table><thead><tr><th>候选</th><th>放置量</th><th>终态违规实例</th><th>过程实例步数</th><th>同托盘冲突对</th><th>限载实例 / 超限量</th><th>禁压实例 / 违规上载</th></tr></thead><tbody>__ROWS__</tbody></table></div><p>三条分支均以物理候选耗尽终止，未完成15件订单。C36在第3件后停止，不是后续一直零违规。C39虽同放6件，但最终箱体集合和已放体积也不同。</p><div class="legend"><span><i class="dot" style="background:#365d7b"></i>C15 实际第一名</span><span><i class="dot" style="background:#ad6142"></i>C36 并列项</span><span><i class="dot" style="background:#207663"></i>C39 并列项</span></div><svg viewBox="0 0 960 330" role="img" aria-label="逐次放置后违规实例数；C36第3件后停止">__CHART__</svg><p class="muted">过程实例步数为各次放置后实例数之和；它与严重度不同，不能将kg和mm混合成总严重度。</p></section>
<section class="card"><h2>03　这次真正沉淀的经验</h2><div class="grid"><div><h3>第二名不是自动改进</h3><p>C36仅放3件，其3个违规不能直接优于C15放6件时的12个。必须检查后续可继续放置能力。</p></div><div><h3>总数下降也可能转移代价</h3><p>C39终态实例12→7，过程34→22，但超载2.24→3.89 kg。应保留这项权衡，不写成全面降低业务风险。</p></div><div><h3>混放不是间距问题</h3><p>按食品与清洁品不可同托盘评估，每一对不相容箱均记冲突。三条分支都还有混放，移动5 cm不能消除它。</p></div></div><div class="warn">这是一条单来源、固定后续策略下的候选风险案例。它不支持“以后直接选第二名”，也不证明真实Jev收益；经验未激活。</div></section>
<section class="card"><h2>04　如何与旧结论区分</h2><p>此前“平移50 mm解决接触要求”的业务结论已撤回。旧实验使用禁止面接触，本次另建不可同托盘评估视图，保留其他规则及旧反馈，不改历史。共托盘冲突按箱体对计数；只要有一对，托盘便不符合隔离要求。</p><p>本地模拟未实现多托盘分配或强制隔离，仍允许违规来观察后果。若作为实际硬约束部署，需要另外实现阻止混放与托盘分配，不能使用本次模拟当作部署验证。</p><p>历史Jev轨迹重评为8个终态实例，本次C15本地续跑为12。后续策略不同，只能比较本次三条同策略分支。</p></section>
<section class="card"><h2>完整证据</h2><p><a href="../../Jev_J4同箱候选排名分叉对照_20261101.md">实验报告与复现指令</a> · <a href="../../../../../semantic_pallet_planner/outputs/CASE_JEV_J4_SAME_BOX_RANK_20261101_01/comparison.json">封存比较JSON</a> · <a href="same_box_verification.json">执行与复核记录</a></p><details><summary>查看本次预注册和源目录</summary><p><code>CASE_JEV_J4_SAME_BOX_RANK_20261101_01</code>；先登记D0000和三个原始概率候选，再自然续跑，无效果筛选后换点。真实来源和共享请求账目未改变。</p></details><button onclick="window.print()">打印 / 保存为PDF</button></section>
</main></html>'''
(HERE/'同箱候选排名对照.html').write_text(html.replace('__POSES__',''.join(poses)).replace('__ROWS__',''.join(rows)).replace('__CHART__',''.join(grid+lines)))
print('Built same-box rank visualization from preserved results; no simulation.')
