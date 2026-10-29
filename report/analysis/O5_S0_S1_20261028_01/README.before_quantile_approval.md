# O5 S0/S1 交付记录（2026-10-28）

**离线功能通过；完整阶段目标尚未通过，正式数据划分等待 OOD 规则决定。**

新增独立 O5 物理任务闭环、公共图文请求与显示映射、G0/D0 选择契约、可控替身、原子账本、未知在途请求处理、断点恢复、整单计分、来源聚类统计和实际提交状态回放。真实 API 0；不实现 R0/M0、不采集训练轨迹、不安装或初始化 ReMe。

首轮验收：160项通过，其中O5 32项、原几何/缓冲/E2回归128项。恢复加固后，最新40项O5专项全部通过；原128项共享回归证据保留，共享源码未变，未重复运行。两项完整合成订单（14/20 箱）×G0/D0 共四条记录，68 次实际物理提交；四条均通过只读重建核验。替身只验证工程，不作模型装载收益证据。STOP、双次格式失败、服务失败、预算耗尽现场另存。

历史保护：124230 个原有非缓存文件摘要全部一致；起始提交 e540541a870973af034f030ce8cc0421a62f5e07，起始工作区干净。原 E2、共享评分、ReMe vendor、旧默认和历史产物均未修改。

数据：两次审计原件均保留。第二次补充跨字段别名和无序窗口，读取64905份相关来源文件后，得到353个可用短订单来源簇。初步 OOD 草案“最大箱体平面长宽比>3”仅4簇，其余349簇。正式140来源数据尚未生成；没有降低阈值凑数。此阈值是本轮新增草案，并非上位规范规定。待用户选择是否允许在任何模型实验前改为几何特征分位数设计。UNKNOWN 引用单独保留、不参与可用来源选择。

本地 ReMe 源码声明0.4.1.11，但当前解释器没有安装reme-ai/agentscope。实际记忆整理接口含Agent多轮、内部重试及默认后台任务，S3需要专门限制底层调用并记账。当前仅有静态接口审计，不宣称ReMe已经接入。

## 证据

- [最终分项交付审计](delivery_audit.json)：E01—E16的本轮状态、未完成项和数据阻塞。
- [历史文件保护](historical_protection.json)与[起始摘要](protected.before.json)。
- [活动导入与ReMe接口](s0_interfaces.json)、[O4/B0原始证据摘录](prior_evidence.json)。
- [新增文件与摘要](new_files.json)、[版本化记录Schema](record_schemas.json)。
- [最新O5专项XML](tests.hardening.xml)：40项通过；[首轮组合验收XML](tests.acceptance.xml)与所有中间失败原件保留。
- [CLI断点记录](cli.partial.json)、[CLI完成记录](cli.complete.json)、[只读核验](cli.verify.json)。
- [失败现场摘要](protocol_failures.json)、[图像与回放绑定](visual_binding_checks.json)。
- [实际状态逐步回放](../O5_S1_FIXTURE_REPLAY_20261028_02/replay.html)。Node DOM桩验证12个控件位置；未进行真实浏览器渲染验收。
- [运行与复核手册](../../../docs/04_运行与复核手册/O5/O5S0S1独立离线入口运行与验收_20261028.md)。

## 产物路径

仓库根目录下：

- `semantic_pallet_planner/outputs/DATA_O5_DIRECT_MEMORY_20261028_01`：首次BLOCKED_DATA。
- `semantic_pallet_planner/outputs/DATA_O5_DIRECT_MEMORY_20261028_02`：补充去重后的BLOCKED_DATA。
- `semantic_pallet_planner/outputs/PLAN_O5_DIRECT_MEMORY_S1_FIXTURE_20261028_02`：冻结离线夹具计划。
- `semantic_pallet_planner/outputs/EXP_O5_DIRECT_MEMORY_S1_FIXTURE_20261028_02`：四条离线运行。
- `semantic_pallet_planner/outputs/EXP_O5_DIRECT_MEMORY_S1_FAILURES_20261028_01`：四类失败现场。
- `semantic_pallet_planner/outputs/PLAN_O5_DIRECT_MEMORY_S2_DRAFT_20261028_03`：最新S2草案；数据、模型、费用未冻结，不可执行。

一次中间回归因开发期间源码变化触发源码漂移拒绝，原XML保留；停止源码编辑后完整验收160项通过。没有放宽源码冻结检查，也没有改写历史验收。

## 恢复加固与具体待审方案

新增故障注入确认并修复三处恢复缺口，失败原件见 [recovery.before.xml](recovery.before.xml)：请求与映射持久化间隙导致无法恢复；缺失账本会重建预算；续跑前未核对已提交响应账本。现在先保存映射再提交请求，缺失映射可对照完整请求确定性重建，缺失账本直接拒绝，续跑前核对每个已提交决策与原账本；待提交G0图片也必须通过核验。没有删除或放宽预算/绑定检查。

[最新40项测试](tests.hardening.xml)还覆盖合成仓库完整140来源派生、保留原始到货序列、来源排除、文件权限/校验和以及OOD不足时不生成部分划分。这是算法工程验证，不代表真实数据已经通过划分。

新代码封存为02号夹具计划/运行，四条完整记录与只读核验通过，见 [断点](cli.hardening.partial.json)、[完成](cli.hardening.complete.json)、[核验](cli.hardening.verify.json)。01号计划、运行、回放及原审计均保留；旧计划因源码变更不能继续在新代码上运行。新旧实际终态PNG完全一致，见 [图像绑定检查](visual_binding_checks.hardened.json)。这次改变恢复可靠性，不宣称装载性能提升。

[1050个既有关键文件复核](followup_protection.json)通过。首次辅助脚本把符号链接目标字符串与内容哈希混比，保留first记录后改为比较链接目标；符号链接没有改动。

[OOD具体待审方案](OOD划分待审方案.md)提出 nearest-rank 第80百分位，精确阈值2.0344827586206895；边界同值全部留ID，可形成291个ID候选簇和62个OOD候选簇。没有应用该规则，没有生成正式划分，没有修改原配额或当前BLOCKED_DATA。仍需用户决定；目标保持未完成。
