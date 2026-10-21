# O3 布局 Flash 阶段 B/C 只读复核

2026-10-20。本目录只新增分析附件，没有改写 B/C 或历史布局实验，没有新增 API 调用。

结论：B 工程验收 PASS；C 完成 240 episode，但历史布局一致性 FAIL。B 的 508 次和 C 的 1495 次 Flash AST/同状态动作均与 Parser 一致。C 的 5 个历史差异来自 `relaxed_wo_floor`；在本机两个解释器上复现了同一特征求平均的末位差异及其排序影响。

| 文件 | 内容 |
|---|---|
| [review_data.json](review_data.json) | B/C 验收、API、指标、配对区间、一致率及原交付清单核验 |
| [B_replay.json](B_replay.json)、[C_replay.json](C_replay.json) | 使用原 pallet_vlm Python 3.11.16 实际重新回放的结果；C 的 5 条失败被保留 |
| [first_divergences.json](first_divergences.json) | 5 个首动作分叉的同状态检查、允许集合和相关候选特征/评分 |
| [historical_summary_changes.json](historical_summary_changes.json) | 当前 C 与旧布局实验的主要逐单指标变化 |
| [numeric_reproduction.json](numeric_reproduction.json) | 同一输入特征分别由 Python 3.13.5 与 3.11.16 求平均的实际结果 |
| [provenance.json](provenance.json) | 原报告与表格 SHA256、分析脚本摘要 |
| [review.py](review.py) | 纯读取抽取脚本，使用两份已归档的回放报告；不会调用 API |

重新抽取分析文件（不重新回放实验）：

```bash
python report/analysis/O3_LAYOUT_FLASH_BC_REVIEW_20261020_01/review.py
```

若默认 `python` 不是 3.13，`numeric_reproduction.json` 第一项会随所用解释器变化，必须阅读其中明确保存的版本。当前归档是 3.13.5 与 3.11.16。

重新对原实验回放，可使用：

```bash
PYTHONPATH=semantic_pallet_planner/src \
/home/cyw/anaconda3/envs/pallet_vlm/bin/python \
  -m semantic_pallet_planner.runners.layout_flash_validation \
  --output semantic_pallet_planner/outputs/EXP_OPT_O3_LAYOUT_FLASH_VALIDATION_20261020_01 \
  --replay-only
```

C 应继续返回 FAIL 和对应非零退出码；不能把它作为待手工改成 PASS 的报告。

详细讨论见[阶段 B/C 结果分析](../../../docs/03_阶段产出分析/O3/O3布局机制Flash阶段B与C结果分析及数值复现诊断_20261020.md)。
