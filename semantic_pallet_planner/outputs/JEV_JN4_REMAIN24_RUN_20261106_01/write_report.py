"""Render the saved-record execution report; never starts an experiment."""
from pathlib import Path
import json
B=Path(__file__).parent
read=lambda n:json.loads((B/n).read_text())
r=read('evaluation_receipt.json');d=read('descriptive_summary.json');rows=read('all_36_slots.json');pairs=read('paired_comparisons_v2.json');coverage=read('coverage_summary.json')
report=Path('docs/03_阶段产出分析/Jev/Jev_JN4剩余24项真实执行与阶段收尾验收_20261106.md')
prefix='../../../'+B.resolve().relative_to(Path.cwd()).as_posix()
names={'local_geometry_test_double':'几何','local_first_test_double':'固定顺序','jev_no_memory':'无经验','jev_with_trajectory':'T','jev_with_contrast_experience':'E','jev_with_unrelated_E_control':'无关E'}
new=r['new_request_statistics'];total=r['cumulative_requests'];complete=r['new24_execution_coverage_complete']
def fmt(x):return f'{x:.4f}' if isinstance(x,float) else str(x)
text=['# Jev JN4剩余24项真实执行与阶段收尾验收','',
 '日期：2026-11-06。接续验收基线 `52d3252e`，进入HEAD `c3ff2a09`（后续只同步执行方案及索引）。用户明确授权冻结24项的本地执行和真实Jev调用；未开展接入开发、Fake回归、全量历史测试、训练或经验生成，未commit/push、未启动子代理。原未跟踪原始数据目录保留。','',
 f'本次收尾 **{r["new24_closed"]}/24**，未运行 **{r["new24_not_run"]}/24**；停止状态 `{r["stop_reason"]}`。'+('本次24项执行覆盖完成；不表示全部装完，也不改写旧技术失败。' if complete else '本次部分完成并技术停批；没有重试或自动追加下一层接续。'),'',
 f'[执行收据]({prefix}/evaluation_receipt.json) · [新24项]({prefix}/new_24_slots.csv) · [全36项JSON]({prefix}/all_36_slots.json) · [全36项CSV]({prefix}/all_36_slots.csv) · [配对]({prefix}/paired_comparisons_v2.json) · [账目]({prefix}/budget_accounting.json) · [handoff]({prefix}/handoff.json)','',
 '## 实际执行与身份','',
 '唯一计划 `semantic_pallet_planner/outputs/JEV_JN4_REMAIN24_20261106_01/plan`，唯一run为同包 `run`；分析包另置 `JEV_JN4_REMAIN24_RUN_20261106_01`，没有作为新的执行目录。先执行原validate，返回PASS_STATIC_ONLY；初始run及remaining24_owner均不存在，随后只调用一次run。源码、依赖、数据、候选、提示、T/E/对照、查询和排除、v12及精确位置监测v3均按冻结计划，未升级依赖、重签计划或修改生产源码。','',
 '当日核对官方[System One](https://docs.typesafe.ai/api/system-one)、[模型](https://docs.typesafe.ai/models)、[Choice](https://docs.typesafe.ai/primitives/choice)及[错误合同](https://docs.typesafe.ai/api/errors)，与冻结接口匹配；固定jev-1.14.0、30秒超时、零重试、10000事件/1800秒活动看门狗。凭证沿既有credential加载后仅注入子进程环境，未打印、复制到产物或归档鉴权头。没有服务探测/冒烟调用；实际服务元数据见actual_service_observation.json。费用以实际可得记录为准，官方标价不冒充账单。','',
 '原account/owner.json保持原字节；首次执行由公共入口登记remaining24_owner.json，绑定旧owner、停止父run摘要、24项范围、新plan/run。登记和摘要见owner_records.json。旧J0000—J0011不重跑；旧A000057/J0011_D0006未知发送保留，不退款、不重发。未创建新首单门槛或经验命中筛选。','',
 '实际命令（环境和时间另见preflight.json、execution_command.json、execution_exit.json）：','',
 '```bash',
 'PYTHONPATH=semantic_pallet_planner/src python3 -m semantic_pallet_planner.jev_select.packaging_exact_orders validate \\\n  --plan semantic_pallet_planner/outputs/JEV_JN4_REMAIN24_20261106_01/plan',
 'PYTHONPATH=semantic_pallet_planner/src python3 -m semantic_pallet_planner.jev_select.packaging_exact_orders run \\\n  --plan semantic_pallet_planner/outputs/JEV_JN4_REMAIN24_20261106_01/plan',
 'PYTHONPATH=semantic_pallet_planner/src python3 -m semantic_pallet_planner.jev_select.packaging_exact_orders validate-run \\\n  --output semantic_pallet_planner/outputs/JEV_JN4_REMAIN24_20261106_01/run','```','',
 'run由execute_frozen.py调用上述模块命令，沿既有credential方式注入环境；调用一次、无resume或隐式重试。24个job已结束且run清单保存后，独立只读校验与内部收尾核验并行；两者完成后再验收交付。validate-run只检验保存事实，不回放轨迹、检索、选择或监测求解。本次有1728份阶段检查点，收尾校验耗时较长；未临时修码或跳过检查，时间记录见执行及校验收据。','',
 '## 全36槽位与完整订单指标','',
 'R0＝JEV_JN4_SYNTH_EXEC_20261105_01/run（旧7项，v2，源码交付34fc871d）；R1＝JEV_JN4_EXACT_20261106_01/run（已结束5项，v3，源码交付15d0c809）；R2＝JEV_JN4_REMAIN24_20261106_01/run（本次24项，v3，源码交付52d3252e）。以上run均位于semantic_pallet_planner/outputs/。每行完整源码manifest摘要、策略身份、终止原因及证据路径保存于JSON/CSV；交付提交仅定位归档，冻结manifest是源码身份依据。','',
 '| job | 任务 | 方法 | 算法/源码/run | 实际状态 | 件数 | 件数比 | 体积比 | 质量比 | 容器利用率 | 高mm/包络 | 真实非空注入 |',
 '|---|---|---|---|---|---:|---:|---:|---:|---:|---|---:|']
