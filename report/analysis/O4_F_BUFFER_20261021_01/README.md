# O4-F独立复核证据

最终验收：2026-10-22；对应实现规范20261021。F1—F10、360条主运行、独立重复、恢复、完整重跑及独立事件审核全部通过。源码与原数据保护未放宽。

- `evidence.json`：逐条门槛与实际证据映射。
- `completion_audit.json` / `audit_completion.py`：9123个事件、3980次物理及参考业务、7560项核心指标、390378次候选评价计数的独立复核；原62072文件不变。
- `full_rerun_replay.json` / `parallel_full_replay.py`：360条实际从空状态重跑，逐候选、编译、搜索trace、动作、终止一致；只读。
- `semantic_metrics.json` / `audit_semantics.py`：4275次实际编译的完整语义、对象集合及允许集合；真实模型准确率为null。
- `future_environment_audit.json`：两次环境前缀执行，改变13个未到货箱后，首次动作与搜索trace不变。
- `effect_analysis.json` / `results_fragment.md`：12来源×6配置的描述性配对效果；搜索35单多放、17单少放；启发式优于搜索。
- `pytest.xml`、`binding_pytest.xml`、`dataset_pytest.txt`：344＋1项规划器测试、7项数据集回归通过。
- `legacy_*_snapshot_replay.json` / `replay_legacy_*.py`：冻结A/B、C源码实际回放；路径解析映射回原数据，保护检查真实执行，不改旧文件。
- `cli_help.txt`、`single_cli.json`、`capacity2_cli.json`：实际运行入口与容量试跑证据。

本目录脚本从仓库根目录执行；历史快照回放需设置`PYTHONDONTWRITEBYTECODE=1`，避免在冻结目录产生缓存。完整实验目录保持封存，不在其中改写报告。正式图像、人工审阅、真实模型及E扩展未完成；F无需Flash。
