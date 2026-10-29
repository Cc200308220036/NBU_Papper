# O5 S2-A 离线工程证据

本目录记录通用远程工程，不记录真实provider已通过。本轮真实API=0，未采集训练轨迹、运行测试集或实现R0/M0。

- `startup_audit.json`：HEAD、未提交改动和374个启动文件哈希。
- `startup_protection.json`：仅活动O5 episode为授权变更。
- `historical_protection.json`：原124230文件完整保护检查。
- `interfaces.json`：活动import、物理候选和ReMe静态差异；本轮未初始化ReMe。
- `episode.diff`：相对S1原冻结源码的可审查运行时接口变更。
- `tests.acceptance.xml`：最新完整回归；`tests.fourth.xml`保留中间错误码分类失败，其他轮次原样保留。
- `cli.*.final.json`：最终03号计划及夹具的实际命令输出，部分执行→恢复→verify/report。
- `delivery_audit.json`、`goal_completion_audit.json`：需求到证据、S2-01—16适用范围及剩余真实provider缺口。
- `change_manifest.json`：新增文件/活动episode哈希；未修改原共享模块或历史证据。

01号源码冻结计划/运行原样保留，最终使用补齐授权和缺失文件拒绝规则后的03号计划，不让旧计划静默适配新源码。

[运行手册](../../../docs/04_运行与复核手册/O5/O5S2A离线工程运行与复核_20261028.md)；[阶段总结](../../../docs/03_阶段产出分析/O5/O5S2A通用远程接入离线开发与验收_20261028.md)。