for i,row in enumerate(rows):
 group=0 if i<7 else 1 if i<12 else 2
 version=f'v{2 if group==0 else 3}/{row["source_delivery_commit"]}/R{group}'
 values=[row['job_id'],row['task_id'],names[row['method_id']],version,row['status']['category']];m=row['metrics']
 if isinstance(m,dict):
    l=m['loading'];values += [f'{l["placed_items"]}/{l["planned_items"]}',l['placed_item_ratio'],l['placed_volume_ratio'],l['placed_mass_ratio'],m['fixed_container_utilization'],f'{fmt(m["actual_height_mm"])}/{fmt(m["envelope_utilization"])}',m['memory_metrics']['actually_sent_nonempty_count']]
 else:values += [m]*7
 text.append('| '+' | '.join(map(fmt,values))+' |')
text += ['',f'本次24项状态：`{r["new24_categories"]}`；全36槽位状态：`{r["all36_categories"]}`。已保存监测状态计数：`{d["new24_observed_monitor_statuses"]}`（仅实际观察动作，不给未运行项填零）。', '',
 '完整指标JSON保留装入件数/体积/质量比例、固定容器利用率、高度/包络、原面积分载账本、监测状态及原因、首次预测失稳进度、不可评价/技术失败、每阶段时延n/p50/p95、请求usage与费用。检索非空、视图非空、请求体非空和实际发送非空分别记录于coverage_summary.json，singleton及其非空视图也单列。不能以库非空代替真实注入。NOT_RUN、NA、UNKNOWN按保存记录保留，不虚填0。','',
 'EMPTY_POOL只表示冻结采样候选池为空，不证明全局无解；预测静态失稳不是真实坍塌。失败箱不提交；预测失稳、不可评价、技术失败分开记录。全单装入时固定容器利用率相同，不能单凭它判断布局优劣。','',
 '## 同版本配对与有限结论','',
 '| 任务 | 比较 | 算法 | v2评价标签 | 决定层 |','|---|---|---|---|---|']
for pair in pairs:
 e=pair['evaluation'];text.append('| '+' | '.join([pair['task_id'],pair['comparison'],pair['algorithm'],e['label_v2'],e.get('decisive_level','NOT_RUN')])+' |')
