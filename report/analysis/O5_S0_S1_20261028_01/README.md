# O5 S0/S1 离线验收证据

2026-10-28，S0/S1离线目标完成，真实API为0。入口、公共图文协议、整单状态机、物理提交、失败账本、恢复及保存状态回放均已实现；不包含R0/M0、训练轨迹或真实模型性能结论。

- `delivery_audit.json`：E01—E16适用范围与证据；E08—E10延期S3，E13真实provider预检延期S2。
- `authorization.quantile.json`：用户批准分位数OOD。先冻结规则计划，再形成03号正式数据；旧>3草案和01/02号BLOCKED数据保留为历史证据。
- `data.quantile.audit.json`：140独立簇，60/20/40/20完整订单划分、2519箱；q80严格大于阈值，边界并列归ID。
- `tests.quantile.acceptance.xml`：最新171通过、0失败，含43项O5及128项原共享回归。旧红测试保留，勿将其误作最终结果。
- `cli.development.partial/complete/verify.json`：开发集两单四条离线G0/D0记录，中断恢复、38次物理提交、0物理违规、4/4复核通过。未装完，均为当前候选池为空停止；D0为替身。
- `visual.development.audit.json`：保存状态PNG绑定和DOM-stub控件检查；未做真实浏览器渲染测试。
- `s0_interfaces.json`、`prior_evidence.json`：活动源码、ReMe静态差异及O4/B0原冻结证据。
- `historical_protection.final.json`：原124230文件及符号链接均未改变。
- `new_files.json`：新增源码、配置、测试和文档哈希。所有改动尚未提交。
- `goal_completion_audit.json`：本轮目标逐项完成核对；旧`goal_blocker_audit.json`只记录批准前的阻塞。

S2草案04号已有8个开发完整订单，最多290次选择尝试≤320，但模型、价格、金额及真实PNG传输未冻结，保持不可执行。

[开发集回放](../O5_S1_DEVELOPMENT_REPLAY_20261028_01/replay.html)；[运行手册](../../../docs/04_运行与复核手册/O5/O5S0S1独立离线入口运行与验收_20261028.md)。
