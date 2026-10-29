# O5 Direct-Text 独立协议离线开发与验收

2026-10-28。**离线工程验收通过；真实文本预检尚待用户执行；D0 Pilot表现未验证。** 本轮真实API调用0，没有启动真实Pilot或S3。

## 1. 现状核实和研究条件

活动源码位于 `semantic_pallet_planner/src/semantic_pallet_planner/`，HEAD仍为 `e540541a870973af034f030ce8cc0421a62f5e07`。适用祖先及活动目录未找到AGENTS.md；ReMe vendor内的文件不适用于本次未修改的O5路径。启动时已有大量未提交O5成果，已保存状态与14061个文件哈希；最终仅9个预期O5适配源码发生变化，旧配置/规范/手册/数据/输出原件不变。新增文本runner、profile、风险测试和本轮文档/证据。

核实S0/S1的171项和S2-A的215项历史验收记录，而非把其数字计入本轮。继续使用DATA03的train60/dev20/ID40/OOD20共140来源簇、2519箱冻结数据和原来源审计，未重派生或抽样。八单计划保持145箱、16作业及D0最多290次尝试；单箱缓冲、Top-K≤16、原A/E2候选、物理oracle、共享评分及完整订单分母保持不变。未改原A默认、旧O4/E2或vendor。

## 2. 协议与代码

先编写 [独立修订与验收规范](../../02_阶段实施方案/O5/O5DirectText独立协议修订与开发验收规范_20261028.md)，再实现 `o5_direct_text_v1`。请求、journal、profile、plan和预检分别有独立文本版本；共享attempt账本由profile及campaign摘要继续隔离。原图文入口默认含义保留。

公共请求只含当前箱、已放箱、容器、候选、固定目标/输出契约及单位坐标，递归闭合白名单；不含未来箱、split、来源、AST、内部评分或推荐排名。实际body只含text，不调用render或图片校验，不依赖PNG/image_url/字体文件。固定种子排列及私有候选映射与原协议一致，独立oracle仍在PLACE提交前执行。

文本输入上界为全部消息UTF-8字节＋512 framing余量，修复文本也计入，输入≤12000、输出≤256；每决策最多一次格式修复，服务重试0。unlimited无金额上限，费用未知为null/UNKNOWN。失败、过期绑定、未知候选、重复键、UNKNOWN调用明确处理；无静默几何回退。预检恢复会先重验已完成探针，再允许后续发送。

## 3. 本轮验收证据

最终 **299项通过，0失败、0跳过**：40项文本风险测试、115项既有O5测试、144项原几何/缓冲/E2回归。测试在pallet_vlm下运行，关闭ROS第三方pytest插件自动加载，不安装或改环境依赖。测试覆盖PLACE/STOP、非法JSON/重复键/过期/未知候选/额外坐标、映射与物理拒绝、空池无调用、输入/usage上界、费用未知、服务无重试、sent/receipt/缺账本及锁、源码/响应/body漂移与恢复幂等。中间断言错误和ROS启动问题证据保留；最终以 `tests.acceptance.final.xml` 为准。

两个真实开发公共状态的替身预检完成（3次wire含一次修复），第二个状态含已放箱及其当前承载。所有替身标记test_double=true，验证不能解锁真实Pilot。合成14/20箱任务G0/D0共4条记录完成2步断点、恢复、独立重建及报告：68次物理提交、34次替身wire，生成图片0。以上都不是实际模型结果或真实八单Pilot。

[机器验收](../../../report/analysis/O5_DIRECT_TEXT_ENGINEERING_20261028_01/acceptance.json)、[证据目录](../../../report/analysis/O5_DIRECT_TEXT_ENGINEERING_20261028_01/README.md)、[最终测试](../../../report/analysis/O5_DIRECT_TEXT_ENGINEERING_20261028_01/tests.acceptance.final.xml)。

## 4. 具体计划及本地执行

最终计划 `PLAN_O5_DIRECT_TEXT_PREFLIGHT_20261028_02` 的canonical摘要：`6d7dd0c5706222f034536e2a0d81f93fffd78aec208005eaa1a1849e17f98884`。封存实际源码及快照、依赖、profile、DATA03与完整八单私有任务、物理规则、旧规范及独立修订。两个文本请求输入上界3570/5415；原始发送体及绑定复核在 `final_plan_review.json`。02号真实run/campaign/Pilot目录均未创建。01号开发中计划未调用API，纳入恢复补强前的版本原件保留，当前校验按源码漂移拒绝，不能继续使用。

[本地运行手册](../../04_运行与复核手册/O5/O5DirectText本地预检与D0Pilot命令_20261028.md)提供validate-plan、真实文本预检、verify/report、通过后prepare-pilot/run-pilot及恢复命令。凭据继续引用本地DEEPSEEK_API_KEY，不需用户重填provider/model/endpoint/金额。只有用户手动执行远程命令才调用API，真实文本预检PASS且非替身后才能准备并运行开发集前八单Pilot。

## 5. 未验证项和残余限制

真实服务兼容、实时Flash别名稳定性、实际usage/费用及模型候选选择质量未验证；512是工程余量，usage超界必须停止。文本PASS不证明识图能力；历史01号图文预检1次真实调用（424输入/25输出、费用未知）的HOLD证据未删除或改判。活动源码变化后旧计划复核拒绝漂移，历史解释依据原封存快照及原验收证据。

Pilot表现、98%最终合法率、真实trace/物理门槛和任务难度均待实际执行；当前报告提供逐单描述，不自动判研究准入或封存D0。完整三维回放及D0封存仍属后续真实S2-C工作。不运行训练/正式测试集、经验生成、ReMe、R0/M0或S3，不依据替身收益声称论文结论。
