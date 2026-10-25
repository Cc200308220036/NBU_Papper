# O4-D研究实验开发与离线验证

- [开发说明](../../../docs/03_阶段产出分析/O4/O4D独立能力实验框架与开发交付_20261024.md)
- [终端运行手册](../../../docs/04_运行与复核手册/O4D独立能力实验运行手册_20261024.md)
- [最终证据摘要](evidence.json)
- [170项相关测试JUnit](pytest.xml)
- [预冻结六份研究计划与两份V2计划](ready_plans.json)
- [调用前强基线增量空间审计](baseline_headroom.json)及[只读脚本](audit_baselines.py)
- [开发前原文件保护清单](protected.before.json)及[开发后核验](protected.after.json)

正式数据为`DATA_O4_D_RESEARCH_20261024_01`，40个来源、528固定题、160在线任务，全部在任何本轮真实API调用前冻结。独立组合金标准在数据目录`audit/reference_gold.json`，来源选择/排除证据在`audit/source_audit.json`、`selection.json`及`private/source_registry.json`。

新数据默认开发固定题480条五来源记录和在线校准160个episode执行了离线服务替身验证，原始证据在对应`EXP_O4_D_RESEARCH_*_OFFLINE_20261024_01`目录。替身请求不是真实模型请求或独立模型重复。

原Parser在非规范表达上有拒绝，归一化Parser在自带528题上全部语义正确。因此自带程序语料没有超过强Parser的正向准确率空间，大规模TEST API命令是可选可靠性测量，不承诺模型增量。外部表达入口用于后续独立编写的新语料，导入不自动认证作者身份或参考含义等价。

所有新真实API实验仍未执行；当前没有正式功效或人类盲测证据，统计仅为条件于固定模板库的探索性来源聚类结果。
