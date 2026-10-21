# O3 数值稳定 V2：前四步验收附件

2026-10-20，整体 **PASS**；真实 API 调用 **0**。六个旧实验的 17309 文件和原包源码不变，旧 B PASS / C FAIL 保留。

| 文件 | 证据 |
|---|---|
| [acceptance_report.json](acceptance_report.json) | 前四步整体验收与 API 委托边界 |
| [verification_report.json](verification_report.json) | 两环境测试、两矩阵实际命令和源码摘要 |
| [protected_runs.before.json](protected_runs.before.json)、[protected_runs.after.json](protected_runs.after.json) | 6 个旧实验全部文件清单和 SHA256 |
| [legacy_source.before.json](legacy_source.before.json) | 改动前已有包源码摘要，最终逐项核验无修改 |
| [environment.py311.json](environment.py311.json)、[environment.py313.json](environment.py313.json) | 实际 Python、路径、平台及已安装依赖 |
| [tests.py311.log](tests.py311.log)、[tests.py313.log](tests.py313.log) | 两环境均 185 passed；3.11 另有 14 条原依赖警告 |
| [matrix.py311.log](matrix.py311.log)、[matrix.py313.log](matrix.py313.log) | 两环境各 120 episode 实际运行 stdout；各附同名 JSON 命令和退出码 |
| [saved_request_cross_runtime.json](saved_request_cross_runtime.json) | 五个历史分叉请求×三变体的跨解释器实测 |
| [cross_runtime_matrix.json](cross_runtime_matrix.json) | 120 episode / 1521 决策交叉一致，离散动作和物理哈希精确比较 |
| [version_metric_changes.json](version_metric_changes.json) | V2 与旧布局、V1 C 的逐单主要指标变化，含负结果 |
| [finalize.py](finalize.py) | 只读复核旧实验并汇总前四步验收，不发起 API |

主基线：[PY311](../../../semantic_pallet_planner/outputs/EXP_OPT_O3_LAYOUT_STABLE_V2_PY311_20261020_01/README.md)。交叉复本：[PY313](../../../semantic_pallet_planner/outputs/EXP_OPT_O3_LAYOUT_STABLE_V2_PY313_20261020_01/README.md)。两次执行只对应 120 个逻辑任务，不增加独立研究样本量。

详细解释见[阶段结果报告](../../../docs/03_阶段产出分析/O3/O3数值稳定V2修复与前四步验收_20261020.md)，用户后续 API 指令见[V2 交接手册](../../../docs/04_运行与复核手册/O3布局数值稳定V2运行与API交接_20261020.md)。
