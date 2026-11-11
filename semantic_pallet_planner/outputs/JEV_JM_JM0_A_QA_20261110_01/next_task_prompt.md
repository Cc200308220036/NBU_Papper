你是NBU_Papper项目JM0-A最小整改开发助手。仅处理质检缺陷，不实施JM0-B或JM1。

项目根为/Users/cyw/Desktop/NBU_Papper；先pwd确认已有工程，读取根AGENTS.md及补交目标树适用约定，不重新克隆。质检时HEAD为3a3f83384b6cdde19cd5262cc86f27c4b8cd7011，JM0-A报告起始基线为5e6bfe4775d74b11d6b915687e7f3a5faae15385；进入时重新核对HEAD、近期相关提交和git status，记录漂移，不沿用过时身份，不覆盖其他窗口修改。

父方案：JM-plan-v2。必读：
- docs/02_阶段实施方案/Jev/Jev经验构建检索与无经验Jev分叉改进分阶段开发方案_20261109.md，重点4.1/4.2、5.2/5.3、14.2。
- docs/03_阶段产出分析/Jev/Jev_JM0-A独立质检与交接_20261110_01.md
- semantic_pallet_planner/outputs/JEV_JM_JM0_A_QA_20261110_01/quality_review.json、next_stage_admission.json、static_checks.json、delivery_manifest.json及handoff.json。
- docs/03_阶段产出分析/Jev/Jev_JM0-A源码数据来源与暴露审查_20261110.md
- 原声明包semantic_pallet_planner/outputs/JEV_JM0_A_20261110_01/（质检时不存在，先确认，不假装已读）。
- semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_20261107_03/handoff.json、delivery_manifest.json、evidence_index.json。
- semantic_pallet_planner/outputs/JEV_JN4_20261105_01/source_audit.json、source_manifest.json、split_manifest.json及exposure_records.json。
- semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02/manifest.json、handoff.json、source_manifest.json、split_manifest.json。
- semantic_pallet_planner/outputs/JEV_JN3_20261104_01/trajectory_snapshot.json和JEV_JN3_20261104_02/contrast_snapshot.json及各自delivery_manifest.json。
按原报告追溯JN1/JN2、合成六任务及保存分叉；缺材料显式列出，不启动历史回放。

已核实：原报告存在且HEAD提交只有报告和索引；原交付包缺失、9个链接失效。4来源全train；继承组件3648=3522 UNKNOWN_EXPOSURE+64 TRAIN_DEV_OR_REAL_RUN+62 HISTORICAL_TEST，strict eligible=0；T/E各2；抽查6份历史文件摘要与各自manifest一致。以上是质检范围内事实，不等于整套材料验收通过。

目标与修改边界：
1. 关闭阻断QA-JM0A-01：优先定位并恢复原交付字节、原handoff/manifest/验证记录及来源身份。不能用当前重新生成结果冒充旧记录；无法恢复时在独立新目录形成本轮补交，记录实际源码身份及来源，明确历史证据NOT_AVAILABLE。不能反向重签原摘要。
2. 处理QA-JM0A-02：当前ReMe-main/zip和raw/mixed_pallet_boxes均未见，原报告曾声明存在。恢复可信旧身份收据，或在新补交说明当前缺失与历史不可复验。不因目录缺失下载、安装或伪造版本。原材料缺失不证明原报告虚假。
3. 补交review-only的source_and_exposure_receipt.json、逐来源/任务用途与暴露登记、实际接口和拟议API区分、材料覆盖/缺口、证据索引、validation_receipt、delivery_manifest和handoff。保留同源、近重复、共享原型关系及UNKNOWN，不要求凭空生成新未见数据或未来卡片ID。此为补交内容要求，不声称这些接口已存在。
4. 允许新增静态审查脚本、补交文档与索引入口；禁止修改被审生产实现、Schema、冻结策略、原始报告/收据/快照以让验收通过。新报告链接到原记录并解释差异。归档遵守现有.gitignore，不扩大例外，不自动commit/push。

复用静态证据位置：jev_select/episode.py、execution.py、packaging_remote.py、packaging_counterfactual.py、packaging_experience.py、packaging_contrast.py、stability/monitor.py及来源审计模块。仅文本/AST读取，不调用业务入口。原几何后续、非空保护和高度口径缺口均属后续开发，不能在本整改修实现。

逐项验收：M00-01实际基线/入口/父证据/缺件与蓝图区分可追溯；M00-02逐来源关系/暴露/真实合成/用途理由可追溯，缺证明严格未见不准入。方案14.2补齐manifest/handoff/验收逐项状态及停止标志。M00-03—08属JM0-B，不在本任务关闭。缺数据证明可以是静态审查完成，但不得缺必交审查证据。

真实调用范围为0。不得读取凭证、访问模型/网络、运行订单、分叉、候选重建或稳定性求解；不安装依赖、下载权重或第三方、不启子代理。用现有Python标准库做路径/JSON指针/摘要/计数/源码文本及链接验证，检查脚本副作用后才执行。记录相对路径命令、完整失败/未运行分母、实际验证范围；不做全量历史回放。

交付独立补交包、中文补交报告、索引、逐项验收和缺陷关闭映射；标清工程状态、证据就绪、研究结果（本阶段不评价收益）、JM0-B准入建议。停止于JM0-A补交，等待独立复核；不得自动执行JM0-B及任何真实实验。后续涉及真实调用必须先有用户对具体冻结范围的授权。
