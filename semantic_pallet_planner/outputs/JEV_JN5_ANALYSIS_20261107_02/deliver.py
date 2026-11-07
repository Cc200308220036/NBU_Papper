"""Build the JN5 report/receipts and seal a new offline analysis delivery."""
import argparse, csv, hashlib, importlib.metadata, json, os, shutil, sys
from pathlib import Path
from collections import Counter
from verify import verify
HERE=Path(__file__).resolve().parent
REPORT=Path('docs/03_阶段产出分析/Jev/Jev_JN5合成路线限定分析与证据整理验收_20261107_02.md')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,default=HERE);ap.add_argument('--report',type=Path,default=REPORT);a=ap.parse_args();b=Path(os.path.relpath(a.input,Path.cwd()));report=a.report
    if (b/'delivery_manifest.json').exists():raise RuntimeError('sealed_output_refuse_overwrite')
    if b.resolve()!=HERE:
        for n in ['deliver.py','verify.py']:shutil.copyfile(HERE/n,b/n)
    def write(n,x):(b/n).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    def link(n,label=None):return '['+(label or n)+']('+os.path.relpath(b/n,report.parent)+')'
    def pathlink(p,label):return '['+label+']('+os.path.relpath(p,report.parent)+')'
    def mdtable(headers,rows):return '\n'+'| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(map(str,r))+' |' for r in rows)+'\n'
    def val(x):return f'{x:.2f}'
    def pct(x):return f'{100*x:.2f}%'
    rows=read(b/'all_36_metrics.json');mainrows=read(b/'main_24_metrics.json');pairs=read(b/'main_16_pairs.json');histpairs=read(b/'historical_and_partial_pairs.json');ps=read(b/'pair_summary.json');ms=read(b/'method_summary.json');cs=read(b/'memory_coverage.json');cost=read(b/'cost_and_api_latency.json');div=read(b/'first_divergence.json');scope=read(b/'analysis_scope.json');coverage=read(b/'coverage_and_status.json')
    covrows=[]
    for group in ['main_v3_R2','all36']:
        for method in ['geometry','fixed','none','T','E','unrelated_E']:
            ids={r['job_id'] for r in rows if r['method']==method and (group=='all36' or r['group']==group)};sub=[r for r in cs if r['job_id'] in ids]
            covrows.append({'group':group,'method':method,**{k:sum(r[k] for r in sub) for k in ['decisions','library_nonempty_decisions','retrieval_nonempty','view_nonempty','body_nonempty','actually_sent_nonempty','singleton_decisions','singleton_nonempty_view']}})
    write('memory_coverage_summary.json',covrows)
    with (b/'memory_coverage_summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(covrows[0]));w.writeheader();w.writerows(covrows)
    write('dependencies.json',{'python':sys.version,'packages':{k:importlib.metadata.version(k) for k in ['numpy','matplotlib']},'new_dependencies_installed':False,'runtime_import_policy':'only Python standard library, numpy, matplotlib; original pure ranking functions AST-extracted without importing project runtime'})
    # Add generated figure/table hashes to raw evidence anchors. Manifest is sealed later.
    evidence=read(b/'evidence_index.json')
    evidence['figures']=[{'figure':f['figure'],'files':[{'path':p,'sha256':sha(p)} for p in f['files']],'plot_inputs':f['inputs'],'raw_evidence_ids':['P01_F1_F2_MAIN_AND_HISTORY'] if f['figure'].startswith(('F1','F2')) else ['F3_J0014','F3_J0015','F3_J0016'] if f['figure'].startswith('F3') else ['F4_GAP','F4_TIMEOUT']} for f in read(b/'figure_manifest.json')]
    evidence['key_claim_artifacts']=[{'claim':'main pair labels and task-equal volume difference summaries','path':str(b/'pair_summary.json'),'sha256':sha(b/'pair_summary.json'),'pointer':''},{'claim':'first exact action divergences with same-state/pool checks','path':str(b/'first_divergence.json'),'sha256':sha(b/'first_divergence.json'),'pointer':''},{'claim':'memory layers distinct','path':str(b/'memory_coverage_summary.json'),'sha256':sha(b/'memory_coverage_summary.json'),'pointer':''}]
    write('evidence_index.json',evidence)
    text=f'''# Jev JN5合成路线限定分析与证据整理验收

日期：2026-11-07。进入 HEAD `{scope['head'][:8]}`（已同步JN5方案；方案原基线 `2b8a8042`）。**JN5合成路线限定分析交付完成；P01—P04均在本限定范围完成。研究收益仍为 `NOT_ESTABLISHED`。**

本轮只对已保存JN4结果做离线计算、绘图、证据整理和检查。最终包为 `JEV_JN5_ANALYSIS_20261107_02`；开发包01及其初次报告保留，因命令被展开为本机绝对路径而被本交付替代，不作为最终验收入口。02修正相对路径序列化，冻结分析范围、指标及原始结果不变。新增模型调用、正式订单、分叉、训练、经验生成、凭证读取均为0；未联网调用模型、未重跑轨迹或全量validate-run、未启动子代理、未commit/push。已有未提交的JN4方案、可视化文档、两份索引增补、原始数据和展示目录均保留。本报告只新增JN5结果和索引入口，未改生产实现、冻结数据、T/E、历史运行包及历史报告。

依据{pathlink(Path(scope['scheme']),'JN5方案')}与{pathlink(Path('docs/02_阶段实施方案/Jev/Jev新数据完整订单与经验增强分阶段开发规范_20261103.md'),'主规范9.6及公共指标合同')}。{link('analysis_scope.json','分析范围')}在新指标计算前保存，类型为 `POST_HOC_FROZEN_RESULT_ANALYSIS`，不是原实验事前预注册。{link('input_manifest.json','消费输入摘要')}与{link('evidence_index.json','证据索引')}登记仓库相对路径、SHA256、job/decision/attempt与JSON指针。

## 证据层与分组

报告声明：JN4报告声称36槽位已收尾及累计账目。代码实现：本轮仅新增独立离线入口，按原函数AST选取纯评价函数，未导入工程运行模块；冻结 `jev_branch_comparison_rule_v2` 的优先级、阈值及标签保留，函数摘录和完整规则归档。归档证据：原task、metrics、status、layout、请求账本及固定案例动作/检查点均存在。本机复验：重算完整订单分母、提交布局对应量、24个主槽位身份、16对差值与评价、历史配对有效性、账目及图表证据；不声称本轮重新运行历史模型或静态内核。

| 层 | 范围与身份 | 本次用途 |
|---|---|---|
| 主分析 | SYN_COMBO_03—06，4任务×6方法，R2，同v3、同源码manifest | 逐任务及任务等权汇总；16对 |
| 部分补充 | SYN_COMBO_02，R1五项v3；几何是R0旧v2 | 同v3有效部分比较；无关E超时配对无效 |
| 历史展示 | SYN_COMBO_01，R0旧v2完整六方法 | 单列，不进入主均值 |
| 工程覆盖 | 全36槽位 | 保留6 COMPLETE、28 EMPTY_POOL、1 UNASSESSABLE、1 SELECTION_FAILURE；0 NOT_RUN |

R0=`JEV_JN4_SYNTH_EXEC_20261105_01/run`，R1=`JEV_JN4_EXACT_20261106_01/run`，R2=`JEV_JN4_REMAIN24_20261106_01/run`，均位于 `semantic_pallet_planner/outputs/`。逐行算法、协议、源码manifest及run见{link('all_36_metrics.csv','全36索引/指标CSV')}与{link('all_36_metrics.json','JSON')}。主矩阵只有4个任务级观测，任务共享原型；24方法槽位、箱体、请求、共享SKU均不是独立样本。

## 主结果与配对

所有24个主槽位均为 `EMPTY_POOL`，完整完成0/24；自然候选空池表示冻结采样池为空，不表示未执行或证明全局无解。件数、体积和质量比例以完整订单为分母，未到货箱体仍在分母，失败尝试不计已装。下表为保存布局复算后与原metrics一致的结果；比例以百分比显示。
'''
    text+=mdtable(['任务','方法/job','状态','件数','件数比','体积比','质量比','固定容器利用率','高度mm','包络利用率'],[[r['task_id'][-2:],r['method']+'/'+r['job_id'],r['category'],f"{r['placed_items']}/{r['planned_items']}",pct(r['placed_item_ratio']),pct(r['placed_volume_ratio']),pct(r['placed_mass_ratio']),pct(r['fixed_container_utilization']),val(r['actual_height_mm']),pct(r['envelope_utilization'])] for r in mainrows])
    text+=f'''\n详细{link('main_24_metrics.csv','主指标CSV')}同时保留不可评价/技术失败标识、监测状态/原因、首次预测失稳进度及精确终止原因。主24项监测共426次STABLE，UNSTABLE/UNASSESSABLE/ERROR均未观察到；它们不是未选候选的稳定性评估。主任务无自然预测静态失稳案例，不据此估计真实坍塌率。

配对方向固定 `delta = alternative - reference`。比例差以百分点（pp）、高度差以mm报告。主要层级为稳定完整完成→体积装入比例→件数/质量Pareto→装入等价时高度/包络Pareto；不另加事后综合权重。全部原值、差值、标签、决定层及反向次要指标保留在{link('main_16_pairs.json','主16对JSON')}与{link('main_16_pairs.csv','CSV')}。
'''
    text+=mdtable(['任务','比较','Δ体积pp','Δ件数','Δ质量pp','Δ高度mm','标签','决定层'],[[p['task_id'][-2:],p['comparison'],val(p['volume_delta_pp']),p['delta']['placed_items'],val(p['mass_ratio_delta_pp']),val(p['height_delta_mm']),p['evaluation']['label_v2'],p['evaluation']['decisive_level']] for p in pairs])
    text+='\n四任务等权汇总（以下范围均为观测min—max，不是置信区间）：\n'
    text+=mdtable(['比较','改善/中性/退化','平均Δ体积pp','中位Δ体积pp','观测范围pp'],[[p['comparison'],'/'.join(str(p['label_counts'].get(k,0)) for k in ['improved','neutral','degraded']),val(p['metrics']['volume_delta_pp']['mean']),val(p['metrics']['volume_delta_pp']['median']),f"[{val(p['metrics']['volume_delta_pp']['observed_min'])}, {val(p['metrics']['volume_delta_pp']['observed_max'])}] "] for p in ps])
    text+='\n六方法体积装入比例的任务等权描述：\n'
    text+=mdtable(['方法','均值','中位数','观测min—max'],[[p['method'],pct(p['metrics']['placed_volume_ratio']['mean']),pct(p['metrics']['placed_volume_ratio']['median']),pct(p['metrics']['placed_volume_ratio']['observed_min'])+'—'+pct(p['metrics']['placed_volume_ratio']['observed_max'])] for p in ms])
    text+=f'''\n每方法件数/体积/质量比例、固定容器利用率、高度、包络及件数均值/中位数/观测范围见{link('method_summary.json','完整方法汇总')}；各配对件数比、质量比、高度的同类汇总见{link('pair_summary.json','完整配对汇总')}。均为4任务等权，不做总体积加权或跨版本统一平均。统计置信区间为 `NOT_ESTIMATED`：任务仅4个、共享素材、无模型重复；未做显著性检验、bootstrap或功效分析。

本批T/none为2改善2退化；E/none在四任务体积均退化，任务等权均值为-11.11 pp；E/T为2改善2退化；E/无关E为1改善1退化2中性。正负与无收益均保留。E未显示一致增益，不能推广为E普遍无效；T的局部改善也不证明稳定收益。同单全装时固定容器利用率相同不能证明布局更优，少装形成的低垛高不能单独称改善。

## 部分补充与旧版本历史

第二单同v3的T/none、E/none和E/T保留；E/无关E因J0011技术超时无效，不按停前装入量排名。第二单几何的v2与其他v3方法比较为 `INVALID_CROSS_VERSION / NOT_RANKED`。第1单旧v2的六方法只作历史描述，所有方法均全装，冻结评价在装入等价后转入紧凑性层。历史紧凑性改善不混成主分析装载收益。
'''
    text+=mdtable(['任务/层','比较','Δ体积pp','Δ高度mm','标签','决定层'],[[p['task_id'][-2:]+'/'+('旧v2' if p['task_id'].endswith('01') else 'v3部分'),p['comparison'],val(p['volume_delta_pp']),val(p['height_delta_mm']),p['evaluation']['label_v2'],p['evaluation']['decisive_level']] for p in histpairs])
    text+=f'''\n无效配对的停前差值仅作进度描述，不是方法优劣。历史及第二单全部12槽位的完整指标见{link('historical_and_partial_metrics.csv','分层历史指标')}，原值与有效性理由见{link('historical_and_partial_pairs.json','历史/部分配对')}；{link('comparison_exclusions.json','排除登记')}明确保留版本与技术原因。

## 图表与固定案例

F1—F4均由标准Matplotlib读取保存JSON绘制，交付PNG预览及SVG/PDF矢量稿；3D为投影多边形导出，保留高分辨率PNG。无AI生成图、候选重建、轨迹求解或旧演示目录恢复。{link('figure_manifest.json','图表输入/设置')}与{link('visual_review.json','视觉检查记录')}登记实际数据、单位、色标、视角及遮挡限制。

**F1：四任务六方法装入比例和件数。** 所有面板同0—100%横轴，逐方法列件数并标完整状态；两本地方法完整保留。

!{link('figures/F1_main_loading.png','F1主结果')}

{link('figures/F1_main_loading.svg','F1 SVG')} · {link('figures/F1_main_loading.pdf','F1 PDF')}

**F2：16对体积装入差。** 颜色正负对称且零居中，pp为百分点；高度等次要代价在配对表中保留。无效历史配对不填0。

!{link('figures/F2_pair_deltas.png','F2配对差')}

{link('figures/F2_pair_deltas.svg','F2 SVG')} · {link('figures/F2_pair_deltas.pdf','F2 PDF')}

**F3：固定SYN_COMBO_03的none/T/E最终三维布局。** 同1200×1000×850 mm容器、轴比例、正交视角和箱体身份颜色；图例列整单24箱身份，图中仅画实际提交箱体。遮挡是单视角显示限制，不能从可见箱数读出提交数。三方法依次19/24、19/24、18/24，体积69.93%、73.85%、65.20%，高度785、705、655 mm，均EMPTY_POOL。

!{link('figures/F3_saved_layouts.png','F3最终布局')}

{link('figures/F3_saved_layouts.svg','F3 SVG')} · {link('figures/F3_saved_layouts.pdf','F3 PDF')}

{link('F3_plot_data.json','F3布局与逐箱动作追溯')}将56个提交动作逐一关联候选映射、当前公开输入/请求、真实原始响应账本、selection、monitor、COMMITTED检查点和最终布局索引。保存动作内monitor是提交前快照，其`committed=false`不能单独否定提交；本轮以STABLE、PLACE、COMMITTED阶段状态、前后件数增加1及最终布局共同确认，不篡改原字段。

首处分化按实际箱体、位置与朝向核对，未用Cxx或候选ID差异替代精确动作差异：
'''
    for d in div:
        ra=d['reference_action'];aa=d['alternative_action']
        text+=f"\n- {d['reference_decision']} 对 {d['alternative_decision']}：{ra['pick_item_id']}，none位置/朝向 `{ra['pose']}`，替代位置/朝向 `{aa['pose']}`；同公开物理前状态=`{d['same_physical_public_state']}`，同规范化候选动作池=`{d['same_normalized_selectable_action_pool']}`，同箱换位置。替代请求MemoryView有{len(d['alternative_memory_entries'])}条实际内容。\n"
    text+=f'''\n{link('first_divergence.json','首处分化证据')}保存公开可见箱体属性、池/状态摘要和实际记忆内容。T在D0000、E在D0004首次改变精确位置；E前四个动作与none一致。此后轨迹分化，不继续按同池反事实比较。指标neutral不等于动作相同或模型忽略记忆；行为不同也不证明有效利用。若解释为“不同位置影响后续空间/承载资源”，只能标 `ANALYSIS_HYPOTHESIS`，未证明模型内部理由、因果机制或全局最优。

**F4：固定历史范围停单与超时。** J0006_D0014在Y=305 mm切面显示请求箱体I0017位于下方空隙、实际z=0；旧v2内核恢复到z=490 mm，与动作不一致，`POSE_HEIGHT_MISMATCH / UNASSESSABLE`。基线STABLE，停前14/20；虚线为未提交的诊断位置，不是实际放置或坍塌。J0011_D0006/A000057为v3请求30.023秒超时，`UNKNOWN_SEND / UNKNOWN_IN_FLIGHT`；停前后均6/20，无选定新动作、监测或提交，不能与范围不可评价合并。

!{link('figures/F4_historical_failures.png','F4历史失败')}

{link('figures/F4_historical_failures.svg','F4 SVG')} · {link('figures/F4_historical_failures.pdf','F4 PDF')} · {link('F4_plot_data.json','F4精确剖面/超时数据')}

本批未观察到自然UNSTABLE，没有伪造失稳图。严格内部反力、保守凸包及退化接触的不可评价边界仍适用；只讨论轴对齐0/90、均匀刚性箱、竖直准静态反力与合成包装承载，不外推冲击、摩擦滑移、变形或真实坍塌。

## 注入、成本、时延与工程覆盖

库非空、检索非空、MemoryView非空、请求正文非空、确认实际非空发送及singleton单列。下表决策分母包括空池终止；singleton可有非空视图但无需发送。正文非空但未确认发送/响应的旧超时不补记成功。
'''
    text+=mdtable(['范围','方法','决策数','库非空','检索非空','视图非空','正文非空','真实非空发送','singleton/非空视图'],[[r['group'],r['method'],r['decisions'],r['library_nonempty_decisions'],r['retrieval_nonempty'],r['view_nonempty'],r['body_nonempty'],r['actually_sent_nonempty'],f"{r['singleton_decisions']}/{r['singleton_nonempty_view']}"] for r in covrows if r['method'] in ['T','E','unrelated_E']])
    text+=f'''\n{link('memory_coverage.csv','逐job覆盖表')}保留所有本地/无经验行、视图entry数与长度描述；{link('memory_coverage_summary.csv','覆盖汇总CSV')}提供计数。库非空用原逐决策library_nonempty事实，不冒称本轮重新生成或检索；非空注入成立不等于模型有效利用经验。

历史账目逐run从实际请求账本、summary和旧预算再核对，未新增采集：
'''
    text+=mdtable(['run','预约','已知真实调用','未知发送','输入tokens','输出tokens','费用'],[[Path(r['run']).parent.name,r['statistics']['send_reservations'],r['statistics']['known_real_model_calls'],r['statistics']['unknown_real_send_count'],r['statistics']['usage']['input_tokens'],r['statistics']['usage']['output_tokens'],'UNKNOWN'] for r in cost['per_run']])
    q=cost['pooled_actual_transport_latency_s']
    text+=f'''\n累计412预约、411已知真实调用、1未知发送，实际调用 `UNKNOWN` / 区间[411,412]；已知usage输入5,715,409 tokens、输出151,626 tokens，缺1次usage。费用 `UNKNOWN`，未用标价估账；旧未知发送不退款、不重试、不补成成功。JN5新增上述消耗均0。详细账目、原始样本及逐run统计见{link('cost_and_api_latency.json','成本/时延数据')}。

跨run API统计由412个实际保存transport样本重算（含1次超时，不代表412次已知成功模型调用）：p50={q['p50']:.6f} s，p95={q['p95']:.6f} s，总和={q['sum']:.6f} s。没有平均各job/run的p50/p95。候选、选择、监测、决策及order时延保留逐job原统计与样本量；job活动时间单列，候选/选择/监测/请求存在包含关系，不能相加当总墙钟。见{link('latency_by_job.json','阶段与job活动时延')}。旧保存校验墙钟另列 `saved_validation`，约37分48秒；它是历史校验，不是模型推理、订单执行或本轮分析耗时。本轮不新增计时实验。

工程层：全36身份及终止分母完整，主24全部执行至自然空池；不称36项全成功。注入层：T/E/无关E真实非空发送分别保留。行为层：固定案例同前状态/同动作池存在精确位置差异。收益层：四任务E/none全退化，T有正负；`NOT_ESTABLISHED`。公共硬过滤保证的零违规属于共同物理一致性，未作为选择器创新或经验收益。本轮未重新运行物理检查。

## 验收、复现与交接

| 项 | 状态 | 证据与边界 |
|---|---|---|
| P01 | PASS_IN_SYNTHETIC_SCOPE | 4×6主指标、16对、任务等权描述/观测范围、全36与分层历史；CI NOT_ESTIMATED |
| P02 | PASS_IN_SYNTHETIC_SCOPE | 工程、注入、行为、研究收益分开；正负/未知及预测静态边界保留 |
| P03 | PASS_IN_SYNTHETIC_SCOPE | F1—F4与固定首处分化关联保存候选、公开输入、真实响应、监测、COMMITTED及布局；假设明确 |
| P04 | PASS_IN_SYNTHETIC_SCOPE | 报告、CSV/JSON、PNG/SVG/PDF、预算/覆盖/限制、脚本/依赖/摘要/复现与两索引齐全 |

相对路径修订与原开发包的冻结scope、主指标/配对、案例及四幅PNG逐字节一致，见{link('path_portability_check.json','路径修订一致性检查')}。本机实际执行以下离线命令，均成功；开发时的方法名、提交快照语义及交付链接顺序检查已修正，仅重运行新分析，不改历史原件：

```bash
python3 {b}/analyze.py
python3 {b}/plot.py
python3 {b}/verify.py --report {report}
python3 {b}/deliver.py
```

最后一条生成本报告、收据并封存本新包。脚本拒绝覆盖已有delivery_manifest的封存目录。离线复现请指定未占用新目录，例如：

```bash
python3 {b}/analyze.py --output semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01
python3 {b}/plot.py --input semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01
python3 {b}/verify.py --input semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01
python3 {b}/deliver.py --input semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01 --report semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01/analysis_report.md
```

原scope冻结日期/来源保持不变，新目录是同一事后分析的再计算，不是新实验。{link('dependencies.json','实际依赖')}记录现有Python/numpy/Matplotlib版本，无新增安装。{link('analysis_checks.json','分析检查')}与{link('delivery_checks.json','交付检查')}区分本轮离线复验和历史validate-run声明；未扩展全量测试体系。图表检查包含视觉检查：F1同轴/状态件数，F2零中心对称pp，F3同容器/视角/颜色且承认遮挡，F4精确Y剖面与未提交标记。

主要交付入口：{link('evaluation_receipt.json','P01—P04收据')}、{link('delivery_manifest.json','文件归档清单')}、{link('handoff.json','handoff')}、{link('evidence_index.json','逐图/关键论断证据索引')}。本包受已有 `JEV_JN[0-9]*` 归档规则覆盖，未修改.gitignore；未自动git add/commit/push。delivery_manifest含包内文件与外置报告、两个索引摘要；清单不自摘要，handoff不反向签清单，避免循环。

限制与未证实：熟悉BED-BPP原型的新合成组合，合成包装承载；4任务共享素材且每方法单次运行，无独立真实来源、无重复、无置信区间；可满足性仍UNKNOWN，候选空池不证明全局无解；精确位置选择与后续结果仅描述关联，没有注册新反事实、因果收益、普遍策略、真实坍塌或跨数据集泛化证明。原真实来源 `JN4_B_admitted=false` 不改变。旧v2边界、旧超时和UNKNOWN发送保留。

已满足P01—P04的合成路线限定交付。下一接口仅为使用本报告和冻结证据开展经另行授权的研究规划/论文整理；本轮停止，不追加实验、补成功对照、投稿或推进新路线。
'''
    assert '/home/' not in text,'report_requires_repository_relative_commands'
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(text)
    # Report generated before verification, allowing actual link validation.
    result=verify(b);write('delivery_checks.json',result)
    criteria={k:{'status':'PASS_IN_SYNTHETIC_SCOPE','evidence':v} for k,v in {'P01':['main_24_metrics.json','main_16_pairs.json','method_summary.json','pair_summary.json','all_36_metrics.json'],'P02':['memory_coverage_summary.json','first_divergence.json','cost_and_api_latency.json'],'P03':['figure_manifest.json','evidence_index.json','visual_review.json'],'P04':[str(report),'dependencies.json','delivery_checks.json','handoff.json','delivery_manifest.json']}.items()}
    receipt={'version':'jev_jn5_analysis_receipt_v1','analysis_type':scope['analysis_type'],'criteria':criteria,'analysis_complete_in_synthetic_scope':True,'completion':'JN5合成路线限定分析交付完成','research_benefit':'NOT_ESTABLISHED','observed_E_none':'NEGATIVE_IN_OBSERVED_TASKS','main_observations':4,'main_slots':24,'main_pairs':16,'historical_slots':12,'full_slots':36,'statistical_ci':'NOT_ESTIMATED','new_operations':scope['operations'],'JN4_B_admitted':False,'stop':True,'verification':result}
    write('evaluation_receipt.json',receipt)
    write('handoff.json',{'version':'jev_jn5_analysis_handoff_v1','report':str(report),'receipt':str(b/'evaluation_receipt.json'),'scope':str(b/'analysis_scope.json'),'evidence':str(b/'evidence_index.json'),'manifest':str(b/'delivery_manifest.json'),'completion':'JN5合成路线限定分析交付完成','research_benefit':'NOT_ESTABLISHED','next':'only independently authorized planning/paper work; no automatic experiments','new_operations':scope['operations'],'stop':True})
    (b/'reproduce.md').write_text('# Offline reproduction\n\nRun from NBU_Papper root. Existing sealed directories refuse overwrite.\n\n```bash\n'+f'python3 {b}/analyze.py --output semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01\npython3 {b}/plot.py --input semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01\npython3 {b}/verify.py --input semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01\npython3 {b}/deliver.py --input semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01 --report semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01/analysis_report.md\n```\n\nThe scope file preserves the original post hoc freeze; dependency identity is in dependencies.json. Original saved records are required. No model or runtime replay. For sealing a reproduced copy, copy the original visual_review.json as prior review evidence or explicitly inspect regenerated figures; do not claim a new visual review automatically.\n')
    result=verify(b,report,deferred={(b/'delivery_manifest.json').resolve()})
    write('delivery_checks.json',result)
    receipt['verification']=result;write('evaluation_receipt.json',receipt)
    files=[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(b.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.name!='delivery_manifest.json']
    ext=[report]
    if report==REPORT:ext += [Path('docs/02_阶段实施方案/Jev/README.md'),Path('docs/03_阶段产出分析/Jev/README.md')]
    write('delivery_manifest.json',{'version':'jev_jn5_delivery_manifest_v1','files':files,'external_files':[{'path':str(p),'sha256':sha(p)} for p in ext],'self_hash':'EXCLUDED_TO_AVOID_CYCLE','original_inputs':'input_manifest.json','no_git_commit_or_push':True})
    assert verify(b,report)==result
    print(json.dumps({'criteria':{k:v['status'] for k,v in criteria.items()},'report':str(report),'checks':result,'files':len(files)},ensure_ascii=False))
if __name__=='__main__':main()
