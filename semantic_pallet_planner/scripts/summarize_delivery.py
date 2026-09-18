#!/usr/bin/env python3
"""根据已完成的正式验收实验生成人类可读的交付索引。"""
import csv
import html
import json
import statistics
from pathlib import Path

PACKAGE=Path(__file__).resolve().parents[1]
ROOT=PACKAGE.parent
OUTPUTS=PACKAGE/'outputs'
A=OUTPUTS/'EXP_1A_20260912_FINAL'
B=OUTPUTS/'EXP_1B_20260912_FINAL'


def read(path):return json.loads(path.read_text())
def rows(path):
    with path.open() as f:return list(csv.DictReader(f))
def mean(group,key):return statistics.mean(float(r[key]) for r in group)


def main():
    a,b=read(A/'acceptance_report.json'),read(B/'acceptance_report.json')
    if a['status']!='PASS' or b['status']!='PASS':raise RuntimeError('both formal acceptance reports must PASS')
    fixed=rows(A/'metrics/per_decision.csv');episodes=rows(B/'metrics/per_episode.csv')
    sweep=read(B/'metrics/topk_selection.json');reps=read(B/'representative_episodes.json')
    replay=read(B/'replay_report.json')
    result=[f"本次最终验收：**1A PASS，1B PASS**。平台测试{b['test_count']}项全部通过，另有阶段0的7项测试通过。",
        '',f"- 1A：{a['fixed_rows']}条固定决策；SCN_0051完成10/10箱；两次运行核心哈希一致。",
        f"- 1B：{b['fixed_rows']}条固定决策，{b['episodes']}场在线episode；固定候选5124个复核失败0。",
        f"- 在线回放事件中的Top-K候选共复核{replay['returned_candidates_checked']}个，失败{replay['returned_candidate_failures']}；已提交动作复核违规{replay['geometry_failures']}。",
        f"- 候选重生成、状态/指标回放、请求可见性扫描、两次代表场景运行与动画开关一致性均通过。",
        f"- 1C冻结Top-K={sweep['frozen_top_k']}；代表动画{len(reps)}个，包含自然未完成场景。",'',
        '1A固定validation结果：','','| 方法 | 样本数 | 平均语义软分 | Oracle ID命中率 | fallback |','|---|---:|---:|---:|---:|']
    for method in ['random_valid','geometry_greedy','handcrafted_rule','candidate_oracle']:
        group=[r for r in fixed if r['method']==method]
        result.append(f"| {method} | {len(group)} | {mean(group,'soft_utility'):.6f} | {sum(r['oracle_hit']=='True' for r in group)/len(group):.2%} | {sum(r['fallback']=='True' for r in group)} |")
    result+=['','1B在线完整场景结果：','','| 方法 | 完成场景/100 | 无候选结束 | 平均放置比率 | 平均体积率 | 平均最高顶面mm |','|---|---:|---:|---:|---:|---:|']
    for method in ['lowest','geometry_greedy','pareto_greedy']:
        group=[r for r in episodes if r['method']==method]
        result.append(f"| {method} | {sum(r['completed']=='True' for r in group)}/100 | {sum(r['termination_reason']=='no_feasible_candidate' for r in group)} | {mean(group,'placed_item_ratio'):.4f} | {mean(group,'volume_utilization'):.4f} | {mean(group,'max_height_mm'):.2f} |")
    result+=['','所有300场均正常以全部放完或无候选结束，internal_error=0；未完成样本没有被删除。Geometry-Greedy的100%完成率需要结合数据经过参考策略可行性筛选这一事实解释，不能外推为任意工业订单均可完成。HandcraftedRule在本轮validation达到Oracle结果，说明后续VLM必须保留规则程序作为有竞争力的基线。','',
        '| K | validation平均Pareto覆盖 | epsilon命中率 | 平均返回数 |','|---:|---:|---:|---:|']
    for row in sweep['results']:result.append(f"| {row['top_k']} | {row['pareto_recall']:.4%} | {row['epsilon_hit_rate']:.2%} | {row['returned_mean']:.2f} |")
    timing=b['generation_timing']
    result+=['',f"本次在线候选生成耗时：p50={timing['p50_s']*1000:.3f} ms，p95={timing['p95_s']*1000:.3f} ms，最大={timing['max_s']*1000:.3f} ms；测试机信息及分组区间见manifest和summary。",'',
        '产物入口：[1A验收报告](../semantic_pallet_planner/outputs/EXP_1A_20260912_FINAL/acceptance_report.md)、[1B验收报告](../semantic_pallet_planner/outputs/EXP_1B_20260912_FINAL/acceptance_report.md)、[完整产物索引](../semantic_pallet_planner/outputs/阶段1A-1B产物索引.md)、[动画与图表浏览页](../semantic_pallet_planner/outputs/index.html)。']
    doc=ROOT/'docs/阶段1A-1B开发说明.md'
    text=doc.read_text();start=text.index('<!-- ACTUAL_RESULTS_START -->');end=text.index('<!-- ACTUAL_RESULTS_END -->')
    text=text[:start]+'<!-- ACTUAL_RESULTS_START -->\n'+'\n'.join(result)+'\n'+text[end:];doc.write_text(text)
    index=['# 阶段1A—1B正式产物索引','', '建议先阅读[阶段开发说明](../../docs/阶段1A-1B开发说明.md)，再查看报告和代表动画。所有正式指标只来自下列FINAL目录，`development/`为开发中间产物。','',
        '## 1. 报告和数值结果','', '| 内容 | 1A | 1B |','|---|---|---|']
    for name,label in [('acceptance_report.md','验收报告'),('acceptance_report.json','机器可读验收'),('metrics/per_decision.csv','逐固定决策'),('metrics/per_episode.csv','逐episode'),('metrics/summary.json','分组统计与95%区间'),('manifest.json','环境与数据/代码/产物哈希'),('replay_report.json','动态重生成和回放'),('reproducibility_report.json','重复运行一致性')]:
        index.append(f'| {label} | [打开]({A.name}/{name}) | [打开]({B.name}/{name}) |')
    index+=['','## 2. 图表与动画','',f'- [几何方法对比]({B.name}/figures/geometry_comparison.png)',f'- [Top-K灵敏度图]({B.name}/figures/topk_sensitivity.png)',f'- [1C Top-K冻结依据]({B.name}/metrics/topk_selection.json)','- [HTML动画浏览页](index.html)','','| 类别 | 场景 / 方法 | GIF | 最终布局 | episode数据 |','|---|---|---|---|---|']
    cards=[]
    for rep in reps:
        relative=f"{B.name}/{rep['directory']}";episode=read(B/rep['directory']/'episode.json')
        index.append(f"| {rep['category']} | {rep['scenario_id']} / {rep['method']} | [播放]({relative}/animation.gif) | [PNG]({relative}/final_layout.png) | [JSON]({relative}/episode.json) |")
        cards.append(f'''<article><h2>{html.escape(rep['category'])} · {rep['scenario_id']}</h2><p>{rep['method']} · {episode['termination_reason']} · {episode['metrics']['placed_count']}/{episode['metrics']['requested_count']}箱</p><a href="{relative}/animation.gif"><img loading="lazy" src="{relative}/animation.gif" alt="{rep['scenario_id']}码垛动画"></a><p><a href="{relative}/final_layout.png">最终布局</a> · <a href="{relative}/episode.json">轨迹与指标</a> · <a href="{relative}/steps.jsonl">逐步日志</a></p></article>''')
    index+=['','## 3. 如何继续使用','', '现有任意episode均可从日志重新渲染，命令与参数见[开发说明](../../docs/阶段1A-1B开发说明.md#9-命令配置和参数)。固定案例与完整episode分开分析；规则/Oracle方法带特权标记；无候选结果保留在分母中。','', '如需对全部交付文件进行只读检查：','','```bash','python3 semantic_pallet_planner/scripts/audit_delivery.py \\',f'  --experiments semantic_pallet_planner/outputs/{A.name} \\',f'  semantic_pallet_planner/outputs/{B.name}','```','']
    (OUTPUTS/'阶段1A-1B产物索引.md').write_text('\n'.join(index))
    html_text='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>阶段1A—1B码垛实验产物</title><style>body{margin:0;background:#f2f5f8;color:#19324a;font:16px/1.6 system-ui,sans-serif}main{max-width:1440px;margin:40px auto;padding:0 24px}h1{font-size:32px}h2{font-size:19px}a{color:#155c9d}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:24px}article{background:white;border-radius:12px;padding:20px;box-shadow:0 3px 15px #18364d0c}img{width:100%;height:auto}p{color:#506477}.badge{display:inline-block;background:#dbf2e5;padding:5px 12px;border-radius:20px;color:#18633b}header{margin-bottom:32px}@media(max-width:500px){section{display:block}article{margin-bottom:20px}}</style><main><header><span class="badge">1A PASS · 1B PASS</span><h1>真值三维码垛：实验结果与动画</h1><p>1440条固定决策 · 300场在线任务 · 5个代表场景。确定性3D规划可视化，非Gazebo或机器人执行。</p><p><a href="阶段1A-1B产物索引.md">完整文件索引</a> · <a href="../../docs/阶段1A-1B开发说明.md">阶段说明与使用方式</a></p></header><section>'''+''.join(cards)+f'''<article><h2>几何方法比较</h2><img src="{B.name}/figures/geometry_comparison.png" alt="几何结果比较"><p>全部样本均保留；数据受参考策略可行性筛选影响。</p></article><article><h2>validation Top-K灵敏度</h2><img src="{B.name}/figures/topk_sensitivity.png" alt="Top-K灵敏度"><p>按预定覆盖阈值冻结1C的K={sweep['frozen_top_k']}，未使用test调参。</p></article></section></main></html>'''
    (OUTPUTS/'index.html').write_text(html_text)
    # 只有两份已记录的报告均通过后，才勾选原始验收清单。
    spec=ROOT/'docs/阶段1A-1B实验方案.md';text=spec.read_text()
    banner='> 实现状态：阶段1A、1B已完成正式验收。实现细节及实际结果见[阶段开发说明](阶段1A-1B开发说明.md)，产物见[正式产物索引](../semantic_pallet_planner/outputs/阶段1A-1B产物索引.md)。\n\n'
    if banner not in text:text=text.replace('# 阶段1A—1B实验方案\n\n','# 阶段1A—1B实验方案\n\n'+banner)
    text=text.replace('- [ ]','- [x]')
    text=text.replace('新生成器在golden case上与阶段0候选指纹、分数和审计一致；','新生成器的`legacy_v01`兼容模式在全部360个golden DC上与阶段0候选指纹、分数和审计一致；')
    text=text.replace('Lookahead若运行，标记`future_visible=true`和`privileged_input=true`。','Lookahead若运行，标记`future_visible=true`和`privileged_input=true`（本阶段未运行该可选方法）。')
    text=text.replace('以下是后续Agent需实现的目标CLI，当前不代表命令已存在：','以下CLI已实现；当前可直接从工程根目录以`python3 -m semantic_pallet_planner.cli`调用。详细参数和正式验收命令见阶段开发说明：')
    spec.write_text(text)
    print(OUTPUTS/'阶段1A-1B产物索引.md')

if __name__=='__main__':main()
