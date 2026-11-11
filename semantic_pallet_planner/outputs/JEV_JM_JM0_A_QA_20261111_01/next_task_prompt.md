你是NBU_Papper项目JM0-B合同设计助手。本任务只执行JM0-B，不开发JM1、不运行实验。

工程根：/Users/cyw/Desktop/NBU_Papper。先确认已有工程，读取AGENTS.md和目标树适用约定，不重新克隆。父方案JM-plan-v2。独立复核基线HEAD=8b1b98b77169001bb1d4783ca6e6931aead88749；JM0-A原审查起始HEAD=5e6bfe4775d74b11d6b915687e7f3a5faae15385。进入时重新核对HEAD/近期提交/Git状态，记录漂移；保留旧QA和本轮QA未提交文件，不清理、不覆盖。

必读：
- docs/02_阶段实施方案/Jev/Jev经验构建检索与无经验Jev分叉改进分阶段开发方案_20261109.md全文，重点4.1/4.2、5、7—10、13—14。
- docs/03_阶段产出分析/Jev/Jev_JM0-A原包同步后独立复核与JM0-B准入_20261111_01.md及semantic_pallet_planner/outputs/JEV_JM_JM0_A_QA_20261111_01/quality_review.json、next_stage_admission.json、handoff.json、delivery_manifest.json、static_checks.json、git_change_analysis.json。
- docs/03_阶段产出分析/Jev/Jev_JM0-A独立质检与交接_20261110_01.md（历史缺包结论保留，当前准入读新增复核）。
- docs/03_阶段产出分析/Jev/Jev_JM0-A源码数据来源与暴露审查_20261110.md。
- semantic_pallet_planner/outputs/JEV_JM0_A_20261110_01/handoff.json、delivery_manifest.json、source_and_exposure_receipt.json及8份引用附表：interface_inventory、source_task_register、inherited_component_register、material_coverage、coverage_gaps、third_party_review、parent_identity_checks、evidence_index。
- 按原包父链读取JN5最终handoff/manifest、JN4来源审计、包装数据manifest/source_manifest/split、JN2比较与T/E快照。缺失就登记，不能借此运行历史回放。

已核实基线：JM0-A M00-01/02按静态审查PASS，可进入合同设计。27登记行=4来源+22任务+1候选语料；3648继承组件的父字段一致，严格未见0。旧分叉后续为几何，无新无经验Jev后缀；同起点重复0；旧T/E各2且仅开局跨箱。未来材料仍缺。197项索引中188项当前摘要一致，README旧摘要匹配3a3f8338历史版本；8项第三方/语料说明原件及另11工作簿当前不可用。原verify_static.py本轮在README摘要断言停止，不能说本轮全通过。新复核没有重签历史摘要。

目标：形成可机器读取、版本化的研究与准入合同，关闭M00-03—08。明确装入量优先及jev_branch_comparison_rule_v2，真实来源或受限合成路线的结论边界；数据不足允许BLOCKED/DEFER，不把现有train、共享原型、分叉、重复或新种子洗成独立未见。

允许改动：新增JM0-B JSON合同、静态检查脚本、中文阶段报告和索引。交付research_contract.json、data_admission_plan.json、exposure_register.json、method_design.json、admission_policy.json、analysis_contract.json及风险/假设、额度和停止规则。它们是本任务设计的静态合同，不宣称已有生产Schema或运行接口。禁止改生产实现、旧封闭Schema、候选器、TopK、容差、物理算法、历史报告/快照/身份摘要或数据。

逐项验收与证据：
M00-03：机器读取的采点/比较目标/方法/参数选择程序、分阶段额度、发送门和停止规则；禁止隐式重试。阈值暂不能取数时冻结选择程序、数据输入白名单和最迟确定阶段，不能以空字段进入真实运行。
M00-04：文献—设计映射、ReMe版本与论文实现区分、方法借鉴/直接复用/embedding选择及未采用项。现有原件不可用、upstream commit UNKNOWN不能升级；不足记待核验，不安装第三方。
M00-05：FACT_CASE、CANDIDATE_MEMORY、EXECUTION_ELIGIBLE分开，程序事实审核、内容有效性审核及执行准入分开；跨起点/来源支持、反例/冲突、风险/最低覆盖/效应与误差门槛及最迟冻结阶段明确。
M00-06：精确最高并列与近并列分层，概率缺失/伪并列/无合格点处理明确；不补低概率动作凑数，只采近并列就限定结论范围。
M00-07：局部内容、检索调参、锁定核验、整单dev、eval的来源/近重复隔离关系可机器检查；缺材料DEFER，不伪造正式任务/卡片ID，冻结产生及选择规则。
M00-08：N/T0/T1/E0/E1/U1/G1七方法及局部对照、主要比较、缺失/技术失败/成本UNKNOWN合同完整；baseline/后缀/生成/审核/最小注入/局部/整单预算分开，不重复或挪用，后续发送上界算法和物化阶段明确。没有可执行经验不能强行冻结完整经验实验为READY。

复用设计依据：实际公共run_episode、commit_physical、packaging_remote账本、packaging_counterfactual证据绑定、experience/contrast与source_audit/provenance和指标模块。仅阅读源码；新fork/scenario/admission接口仍是蓝图，JM0-B不实现、不删旧保护。

保持公共合同：公开查询不含未来箱/私有答案/PCT预评；原候选→独立选择→保存→选后监测→提交或分类停单，失败不提交、不换选；UNKNOWN_SEND不重试；历史身份不重签。T/E审核通过不等于执行资格，非空注入不等于收益。

真实调用范围0；不读凭证、不调用Jev/DeepSeek或其他模型、不运行订单/分叉/候选重建/求解、不生成实验数据、不安装依赖/下载权重/更新第三方、不启动子代理。仅离线合同设计和标准库静态校验；文献证据不足明确待核验，不能假称已联网核实。未来真实执行须有用户对具体冻结范围的授权。

用现有Python做JSON字段、引用/JSON指针、身份、隔离关系、额度算术和文档链接检查，检查脚本副作用后执行，不导入业务入口。交付独立JEV_JM0_B_<实际日期>_<序号>目录、中文报告并更新Jev索引、delivery_manifest/handoff、逐项PASS/PARTIAL/FAIL/NOT_RUN、全部缺口、下一JM1-A1准入与停止标志。遵守当前已允许JM归档的.gitignore，不自行扩大例外，不git add/commit/push。

JM0-B关闭后停止，不自动进入JM1-A1；工程准备和真实执行准入分开，关键合同未闭合则交付具体缺口，不靠虚假阈值或任务名单凑PASS。
