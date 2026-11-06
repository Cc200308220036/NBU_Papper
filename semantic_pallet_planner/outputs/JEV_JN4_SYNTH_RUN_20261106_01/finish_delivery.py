"""Finalize documentary delivery after the authorized runner has exited."""
import hashlib
import json
from pathlib import Path
from collections import Counter

OUT=Path(__file__).resolve().parent
ROOT=Path.cwd()
def read(p): return json.loads(p.read_text())
def write(n,x): (OUT/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
planroot=Path('semantic_pallet_planner/outputs/JEV_JN4_SYNTH_EXEC_20261105_01/plan')
p=read(planroot/'plan.json');run=Path(p['run_location'])
rows=read(OUT/'all_slots.json');s=read(OUT/'descriptive_summary.json')
pair=read(OUT/'paired_comparisons_v2.json');summary=read(run/'summary.json')
gate=read(run/'first_gate.json') if (run/'first_gate.json').exists() else {'status':'NOT_PUBLISHED_TECHNICAL_STOP'}
calls=summary['request_statistics'];closed=sum(r['status']['state']=='FINISHED' for r in rows)
notrun=sum(r['status']['state']=='NOT_RUN' for r in rows)
stop='MATRIX_COMPLETED' if closed==36 else gate['status'] if gate['status']!='PASS' else 'STOP_AFTER_FIRST_GATE_PASS_SEE_RUN_STATUS'
if summary['status']=='ERROR':stop='STOP_TECHNICAL'
technical=read(run/'technical_failure.json') if (run/'technical_failure.json').exists() else None
diagnosis=read(OUT/'stop_diagnosis.json') if (OUT/'stop_diagnosis.json').exists() else None
full=closed==36 and summary['status']!='ERROR'
criteria={'V01':'PASS_SYNTHETIC_SCOPE' if full else 'PARTIAL_EXECUTED_SCOPE_WITH_STOP',
 'V02':'PASS_EXECUTED_SCOPE_FROZEN_COMMON_CONTRACT',
 'V03':'PASS_SAVED_VALIDATION' if summary['status']!='ERROR' else 'PARTIAL_BATCH_SCOPE_CLASSIFICATION_FAILURE_SEE_EVIDENCE',
 'V04':'PASS_COMPLETE_DENOMINATOR_AND_UNKNOWN_COST_RETAINED',
 'V05':'PASS_REGISTERED_SYNTHETIC_MATRIX' if full else 'PARTIAL_UNEXECUTED_PAIRS_RETAINED',
 'V06':'PASS_DELIVERY_RESEARCH_BENEFIT_NOT_ESTABLISHED'}
receipt={'version':'jev_synthetic_six_method_execution_receipt_v1','date':'2026-11-06','head':'34fc871d',
 'scope':'six frozen synthetic combination orders; not independent unseen real sources',
 'plan':str(planroot),'run':str(run),'analysis':str(OUT.relative_to(ROOT)),
 'first_gate':gate['status'],'closed_slots':closed,'not_run_slots':notrun,'planned_slots':36,
 'request_budget':p['request_budget'],'request_statistics':calls,'stop_reason':stop,
 'criteria':criteria,'research_benefit':'NOT_ESTABLISHED','JN4_B_admitted':False,'technical_stop_evidence':technical,'stop_diagnosis':diagnosis,
 'real_injection':{r['job_id']:{'task':r['task_id'],'method':r['method_id'],'count':r['metrics']['memory_metrics']['actually_sent_nonempty_count']} for r in rows if isinstance(r['metrics'],dict)},
 'validation':'runner validates saved records before returning; see commands and exit records',
 'source_changed':False,'experience_updated':False,'implicit_retries':0,'extra_model_probes':0,
 'continuation':str(run/'continuation.json') if (run/'continuation.json').exists() else 'NOT_RUN',
 'resume_commands':0,'next':'stop; no further experiment authorized by this receipt'}
write('evaluation_receipt.json',receipt)
report=Path('docs/03_阶段产出分析/Jev/Jev_JN4合成组合订单六方法执行验收_20261106.md')
rel='../../../'+str(OUT.relative_to(ROOT))
text=['# Jev JN4合成组合订单六方法执行验收','',
 '日期：2026-11-06。执行基线 `34fc871d`。本轮按目标文件授权执行冻结的合成路线；未修改生产代码、策略、数据、提示、候选器、PCT或T/E，不commit/push，不启动子代理。既有 `raw/mixed_pallet_boxes/` 保留。',
 '',f'首批门槛 **{gate["status"]}**；已收尾 **{closed}/36** 槽位，未运行 **{notrun}**；停止原因 `{stop}`。首批和后续共用冻结run及账本，不重置额度。',
 '',f'[执行收据]({rel}/evaluation_receipt.json) · [全部指标JSON]({rel}/all_slots.json) · [CSV]({rel}/all_slots.csv) · [配对比较]({rel}/paired_comparisons_v2.json) · [handoff]({rel}/handoff.json)',
 '',f'实际运行目录：`{run}`。计划：`{planroot}`，数据身份 `{p["data"]["data_identity"]}`。父准备包与旧收据不改写；旧真实来源 `JN4_B_admitted=false` 保留。',
 '', '## 执行与协议', '',
 f'[实际命令与环境]({rel}/commands.json)、[官方协议核对]({rel}/official_api_review.json)、[父包保护]({rel}/preservation_check.json)、[运行证据摘要]({rel}/run_evidence_identity.json)随包交付。',
 '', '2026-11-06查阅 [System One](https://docs.typesafe.ai/api/system-one)、[Models](https://docs.typesafe.ai/models)、[Choice](https://docs.typesafe.ai/primitives/choice)、[Errors](https://docs.typesafe.ai/api/errors)。冻结服务为 `https://api.typesafe.ai/v1/systemone`，模型 `jev-1.14.0`，原生Choice；30秒超时、零重试。未做探测请求。凭证仅通过既有credential加载器进入子进程环境，不写入产物。',
 '', '本机已完成冻结计划校验。正式运行器负责保存记录校验；本轮未重跑历史测试或Fake回归、未额外回放轨迹。各job请求、选择、监测、提交、检查点和阶段快照保存在原run，分析脚本仅读取保存事实。',
 '', '## 全36槽位', '',
 '体积/质量/件数比例分母始终为完整订单；未运行项保留NOT_RUN。完整JSON另含到货、预测静态失稳进度、不可评价原因、技术错误、物理诊断、全部记忆覆盖、singleton和分阶段时延。', '',
 '| 任务 | 方法 | 状态/终止 | 件数 | 件数比例 | 体积比例 | 质量比例 | 固定容器利用率 | 垛高mm | 包络利用率 | 非空真实注入 |',
 '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
names=dict(zip(p['method_ids'],['几何','固定顺序','无经验','T','E','无关E']))
def fmt(v):return f'{v:.6f}' if isinstance(v,float) else str(v)
for r in rows:
 m=r['metrics'];vals=[r['task_id'],names[r['method_id']],r['status']['category']]
 if isinstance(m,dict):
  l=m['loading'];vals += [f'{l["placed_items"]}/{l["planned_items"]}',l['placed_item_ratio'],l['placed_volume_ratio'],l['placed_mass_ratio'],m['fixed_container_utilization'],m['actual_height_mm'],m['envelope_utilization'],m['memory_metrics']['actually_sent_nonempty_count']]
 else: vals += [('NOT_RUN' if r['status']['state']=='NOT_RUN' else 'UNKNOWN')]*8
 text.append('| '+' | '.join(fmt(v) for v in vals)+' |')
text += ['', '## 配对与结论边界','', '冻结评价 `jev_branch_comparison_rule_v2` 按稳定完整完成→装入体积→件数/质量Pareto→同装入量下紧凑性比较；方向为后者减参考。不可评价/技术状态不作为有效策略排名。', '', '| 任务 | 比较 | v2结果 | 决定层 |', '|---|---|---|---|']
for x in pair:text.append(f'| {x["task_id"]} | {x["comparison"]} | {x["evaluation"]["label_v2"]} | {x["evaluation"].get("decisive_level","NOT_RUN")} |')
text += ['',f'配对标签分布：`{dict(Counter(x["evaluation"]["label_v2"] for x in pair))}`。', '',
 '工程运行状态、实际经验注入、行为差异和研究收益分别记录。选箱与位置序列见 `behavior_observations.json`；轨迹分化后不把不同状态当同池反事实。同订单全部装入时固定容器利用率不能证明布局更优。公共硬过滤的零违规不作为选择器收益。', '',
 '这是6个合成组合订单、每方法1次的小样本描述；尺寸/质量来自熟悉的BED-BPP原型，包装承载为合成参数。不能宣称真实业务新订单、独立未见来源泛化、稳定因果收益或全局最优；预测静态失稳不称真实坍塌。研究收益 `NOT_ESTABLISHED`，不以E胜出作为工程验收条件。', '',
 '## 请求、时延与成本','',f'完整账目：`{json.dumps(calls,ensure_ascii=False)}`。共享发送上限656；首单上限64。未知费用保留UNKNOWN。模型调用、预约、网络尝试、未知发送和失败分别列出；singleton不计模型调用。', '',
 '逐job决策、候选、选择、监测和订单活动时延含n/p50/p95，见全部指标JSON；请求时延见上述账目。校验墙钟不混入API时延，整条命令的额外收尾开销不据活动时延推定。', '',
 '## V01—V06与停止','', '| 条目 | 实际状态 |','|---|---|']
for k,v in criteria.items():text.append(f'| {k} | {v} |')
text += ['', 'V条目仅对应本次合成专用冻结合同，不能替代旧真实来源准入。未运行和失败保留完整分母，不以总体PASS覆盖缺失或技术问题。', '',
 f'批次技术停止记录：`{json.dumps(technical,ensure_ascii=False)}`。各job的不可评价原因见 `all_slots.json` 的 `monitor_reasons`，不将UNASSESSABLE归为预测失稳或策略劣势。', '',
 ('本次只读诊断：第二单几何方法已提交14/20箱，14次STABLE、1次UNASSESSABLE。实际终止原因 `POSE_HEIGHT_MISMATCH` 在冻结允许列表中；批次代码却把包含14次成功 `CONTACT_NETWORK_BALANCED` 的全部 `monitor_reasons` 与不可评价白名单比较，导致 `UNREGISTERED_MONITOR_SCOPE` 误报。位置为 `packaging_evaluation_orders.py:254`。这是冻结批次范围检查问题，不是新发现的未登记PCT范围；仍保留原始技术停批，未改算法、白名单或源码，未继续第8项。见 `stop_diagnosis.json`。' if diagnosis else '未额外诊断或更改运行行为。'), '',
 f'停止于 `{stop}`。下一步只可对当前交付进行只读复核；新增实验、重试、策略/经验修改或JN5开发须另行明确任务。本轮未追加训练、经验生成或未登记消融。','']
report.write_text('\n'.join(text))
index=report.parent/'README.md';old=index.read_text()
entry=f'| [JN4合成组合订单六方法执行]({report.name}) | 首批{gate["status"]}；{closed}/36收尾，{notrun}未运行；发送{calls["network_attempts"]}/656，费用UNKNOWN；{stop}，合成描述性范围，研究收益未建立。 |\n'
if report.name not in old:index.write_text(old.replace('|---|---|\n','|---|---|\n'+entry,1))
write('handoff.json',{'version':'jev_synthetic_six_method_handoff_v1','receipt':'evaluation_receipt.json','report':str(report),'plan':str(planroot),'run':str(run),'first_gate':gate['status'],'stop_reason':stop,'stopped':True,'JN4_B_admitted':False,'research_benefit':'NOT_ESTABLISHED','next':'read-only quality review; no automatic further runs'})
write('delivery_manifest.json',{'version':'jev_synthetic_six_method_delivery_manifest_v1','report':{'path':str(report),'sha256':sha(report)},'run_manifest':{'path':str(run/'delivery_manifest.json'),'sha256':sha(run/'delivery_manifest.json')},'files_sha256':{str(f.relative_to(OUT)):sha(f) for f in sorted(OUT.rglob('*')) if f.is_file() and f!=OUT/'delivery_manifest.json'}})
print(json.dumps({'report':str(report),'first_gate':gate['status'],'closed':closed,'not_run':notrun,'stop_reason':stop},ensure_ascii=False))