text += ['',f'本次第3—6单配对标签计数：`{d["new24_paired_labels"]}`。其中E/无经验为`{d["new24_E_vs_none_labels"]}`：这四个新订单中，E装入体积均低于无经验，是本批有限负向观察，不能扩大为E普遍无效或因果结论。', '',
 '四个新订单中，T/none为2改进、2退化；E/none为4退化；E/T为2改进、2退化；E/无关E为1改进、1退化、2项指标等价。neutral只表示冻结指标范围内等价，不说明动作、箱集或布局相同。比较使用冻结装入量优先评价v2，先稳定完整完成/体积，再件数质量，只有同装入量才比较高度与包络；完整delta及次要指标回退见paired_comparisons_v2.json。第2单E/无关E配对仍因旧J0011技术失败无效，没有补跑洗掉；第1单v2仅为历史，不与v3合并成同算法重复证据。轨迹分化后不将不同状态下的动作当同池反事实，行为序列只作描述。','',
 '本轮合成路线使用熟悉原型的新组合及合成包装承载参数，单次小样本；不证明真实独立来源泛化、稳定因果收益、全局最优或真实坍塌率。公共硬过滤零违规不当作选择器创新收益。研究收益保持NOT_ESTABLISHED，具体任务上的改善/退化仅按保存结果描述。','',
 '## 请求、预算、技术状态与收尾','',
 f'新run预约 **{new["send_reservations"]}**，已知调用 **{new["known_real_model_calls"]}**，未知发送 **{new["unknown_real_send_count"]}**，网络尝试{new["network_attempts"]}，失败请求{new["failed_requests"]}。实际调用 `{new["actual_model_api_calls"]}`；区间 `{new["real_model_call_interval"]}`。请求时延 `{new["request_latency_s"]}`。','',
 f'累计预约 **121+{new["send_reservations"]}={total["send_reservations"]}/656**，已知调用 **120+{new["known_real_model_calls"]}={total["known_real_model_calls"]}**，未知 **1+{new["unknown_real_send_count"]}={total["unknown_real_send_count"]}**，实际调用保持 `{total["actual_model_api_calls"]}`/区间 `{total["real_model_call_interval"]}`。全局余额{total["remaining_reservations"]}；本次535共享余额同时受逐job合计512约束，未转用旧23次空余，不退款未知发送。','',
 f'新run usage：`{new["usage"]}`；累计usage：`{total["usage"]}`。累计网络尝试{total["network_attempts"]}，复用不重复计发送；跨run请求ID以run为作用域。实际模型费用UNKNOWN；缺失usage、未知服务端处理与历史费用均不补成0或成功。','',
 f'保存记录校验：`{read("saved_validation.json")}`；技术停止/诊断见stop_diagnosis.json及unknown_sends.json。旧错误与旧未知请求保留；即使新run完成，也不能把原矩阵改称36项全成功。','',
 '| 验收 | 实际状态 |','|---|---|']
for key,value in r['criteria'].items():text.append(f'| {key} | {value["status"]} |')
text += ['', '本次执行覆盖完成且保存记录/账目可审计，可提交JN5限定分析准入审查；本轮没有自动开展JN5。' if r['JN5_limited_analysis_review_eligible'] else '本次技术停批、覆盖仍有缺口，暂不满足方案所定JN5限定分析准入条件；如实交付部分结果，后续由用户另定。', '',
 '旧真实来源JN4_B_admitted=false保持原适用范围，不因合成路线运行而改为真实来源准入。工程执行、真实经验注入和研究收益分别表述。完成或技术停止后立即交付并停止；不追加实验、重试、训练、经验生成或提示调整。','']
report.write_text('\n'.join(text))
index=report.parent/'README.md';s=index.read_text();entry=f'| [剩余24项真实执行与阶段收尾]({report.name}) | 本次{r["new24_closed"]}/24收尾、{r["new24_not_run"]}未运行；累计预约{total["send_reservations"]}/656，未知{total["unknown_real_send_count"]}；{r["stop_reason"]}，分算法/源码/run保留36分母。 |\n'
if report.name not in s:index.write_text(s.replace('|---|---|\n','|---|---|\n'+entry,1))
print(report)
