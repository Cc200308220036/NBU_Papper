# O4评价器V2等价处理验证

- [开发说明与离线复评命令](../../../docs/03_阶段产出分析/O4/O4评价器V2等价规则与离线复评_20261025.md)
- [验证摘要](evidence.json)
- [109项测试JUnit](pytest.xml)
- [原有文件保护清单](protected.before.json)及[开发后核验](protected.after.json)
- [正式离线复评验收](../../../semantic_pallet_planner/outputs/EXP_O4_EVAL_V2_RESCORE_20261025_01/evaluation_report.json)
- [624条旧新指标对照CSV](../../../semantic_pallet_planner/outputs/EXP_O4_EVAL_V2_RESCORE_20261025_01/comparison.csv)
- [完整逐题旧新指标](../../../semantic_pallet_planner/outputs/EXP_O4_EVAL_V2_RESCORE_20261025_01/rows.json)

整体语义分数只改变6条Text的零限载等价表示，其他618条保持不变。候选判定全部保持不变。旧评价代码、真实响应、评分和验收均保留，真实API新增调用0，不重复整套replay。新评价没有静默接入旧冻结运行器。
