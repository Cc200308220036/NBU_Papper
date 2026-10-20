# O3失败归因产物

本目录是2026-10-19的正式诊断输出，来自只读的`EXP_OPT_O3B_BUSINESS_OBSERVE_20261016_REMOTE_01`。无模型调用、无原始实验改写。`_01`为首轮输出；以本目录为准。

完整结论、方法、局限与复算命令见[O3失败归因报告](../../../docs/03_阶段产出分析/O3/O3失败归因与轨迹分叉诊断_20261019.md)。

- [失败任务](failure_cases.csv)、[首次分叉](divergence_steps.csv)、[逐状态指标](state_metrics.csv)。
- [终止时刻对照](terminal_diagnostics.csv)、[过滤漏斗](terminal_gate_funnel.csv)。
- [单动作干预汇总](single_action_interventions.csv)；完整模拟续跑保存在`counterfactuals/`。
- JSON详情：[分叉](divergence_details.json)、[终止](terminal_details.json)。
- 校验：[摘要](analysis_summary.json)、[逐项检查](checks.json)、[原始文件清单](source_inventory.before.json)。
- `terminal_attempts_*.csv`逐条列出枚举位姿及首次拒绝原因。

## 图像索引

图中到货序号从1开始；原日志`step_index`从0开始。左中两列比较相同订单和到货时刻、各方法自己的实际布局；第二行Geometry的标题指Parser失败的检查时刻，不表示Geometry也失败。叠箱在俯视投影中重叠，颜色是顶面高度，文字`z`是箱底高度；红虚线表示最大地面全高净空矩形。面积指标的完整定义和限制见报告第3节。

| 案例 | 图像 |
|---|---|
| 0052/P0 | [打开](figures/O3_SCN_0052_P0.png) |
| 0052/P1 | [打开](figures/O3_SCN_0052_P1.png) |
| 0053/P0 | [打开](figures/O3_SCN_0053_P0.png) |
| 0053/P1 | [打开](figures/O3_SCN_0053_P1.png) |
| 0054/P1 | [打开](figures/O3_SCN_0054_P1.png) |
| 0056/P1 | [打开](figures/O3_SCN_0056_P1.png) |
| 0057/P0 | [打开](figures/O3_SCN_0057_P0.png) |
| 0060/P0 | [打开](figures/O3_SCN_0060_P0.png) |
| 0060/P1 | [打开](figures/O3_SCN_0060_P1.png) |

单动作干预允许偏离原政策的严格软最优，只用来诊断历史布局选择的后果；不是新算法、独立test或实际Flash续跑。不得把4个放完写成4个完整无违规，也不得把9个政策任务当成9个独立订单。
