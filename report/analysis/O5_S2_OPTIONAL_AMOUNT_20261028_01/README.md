# O5 S2 金额预算可选改进验收

按用户指令完成，不调用真实API。新版profile v2默认amount_policy=unlimited；价格/币种/金额可省略或为null，不再阻断。未知费用记null/UNKNOWN，已知部分与未知请求数分开汇总。capped与旧v1继续执行原有限额；不存在缺字段自动降级。

- tests.remote.xml：58项远程/金额测试通过，包含无金额字段的授权、预检→pilot→只读复核、完整恢复、未知停止与旧版兼容。
- tests.regression.xml：171项原S1/几何/缓冲/E2回归通过，共229项通过。
- offline_example.json：一次HTTP替身调用，usage保留、费用null，无真实API；不是pilot成绩。
- cli.preflight_draft.json：新版草案无金额缺项，仍保留provider/图文token待补项、16作业和290次pilot上限。
- before.json、before/、changes.json：本轮前后文件证据；旧计划、报告、快照不覆写。
- acceptance.json：本轮机器可读验收结论。

源码变化后旧冻结计划按原规则拒绝在新源码恢复，需要新建计划。新版授权使用v2、显式amount_policy=unlimited，可不填currency/stage_amount/total_amount；计划/账户/阶段绑定仍校验。并未授权自动执行真实API或后续阶段。

[修订规范](../../../docs/02_阶段实施方案/O5/O5S2金额预算可选修订_20261028.md)；[运行手册](../../../docs/04_运行与复核手册/O5/O5S2A离线工程运行与复核_20261028.md)。
